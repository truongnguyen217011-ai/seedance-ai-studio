"""Worker: vòng lặp 2 giây nhặt job 'Chờ', chọn nick qua AccountPool, chạy job trong thread
(docs/KIEN_TRUC.md mục 2, 4). Giới hạn Chrome đếm bằng browser.BrowserSlots, không bằng chuỗi trong CSDL.

Luồng:
- `_tick` chạy trên executor MẶC ĐỊNH của asyncio (`asyncio.to_thread`): việc ngắn, chỉ đọc/ghi CSDL.
- Job (mở Chrome, render hàng phút) chạy trên `JOB_EXECUTOR` riêng (BH-32) để không chiếm hết executor
  mặc định rồi làm `_tick`, `/api/health` và các thao tác tay phải xếp hàng sau job.
"""
import asyncio
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as _policy_err:  # noqa: BLE001
        print(f"[worker] Không đặt được WindowsProactorEventLoopPolicy: {_policy_err}", flush=True)

import browser
import config
from account_pool import AccountPool, select_account_for_job
from constants import AccountStatus, JobStatus, Reason
from database import get_connection, get_int_setting, reset_orphans_on_startup
from dola_service import execute_video_job, update_job_status
from logger import get_logger, log_event

log = get_logger("Worker")

LOOP_INTERVAL_SECONDS = 2
MUSE_UNSUPPORTED = "Muse AI không còn được hỗ trợ"
NO_CHROME_MESSAGE = ("Không tìm thấy Google Chrome/Chromium. Chạy CAI_TRINH_DUYET.bat hoặc điền đường dẫn Chrome "
                     "trong Cài đặt")
NO_CHROME_WARN_INTERVAL = 60  # giây giữa hai lần ghi WARNING "không có Chrome" (không spam log)

# Executor riêng cho job và thao tác tay mở Chrome (auto login, check credit, chẩn đoán) — BH-32.
# ThreadPoolExecutor không đổi được max_workers sau khi tạo, nên chọn 32 cố định: setting
# max_concurrent_jobs thực tế 6–20 Chrome, cộng vài thao tác tay vẫn còn dư; thread rảnh không tốn gì.
# Giới hạn Chrome thật vẫn do browser.BrowserSlots quyết định, không phải số thread.
JOB_EXECUTOR_WORKERS = 32
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=JOB_EXECUTOR_WORKERS, thread_name_prefix="job")

is_running = True
_last_tick = 0.0
_running_jobs = set()  # job_id đang chạy trong thread (để không nhặt lại trước khi CSDL cập nhật)
_background_tasks = set()  # giữ tham chiếu task asyncio (G-1): task đang chạy không bị GC thu
_last_no_chrome_warn = 0.0


def worker_alive(max_age_seconds: float = 10.0) -> bool:
    """Worker còn sống nếu vòng lặp vừa chạy trong max_age_seconds gần đây."""
    return is_running and (time.monotonic() - _last_tick) < max_age_seconds


def running_job_ids() -> set:
    return set(_running_jobs)


async def run_in_job_executor(fn, *args):
    """Chạy hàm sync (mở Chrome, chạy hàng phút) trên JOB_EXECUTOR thay vì executor mặc định của asyncio."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(JOB_EXECUTOR, fn, *args)


def _set_message_if_changed(conn, job_row, message: str) -> None:
    if (job_row["status_message"] or "") != message:
        conn.execute("UPDATE jobs SET status_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (message, job_row["id"]))
        conn.commit()


def _recover_accounts(conn) -> None:
    """Hết hạn rest_until → bỏ nghỉ; rate_limited quá 30 phút → ready."""
    conn.execute("""
        UPDATE accounts SET rest_until = NULL, rest_reason = NULL
        WHERE rest_until IS NOT NULL AND rest_until <= datetime('now', 'localtime')
    """)
    conn.execute("""
        UPDATE accounts SET status = ?
        WHERE status = ? AND (last_used IS NULL OR (strftime('%s', 'now') - strftime('%s', last_used)) > 1800)
    """, (AccountStatus.READY, AccountStatus.RATE_LIMITED))
    conn.commit()


async def _run_job(job_id: int, account_id: int) -> None:
    pool = AccountPool.get()
    try:
        await run_in_job_executor(execute_video_job, job_id, account_id)
    except Exception as e:  # noqa: BLE001 - execute_video_job đã tự xử lý lỗi; đây là lưới cuối
        log.error("Job #%s văng lỗi ngoài dự kiến: %s", job_id, e, extra={"job_id": job_id, "account_id": account_id})
        try:
            update_job_status(job_id, JobStatus.THAT_BAI, Reason.BROWSER_ERROR.format(error=str(e)[:160]), 0)
        except Exception as e2:  # noqa: BLE001
            log.error("Không cập nhật được trạng thái job #%s: %s", job_id, e2, extra={"job_id": job_id})
    finally:
        pool.release(account_id)
        _running_jobs.discard(job_id)


class TickCache:
    """Kết quả dùng lại trong MỘT vòng quét (N-6).

    Điều kiện đủ của nick không phụ thuộc job (chỉ thứ tự ưu tiên phụ thuộc job), nên job đầu tiên
    không có nick thì các job sau trong cùng tick cũng không: ghi `no_account_summary` và dùng lại
    thay vì gọi select_account_for_job tới 500 lần. `session_cache` nhớ has_dola_session theo nick
    (đọc cookies/storage_state.json) trong tick.
    """

    def __init__(self):
        self.no_account_summary = None  # str khi tick này đã biết không còn nick đủ điều kiện
        self.session_cache = {}  # account_id -> bool


def _dispatch_one(conn, job_row, cache: Optional[TickCache] = None):
    """Chọn nick, khóa nick và đánh dấu job 'Đang chạy'. Trả về account_id nếu job sẵn sàng chạy, None nếu không."""
    job_id = job_row["id"]
    model = (job_row["model"] or "").lower()
    if "muse" in model:
        _set_message_if_changed(conn, job_row, MUSE_UNSUPPORTED)
        return None

    if cache is not None and cache.no_account_summary is not None:
        _set_message_if_changed(conn, job_row, Reason.WAITING_ACCOUNT.format(summary=cache.no_account_summary))
        return None

    acc, summary = select_account_for_job(job_row, session_cache=cache.session_cache if cache is not None else None)
    if not acc:
        if cache is not None:
            cache.no_account_summary = summary
        _set_message_if_changed(conn, job_row, Reason.WAITING_ACCOUNT.format(summary=summary))
        return None

    pool = AccountPool.get()
    if not pool.acquire(acc["id"], job_id):
        _set_message_if_changed(conn, job_row, Reason.ACCOUNT_BUSY.format(name=acc["name"], job_id=pool.holder(acc["id"])))
        return None

    try:
        conn.execute(
            """UPDATE jobs SET status = ?, status_message = ?, progress = 0, account_id = ?,
               attempts = COALESCE(attempts, 0) + 1, started_at = CURRENT_TIMESTAMP, finished_at = NULL,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (JobStatus.DANG_CHAY, f"Đã chọn nick '{acc['name']}', đang mở trình duyệt", acc["id"], job_id),
        )
        conn.commit()
    except Exception:
        pool.release(acc["id"])
        raise

    _running_jobs.add(job_id)
    log_event(f"Job #{job_id}: bắt đầu chạy bằng nick '{acc['name']}'", "INFO", "Worker", job_id=job_id, account_id=acc["id"])
    return acc["id"]


def _rollback_dispatched(to_start: list) -> None:
    """Vòng quét văng lỗi SAU khi đã điều phối job (BH-27): trả job về Chờ, trả nick, bỏ khỏi _running_jobs.

    Không có bước này, job kẹt 'Đang chạy' mà không thread nào chạy nó, nick khóa vĩnh viễn và
    capacity giảm dần vì `_running_jobs` không bao giờ được dọn.
    """
    pool = AccountPool.get()
    for job_id, account_id in to_start:
        _running_jobs.discard(job_id)
        pool.release(account_id)
        try:
            conn = get_connection()
            try:
                conn.execute(
                    """UPDATE jobs SET status = ?, status_message = ?, attempts = MAX(COALESCE(attempts, 1) - 1, 0),
                       started_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = ?""",
                    (JobStatus.CHO, "Vòng quét worker gặp lỗi trước khi khởi chạy, sẽ nhặt lại", job_id, JobStatus.DANG_CHAY),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.error("Không trả được job #%s về '%s' sau lỗi vòng quét: %s", job_id, JobStatus.CHO, e,
                      extra={"job_id": job_id, "account_id": account_id})


def _mark_no_chrome(conn) -> None:
    """Không có Chrome (N-3): không điều phối; ghi lý do lên job Chờ (chỉ khi đổi), WARNING tối đa 1 lần/60 s."""
    global _last_no_chrome_warn
    now = time.monotonic()
    if now - _last_no_chrome_warn >= NO_CHROME_WARN_INTERVAL:
        _last_no_chrome_warn = now
        log.warning("%s — worker không chạy job nào cho đến khi có Chrome", NO_CHROME_MESSAGE)
    pending = conn.execute("SELECT id, status_message FROM jobs WHERE status = ?", (JobStatus.CHO,)).fetchall()
    for job_row in pending:
        _set_message_if_changed(conn, job_row, NO_CHROME_MESSAGE)


WAITING_SLOT_MESSAGE_LIMIT = 20  # chỉ ghi lý do "chờ chỗ mở Chrome" lên chừng này job Chờ đầu hàng (N-5)


def _mark_waiting_for_slot(conn) -> None:
    """Hết chỗ mở Chrome (N-5): các job Chờ đầu hàng nhận lý do "Đang chờ chỗ mở Chrome (x/N đang dùng)" để người
    dùng biết vì sao hàng đợi đứng yên. Chỉ ghi khi nội dung đổi; khi có chỗ lại worker tự nhặt nên không cần xóa."""
    pending = conn.execute(
        "SELECT id, status_message FROM jobs WHERE status = ? ORDER BY batch_id, seq, id LIMIT ?",
        (JobStatus.CHO, WAITING_SLOT_MESSAGE_LIMIT),
    ).fetchall()
    if not pending:
        return
    message = browser.slot_wait_message()
    for job_row in pending:
        if job_row["id"] in _running_jobs:
            continue
        _set_message_if_changed(conn, job_row, message)


def _tick() -> list:
    """Một vòng quét (chạy trong thread). Trả về danh sách (job_id, account_id) cần khởi chạy.

    Bất biến (BH-27): mọi job đã được `_dispatch_one` đánh dấu 'Đang chạy' đều PHẢI được trả về cho
    worker_loop khởi chạy, hoặc được rollback về 'Chờ'. Lỗi ở bước sau điều phối (_recover_accounts,
    đóng kết nối) không được làm mất danh sách này.
    """
    to_start = []
    try:
        conn = get_connection()
        try:
            browser.SLOTS.resize(get_int_setting("max_concurrent_jobs", config.DEFAULT_MAX_BROWSERS))
            if not browser.find_chrome():
                _mark_no_chrome(conn)
            else:
                # Slot trống = min(chỗ Chrome còn trống, giới hạn trừ số job đang chạy).
                # Vế thứ hai chặn trường hợp job vừa khởi chạy chưa kịp giữ slot (tránh mở quá giới hạn).
                free = min(browser.available(), browser.capacity() - len(_running_jobs))
                if free <= 0:
                    _mark_waiting_for_slot(conn)
                else:
                    pending = conn.execute(
                        "SELECT * FROM jobs WHERE status = ? ORDER BY batch_id, seq, id LIMIT 500",
                        (JobStatus.CHO,),
                    ).fetchall()
                    cache = TickCache()
                    started = 0
                    for job_row in pending:
                        if started >= free:
                            break
                        if job_row["id"] in _running_jobs:
                            continue
                        try:
                            acc_id = _dispatch_one(conn, job_row, cache)
                            if acc_id is not None:
                                to_start.append((job_row["id"], acc_id))
                                started += 1
                        except Exception as e:  # noqa: BLE001 - một job lỗi không được chặn job khác
                            log.error("Lỗi khi điều phối job #%s: %s", job_row["id"], e, extra={"job_id": job_row["id"]})
            try:
                _recover_accounts(conn)
            except Exception as e:  # noqa: BLE001 - không được làm mất to_start (BH-27)
                log.error("Lỗi khi hồi phục trạng thái nick: %s", e)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - lưới cuối: không để job đã điều phối kẹt 'Đang chạy'
        log.error("Vòng quét worker lỗi: %s", e)
        if to_start:
            _rollback_dispatched(to_start)
            to_start = []
    return to_start


def _startup() -> None:
    reset_count = reset_orphans_on_startup()
    AccountPool.get().clear()
    cleaned = browser.cleanup_profiles_on_startup()
    log_event(
        f"Worker khởi động: reset {reset_count} job mồ côi về '{JobStatus.CHO}', dọn {cleaned} Chrome mồ côi, "
        f"giới hạn {get_int_setting('max_concurrent_jobs', config.DEFAULT_MAX_BROWSERS)} Chrome",
        "INFO", "Worker",
    )


def track_task(task: "asyncio.Task") -> "asyncio.Task":
    """Giữ tham chiếu task cho tới khi xong (G-1); asyncio chỉ giữ weakref nên task có thể bị GC giữa chừng."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def worker_loop():
    global is_running, _last_tick
    is_running = True
    try:
        _startup()
    except Exception as e:  # noqa: BLE001
        log.error("Khởi động worker lỗi: %s", e)
    while is_running:
        try:
            to_start = await asyncio.to_thread(_tick)
            for job_id, account_id in to_start:
                track_task(asyncio.create_task(_run_job(job_id, account_id)))
        except Exception as loop_err:  # noqa: BLE001 - vòng lặp không bao giờ được chết
            log.error("Lỗi vòng lặp worker: %s", loop_err)
        _last_tick = time.monotonic()
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)


def start_worker():
    return track_task(asyncio.create_task(worker_loop()))


def stop_worker():
    global is_running
    is_running = False
