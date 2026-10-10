"""
Helper dùng chung cho test tích hợp. MỌI chỗ phụ thuộc vào tên hàm/lớp của backend mới
(browser.py, account_pool.py, worker.py, database.py) đều gom ở đây để sau chỉ sửa một chỗ.
"""
from __future__ import annotations

import asyncio
import glob
import inspect
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pytest

from constants import JobStatus

TODAY = datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- CSDL
class DbHelper:
    def __init__(self, env):
        self.env = env
        import database
        self.database = database
        import config
        self.config = config
        self._n_acc = 0
        self._n_job = 0

    # --- khởi tạo
    def init(self):
        self.database.init_db()
        if hasattr(self.database, "reset_orphans_on_startup"):
            self.database.reset_orphans_on_startup()

    def conn(self):
        return self.database.get_connection()

    def exec(self, sql: str, params=()):
        c = self.conn()
        try:
            cur = c.execute(sql, params)
            c.commit()
            return cur.lastrowid
        finally:
            c.close()

    def rows(self, sql: str, params=()) -> List[Dict[str, Any]]:
        c = self.conn()
        try:
            return [dict(r) for r in c.execute(sql, params).fetchall()]
        finally:
            c.close()

    def row(self, sql: str, params=()) -> Optional[Dict[str, Any]]:
        r = self.rows(sql, params)
        return r[0] if r else None

    def columns(self, table: str) -> List[str]:
        return [r["name"] for r in self.rows(f"PRAGMA table_info({table})")]

    # --- dữ liệu giả
    def fake_cookies(self, sessionid: str, domain: Optional[str] = None, days: int = 7) -> str:
        """Cookie JSON kiểu Playwright: sessionid cho host fake Dola (config.DOLA_DOMAIN = 127.0.0.1), hạn tương lai."""
        exp = int(time.time() + days * 86400)
        return json.dumps([{
            "name": "sessionid", "value": sessionid, "domain": domain or self.config.DOLA_DOMAIN,
            "path": "/", "expires": exp, "httpOnly": False, "secure": False, "sameSite": "Lax",
        }])

    def add_account(self, name: Optional[str] = None, *, ready: bool = True, with_session: bool = True,
                    proxy: str = "", **overrides) -> int:
        """Nick facebook, status ready, cookies sessionid domain 127.0.0.1, proxy rỗng. Trả về id."""
        self._n_acc += 1
        n = self._n_acc
        name = name or f"nick{n}"
        sessionid = overrides.pop("sessionid", f"fake-acc-{n}-{int(time.time()) % 100000}")
        row = {
            "account_type": "facebook",
            "name": name,
            "fb_uid": f"1000{n:011d}",
            "proxy": proxy,
            "status": "ready" if ready else "disabled",
            "cookies": self.fake_cookies(sessionid) if with_session else None,
            "credits": None,
        }
        row.update(overrides)
        cols = ", ".join(row.keys())
        marks = ", ".join("?" for _ in row)
        acc_id = self.exec(f"INSERT INTO accounts ({cols}) VALUES ({marks})", tuple(row.values()))
        os.makedirs(os.path.join(self.config.PROFILES_DIR, f"acc_{acc_id}"), exist_ok=True)
        return acc_id

    def account_sessionid(self, acc_id: int) -> str:
        acc = self.account(acc_id)
        return json.loads(acc["cookies"])[0]["value"]

    def add_job(self, prompt: Optional[str] = None, *, status: str = JobStatus.CHO, account_id: Optional[int] = None,
                batch_id: Optional[str] = None, seq: Optional[int] = None, **overrides) -> int:
        self._n_job += 1
        n = self._n_job
        row = {
            "prompt": prompt or f"Con mèo bay qua thành phố ban đêm #{n}",
            "status": status,
            "status_message": overrides.pop("status_message", ""),
            "account_id": account_id,
            "batch_id": batch_id or "batch-test",
            "title": f"Job test {n}",
        }
        if "seq" in self.columns("jobs"):
            row["seq"] = n if seq is None else seq
        row.update(overrides)
        cols = ", ".join(row.keys())
        marks = ", ".join("?" for _ in row)
        return self.exec(f"INSERT INTO jobs ({cols}) VALUES ({marks})", tuple(row.values()))

    def set_setting(self, key: str, value) -> None:
        self.exec("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

    # --- đọc
    def job(self, job_id: int) -> Dict[str, Any]:
        return self.row("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def jobs(self) -> List[Dict[str, Any]]:
        return self.rows("SELECT * FROM jobs ORDER BY id")

    def account(self, acc_id: int) -> Dict[str, Any]:
        return self.row("SELECT * FROM accounts WHERE id = ?", (acc_id,))

    def accounts(self) -> List[Dict[str, Any]]:
        return self.rows("SELECT * FROM accounts ORDER BY id")

    def running_jobs(self) -> List[Dict[str, Any]]:
        return self.rows("SELECT id, account_id FROM jobs WHERE status = ?", (JobStatus.DANG_CHAY,))

    def system_logs(self) -> List[Dict[str, Any]]:
        return self.rows("SELECT * FROM system_logs ORDER BY id")

    def video_file(self, job: Dict[str, Any]) -> Optional[str]:
        """Dựng đường dẫn file mp4 từ local_video_path (BH-13: tương đối so với OUTPUTS_DIR; chấp nhận cả '/outputs/x.mp4' và tuyệt đối)."""
        p = job.get("local_video_path")
        if not p:
            return None
        cands = []
        if os.path.isabs(p):
            cands.append(p)
        rel = p.lstrip("/")
        if rel.startswith("outputs/"):
            rel = rel[len("outputs/"):]
        cands.append(os.path.join(self.config.OUTPUTS_DIR, rel))
        cands.append(os.path.join(self.config.OUTPUTS_DIR, os.path.basename(p)))
        for c in cands:
            if os.path.isfile(c):
                return c
        return None


# ---------------------------------------------------------------- chờ điều kiện
def wait_until(cond: Callable[[], Any], timeout: float, interval: float = 0.25, what: str = "điều kiện") -> Any:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = cond()
        if last:
            return last
        time.sleep(interval)
    pytest.fail(f"Hết {timeout}s vẫn chưa đạt {what} (giá trị cuối: {last!r})")


def wait_jobs_finished(db: DbHelper, job_ids: List[int], timeout: float, interval: float = 0.5) -> Dict[int, Dict[str, Any]]:
    """Chờ tất cả job rời khỏi Chờ/Đang chạy."""
    def done():
        js = {j["id"]: j for j in db.jobs() if j["id"] in job_ids}
        if all(j["status"] not in (JobStatus.CHO, JobStatus.DANG_CHAY) for j in js.values()):
            return js
        return None
    return wait_until(done, timeout, interval, what=f"các job {job_ids} kết thúc")


# ---------------------------------------------------------------- browser slots (tên API chưa chốt → dò)
def get_active_browser_count() -> Optional[int]:
    try:
        import browser
    except ImportError:
        return None
    for getter in (
        lambda: browser.active_count(),
        lambda: browser.BrowserSlots.active_count(),
        lambda: browser.slots.active_count(),
        lambda: browser.SLOTS.active_count(),
        lambda: browser.get_slots().active_count(),
        lambda: browser.BrowserSlots.instance().active_count(),
    ):
        try:
            v = getter()
            if isinstance(v, int):
                return v
        except Exception:
            continue
    return None


# ---------------------------------------------------------------- account pool (tên API chưa chốt → dò)
def get_pool():
    import account_pool
    for name in ("pool", "POOL", "account_pool", "PoolInstance"):
        obj = getattr(account_pool, name, None)
        if obj is not None and hasattr(obj, "acquire"):
            return obj
    for name in ("get_pool", "instance", "get_instance"):
        fn = getattr(account_pool, name, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    cls = getattr(account_pool, "AccountPool", None)
    if cls is None:
        pytest.skip("account_pool.AccountPool chưa có")
    for name in ("get", "instance", "get_instance"):  # singleton (account_pool.AccountPool.get())
        fn = getattr(cls, name, None)
        if callable(fn):
            try:
                obj = fn()
                if hasattr(obj, "acquire"):
                    return obj
            except Exception:
                pass
    try:
        return cls()
    except TypeError:
        return cls


def pool_acquire(pool, account_id: int, job_id: int) -> bool:
    fn = pool.acquire
    try:
        return bool(fn(account_id, job_id))
    except TypeError:
        return bool(fn(account_id, job_id=job_id))


def pool_release(pool, account_id: int, job_id: Optional[int] = None) -> None:
    fn = pool.release
    try:
        fn(account_id)
    except TypeError:
        fn(account_id, job_id)


def pool_is_busy(pool, account_id: int) -> bool:
    return bool(pool.is_busy(account_id))


def pool_reset(pool) -> None:
    """Xóa trạng thái bộ nhớ giữa các test (singleton)."""
    for name in ("reset", "clear", "release_all"):
        fn = getattr(pool, name, None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:
                continue
    for attr in ("_busy", "busy", "_locks", "locks"):
        d = getattr(pool, attr, None)
        if isinstance(d, dict):
            d.clear()


def select_account(pool, job: Dict[str, Any], excluded=None):
    """select_account_for_job(job, excluded=None) → (account_dict | None, summary_str). Thử method rồi hàm module."""
    import account_pool
    fn = getattr(pool, "select_account_for_job", None) or getattr(account_pool, "select_account_for_job", None)
    if fn is None:
        pytest.skip("select_account_for_job chưa có")
    res = fn(job, excluded) if excluded is not None else fn(job)
    if isinstance(res, tuple) and len(res) == 2:
        return res
    return res, ""


# ---------------------------------------------------------------- worker
class WorkerRunner:
    """Chạy worker.worker_loop() thật trong thread (asyncio loop riêng). Dừng bằng stop()."""

    def __init__(self, env):
        self.env = env
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.error: Optional[BaseException] = None
        import worker
        self.worker = worker

    def start(self) -> "WorkerRunner":
        w = self.worker
        if hasattr(w, "is_running"):
            w.is_running = True
        ev = getattr(w, "stop_event", None)
        if ev is not None and hasattr(ev, "clear"):
            ev.clear()
        loop_fn = getattr(w, "worker_loop")

        def run():
            try:
                if inspect.iscoroutinefunction(loop_fn):
                    self.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self.loop)
                    self.loop.run_until_complete(loop_fn())
                else:
                    loop_fn()
            except BaseException as e:  # noqa: BLE001
                self.error = e

        self.thread = threading.Thread(target=run, name="test-worker", daemon=True)
        self.thread.start()
        return self

    def stop(self, timeout: float = 30.0) -> None:
        w = self.worker
        for name in ("stop_worker", "stop", "request_stop"):
            fn = getattr(w, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
        if hasattr(w, "is_running"):
            w.is_running = False
        ev = getattr(w, "stop_event", None)
        if ev is not None and hasattr(ev, "set"):
            ev.set()
        if self.thread:
            self.thread.join(timeout=timeout)

    def kill_leftover_chrome(self) -> None:
        """Chỉ giết Chromium có user-data-dir nằm trong thư mục tạm của test (không đụng Chrome khác)."""
        try:
            subprocess.run(["pkill", "-f", f"user-data-dir={self.env.profiles_dir}"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass


# ---------------------------------------------------------------- lấy mẫu độ đồng thời
class Sampler:
    """Thread lấy mẫu mỗi `interval` giây: số job Đang chạy, trùng account_id, active_count() của BrowserSlots."""

    def __init__(self, db: DbHelper, interval: float = 0.2):
        self.db = db
        self.interval = interval
        self.max_running = 0
        self.max_active = 0
        self.active_seen = False
        self.duplicate_account_samples: List[List[Dict[str, Any]]] = []
        self.accounts_used: set = set()
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="sampler")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self.thread.join(timeout=5)

    def _run(self):
        while not self._stop.is_set():
            try:
                running = self.db.running_jobs()
                self.max_running = max(self.max_running, len(running))
                ids = [r["account_id"] for r in running if r["account_id"] is not None]
                self.accounts_used.update(ids)
                if len(ids) != len(set(ids)):
                    self.duplicate_account_samples.append(running)
                a = get_active_browser_count()
                if a is not None:
                    self.active_seen = True
                    self.max_active = max(self.max_active, a)
            except Exception:
                pass
            time.sleep(self.interval)


# ---------------------------------------------------------------- log
def log_files(env) -> List[str]:
    return sorted(glob.glob(os.path.join(env.logs_dir, "*.log")))


def log_offsets(env) -> Dict[str, int]:
    return {p: os.path.getsize(p) for p in log_files(env)}


def new_log_text(env, offsets: Dict[str, int]) -> str:
    out = []
    for p in log_files(env):
        start = offsets.get(p, 0)
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            f.seek(start)
            out.append(f.read())
    return "\n".join(out)


def conv_id_in_mp4(path: str) -> Optional[str]:
    with open(path, "rb") as f:
        head = f.read(128)
    m = re.search(rb"conv=(\d+);", head)
    return m.group(1).decode() if m else None


def future_ts(minutes: int = 60) -> str:
    return (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
