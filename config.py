"""Cấu hình tập trung. Mọi đường dẫn, URL, Chrome đều lấy từ đây (docs/KIEN_TRUC.md mục 1.6)."""
import os
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Dữ liệu người dùng nằm ngoài phần mã để cập nhật không ghi đè (có thể đổi bằng env)
DATA_DIR = os.environ.get("SEEDANCE_DATA_DIR", BASE_DIR)
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
SCREENSHOTS_DIR = os.path.join(LOGS_DIR, "screenshots")
DB_PATH = os.environ.get("SEEDANCE_DB_PATH", os.path.join(DATA_DIR, "studio.db"))
STATIC_DIR = os.path.join(BASE_DIR, "static")

for _d in (PROFILES_DIR, OUTPUTS_DIR, LOGS_DIR, SCREENSHOTS_DIR):
    os.makedirs(_d, exist_ok=True)

# Dola
DOLA_BASE_URL = os.environ.get("SEEDANCE_DOLA_URL", "https://www.dola.com").rstrip("/")
DOLA_DOMAIN = urlparse(DOLA_BASE_URL).hostname or "dola.com"
DOLA_CHAT_URL = f"{DOLA_BASE_URL}/chat/"

# Chrome: env thắng setting, setting thắng dò tự động (xem browser.find_chrome)
CHROME_PATH_ENV = os.environ.get("SEEDANCE_CHROME_PATH", "")

# Chế độ mở Chrome cho thao tác tự động (job, auto login ẩn, check credit, chẩn đoán) — BH-39:
# Dola chặn Chrome headless bằng captcha ByteDance ngay sau khi gửi prompt, nên mặc định (0) là Chrome THẬT
# với cửa sổ đặt ngoài màn hình (HIDDEN_WINDOW_POSITION). Đặt SEEDANCE_HEADLESS=1 chỉ cho test trên máy
# không có màn hình (Linux CI): khi đó browser.show_window/hide_window là no-op.
HEADLESS = os.environ.get("SEEDANCE_HEADLESS", "0") == "1"
HIDDEN_WINDOW_POSITION = "-32000,-32000"

# Giới hạn mặc định
DEFAULT_MAX_BROWSERS = 6
RENDER_TIMEOUT_SECONDS = 480
LOGIN_TIMEOUT_SECONDS = 180
MAX_AUTO_RETRIES = 2
# Captcha trong lúc chạy job: đưa cửa sổ Chrome ra màn hình và chờ người dùng kéo mảnh ghép chừng này giây
# rồi mới Tạm dừng job (test đặt nhỏ hơn qua monkeypatch)
CAPTCHA_SOLVE_TIMEOUT_SECONDS = 180
# Không đưa được cửa sổ ra màn hình (CDP lỗi, config.HEADLESS): người dùng không thấy gì để kéo, chỉ chờ
# chừng này giây (phòng khi họ tự tìm cửa sổ) rồi Tạm dừng để kéo tay qua nút Chrome (N-4)
CAPTCHA_NO_WINDOW_TIMEOUT_SECONDS = 20


def _read_version() -> str:
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


VERSION = _read_version()
