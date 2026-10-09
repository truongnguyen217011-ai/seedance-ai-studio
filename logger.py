"""Nhật ký tập trung (docs/KIEN_TRUC.md mục 2).

- get_logger(module): logger chuẩn, ghi file logs/studio_YYYY-MM-DD.log (xoay theo ngày) và console.
- log_event(...): ghi cả file lẫn bảng system_logs để giao diện đọc được.
- save_failure_artifacts(page, tag, ...): chụp ảnh + lưu HTML trang khi job lỗi.

Không hàm nào ở đây được phép raise: nhật ký hỏng không được làm hỏng job.
"""
import logging
import logging.handlers
import os
import sys
import threading
from datetime import datetime

import config

_ROOT_NAME = "studio"
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(module_name)s | job=%(job_id)s acc=%(account_id)s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"
_lock = threading.Lock()
_configured = False

# Mức "SUCCESS" của mã cũ không có trong logging chuẩn: ghi file ở mức INFO, giữ nguyên chữ trong CSDL
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "SUCCESS": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class _ContextFilter(logging.Filter):
    """Bổ sung các trường module_name / job_id / account_id nếu bản ghi chưa có."""

    def filter(self, record):
        if not hasattr(record, "module_name"):
            name = record.name
            record.module_name = name.split(".", 1)[1] if "." in name else name
        if getattr(record, "job_id", None) is None:
            record.job_id = "-"
        if getattr(record, "account_id", None) is None:
            record.account_id = "-"
        return True


class DailyFileHandler(logging.handlers.TimedRotatingFileHandler):
    """TimedRotatingFileHandler xoay lúc nửa đêm, nhưng tên file luôn là studio_YYYY-MM-DD.log
    (file đang ghi mang ngày hôm nay thay vì studio.log + hậu tố)."""

    def __init__(self, directory: str):
        self._directory = directory
        super().__init__(self._path_for_today(), when="midnight", encoding="utf-8", utc=False)

    def _path_for_today(self) -> str:
        return os.path.join(self._directory, f"studio_{datetime.now().strftime('%Y-%m-%d')}.log")

    def doRollover(self):
        # Không đổi tên file cũ: chỉ đóng file hôm qua và mở file mang ngày mới
        if self.stream:
            self.stream.close()
            self.stream = None
        self.baseFilename = self._path_for_today()
        if not self.delay:
            self.stream = self._open()
        current = int(datetime.now().timestamp())
        new_rollover = self.computeRollover(current)
        while new_rollover <= current:
            new_rollover += self.interval
        self.rolloverAt = new_rollover


def _configure():
    global _configured
    with _lock:
        if _configured:
            return
        root = logging.getLogger(_ROOT_NAME)
        root.setLevel(logging.DEBUG)
        root.propagate = False
        fmt = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
        ctx = _ContextFilter()

        try:
            os.makedirs(config.LOGS_DIR, exist_ok=True)
            fh = DailyFileHandler(config.LOGS_DIR)
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            fh.addFilter(ctx)
            root.addHandler(fh)
        except OSError as e:
            sys.stderr.write(f"[logger] Không mở được file log trong {config.LOGS_DIR}: {e}\n")

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        ch.addFilter(ctx)
        root.addHandler(ch)
        _configured = True


def get_logger(module: str) -> logging.Logger:
    """Trả về logger con "studio.<module>"; cột module trong file log chính là tên này."""
    _configure()
    return logging.getLogger(f"{_ROOT_NAME}.{module}")


def _write_db(message: str, level: str, module: str, job_id, account_id):
    # Import muộn để tránh vòng import (database.log_event là wrapper của hàm này)
    from database import get_connection
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO system_logs (level, module, message, job_id, account_id) VALUES (?, ?, ?, ?, ?)",
            (level, module, message, job_id, account_id),
        )
        conn.commit()
    finally:
        conn.close()


def log_event(message: str, level: str = "INFO", module: str = "System", job_id=None, account_id=None):
    """Ghi một sự kiện vào file log và bảng system_logs. Không bao giờ raise."""
    level_str = str(level or "INFO").upper()
    try:
        lg = get_logger(module)
        lg.log(
            _LEVEL_MAP.get(level_str, logging.INFO),
            message,
            extra={"module_name": module, "job_id": job_id, "account_id": account_id},
        )
    except Exception as e:  # noqa: BLE001 - nhật ký không được làm hỏng luồng chính
        sys.stderr.write(f"[logger] Ghi file log lỗi: {e}\n")
    try:
        _write_db(message, level_str, module, job_id, account_id)
    except Exception as e:  # noqa: BLE001
        try:
            get_logger("Logger").debug("Ghi system_logs thất bại: %s", e)
        except Exception:  # noqa: BLE001 - đã hết cách ghi, chỉ còn stderr
            sys.stderr.write(f"[logger] Ghi system_logs lỗi: {e}\n")


def save_failure_artifacts(page, tag: str, job_id=None, account_id=None) -> dict:
    """Chụp ảnh toàn trang và lưu HTML vào config.SCREENSHOTS_DIR.

    Trả về {"png": đường dẫn | None, "html": đường dẫn | None, "png_name": tên file | None}.
    Không bao giờ raise: trang có thể đã đóng.
    """
    result = {"png": None, "html": None, "png_name": None, "html_name": None}
    lg = get_logger("Artifacts")
    if page is None:
        return result
    ident = job_id if job_id is not None else (account_id if account_id is not None else "x")
    safe_tag = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(tag or "loi"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{safe_tag}_{ident}_{stamp}"
    try:
        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
    except OSError as e:
        lg.debug("Không tạo được thư mục ảnh chụp: %s", e)
        return result

    png_path = os.path.join(config.SCREENSHOTS_DIR, base + ".png")
    try:
        page.screenshot(path=png_path, full_page=True)
        result["png"] = png_path
        result["png_name"] = os.path.basename(png_path)
    except Exception as e:  # noqa: BLE001
        lg.debug("Chụp ảnh %s thất bại: %s", base, e, extra={"job_id": job_id, "account_id": account_id})

    html_path = os.path.join(config.SCREENSHOTS_DIR, base + ".html")
    try:
        content = page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(content)
        result["html"] = html_path
        result["html_name"] = os.path.basename(html_path)
    except Exception as e:  # noqa: BLE001
        lg.debug("Lưu HTML %s thất bại: %s", base, e, extra={"job_id": job_id, "account_id": account_id})

    if result["png"] or result["html"]:
        lg.info("Đã lưu bằng chứng lỗi: %s", result["png_name"] or result["html_name"],
                extra={"job_id": job_id, "account_id": account_id})
    return result


def artifact_suffix(artifacts: dict) -> str:
    """Chuỗi ' [ảnh: tên file]' để nối vào cuối status_message; rỗng nếu không chụp được."""
    if not artifacts:
        return ""
    name = artifacts.get("png_name") or artifacts.get("html_name")
    return f" [ảnh: {name}]" if name else ""
