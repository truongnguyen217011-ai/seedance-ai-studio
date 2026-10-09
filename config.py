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

# Giới hạn mặc định
DEFAULT_MAX_BROWSERS = 6
RENDER_TIMEOUT_SECONDS = 480
LOGIN_TIMEOUT_SECONDS = 180
MAX_AUTO_RETRIES = 2


def _read_version() -> str:
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


VERSION = _read_version()
