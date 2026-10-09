"""
Migration CSDL cũ → mới và reset job mồ côi (docs/KIEN_TRUC.md mục 3, 4; BH-05).

CSDL "cũ" được tạo bằng bản sao database.py ở commit gốc (tests/fixtures/old_database.py; nếu thiếu
thì lấy `git show HEAD:database.py`), rồi chạy database.init_db() + reset_orphans_on_startup() mới.
"""
import importlib.util
import os
import pathlib
import subprocess

import pytest

from constants import LEGACY_JOB_STATUS_MAP, JobStatus, Reason

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "old_database.py"

NEW_ACCOUNT_COLS = ["busy_job_id", "needs_manual", "last_error", "last_ip", "chrome_ok"]
NEW_JOB_COLS = ["batch_name", "seq", "prompt_final", "attempts", "started_at", "finished_at", "ratio", "dola_reply"]
NEW_LOG_COLS = ["job_id", "account_id"]


def _load_old_database_module(tmp_path, db_path):
    src = FIXTURE
    if not src.exists():
        out = tmp_path / "_old_database.py"
        code = subprocess.run(["git", "show", "HEAD:database.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        out.write_text(code, encoding="utf-8")
        src = out
    spec = importlib.util.spec_from_file_location("old_database_for_test", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB_PATH = db_path  # mã cũ hard-code DB cạnh file; trỏ sang CSDL tạm
    return mod


LEGACY_JOBS = [
    ("Đang chờ", "Chờ xử lý"),
    ("Đang xử lý", "Chờ render"),
    ("Lỗi", "Lỗi gì đó"),
    ("Chờ đăng nhập Dola", "Chưa đăng nhập"),
    ("Đang chạy", "Dola AI đang render (12s)..."),
    ("Hoàn thành", "Đã tạo video thành công!"),
]


@pytest.fixture
def old_db(env_tmp, tmp_path):
    """CSDL theo schema cũ + dữ liệu cũ; trả về dict {status_cũ: job_id}."""
    old = _load_old_database_module(tmp_path, env_tmp.db_path)
    old.init_db()
    conn = old.get_connection()
    conn.execute("INSERT INTO accounts (name, fb_uid, status, credits) VALUES ('nick cũ', '100000000000001', 'ready', 3)")
    conn.execute("INSERT INTO accounts (name, fb_uid, status) VALUES ('nick cũ 2', '100000000000002', 'ready')")
    ids = {}
    for status, msg in LEGACY_JOBS:
        cur = conn.execute("INSERT INTO jobs (account_id, prompt, status, status_message) VALUES (1, ?, ?, ?)",
                           (f"prompt {status}", status, msg))
        ids[status] = cur.lastrowid
    conn.execute("INSERT INTO system_logs (level, module, message) VALUES ('INFO', 'System', 'log cũ')")
    conn.commit()
    conn.close()
    # bảo đảm schema cũ thật sự thiếu cột mới
    import sqlite3
    c = sqlite3.connect(env_tmp.db_path)
    cols = {r[1] for r in c.execute("PRAGMA table_info(accounts)")}
    c.close()
    assert "busy_job_id" not in cols
    return ids


def _cols(database, table):
    conn = database.get_connection()
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def _job_status(database, job_id):
    conn = database.get_connection()
    try:
        r = conn.execute("SELECT status, status_message FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return r["status"], r["status_message"]
    finally:
        conn.close()


def test_migration_maps_legacy_statuses_and_adds_columns(old_db, env_tmp):
    import database
    database.init_db()

    # 1) Map trạng thái cũ → mới đúng theo constants.LEGACY_JOB_STATUS_MAP (trước khi reset mồ côi)
    for old_status, new_status in LEGACY_JOB_STATUS_MAP.items():
        st, _ = _job_status(database, old_db[old_status])
        assert st == new_status, f"{old_status!r} phải thành {new_status!r}, đang là {st!r}"
    assert _job_status(database, old_db["Hoàn thành"])[0] == JobStatus.HOAN_THANH
    assert _job_status(database, old_db["Đang chạy"])[0] == JobStatus.DANG_CHAY

    conn = database.get_connection()
    try:
        statuses = {r["status"] for r in conn.execute("SELECT status FROM jobs").fetchall()}
        log_messages = [r["message"] for r in conn.execute("SELECT message FROM system_logs ORDER BY id").fetchall()]
        n_acc = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]
    finally:
        conn.close()
    assert statuses <= set(JobStatus.ALL), f"còn trạng thái lạ: {statuses - set(JobStatus.ALL)}"
    assert log_messages[0] == "log cũ" and n_acc == 2, "migration không được mất dữ liệu cũ"
    # BH-46: CSDL cũ có default_duration "30 giây" (Dola không hỗ trợ) → đổi thành 15 giây, báo đúng 1 dòng INFO
    assert len(log_messages) == 2 and "30 giây" in log_messages[1] and "15 giây" in log_messages[1], log_messages

    # 2) Cột mới tồn tại
    assert set(NEW_ACCOUNT_COLS) <= _cols(database, "accounts")
    assert set(NEW_JOB_COLS) <= _cols(database, "jobs")
    assert set(NEW_LOG_COLS) <= _cols(database, "system_logs")

    # 3) Cài đặt mới có mặt, max_concurrent_jobs là số
    conn = database.get_connection()
    try:
        keys = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings").fetchall()}
    finally:
        conn.close()
    for k in ("max_concurrent_jobs", "chrome_path", "dola_base_url", "default_ratio"):
        assert k in keys, f"thiếu setting {k}"
    assert int(keys["max_concurrent_jobs"]) >= 1
    assert keys["default_duration"] == "15 giây" and keys["default_ratio"] == "16:9"


def test_reset_orphans_after_migration(old_db, env_tmp):
    import database
    database.init_db()
    # giả lập nick đang bị khóa bởi job ma
    conn = database.get_connection()
    conn.execute("UPDATE accounts SET busy_job_id = ? WHERE id = 1", (old_db["Đang chạy"],))
    conn.commit()
    conn.close()

    database.reset_orphans_on_startup()

    for old_status in ("Đang chạy", "Đang xử lý"):
        st, msg = _job_status(database, old_db[old_status])
        assert st == JobStatus.CHO, f"job {old_status!r} phải về Chờ, đang là {st!r}"
        assert Reason.APP_RESTARTED in (msg or ""), f"lý do phải là Reason.APP_RESTARTED, đang là {msg!r}"

    # các job khác không bị đụng
    assert _job_status(database, old_db["Đang chờ"])[0] == JobStatus.CHO
    assert _job_status(database, old_db["Lỗi"])[0] == JobStatus.THAT_BAI
    assert _job_status(database, old_db["Hoàn thành"])[0] == JobStatus.HOAN_THANH

    conn = database.get_connection()
    try:
        busy = conn.execute("SELECT COUNT(*) AS n FROM accounts WHERE busy_job_id IS NOT NULL").fetchone()["n"]
        running = conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE status = ?", (JobStatus.DANG_CHAY,)).fetchone()["n"]
    finally:
        conn.close()
    assert busy == 0 and running == 0


def test_init_db_is_idempotent_and_works_on_fresh_db(env_tmp):
    import database
    database.init_db()
    database.init_db()  # chạy lại không được lỗi (ALTER có kiểm tra cột)
    # BH-46: CSDL mới không bị ghi dòng "đã đổi thời lượng" (chỉ CSDL cũ có 30 giây mới bị ghi đè)
    conn = database.get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM system_logs WHERE message LIKE '%thời lượng mặc định%'").fetchone()["n"]
        dur = conn.execute("SELECT value FROM settings WHERE key = 'default_duration'").fetchone()["value"]
    finally:
        conn.close()
    assert n == 0 and dur == "15 giây"
    assert set(NEW_ACCOUNT_COLS) <= _cols(database, "accounts")
    assert set(NEW_JOB_COLS) <= _cols(database, "jobs")
    assert os.path.exists(env_tmp.db_path)
    assert database.reset_orphans_on_startup() in (0, None)


def test_get_connection_uses_wal_and_timeout(env_tmp):
    import database
    database.init_db()
    conn = database.get_connection()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        conn.close()
    assert str(mode).lower() == "wal"
    assert int(busy) >= 30000
