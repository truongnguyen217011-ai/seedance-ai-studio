"""Kiểm tra môi trường trước khi khởi động Seedance AI Studio.

Chạy bởi KHOI_DONG.bat. Mã thoát:
  0  mọi thứ ổn, có thể chạy server
  1  Python quá cũ hoặc thiếu thư viện không tự cài được
  2  không tìm thấy Chrome/Chromium (chạy CAI_TRINH_DUYET.bat)
"""
import glob
import importlib
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(BASE_DIR, "requirements.txt")
MIN_PYTHON = (3, 10)

# Tên import -> tên gói pip (dùng khi cài lẻ từng gói nếu requirements.txt thiếu)
REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "playwright": "playwright",
    "psutil": "psutil",
    "httpx": "httpx",
}


def _print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        # Console Windows không bật UTF-8: in bản không dấu thay vì chết
        print(msg.encode("ascii", "replace").decode("ascii"))


def check_python() -> bool:
    ver = sys.version_info
    ok = ver >= MIN_PYTHON
    mark = "OK " if ok else "LỖI"
    _print(f"[{mark}] Python {ver.major}.{ver.minor}.{ver.micro} (cần >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")
    if not ok:
        _print("      Tải Python mới tại https://www.python.org/downloads/ rồi cài lại, nhớ tích 'Add python.exe to PATH'.")
    return ok


def missing_modules() -> list:
    missing = []
    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
        except Exception:  # ImportError hoặc lỗi khi nạp gói hỏng
            missing.append(mod)
    return missing


def pip_install(args: list) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", *args]
    _print("      Đang chạy: " + " ".join(cmd))
    try:
        result = subprocess.run(cmd, cwd=BASE_DIR)
        return result.returncode == 0
    except OSError as e:
        _print(f"      Không chạy được pip: {e}")
        return False


def check_libraries() -> bool:
    missing = missing_modules()
    if not missing:
        _print("[OK ] Thư viện Python: " + ", ".join(REQUIRED_MODULES))
        return True

    _print("[...] Thiếu thư viện: " + ", ".join(missing) + " -> tự cài từ requirements.txt")
    if os.path.exists(REQUIREMENTS):
        pip_install(["-r", REQUIREMENTS])
    else:
        _print("      Không thấy requirements.txt, cài trực tiếp từng gói.")

    importlib.invalidate_caches()
    missing = missing_modules()
    if missing:
        # requirements.txt có thể thiếu dòng (BH-01): cài lẻ các gói còn thiếu
        _print("[...] Vẫn thiếu: " + ", ".join(missing) + " -> cài lẻ từng gói")
        pip_install([REQUIRED_MODULES[m] for m in missing])
        importlib.invalidate_caches()
        missing = missing_modules()

    if missing:
        _print("[LỖI] Không cài được: " + ", ".join(missing))
        _print("      Hãy mở cmd tại thư mục này và chạy tay:  python -m pip install -r requirements.txt")
        _print("      Nếu máy không có mạng, tải sẵn gói rồi cài offline.")
        return False

    _print("[OK ] Đã cài đủ thư viện Python.")
    return True


def _fallback_find_chrome():
    """Dò Chrome theo các đường dẫn chuẩn khi chưa import được browser.find_chrome."""
    env = os.environ.get("SEEDANCE_CHROME_PATH", "").strip()
    if env and os.path.isfile(env):
        return env

    candidates = []
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
            candidates.append(os.path.join(base, "Chromium", "Application", "chrome.exe"))
    candidates += [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]

    # Chromium do Playwright cài (CAI_TRINH_DUYET.bat)
    pw_roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")]
    if os.environ.get("LOCALAPPDATA"):
        pw_roots.append(os.path.join(os.environ["LOCALAPPDATA"], "ms-playwright"))
    pw_roots.append(os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright"))
    pw_roots.append(os.path.join(os.path.expanduser("~"), "Library", "Caches", "ms-playwright"))
    for root in pw_roots:
        if not root or not os.path.isdir(root):
            continue
        candidates += sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-win", "chrome.exe")), reverse=True)
        candidates += sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-linux", "chrome")), reverse=True)
        candidates += sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium")), reverse=True)

    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def check_chrome() -> bool:
    path = None
    source = "browser.find_chrome()"
    try:
        sys.path.insert(0, BASE_DIR)
        from browser import find_chrome  # type: ignore
        path = find_chrome()
    except Exception as e:  # chưa có browser.py hoặc import lỗi
        source = f"dò đường dẫn chuẩn (browser.find_chrome không dùng được: {e.__class__.__name__})"
        path = _fallback_find_chrome()

    if path:
        _print(f"[OK ] Chrome: {path}  (theo {source})")
        return True

    _print("[LỖI] Không tìm thấy Google Chrome hay Chromium trên máy.")
    _print("      Cách sửa nhanh nhất: nhấp đúp CAI_TRINH_DUYET.bat (tải Chromium của Playwright, ~150 MB).")
    _print("      Hoặc cài Google Chrome, hoặc vào Cài đặt -> 'Đường dẫn Chrome' trong Studio để chỉ tay file chrome.exe.")
    return False


def main() -> int:
    _print("=== Kiểm tra môi trường Seedance AI Studio ===")
    _print(f"Thư mục: {BASE_DIR}")

    if not check_python():
        return 1
    if not check_libraries():
        return 1
    chrome_ok = check_chrome()

    _print("")
    _print("Tóm tắt: Python OK · Thư viện OK · Chrome " + ("OK" if chrome_ok else "THIẾU"))
    if not chrome_ok:
        return 2
    _print("Môi trường sẵn sàng, đang khởi động server...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
