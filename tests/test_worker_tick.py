"""
Test vòng quét worker (gọi `_tick()` trực tiếp, không Chrome trừ N-3 dùng worker thật nhưng không có Chrome):
BH-27 (job đã điều phối không bao giờ kẹt), N-3 (không có Chrome → không điều phối, lý do rõ),
N-6 (dùng lại kết quả chọn nick trong một vòng quét).
"""
from __future__ import annotations

import time

import pytest

from constants import JobStatus, Reason
from _helpers import log_offsets, new_log_text

worker = pytest.importorskip("worker", reason="worker.py chưa có")


@pytest.fixture
def clean_worker(db):
    from account_pool import AccountPool
    worker._running_jobs.clear()
    AccountPool.get().clear()
    worker._last_no_chrome_warn = 0.0
    yield worker
    worker._running_jobs.clear()
    AccountPool.get().clear()


# ---------------------------------------------------------------- BH-27
def test_bh27_tick_returns_dispatched_jobs_when_recover_accounts_raises(db, clean_worker, monkeypatch):
    from account_pool import AccountPool
    acc_id = db.add_account("nick A")
    job_id = db.add_job("job BH-27")

    def boom(conn):
        raise RuntimeError("database is locked (giả lập)")

    monkeypatch.setattr(worker, "_recover_accounts", boom)
    to_start = worker._tick()

    assert to_start == [(job_id, acc_id)], "BH-27: job đã điều phối phải được trả về để khởi chạy dù _recover_accounts ném"
    job = db.job(job_id)
    assert job["status"] == JobStatus.DANG_CHAY and job["account_id"] == acc_id and job["attempts"] == 1
    assert AccountPool.get().holder(acc_id) == job_id
    assert job_id in worker.running_job_ids()


def test_bh27_tick_rolls_back_when_connection_close_raises(db, clean_worker, monkeypatch):
    """Lỗi ở bước SAU điều phối mà không có except riêng (ví dụ đóng kết nối) → job về Chờ, nick rảnh, không kẹt."""
    from account_pool import AccountPool
    acc_id = db.add_account("nick B")
    job_id = db.add_job("job BH-27 rollback")
    real = worker.get_connection
    opened = []

    class BrokenClose:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def close(self):
            raise RuntimeError("close thất bại (giả lập)")

    def fake_get_connection():
        conn = real()
        opened.append(conn)
        return BrokenClose(conn)

    monkeypatch.setattr(worker, "get_connection", fake_get_connection)
    try:
        to_start = worker._tick()
    finally:
        monkeypatch.setattr(worker, "get_connection", real)
        for c in opened:
            c.close()

    assert to_start == [], "BH-27: vòng quét lỗi sau điều phối phải rollback và trả []"
    job = db.job(job_id)
    assert job["status"] == JobStatus.CHO, job
    assert job["attempts"] == 0, job
    assert job["started_at"] is None
    assert not AccountPool.get().is_busy(acc_id)
    assert db.account(acc_id)["busy_job_id"] is None
    assert job_id not in worker.running_job_ids()

    # Vòng quét sau (bình thường) nhặt lại được job
    to_start = worker._tick()
    assert to_start == [(job_id, acc_id)]
    assert db.job(job_id)["status"] == JobStatus.DANG_CHAY


def test_bh27_rollback_dispatched_helper(db, clean_worker):
    from account_pool import AccountPool
    acc_id = db.add_account("nick C")
    job_id = db.add_job("job BH-27 helper")
    conn = db.conn()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert worker._dispatch_one(conn, row, worker.TickCache()) == acc_id
    finally:
        conn.close()
    assert db.job(job_id)["status"] == JobStatus.DANG_CHAY and AccountPool.get().is_busy(acc_id)

    worker._rollback_dispatched([(job_id, acc_id)])
    job = db.job(job_id)
    assert job["status"] == JobStatus.CHO and job["attempts"] == 0
    assert not AccountPool.get().is_busy(acc_id) and job_id not in worker.running_job_ids()


# ---------------------------------------------------------------- N-3
@pytest.mark.integration
@pytest.mark.timeout(60)
def test_n3_no_chrome_blocks_dispatch_with_reason(db, fake_dola, env_tmp, clean_worker, monkeypatch, worker_runner):
    import browser
    monkeypatch.setattr(browser, "find_chrome", lambda refresh=False: None)
    acc_id = db.add_account("nick đủ điều kiện")
    job_id = db.add_job("job không có Chrome")
    offsets = log_offsets(env_tmp)

    worker_runner.start()
    time.sleep(5)

    job = db.job(job_id)
    assert job["status"] == JobStatus.CHO, job
    assert job["attempts"] == 0, job
    assert "Không tìm thấy" in (job["status_message"] or ""), job["status_message"]
    assert "CAI_TRINH_DUYET.bat" in job["status_message"]
    assert db.account(acc_id)["busy_job_id"] is None
    assert fake_dola.get_state()["total_requests"] == 0
    assert worker.worker_alive()

    text = new_log_text(env_tmp, offsets)
    warn_lines = [ln for ln in text.splitlines() if "worker không chạy job nào cho đến khi có Chrome" in ln]
    assert len(warn_lines) == 1, f"WARNING 'không có Chrome' phải ghi đúng 1 lần/60 s, thấy {len(warn_lines)}"

    # status_message chỉ ghi khi đổi: updated_at không nhảy giữa hai vòng quét
    first = db.job(job_id)["updated_at"]
    time.sleep(3)
    assert db.job(job_id)["updated_at"] == first


# ---------------------------------------------------------------- N-6
def test_n6_select_account_called_once_per_tick_when_no_account(db, clean_worker, monkeypatch):
    db.add_account("nick chưa login", with_session=False)
    job_ids = [db.add_job(f"job {i}") for i in range(10)]
    real = worker.select_account_for_job
    calls = {"n": 0}

    def counting(job_row, excluded=None, session_cache=None):
        calls["n"] += 1
        return real(job_row, excluded, session_cache=session_cache)

    monkeypatch.setattr(worker, "select_account_for_job", counting)
    assert worker._tick() == []
    assert calls["n"] == 1, f"N-6: select_account_for_job phải gọi 1 lần cho cả tick, gọi {calls['n']} lần"
    for jid in job_ids:
        msg = db.job(jid)["status_message"] or ""
        assert Reason.WAITING_ACCOUNT.split(":")[0] in msg and "chưa đăng nhập Dola" in msg, msg

    # Vòng quét sau: nội dung không đổi → không ghi lại (updated_at giữ nguyên)
    before = {jid: db.job(jid)["updated_at"] for jid in job_ids}
    time.sleep(1.1)
    assert worker._tick() == []
    assert {jid: db.job(jid)["updated_at"] for jid in job_ids} == before


def test_n6_session_cache_reused_within_tick(db, clean_worker, monkeypatch):
    import dola_service
    from account_pool import select_account_for_job
    for i in range(3):
        db.add_account(f"nick {i}", with_session=False)
    job = db.job(db.add_job("job cache"))
    real = dola_service.account_has_dola_session
    calls = {"n": 0}

    def counting(acc):
        calls["n"] += 1
        return real(acc)

    monkeypatch.setattr(dola_service, "account_has_dola_session", counting)
    cache = {}
    acc, summary = select_account_for_job(job, session_cache=cache)
    assert acc is None and "3 nick chưa đăng nhập Dola" in summary
    acc, _ = select_account_for_job(job, session_cache=cache)
    assert acc is None
    assert calls["n"] == 3, f"has_dola_session phải đọc mỗi nick 1 lần trong tick, gọi {calls['n']} lần"
    # Không cache → đọc lại
    select_account_for_job(job)
    assert calls["n"] == 6
