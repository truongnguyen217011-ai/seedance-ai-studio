"""Mọi Chrome/Chromium của hệ thống đều mở qua module này (docs/KIEN_TRUC.md mục 1.1, 2).

- find_chrome(): dò đường dẫn Chrome theo thứ tự env → setting → đường dẫn chuẩn → Chromium của Playwright.
- BrowserSlots: giới hạn số Chrome đang mở (semaphore đổi được kích thước theo setting max_concurrent_jobs).
- browser_session(...): context manager giữ slot, mở persistent context, đóng và trả slot.
- kill_orphan_chrome(profile_dir): CHỈ gọi lúc khởi động hoặc từ diagnostics khi chắc chắn nick không bận.
- show_window(context, page, account_id=None, title=None) / hide_window(context, page): đưa cửa sổ Chrome ẩn ra
  màn hình (người dùng kéo captcha; xếp bậc thang theo account_id, đặt document.title để nhận ra trên taskbar)
  rồi đặt lại ngoài màn hình, qua CDP Browser.setWindowBounds. No-op khi config.HEADLESS.

Chế độ "ẩn" (BH-39): Dola chặn Chrome headless bằng captcha ngay sau khi gửi prompt, nên thao tác tự động
mặc định dùng Chrome THẬT (headless=False) với cửa sổ đặt ngoài màn hình (--window-position=-32000,-32000).
Chỉ khi config.HEADLESS (SEEDANCE_HEADLESS=1, máy test không có màn hình) mới dùng Playwright headless=True.
"""
import asyncio
import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional, Tuple

import config
from logger import get_logger

log = get_logger("Browser")

_LOCK_FILES = ["SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort", "lockfile"]

_chrome_cache = {"checked": False, "path": None}
_chrome_lock = threading.Lock()


class ChromeNotFoundError(RuntimeError):
    """Không tìm thấy Chrome/Chromium nào để mở."""


def _windows_candidates():
    paths = []
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_key)
        if base:
            paths.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    # Đường dẫn chuẩn phòng khi biến môi trường thiếu
    paths.append(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    paths.append(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
    return paths


def _event_loop_running() -> bool:
    """True nếu luồng hiện tại đang chạy một event loop asyncio (Sync API của Playwright sẽ từ chối)."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _probe_playwright_chromium() -> Tuple[Optional[str], bool]:
    """Hỏi Playwright đường dẫn Chromium. Trả về (đường dẫn | None, dò_sạch).

    dò_sạch=False nghĩa là bước dò KHÔNG chạy được (thiếu playwright, lỗi môi trường), khác với
    "chạy được nhưng Chromium chưa cài" (dò_sạch=True, path None). Chỉ kết quả dò sạch mới được cache (BH-29).
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        log.debug("Không import được playwright: %s", e)
        return None, False
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
    except Exception as e:  # noqa: BLE001 - chỉ là bước dò, không được làm hỏng app
        log.warning("Không hỏi được Playwright về Chromium (sẽ dò lại lần sau): %s", str(e).splitlines()[0][:160])
        return None, False
    if path and os.path.exists(path):
        return path, True
    log.debug("Chromium của Playwright chưa cài (đường dẫn %s không tồn tại)", path)
    return None, True


def _playwright_chromium_path() -> Tuple[Optional[str], bool]:
    """Như _probe_playwright_chromium nhưng an toàn khi gọi từ luồng đang chạy event loop (BH-29).

    Playwright Sync API ném "Sync API inside the asyncio loop" nếu gọi trên luồng event loop; khi đó
    chạy bước dò trong một thread riêng và chờ kết quả.
    """
    if not _event_loop_running():
        return _probe_playwright_chromium()
    result = {}

    def _run():
        try:
            result["value"] = _probe_playwright_chromium()
        except Exception as e:  # noqa: BLE001
            log.warning("Dò Chromium của Playwright trong thread lỗi: %s", e)
            result["value"] = (None, False)

    t = threading.Thread(target=_run, name="chrome-probe", daemon=True)
    t.start()
    t.join(timeout=60)
    if t.is_alive():
        log.warning("Dò Chromium của Playwright quá 60 giây, bỏ qua lần này")
        return None, False
    return result.get("value", (None, False))


def find_chrome(refresh: bool = False) -> Optional[str]:
    """Trả về đường dẫn Chrome dùng được, hoặc None. Kết quả được cache; refresh=True để dò lại.

    Không cache None khi bước dò Chromium của Playwright lỗi vì môi trường (BH-29): lần gọi sau dò lại.
    """
    with _chrome_lock:
        if _chrome_cache["checked"] and not refresh:
            return _chrome_cache["path"]
        clean = True

        found = None
        # 1. Biến môi trường
        if config.CHROME_PATH_ENV:
            if os.path.exists(config.CHROME_PATH_ENV):
                found = config.CHROME_PATH_ENV
            else:
                log.warning("SEEDANCE_CHROME_PATH trỏ tới file không tồn tại: %s", config.CHROME_PATH_ENV)

        # 2. Setting chrome_path trong CSDL
        if not found:
            try:
                from database import get_setting
                setting_path = (get_setting("chrome_path", "") or "").strip()
            except Exception as e:  # noqa: BLE001 - CSDL chưa sẵn sàng thì bỏ qua bước này
                log.debug("Không đọc được setting chrome_path: %s", e)
                setting_path = ""
            if setting_path:
                if os.path.exists(setting_path):
                    found = setting_path
                else:
                    log.warning("Setting chrome_path trỏ tới file không tồn tại: %s", setting_path)

        # 3. Đường dẫn Windows chuẩn
        if not found:
            for cand in _windows_candidates():
                if cand and os.path.exists(cand):
                    found = cand
                    break

        # 4. Chromium của Playwright
        if not found:
            found, clean = _playwright_chromium_path()

        # Chỉ cache khi dò xong sạch; dò lỗi (môi trường) thì lần sau dò lại thay vì kẹt None mãi
        _chrome_cache["checked"] = bool(found) or clean
        _chrome_cache["path"] = found
        if found:
            log.info("Dùng Chrome tại: %s", found)
        else:
            log.warning("Không tìm thấy Chrome hay Chromium nào trên máy")
        return found


def refresh_chrome() -> Optional[str]:
    return find_chrome(refresh=True)


class BrowserSlots:
    """Semaphore đếm số Chrome đang mở, đổi được kích thước lúc chạy.

    Dùng Condition thay vì threading.BoundedSemaphore vì BoundedSemaphore không cho đổi
    giới hạn; ngữ nghĩa giống hệt: acquire chặn khi đã đầy, release trả chỗ.
    """

    def __init__(self, capacity: int):
        self._cond = threading.Condition()
        self._capacity = max(1, int(capacity))
        self._active = 0

    def resize(self, capacity: int) -> None:
        capacity = max(1, int(capacity))
        with self._cond:
            if capacity != self._capacity:
                log.info("Đổi giới hạn Chrome đồng thời: %s → %s", self._capacity, capacity)
                self._capacity = capacity
                self._cond.notify_all()

    def acquire(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while self._active >= self._capacity:
                if deadline is None:
                    self._cond.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._cond.wait(remaining)
            self._active += 1
            return True

    def release(self) -> None:
        with self._cond:
            if self._active > 0:
                self._active -= 1
            self._cond.notify()

    def active_count(self) -> int:
        with self._cond:
            return self._active

    def capacity(self) -> int:
        with self._cond:
            return self._capacity

    def available(self) -> int:
        with self._cond:
            return max(0, self._capacity - self._active)


SLOTS = BrowserSlots(config.DEFAULT_MAX_BROWSERS)


def active_count() -> int:
    return SLOTS.active_count()


def capacity() -> int:
    return SLOTS.capacity()


def available() -> int:
    return SLOTS.available()


def clean_profile_locks(profile_dir: str) -> None:
    """Xóa các file khóa Singleton* còn sót (an toàn khi không có Chrome nào đang dùng profile)."""
    if not profile_dir or not os.path.isdir(profile_dir):
        return
    for lf in _LOCK_FILES:
        lp = os.path.join(profile_dir, lf)
        if os.path.lexists(lp):
            try:
                os.remove(lp)
            except OSError as e:
                log.debug("Không xóa được %s: %s", lp, e)


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path).strip().strip('"').strip("'")))


def _cmdline_uses_profile(cmdline_list, profile_dir: str) -> bool:
    """True nếu dòng lệnh Chrome có `--user-data-dir` trỏ ĐÚNG profile_dir (so bằng, không so chuỗi con).

    BH-28: so chuỗi con (`<đường dẫn> in <cmdline>`) làm `acc_1` khớp cả `acc_10..acc_19`. Chấp nhận các dạng
    `--user-data-dir=<path>`, `--user-data-dir="<path>"`, `--user-data-dir <path>` (hai token), và
    cmdline là một chuỗi duy nhất. So sánh sau normcase/normpath (Windows không phân biệt hoa thường, \\ và /).
    """
    if not profile_dir:
        return False
    target = _norm_path(profile_dir)
    if isinstance(cmdline_list, str):
        cmdline_list = [cmdline_list]
    tokens = []
    for raw in cmdline_list or []:
        raw = str(raw)
        # psutil có thể trả cả dòng lệnh trong một phần tử: tách thô theo khoảng trắng ngoài dấu nháy
        tokens.extend(_split_cmdline_token(raw))
    flag = "--user-data-dir"
    for i, tok in enumerate(tokens):
        if tok.startswith(flag + "="):
            if _norm_path(tok[len(flag) + 1:]) == target:
                return True
        elif tok == flag and i + 1 < len(tokens):
            if _norm_path(tokens[i + 1]) == target:
                return True
    return False


def _split_cmdline_token(raw: str) -> list:
    """Tách một phần tử cmdline thành token: giữ nguyên nếu là một tham số; tách theo khoảng trắng ngoài dấu nháy
    nếu phần tử chứa nhiều tham số (dạng `chrome.exe --a --user-data-dir="C:\\x y\\acc_1" --b`)."""
    if " --" not in raw:
        return [raw]
    out, cur, quote = [], "", None
    for ch in raw:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in ('"', "'"):
            quote = ch
        elif ch.isspace():
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def kill_orphan_chrome(profile_dir: str) -> int:
    """Diệt tiến trình Chrome mồ côi đang giữ profile (chỉ Windows) và dọn file khóa.

    CHỈ được gọi lúc khởi động (chưa có job nào) hoặc từ diagnostics sau khi AccountPool
    xác nhận nick không bận. Trên Linux chỉ dọn file khóa.
    """
    if not profile_dir or not os.path.isdir(profile_dir):
        return 0
    clean_profile_locks(profile_dir)
    if sys.platform != "win32":
        return 0

    killed = 0
    try:
        import psutil
    except ImportError as e:
        log.warning("Thiếu psutil nên không diệt được Chrome mồ côi: %s", e)
        return 0

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            p_name = (proc.info.get("name") or "").lower()
            if "chrome" not in p_name:
                continue
            cmdline = proc.info.get("cmdline") or []
            if _cmdline_uses_profile(cmdline, profile_dir):
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log.debug("Bỏ qua tiến trình %s: %s", proc.pid, e)
    if killed:
        log.info("Đã diệt %s tiến trình Chrome mồ côi của profile %s", killed, profile_dir)
        time.sleep(1)
        clean_profile_locks(profile_dir)
    return killed


def cleanup_profiles_on_startup() -> int:
    """Lúc khởi động (chưa job nào chạy): dọn Chrome mồ côi của mọi profile acc_*."""
    total = 0
    if not os.path.isdir(config.PROFILES_DIR):
        return 0
    for name in os.listdir(config.PROFILES_DIR):
        if name.startswith("acc_"):
            total += kill_orphan_chrome(os.path.join(config.PROFILES_DIR, name))
    return total


def _build_args(hidden: bool, has_proxy: bool) -> list:
    """hidden=True: cửa sổ đặt ngoài màn hình + cờ chống backgrounding; hidden=False: cửa sổ người dùng thấy."""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu-watchdog",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--disable-infobars",
        "--disable-popup-blocking",
    ]
    if hidden:
        args.extend([
            f"--window-position={config.HIDDEN_WINDOW_POSITION}",
            "--window-size=1280,960",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            # Windows: Chrome coi cửa sổ nằm ngoài màn hình là "bị che khuất" (native window occlusion) và
            # ngừng vẽ/giảm ưu tiên tab → trang Dola không chạy JS, captcha/render không tiến. Tắt phép tính đó.
            "--disable-features=CalculateNativeWinOcclusion",
            "--mute-audio",
        ])
    else:
        args.append("--start-maximized")
    if has_proxy:
        args.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")
    else:
        args.append("--force-webrtc-ip-handling-policy=default_public_interface_only")
    return args


def playwright_headless(hidden: bool) -> bool:
    """Chrome có chạy headless thật không: chỉ khi muốn ẩn VÀ config.HEADLESS (máy không có màn hình)."""
    return bool(hidden) and bool(config.HEADLESS)


def launch_context(pw, profile_dir: str, proxy: Optional[dict] = None, headless: bool = True):
    """Mở persistent context (KHÔNG giữ slot). Chỉ browser_session() được gọi hàm này.

    Tham số `headless` giữ tên cũ nhưng nghĩa là **hidden** (ẩn khỏi người dùng), BH-39:
    - headless=True  → config.HEADLESS ? Playwright headless=True : Chrome thật, cửa sổ ngoài màn hình
                       (`--window-position=-32000,-32000 --window-size=1280,960`, đưa ra bằng show_window);
    - headless=False → Chrome thật, `--start-maximized` (người dùng bấm nút Chrome để đăng nhập/kéo captcha).
    """
    hidden = bool(headless)
    chrome = find_chrome()
    if not chrome:
        raise ChromeNotFoundError(
            "Không tìm thấy Google Chrome trên máy. Hãy cài Chrome, hoặc điền đường dẫn chrome.exe "
            "vào Cài đặt (chrome_path), hoặc chạy 'playwright install chromium'."
        )
    os.makedirs(profile_dir, exist_ok=True)
    clean_profile_locks(profile_dir)
    opts = {
        "user_data_dir": profile_dir,
        "headless": playwright_headless(hidden),
        "executable_path": chrome,
        "args": _build_args(hidden, bool(proxy)),
    }
    if proxy:
        opts["proxy"] = proxy
    return pw.chromium.launch_persistent_context(**opts)


def _set_window_bounds(context, page, bounds: dict, what: str) -> bool:
    """Đặt vị trí/trạng thái cửa sổ Chrome chứa `page` qua CDP. Trả True nếu đặt được; lỗi chỉ ghi WARNING."""
    if config.HEADLESS:
        log.debug("config.HEADLESS: không có cửa sổ để %s", what)
        return False
    session = None
    try:
        session = context.new_cdp_session(page)
        win = session.send("Browser.getWindowForTarget")
        window_id = win["windowId"]
        state = (win.get("bounds") or {}).get("windowState")
        # CDP không cho đặt left/top khi cửa sổ đang maximized/minimized: đưa về normal trước
        if state and state != "normal":
            session.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": {"windowState": "normal"}})
        session.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": bounds})
        return True
    except Exception as e:  # noqa: BLE001 - cửa sổ có thể đã đóng; không được làm hỏng job
        log.warning("Không %s được cửa sổ Chrome qua CDP: %s", what, str(e).splitlines()[0][:160])
        return False
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception as e:  # noqa: BLE001
                log.debug("Detach CDP session lỗi: %s", str(e)[:80])


SHOW_WINDOW_BASE = 80       # góc trên-trái của cửa sổ nick đầu tiên
SHOW_WINDOW_STEP = 40       # mỗi nick lệch thêm chừng này px (xếp bậc thang, tối đa 8 bậc)
SHOW_WINDOW_STEPS = 8


def show_window_bounds(account_id=None) -> dict:
    """Vị trí cửa sổ khi đưa ra màn hình: xếp bậc thang theo account_id để nhiều nick cùng đòi captcha
    không đè lên nhau (nick 1 → 120,120; nick 2 → 160,160; ...; None → 80,80)."""
    try:
        step = int(account_id) % SHOW_WINDOW_STEPS if account_id is not None else 0
    except (TypeError, ValueError):
        step = 0
    offset = SHOW_WINDOW_BASE + SHOW_WINDOW_STEP * step
    return {"left": offset, "top": offset, "width": 1280, "height": 960, "windowState": "normal"}


def show_window(context, page, account_id=None, title: Optional[str] = None) -> bool:
    """Đưa cửa sổ Chrome ẩn (ngoài màn hình) ra màn hình và lên trước để người dùng thao tác (kéo captcha).

    account_id: xếp bậc thang (show_window_bounds) để các cửa sổ của nhiều nick không chồng lên nhau.
    title: đặt `document.title` (ví dụ "Nick A — kéo mảnh ghép") TRƯỚC bring_to_front để người dùng nhận ra
    cửa sổ đúng nick trên taskbar; hide_window không cần đặt lại (trang Dola tự đổi title khi điều hướng).
    Trả về True nếu cửa sổ đã được đưa ra; False khi config.HEADLESS (không có cửa sổ) hoặc CDP lỗi (đã ghi log).
    """
    ok = _set_window_bounds(context, page, show_window_bounds(account_id), "đưa ra màn hình")
    if ok:
        if title:
            try:
                page.evaluate("t => { document.title = t; }", str(title))
            except Exception as e:  # noqa: BLE001 - chỉ là tiêu đề, không được làm hỏng bước kéo captcha
                log.warning("Không đặt được tiêu đề cửa sổ '%s': %s", title, str(e).splitlines()[0][:120])
        try:
            page.bring_to_front()
        except Exception as e:  # noqa: BLE001
            log.warning("bring_to_front lỗi: %s", str(e).splitlines()[0][:120])
    return ok


def hide_window(context, page) -> bool:
    """Đặt lại cửa sổ Chrome ra ngoài màn hình (config.HIDDEN_WINDOW_POSITION). No-op khi config.HEADLESS."""
    left, top = (int(v) for v in config.HIDDEN_WINDOW_POSITION.split(","))
    return _set_window_bounds(context, page, {"left": left, "top": top, "windowState": "normal"}, "ẩn")


def slot_wait_message() -> str:
    """Chuỗi hiển thị khi phải chờ chỗ mở Chrome (G-2)."""
    return f"Đang chờ chỗ mở Chrome ({SLOTS.active_count()}/{SLOTS.capacity()} đang dùng)"


@contextmanager
def browser_session(pw, profile_dir: str, proxy: Optional[dict] = None, headless: bool = True,
                    account_id=None, slot_timeout: Optional[float] = None,
                    on_wait: Optional[Callable[[str], None]] = None):
    """Giữ một slot, mở Chrome trên profile_dir, yield context; luôn đóng và trả slot.

    headless=True nghĩa là "ẩn khỏi người dùng" (xem launch_context, BH-39): Chrome thật ngoài màn hình,
    hoặc headless thật khi config.HEADLESS.
    slot_timeout=None: chờ đến khi có slot (không bao giờ vượt quá giới hạn Chrome).
    on_wait(message): được gọi MỘT lần nếu không có slot ngay (job ghi status_message "Đang chờ chỗ mở Chrome (x/N)").
    """
    got = SLOTS.acquire(timeout=0)
    if not got:
        if on_wait is not None:
            try:
                on_wait(slot_wait_message())
            except Exception as e:  # noqa: BLE001 - thông báo chờ không được làm hỏng phiên
                log.debug("on_wait lỗi: %s", e, extra={"account_id": account_id})
        got = SLOTS.acquire(timeout=slot_timeout)
    if not got:
        raise RuntimeError(
            f"Hết chỗ mở Chrome ({SLOTS.capacity()} đang mở), không chờ thêm được nữa"
        )
    context = None
    try:
        log.debug("Mở Chrome (ẩn=%s, headless thật=%s, proxy=%s) cho profile %s", headless,
                  playwright_headless(headless), bool(proxy), os.path.basename(profile_dir),
                  extra={"account_id": account_id})
        context = launch_context(pw, profile_dir, proxy=proxy, headless=headless)
        yield context
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as e:  # noqa: BLE001 - context có thể đã bị đóng
                log.debug("Đóng context lỗi (có thể đã đóng): %s", e, extra={"account_id": account_id})
        SLOTS.release()
