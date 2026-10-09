"""Cơ sở dữ liệu SQLite (docs/KIEN_TRUC.md mục 1.7, 1.8, 3).

Mọi nơi khác chỉ được mở CSDL qua get_connection(). Thay đổi schema chỉ bằng migration trong init_db().
"""
import sqlite3
from datetime import datetime

import config
from constants import (DEFAULT_DURATION, DEFAULT_RATIO, DURATION_MAX_SECONDS, DURATION_MIN_SECONDS, JobStatus,
                       LEGACY_JOB_STATUS_MAP, Reason, normalize_duration)

# Giữ tên cũ để mã cũ còn tham chiếu database.DB_PATH không vỡ
DB_PATH = config.DB_PATH


def get_connection() -> sqlite3.Connection:
    """Kết nối SQLite dùng chung: timeout 30s, WAL, busy_timeout, khóa ngoại, row_factory=Row."""
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_columns(cursor, table: str) -> set:
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(cursor, table: str, column: str, decl: str) -> bool:
    """Thêm cột nếu chưa có (kiểm bằng PRAGMA table_info). Trả về True nếu vừa thêm."""
    if column in _table_columns(cursor, table):
        return False
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    return True


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # ---- Tạo bảng (CSDL mới) ----
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_type TEXT DEFAULT 'facebook',
        name TEXT NOT NULL,
        email TEXT,
        fb_uid TEXT,
        proxy TEXT,
        status TEXT DEFAULT 'ready',
        profile_dir TEXT,
        cookies TEXT,
        credits INTEGER,
        last_used TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        title TEXT,
        prompt TEXT NOT NULL,
        model TEXT DEFAULT 'Seedance 2.5',
        duration TEXT DEFAULT '{DEFAULT_DURATION}',
        ratio TEXT,
        status TEXT DEFAULT '{JobStatus.CHO}',
        status_message TEXT DEFAULT '',
        progress INTEGER DEFAULT 0,
        video_url TEXT,
        local_video_path TEXT,
        reference_image TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    """)

    # Bảng ảnh / asset giữ nguyên (giai đoạn 5 mới gỡ)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        prompt TEXT NOT NULL,
        model TEXT DEFAULT 'Seedance Image 2.5',
        aspect_ratio TEXT DEFAULT '16:9',
        style TEXT DEFAULT 'Cinematic',
        status TEXT DEFAULT 'Hoàn thành',
        image_url TEXT,
        local_image_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        character_code TEXT,
        image_url TEXT,
        description TEXT,
        tags TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level TEXT DEFAULT 'INFO',
        module TEXT DEFAULT 'System',
        message TEXT NOT NULL,
        job_id INTEGER,
        account_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # ---- Migration cột cho CSDL cũ ----
    account_columns = [
        ("account_type", "TEXT DEFAULT 'facebook'"),
        ("email", "TEXT"),
        ("fb_pass", "TEXT"),
        ("fb_2fa", "TEXT"),
        ("login_method", "TEXT DEFAULT 'facebook'"),
        ("session_expires", "TIMESTAMP"),
        ("last_check", "TIMESTAMP"),
        ("credits_date", "TEXT"),
        ("rest_until", "TIMESTAMP"),
        ("rest_reason", "TEXT"),
        ("tokens_balance", "INTEGER"),
        ("otp_key", "TEXT"),
        ("mail_provider", "TEXT DEFAULT 'dongvanfb'"),
        # Giai đoạn 1 (KIEN_TRUC.md mục 3)
        ("busy_job_id", "INTEGER"),
        ("needs_manual", "TEXT"),
        ("last_error", "TEXT"),
        ("last_ip", "TEXT"),
        ("chrome_ok", "INTEGER"),
        # Số lần lỗi kết nối Dola liên tiếp (chưa vào được trang); về 0 khi nick vào được trang (KIEN_TRUC.md mục 4)
        ("consecutive_errors", "INTEGER DEFAULT 0"),
    ]
    for col, decl in account_columns:
        _add_column_if_missing(cursor, "accounts", col, decl)

    job_columns = [
        ("batch_id", "TEXT"),
        ("clip_index", "INTEGER"),
        ("character_name", "TEXT"),
        ("scene_description", "TEXT"),
        # Giai đoạn 1
        ("batch_name", "TEXT"),
        ("seq", "INTEGER"),
        ("prompt_final", "TEXT"),
        ("attempts", "INTEGER DEFAULT 0"),
        ("started_at", "TIMESTAMP"),
        ("finished_at", "TIMESTAMP"),
        # Giai đoạn 4: mã trường phái Đạo diễn AI đã dùng khi ghép prompt_final (docs/KIEN_TRUC.md mục 8)
        ("archetype_code", "TEXT"),
        # BH-46: tỷ lệ khung hình là tham số thật của job (Dola hỏi lại nếu prompt không nói)
        ("ratio", "TEXT"),
        # BH-47: câu trả lời bằng chữ cuối cùng của Dola trong lúc chờ render (hiện trong modal Prompt)
        ("dola_reply", "TEXT"),
    ]
    for col, decl in job_columns:
        _add_column_if_missing(cursor, "jobs", col, decl)

    _add_column_if_missing(cursor, "system_logs", "job_id", "INTEGER")
    _add_column_if_missing(cursor, "system_logs", "account_id", "INTEGER")

    # ---- Migration trạng thái job cũ → 5 trạng thái chuẩn ----
    for old_status, new_status in LEGACY_JOB_STATUS_MAP.items():
        cursor.execute("UPDATE jobs SET status = ? WHERE status = ?", (new_status, old_status))
    cursor.execute("UPDATE jobs SET attempts = 0 WHERE attempts IS NULL")

    # ---- Cài đặt mặc định (giữ giá trị người dùng đã có) ----
    defaults = {
        "max_concurrent_jobs": str(config.DEFAULT_MAX_BROWSERS),
        "chrome_path": "",
        "dola_base_url": "",
        "default_model": "Seedance 2.5",
        "default_duration": DEFAULT_DURATION,
        "default_ratio": DEFAULT_RATIO,
        "proxy_type": "http",
        "auto_download": "true",
        "delay_between_jobs": "5",
    }
    # Đạo diễn AI (director.SETTING_DEFAULTS): bật/tắt từng lớp mẫu ghép vào prompt, trường phái mặc định
    from director import SETTING_DEFAULTS as _DIRECTOR_DEFAULTS
    defaults.update(_DIRECTOR_DEFAULTS)
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    # BH-46: bản cũ mặc định "30 giây" nhưng Dola chỉ hỗ trợ 4-15 giây → ghi đè giá trị ngoài khoảng, báo một dòng INFO
    notices = []
    row = cursor.execute("SELECT value FROM settings WHERE key = 'default_duration'").fetchone()
    old_duration = row["value"] if row is not None else None
    seconds, warning = normalize_duration(old_duration)
    if warning:
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'default_duration'", (DEFAULT_DURATION,))
        notices.append(f"Cài đặt thời lượng mặc định '{old_duration}' ngoài khoảng Dola hỗ trợ "
                       f"({DURATION_MIN_SECONDS}-{DURATION_MAX_SECONDS} giây), đã đổi thành '{DEFAULT_DURATION}'")

    conn.commit()
    conn.close()
    # Ghi log SAU khi đóng kết nối (log_event mở kết nối riêng để ghi system_logs, tránh chờ khóa WAL)
    for msg in notices:
        log_event(msg, "INFO", "Database")


def reset_orphans_on_startup() -> int:
    """Lúc khởi động: job 'Đang chạy' mồ côi → 'Chờ', bỏ khóa nick. Trả về số job đã reset."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE jobs SET status = ?, status_message = ?, progress = 0, updated_at = CURRENT_TIMESTAMP WHERE status = ?",
            (JobStatus.CHO, Reason.APP_RESTARTED, JobStatus.DANG_CHAY),
        )
        reset_count = cur.rowcount if cur.rowcount is not None else 0
        conn.execute("UPDATE accounts SET busy_job_id = NULL WHERE busy_job_id IS NOT NULL")
        conn.commit()
    finally:
        conn.close()
    return reset_count


def get_setting(key: str, default=None):
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    if row is None or row["value"] is None:
        return default
    return row["value"]


def get_int_setting(key: str, default: int) -> int:
    raw = get_setting(key, None)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
    finally:
        conn.close()


def log_event(message: str, level: str = "INFO", module: str = "System", job_id=None, account_id=None):
    """Wrapper giữ tương thích với mã cũ; việc ghi thật nằm ở logger.log_event."""
    import logger as _logger  # import muộn để tránh vòng import
    _logger.log_event(message, level, module, job_id=job_id, account_id=account_id)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully!")
