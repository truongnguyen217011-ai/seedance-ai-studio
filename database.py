import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "studio.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Bảng tài khoản (Facebook Clone/Via hoặc Google Account + Proxy)
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
        credits INTEGER DEFAULT 0,
        last_used TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Safe migrations for existing databases
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN account_type TEXT DEFAULT 'facebook'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN email TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN fb_pass TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN fb_2fa TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN login_method TEXT DEFAULT 'facebook'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN session_expires TIMESTAMP")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN last_check TIMESTAMP")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN credits_date TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN rest_until TIMESTAMP")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN rest_reason TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN tokens_balance INTEGER DEFAULT 1000000000")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN otp_key TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN mail_provider TEXT DEFAULT 'dongvanfb'")
    except Exception:
        pass

    # Safe migrations for jobs
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN batch_id TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN clip_index INTEGER")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN character_name TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN scene_description TEXT")
    except Exception:
        pass
    
    # Bảng Hàng đợi Jobs (Tạo video)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        title TEXT,
        prompt TEXT NOT NULL,
        model TEXT DEFAULT 'Seedance 2.5',
        duration TEXT DEFAULT '30 giây',
        status TEXT DEFAULT 'Đang chờ',
        status_message TEXT DEFAULT 'Chờ xử lý',
        progress INTEGER DEFAULT 0,
        video_url TEXT,
        local_video_path TEXT,
        reference_image TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    """)

    # Bảng Hàng đợi Tạo Ảnh
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
    
    # Bảng Kho Nhân Vật & Assets
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

    # Bảng Nhật ký hệ thống (System Logs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level TEXT DEFAULT 'INFO',
        module TEXT DEFAULT 'System',
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Bảng Cài đặt
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    
    # Cài đặt mặc định
    defaults = {
        "max_concurrent_jobs": "5",
        "default_model": "Seedance 2.5",
        "default_duration": "30 giây",
        "proxy_type": "http",
        "auto_download": "true",
        "delay_between_jobs": "5"
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    conn.commit()
    conn.close()

def log_event(message: str, level: str = "INFO", module: str = "System"):
    try:
        conn = get_connection()
        conn.execute("INSERT INTO system_logs (level, module, message) VALUES (?, ?, ?)", (level, module, message))
        conn.commit()
        conn.close()
    except Exception:
        pass

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully!")
