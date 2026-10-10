"""Khóa nick và chọn nick cho job (docs/KIEN_TRUC.md mục 1.2, 2).

- AccountPool: singleton thread-safe; mỗi nick tại một thời điểm chỉ một luồng được dùng profile.
- select_account_for_job(job_row, excluded=None): chọn nick đủ điều kiện và tóm tắt lý do loại.
"""
import threading
from datetime import datetime
from typing import Optional, Tuple

from constants import AccountStatus, NeedsManual
from database import get_connection
from logger import get_logger

log = get_logger("AccountPool")

# busy_job_id ghi giá trị này khi nick bận vì thao tác không gắn job (đăng nhập tay, chẩn đoán)
MANUAL_HOLDER = 0


class AccountPool:
    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()
        self._busy = {}  # account_id -> job_id (hoặc MANUAL_HOLDER)

    @classmethod
    def get(cls) -> "AccountPool":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def acquire(self, account_id: int, job_id: Optional[int] = None) -> bool:
        """Giữ nick cho job_id (None = thao tác tay). Không chặn; trả False nếu nick đang bận."""
        holder = job_id if job_id is not None else MANUAL_HOLDER
        with self._lock:
            if account_id in self._busy:
                return False
            self._busy[account_id] = holder
        self._write_busy(account_id, holder)
        log.debug("Giữ nick #%s cho %s", account_id, f"job #{job_id}" if job_id else "thao tác tay",
                  extra={"account_id": account_id, "job_id": job_id})
        return True

    def release(self, account_id: int) -> None:
        with self._lock:
            held = self._busy.pop(account_id, None)
        if held is None:
            return
        self._write_busy(account_id, None)
        log.debug("Trả nick #%s", account_id, extra={"account_id": account_id})

    def is_busy(self, account_id: int) -> bool:
        with self._lock:
            return account_id in self._busy

    def holder(self, account_id: int) -> Optional[int]:
        """job_id đang giữ nick, MANUAL_HOLDER nếu thao tác tay, None nếu rảnh."""
        with self._lock:
            return self._busy.get(account_id)

    def busy_map(self) -> dict:
        with self._lock:
            return dict(self._busy)

    def clear(self) -> None:
        """Chỉ dùng lúc khởi động / trong test."""
        with self._lock:
            self._busy.clear()

    @staticmethod
    def _write_busy(account_id: int, holder) -> None:
        try:
            conn = get_connection()
            try:
                conn.execute("UPDATE accounts SET busy_job_id = ? WHERE id = ?", (holder, account_id))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 - cột busy_job_id chỉ để UI nhìn, không được làm hỏng khóa
            log.warning("Không ghi được busy_job_id cho nick #%s: %s", account_id, e,
                        extra={"account_id": account_id})


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def account_has_dola_session(acc: dict) -> bool:
    # Import muộn: dola_service import account_pool ở đầu file
    from dola_service import account_has_dola_session as _has
    return _has(acc)


def _has_session_cached(acc: dict, session_cache: Optional[dict]) -> bool:
    if session_cache is None:
        return account_has_dola_session(acc)
    acc_id = acc.get("id")
    if acc_id not in session_cache:
        session_cache[acc_id] = account_has_dola_session(acc)
    return session_cache[acc_id]


def _credits_today(acc: dict, today: str):
    """Số credit còn hôm nay nếu biết, None nếu chưa rõ."""
    if acc.get("credits_date") == today and acc.get("credits") is not None:
        return int(acc["credits"])
    return None


def _format_summary(counts: dict, total: int) -> str:
    order = [
        ("no_credit", "nick hết credit"),
        ("no_session", "nick chưa đăng nhập Dola"),
        ("busy", "nick đang bận"),
        ("captcha", "nick cần kéo captcha"),
        ("proxy", "nick proxy lỗi"),
        ("resting", "nick đang nghỉ"),
        ("login", "nick cần đăng nhập lại"),
        ("rate_limited", "nick bị giới hạn tạm thời"),
        ("disabled", "nick đã tắt"),
    ]
    parts = [f"{counts[k]} {label}" for k, label in order if counts.get(k)]
    if not parts:
        return "chưa có nick Facebook/Google nào" if total == 0 else "không có nick nào đủ điều kiện"
    return ", ".join(parts)


def select_account_for_job(job_row, excluded=None, session_cache: Optional[dict] = None) -> Tuple[Optional[dict], str]:
    """Chọn nick cho job. Trả về (dict nick | None, tóm tắt lý do loại).

    Điều kiện đủ: status='ready', loại facebook/google, không cần can thiệp tay, không nghỉ,
    không hết credit hôm nay, có phiên Dola, không bận. Ưu tiên nick đã gán cho job,
    rồi credit còn hôm nay giảm dần, rồi last_used tăng dần.

    session_cache: dict account_id -> bool do worker giữ trong MỘT vòng quét (N-6) để không đọc lại
    cookies/storage_state.json của từng nick cho mỗi job; None = không cache.
    """
    excluded = set(excluded or ())
    pool = AccountPool.get()
    today = _today_str()
    now = _now_str()
    job = dict(job_row) if job_row is not None else {}
    assigned_id = job.get("account_id")

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE account_type IN ('facebook', 'google') ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    counts = {}
    eligible = []
    for row in rows:
        acc = dict(row)
        acc_id = acc["id"]
        if acc_id in excluded:
            continue
        reason = None
        if pool.is_busy(acc_id):
            reason = "busy"
        elif acc.get("needs_manual") == NeedsManual.CAPTCHA:
            reason = "captcha"
        elif acc.get("needs_manual") == NeedsManual.PROXY:
            reason = "proxy"
        elif acc.get("needs_manual") == NeedsManual.LOGIN:
            reason = "login"
        elif acc.get("status") == AccountStatus.RATE_LIMITED:
            reason = "rate_limited"
        elif acc.get("status") != AccountStatus.READY:
            reason = "disabled"
        elif acc.get("rest_until") and str(acc["rest_until"]) > now:
            reason = "resting"
        elif acc.get("credits_date") == today and acc.get("credits") == 0:
            reason = "no_credit"
        elif not _has_session_cached(acc, session_cache):
            reason = "no_session"

        if reason:
            counts[reason] = counts.get(reason, 0) + 1
            continue
        eligible.append(acc)

    summary = _format_summary(counts, len(rows))
    if not eligible:
        return None, summary

    def sort_key(acc):
        credits = _credits_today(acc, today)
        return (
            0 if acc["id"] == assigned_id else 1,
            0 if (credits is not None and credits > 0) else 1,
            -(credits or 0),
            str(acc.get("last_used") or ""),
            acc["id"],
        )

    eligible.sort(key=sort_key)
    return eligible[0], summary
