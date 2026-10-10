"""
Cấu hình pytest chung cho Seedance AI Studio.

CÁCH ĐẶT BIẾN MÔI TRƯỜNG (quan trọng):
`config.py` đọc env ngay lúc import (DATA_DIR, DB_PATH, DOLA_BASE_URL, CHROME_PATH_ENV) và các module khác
thường `from config import X`. Vì vậy env phải được đặt TRƯỚC khi bất kỳ module dự án nào được import.
pytest nạp conftest.py trước khi thu thập các file test, nên cách ổn định nhất là đặt env ngay ở
mức module của conftest (không phải trong fixture) và dùng MỘT thư mục dữ liệu tạm cho cả phiên test.
Cách ly giữa các test không làm bằng đổi env + importlib.reload (dễ lệch bản module giữa
`database`, `worker`, `dola_service`...), mà bằng cách xóa/tạo lại CSDL và dọn outputs/profiles
trước mỗi test (fixture `env_tmp`/`db`). Cổng fake Dola cũng được chọn trước ở đây để
SEEDANCE_DOLA_URL khớp với server khởi động sau.

Có thể ghi đè: SEEDANCE_CHROME_PATH (đường dẫn Chromium), SEEDANCE_TEST_KEEP=1 (giữ lại thư mục tạm),
SEEDANCE_HEADLESS=0 (chạy Chrome cửa sổ ẩn thật, cần DISPLAY, ví dụ `xvfb-run -a python -m pytest tests`).
"""
from __future__ import annotations

import atexit
import os
import pathlib
import shutil
import socket
import sys
import tempfile
import time

import pytest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent

for _p in (str(PROJECT_ROOT), str(TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# PROJECT_ROOT phải đứng trước TESTS_DIR để `import database` lấy đúng bản dự án
sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

_ALREADY = [m for m in ("config", "database", "dola_service", "worker", "browser", "account_pool") if m in sys.modules]
if _ALREADY:  # ai đó import module dự án trước conftest → env không có tác dụng
    raise RuntimeError(f"Module dự án đã được import trước conftest: {_ALREADY}. Chạy `python -m pytest tests` từ thư mục gốc.")


def _free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


FAKE_DOLA_PORT = int(os.environ.get("SEEDANCE_TEST_DOLA_PORT") or _free_port())
def _default_chrome() -> str:
    if sys.platform == "win32":
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                cand = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
                if os.path.exists(cand):
                    return cand
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                pw_path = p.chromium.executable_path
                if pw_path and os.path.exists(pw_path):
                    return pw_path
        except Exception:
            pass
    return "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


SESSION_DATA_DIR = tempfile.mkdtemp(prefix="seedance-tests-")
DEFAULT_CHROME = _default_chrome()

os.environ["SEEDANCE_DATA_DIR"] = SESSION_DATA_DIR
os.environ["SEEDANCE_DB_PATH"] = os.path.join(SESSION_DATA_DIR, "studio.db")
os.environ.setdefault("SEEDANCE_CHROME_PATH", DEFAULT_CHROME)
os.environ["SEEDANCE_DOLA_URL"] = f"http://127.0.0.1:{FAKE_DOLA_PORT}"
# BH-39: app mặc định mở Chrome THẬT với cửa sổ ngoài màn hình (headless bị Dola chặn), nhưng máy test Linux
# không có DISPLAY nên launch headless=False thất bại ("Target page, context or browser has been closed").
# Test chạy headless thật; chế độ cửa sổ ẩn thật được kiểm riêng qua xvfb (tests/test_browser_hidden_xvfb.py).
os.environ.setdefault("SEEDANCE_HEADLESS", "1")


def _cleanup_session_dir() -> None:
    if os.environ.get("SEEDANCE_TEST_KEEP") == "1":
        print(f"\n[tests] giữ lại thư mục tạm: {SESSION_DATA_DIR}")
        return
    shutil.rmtree(SESSION_DATA_DIR, ignore_errors=True)


atexit.register(_cleanup_session_dir)


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: test tích hợp chạy worker thật + Chromium + fake Dola (chậm)")
    config.addinivalue_line("markers", "timeout(seconds): giới hạn thời gian (có tác dụng khi cài pytest-timeout)")


# ---------------------------------------------------------------- fixtures
class EnvTmp:
    def __init__(self):
        self.data_dir = SESSION_DATA_DIR
        self.db_path = os.environ["SEEDANCE_DB_PATH"]
        self.chrome_path = os.environ["SEEDANCE_CHROME_PATH"]
        self.dola_url = os.environ["SEEDANCE_DOLA_URL"]
        self.dola_port = FAKE_DOLA_PORT
        self.outputs_dir = os.path.join(self.data_dir, "outputs")
        self.profiles_dir = os.path.join(self.data_dir, "profiles")
        self.logs_dir = os.path.join(self.data_dir, "logs")

    def wipe_db(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.db_path + suffix)
            except FileNotFoundError:
                pass

    def wipe_dirs(self) -> None:
        for d in (self.outputs_dir, self.profiles_dir):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
        os.makedirs(os.path.join(self.logs_dir, "screenshots"), exist_ok=True)


@pytest.fixture
def env_tmp():
    """Env đã đặt ở mức module; fixture này cung cấp đường dẫn và dọn dữ liệu trước/sau mỗi test."""
    import config  # noqa: F401  (import sau khi env đã đặt)
    assert config.DATA_DIR == SESSION_DATA_DIR, "config.DATA_DIR không trỏ vào thư mục tạm của test"
    assert config.DOLA_BASE_URL == os.environ["SEEDANCE_DOLA_URL"]
    e = EnvTmp()
    e.wipe_db()
    e.wipe_dirs()
    yield e


@pytest.fixture(scope="session")
def _fake_dola_server():
    from fake_dola import start_fake_dola
    fd = start_fake_dola(port=FAKE_DOLA_PORT)
    yield fd
    fd.stop()


@pytest.fixture
def fake_dola(_fake_dola_server):
    """Fake Dola đã reset về mode=normal, render_seconds=2, credits=4 trước mỗi test."""
    _fake_dola_server.reset()
    yield _fake_dola_server
    _fake_dola_server.reset()


@pytest.fixture
def db(env_tmp):
    """CSDL tạm mới tinh (database.init_db()) + helper tạo nick giả / job."""
    from _helpers import DbHelper
    helper = DbHelper(env_tmp)
    helper.init()
    yield helper


@pytest.fixture
def worker_runner(env_tmp, db, fake_dola):
    """Chạy worker.worker_loop thật trong thread riêng; dừng và dọn Chrome còn sót khi test xong."""
    from _helpers import WorkerRunner
    runner = WorkerRunner(env_tmp)
    yield runner
    runner.stop()
    runner.kill_leftover_chrome()
