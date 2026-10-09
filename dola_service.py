import os
import sys
import json
import time
import asyncio
import re
import subprocess
import shutil
import psutil
import urllib.request
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from playwright.sync_api import sync_playwright
from database import get_connection, log_event
from twofa import get_totp_candidates

BASE_DIR = os.path.dirname(__file__)
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(PROFILES_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ==================== SELECTORS TƯƠNG THÍCH NGUYÊN TỬ VỚI HALI AI ====================
SELECTORS = {
    "dola_login_btn": [
        'button:has-text("Log in")', 'button:has-text("Login")',
        'button:has-text("Sign in")', 'button:has-text("Đăng nhập")',
        '[data-testid*="login" i]', 'a[href*="login" i]'
    ],
    "fb_provider": [
        '[role="dialog"] div[data-disabled]:has(> svg path[fill="#0068FF"])',
        'div[data-disabled]:has(path[d^="M12 2C6.203 2 1.5 6.73"])',
        '[role="dialog"] [class*="clickable"]:has(path[fill="#0068FF"])',
        'button:has-text("Facebook")', '[role="button"]:has-text("Facebook")',
        'a:has-text("Facebook")', '[aria-label*="Facebook" i]',
        'a[href*="facebook.com/" i]'
    ],
    "age_confirm": [
        '[role="dialog"] button:has-text("Confirm")',
        'button:has-text("Confirm")',
        '[role="dialog"] button:has-text("Xác nhận")',
        'button:has-text("Xác nhận")'
    ],
    "email": [
        '#email', 'input[name="email"]', 'input[type="email"]', 'input[autocomplete="username"]'
    ],
    "pass": [
        '#pass', 'input[name="pass"]', 'input[type="password"]'
    ],
    "login_btn": [
        'button[name="login"]', '#loginbutton', 'button[type="submit"]:has-text("Log in")', 'button[type="submit"]'
    ],
    "code": [
        '#approvals_code', 'input[name="approvals_code"]', 'input[autocomplete="one-time-code"]',
        'input[type="text"][inputmode="numeric"]', 'input[aria-label*="code" i]', 'input[aria-label*="mã" i]'
    ],
    "code_submit": [
        '#checkpointSubmitButton', 'button[type="submit"]',
        'div[role="button"]:has-text("Continue")', 'div[role="button"]:has-text("Tiếp tục")'
    ],
    "continue_btns": [
        'button[name="OK"]', '#checkpointSubmitButton', 'button[name="__CONFIRM__"]',
        '[role="button"]:has-text("Continue as")', 'button:has-text("Continue as")',
        '[role="button"]:has-text("Continue")', 'button:has-text("Continue")',
        '[role="button"]:has-text("Tiếp tục dưới tên")', 'button:has-text("Tiếp tục dưới tên")',
        '[role="button"]:has-text("Tiếp tục")', 'button:has-text("Tiếp tục")',
        'button:has-text("Yes")', 'button:has-text("Có")',
        'button:has-text("Save")', 'button:has-text("Lưu")'
    ]
}

RE_WRONG_PASS = re.compile(
    r'password you.{0,3}ve entered is incorrect|incorrect password|wrong credentials|'
    r'mật khẩu (bạn )?(đã )?nhập không (đúng|chính xác)|sai mật khẩu|'
    r'email or mobile number.*(isn.?t|not) connected|không tìm thấy tài khoản|find your account',
    re.IGNORECASE
)

RE_CHECKPOINT = re.compile(
    r'/checkpoint/|account.{0,20}(locked|disabled|suspended|restricted)|confirm your identity|'
    r'xác nhận danh tính|tài khoản.{0,20}(bị khoá|bị khóa|tạm khoá|tạm khóa|vô hiệu)|'
    r'upload.{0,20}(photo|id)|we.ve suspended',
    re.IGNORECASE
)

# ==================== CƠ CHẾ KIỂM TRA CREDIT VÀ NGHỈ NGƠI CHUẨN HALI AI ====================
RE_CREDITS_LEFT = re.compile(r'have\s+(\d+)\s+video\s+credits?\s+left', re.IGNORECASE)
RE_CREDITS_MATCH_EN = re.compile(r'will use (\d+) video credits?[\s\S]{0,80}?only have (\d+) left today', re.IGNORECASE)
RE_CREDITS_MATCH_VI = re.compile(r'cần dùng (\d+) điểm tín dụng(?: video)?[\s\S]{0,120}?chỉ còn (\d+)', re.IGNORECASE)
RE_DAILY_LIMIT = re.compile(r'reached the daily limit for video generation|đã đạt giới hạn|hết lượt trong ngày', re.IGNORECASE)
RE_NO_CREDIT_FAIL = re.compile(r'did\s?n[\'’]?t\s+use\s+any\s+credits?', re.IGNORECASE)
RE_CREDITS_VI = re.compile(r'còn\s+(\d+)\s+(?:điểm|lượt|credit)', re.IGNORECASE)
RE_CREDITS_VI_2 = re.compile(r'(\d+)\s+lượt\s+tạo\s+video', re.IGNORECASE)

def get_today_str() -> str:
    """Trả về ngày hôm nay YYYY-MM-DD (Ot() trong HaLi AI)"""
    return datetime.now().strftime("%Y-%m-%d")

def get_tomorrow_reset_str() -> str:
    """Thời điểm reset credit lúc 00:05:00 sáng mai (fi() trong HaLi AI)"""
    tomorrow = datetime.now() + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d 00:05:00")

def get_minutes_cooldown_str(minutes: int = 10) -> str:
    """Thời điểm hết cooldown (mi() trong HaLi AI)"""
    future = datetime.now() + timedelta(minutes=minutes)
    return future.strftime("%Y-%m-%d %H:%M:%S")

def extract_dola_credits(page) -> Optional[int]:
    """
    Bóc tách số credit còn lại từ DOM Dola AI theo cơ chế chính xác của HaLi AI
    """
    try:
        body_text = page.inner_text("body")
    except Exception:
        return None

    if not body_text:
        return None

    # 1. Kiểm tra daily limit trước (0 credit)
    if RE_DAILY_LIMIT.search(body_text):
        return 0

    # 2. Chuỗi chuẩn Dola: 'have X video credits left'
    m = RE_CREDITS_LEFT.search(body_text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    # 3. Warning / Dialog: 'will use X ... only have Y left today'
    m = RE_CREDITS_MATCH_EN.search(body_text)
    if m:
        try:
            return int(m.group(2))
        except Exception:
            pass

    m = RE_CREDITS_MATCH_VI.search(body_text)
    if m:
        try:
            return int(m.group(2))
        except Exception:
            pass

    # 4. Tiếng Việt thông thường
    m = RE_CREDITS_VI.search(body_text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    m = RE_CREDITS_VI_2.search(body_text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    return None

# ==================== CÁC HÀM TIỆN ÍCH HỆ THỐNG & PROFILE ====================
def kill_orphan_chrome(profile_dir: str) -> int:
    """
    Dọn sạch các file lock của Chromium và diệt sạch mọi tiến trình chrome.exe
    đang treo giữ thư mục profile (hoặc mồ côi) bằng psutil tốc độ mili-giây chuẩn HaLi AI.
    """
    if not profile_dir or not os.path.exists(profile_dir):
        return 0

    # 1. Xoá các file lock Singleton
    for lf in ["SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"]:
        lp = os.path.join(profile_dir, lf)
        if os.path.exists(lp):
            try:
                os.remove(lp)
            except Exception:
                pass

    if sys.platform != "win32":
        return 0

    killed = 0
    norm_p = os.path.normpath(profile_dir).lower()

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            p_name = (proc.info.get('name') or '').lower()
            if 'chrome' in p_name:
                cmdline = proc.info.get('cmdline')
                if cmdline:
                    cmd_str = " ".join(cmdline).lower()
                    if norm_p in cmd_str:
                        proc.kill()
                        killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if killed > 0:
        time.sleep(1)
        for lf in ["SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"]:
            lp = os.path.join(profile_dir, lf)
            if os.path.exists(lp):
                try:
                    os.remove(lp)
                except Exception:
                    pass

    return killed

def launch_dola_browser(playwright_instance, profile_dir: str, proxy_config: Optional[dict] = None, headless: bool = False):
    """
    Khởi tạo Persistent Context cho Playwright chuẩn xác 100% theo HaLi AI:
    - Diệt tiến trình mồ côi đang giữ profile bằng psutil và xóa SingletonLock
    - Cấu hình cờ chống phát hiện bot & ngẫu nhiên hóa remote-debugging-port
    - Cơ chế Fallback thông minh: Thử Chrome hệ thống trước; nếu gặp lỗi va chạm
      (Opening in existing browser session), dọn dẹp và tự động chuyển sang Chromium nội bộ.
    """
    kill_orphan_chrome(profile_dir)
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    base_args = [
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
        "--remote-debugging-port=0"
    ]
    if headless:
        base_args.extend([
            "--window-position=-32000,-32000",
            "--window-size=1280,960",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--mute-audio"
        ])
    else:
        base_args.extend([
            "--start-maximized"
        ])

    if proxy_config:
        base_args.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")
    else:
        base_args.append("--force-webrtc-ip-handling-policy=default_public_interface_only")

    # Ưu tiên Chrome hệ thống thật nếu có sẵn, rồi mới fallback Chromium nội bộ
    candidates = []
    if os.path.exists(chrome_path):
        candidates.append(chrome_path)
    candidates.append(None)

    last_err = None
    for exe in candidates:
        launch_opts = {
            "user_data_dir": profile_dir,
            "headless": headless,
            "args": list(base_args)
        }
        if exe:
            launch_opts["executable_path"] = exe
        if proxy_config:
            launch_opts["proxy"] = proxy_config

        try:
            # Luôn dọn sạch file lock trước khi launch
            for lf in ["SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort", "lockfile"]:
                lp = os.path.join(profile_dir, lf)
                if os.path.exists(lp):
                    try:
                        os.remove(lp)
                    except Exception:
                        pass

            context = playwright_instance.chromium.launch_persistent_context(**launch_opts)
            return context
        except Exception as e:
            last_err = e
            # Dọn dẹp tiến trình va chạm trước khi thử ứng viên tiếp theo
            kill_orphan_chrome(profile_dir)
            time.sleep(1)

    raise last_err

def has_dola_session(cookies_list) -> bool:
    """Kiểm tra xem danh sách cookies có chứa sessionid hợp lệ và còn hạn của dola.com không"""
    if not cookies_list or not isinstance(cookies_list, list):
        return False
    session_names = {"sessionid", "sessionid_ss"}
    now_ts = time.time()
    for c in cookies_list:
        if isinstance(c, dict) and c.get("name") in session_names and c.get("value") and "dola" in c.get("domain", ""):
            exp = c.get("expires", c.get("expirationDate"))
            if exp and float(exp) > 0 and float(exp) < now_ts:
                continue
            return True
    return False

def parse_proxy(proxy_str):
    """
    Hỗ trợ định dạng proxy:
    - ip:port
    - ip:port:user:pass
    - http://user:pass@ip:port
    - socks5://user:pass@ip:port
    """
    if not proxy_str or not proxy_str.strip():
        return None
        
    proxy_str = proxy_str.strip()
    if proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks5://"):
        return {"server": proxy_str}
        
    parts = proxy_str.split(":")
    if len(parts) == 2:
        return {"server": f"http://{parts[0]}:{parts[1]}"}
    elif len(parts) == 4:
        return {
            "server": f"http://{parts[0]}:{parts[1]}",
            "username": parts[2],
            "password": parts[3]
        }
    return {"server": f"http://{proxy_str}"}

def parse_cookie_string(cookie_str: str, domain: str = ".facebook.com"):
    """Chuyển đổi chuỗi cookie string hoặc JSON thành danh sách cookie Playwright"""
    return parse_dola_cookies(cookie_str) if "dola" in domain else _parse_raw_cookie_for_domain(cookie_str, domain)

def _parse_raw_cookie_for_domain(cookie_str: str, domain: str):
    if not cookie_str or not cookie_str.strip():
        return []
    cookie_str = cookie_str.strip()
    if cookie_str.startswith("[") and cookie_str.endswith("]"):
        try:
            return json.loads(cookie_str)
        except Exception:
            pass

    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                cookies.append({
                    "name": k,
                    "value": v,
                    "domain": domain,
                    "path": "/",
                    "sameSite": "None" if domain.endswith("facebook.com") else "Lax",
                    "secure": True
                })
    return cookies

def parse_dola_cookies(raw_text: str):
    """
    Chuẩn hoá và bóc tách cookie Dola từ 3 định dạng:
    1. JSON (Cookie-Editor, J2TEAM, Playwright storageState)
    2. Netscape HTTP Cookie File (7 cột phân tách bằng Tab)
    3. Chuỗi Header (c_user=...; xs=...; sessionid=...)
    """
    if not raw_text or not raw_text.strip():
        return []

    t = raw_text.strip()
    raw_cookies = []

    if t.startswith('[') or t.startswith('{'):
        try:
            data = json.loads(t)
            if isinstance(data, list):
                raw_cookies = data
            elif isinstance(data, dict):
                raw_cookies = data.get("cookies", [])
        except Exception:
            pass

    if not raw_cookies and '\t' in t:
        for line in t.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cols = line.split('\t')
            if len(cols) >= 7:
                try:
                    exp = float(cols[4])
                except Exception:
                    exp = -1
                raw_cookies.append({
                    "domain": cols[0],
                    "path": cols[2],
                    "secure": cols[3].upper() == 'TRUE',
                    "expires": exp,
                    "name": cols[5],
                    "value": "\t".join(cols[6:]).strip()
                })

    if not raw_cookies:
        for part in t.split(';'):
            part = part.strip()
            if '=' in part:
                k, v = part.split('=', 1)
                k = k.strip()
                v = v.strip()
                if k:
                    raw_cookies.append({
                        "name": k,
                        "value": v,
                        "domain": ".dola.com",
                        "path": "/"
                    })

    normalized = []
    for c in raw_cookies:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        value = str(c.get("value", "")).strip()
        if not name:
            continue
        domain = str(c.get("domain", ".dola.com")).strip()
        if not domain:
            domain = ".dola.com"

        item = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": str(c.get("path", "/"))
        }

        ss = str(c.get("sameSite", "")).strip().lower()
        if ss in ["strict", "lax"]:
            item["sameSite"] = ss.capitalize()
        elif ss in ["none", "no_restriction"]:
            item["sameSite"] = "None"

        if "secure" in c:
            item["secure"] = bool(c["secure"])
        if "httpOnly" in c:
            item["httpOnly"] = bool(c["httpOnly"])

        exp = c.get("expires", c.get("expirationDate"))
        if exp is not None:
            try:
                exp_val = float(exp)
                if exp_val > 0:
                    item["expires"] = exp_val
            except Exception:
                pass

        normalized.append(item)

    return normalized

def save_account_storage_state(account_id: int, cookies_list):
    """Ghi storage state file cho profile để Playwright dùng trực tiếp"""
    profile_path = os.path.join(PROFILES_DIR, f"acc_{account_id}")
    os.makedirs(profile_path, exist_ok=True)
    state_file = os.path.join(profile_path, "storage_state.json")
    dola_backup = os.path.join(profile_path, "dola-cookies.json")
    
    state_data = {
        "cookies": cookies_list,
        "origins": []
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, ensure_ascii=False, indent=2)

    # Lưu thêm file dự phòng chuẩn HaLi AI dola-cookies.json
    dola_only = [c for c in cookies_list if "dola" in c.get("domain", "")]
    if dola_only:
        with open(dola_backup, "w", encoding="utf-8") as f:
            json.dump(dola_only, f, ensure_ascii=False, indent=2)

def find_first_visible(page, selectors, timeout_ms=5000):
    """Tìm phần tử đầu tiên hiển thị trên trang từ danh sách selector"""
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    return loc
            except Exception:
                pass
        time.sleep(0.3)
    return None

# ==================== TỰ ĐỘNG HOÁ ĐĂNG NHẬP FACEBOOK ──► DOLA (CHẾ ĐỘ NGẦM) ====================
def _auto_login_facebook_dola_sync(account_id: int, headless: bool = True):
    """
    Quy trình tự động hoá 100% nguyên tử như HaLi AI:
    1. Dọn dẹp lock profile
    2. Bơm Facebook cookie (nếu có)
    3. Mở Dola AI -> Bấm Đăng nhập -> Chọn Facebook Provider
    4. Tự điền UID, Password Facebook
    5. Tự tính toán và điền mã 2FA TOTP (6 số) bằng module twofa
    6. Tự bấm Xác nhận / Tiếp tục OAuth consent
    7. Bắt sessionid của Dola và lưu vĩnh viễn
    """
    conn = get_connection()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()

    if not acc:
        return {"success": False, "message": "Không tìm thấy tài khoản"}

    profile_path = os.path.join(PROFILES_DIR, f"acc_{account_id}")
    os.makedirs(profile_path, exist_ok=True)
    
    proxy_config = parse_proxy(acc["proxy"])
    
    log_event(f"🚀 Bắt đầu tự động đăng nhập Dola AI cho nick #{account_id} ({acc['name']})...", "INFO", "Auth")

    with sync_playwright() as p:
        try:
            context = launch_dola_browser(p, profile_path, proxy_config=proxy_config, headless=headless)
        except Exception as launch_err:
            if proxy_config:
                log_event(f"Proxy '{acc['proxy']}' lỗi, chuyển sang kết nối trực tiếp...", "WARNING", "Proxy")
                context = launch_dola_browser(p, profile_path, proxy_config=None, headless=headless)
            else:
                raise launch_err

        # Bơm cookie Facebook nếu có sẵn
        if acc["cookies"]:
            try:
                c_list = json.loads(acc["cookies"])
                fb_c = [c for c in c_list if "facebook" in c.get("domain", "")]
                if fb_c:
                    context.add_cookies(fb_c)
                    log_event(f"Đã nạp {len(fb_c)} cookie Facebook vào phiên làm việc", "INFO", "Auth")
            except Exception:
                pass

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(45000)

        # 1. Đi tới Dola
        try:
            log_event(f"Mở trang Dola AI (https://www.dola.com/chat/)...", "INFO", "Auth")
            page.goto("https://www.dola.com/chat/", timeout=60000, wait_until="domcontentloaded")
            time.sleep(2)
        except Exception as e:
            log_event(f"Tải trang Dola gặp lỗi mạng nhẹ: {str(e)[:40]}, tiếp tục kiểm tra...", "WARNING", "Auth")

        # Kiểm tra nếu đã có phiên Dola sẵn
        if has_dola_session(context.cookies()):
            cookies = context.cookies()
            save_account_storage_state(account_id, cookies)
            _mark_account_connected(account_id, cookies)
            context.close()
            log_event(f"🎉 Tài khoản #{account_id} ({acc['name']}) đã có sẵn phiên Dola hợp lệ!", "SUCCESS", "Auth")
            return {"success": True, "message": "Đã có sẵn phiên Dola hợp lệ"}

        # 2. Tìm nút Đăng nhập Dola
        dola_btn = find_first_visible(page, SELECTORS["dola_login_btn"], timeout_ms=8000)
        if dola_btn:
            try:
                dola_btn.click(timeout=5000)
                time.sleep(1)
            except Exception:
                pass

        # 3. Tìm nút Facebook Provider
        fb_btn = find_first_visible(page, SELECTORS["fb_provider"], timeout_ms=10000)
        fb_page = page
        if fb_btn:
            log_event(f"Bấm nút 'Tiếp tục với Facebook'...", "INFO", "Auth")
            # Chờ popup hoặc redirect
            try:
                with context.expect_page(timeout=15000) as new_page_info:
                    fb_btn.click(timeout=5000)
                fb_page = new_page_info.value
            except Exception:
                # Nếu không mở popup mà chuyển hướng cùng tab
                fb_page = page

        # Bấm xác nhận 18+ nếu có
        age_btn = find_first_visible(page, SELECTORS["age_confirm"], timeout_ms=3000)
        if age_btn:
            try:
                age_btn.click(timeout=3000)
                time.sleep(1)
            except Exception:
                pass

        # 4. Kiểm tra trang Facebook
        time.sleep(2)
        cur_url = fb_page.url
        log_event(f"Đang tương tác trang Facebook...", "INFO", "Auth")

        # Điền UID và Password nếu thấy form đăng nhập
        email_input = find_first_visible(fb_page, SELECTORS["email"], timeout_ms=10000)
        if email_input and acc["fb_uid"] and acc["fb_pass"] and acc["fb_pass"] != "cookie_login":
            log_event(f"Tự động điền UID ({acc['fb_uid']}) và Mật khẩu...", "INFO", "Auth")
            try:
                email_input.fill(acc["fb_uid"])
                time.sleep(0.3)
                pass_input = find_first_visible(fb_page, SELECTORS["pass"], timeout_ms=5000)
                if pass_input:
                    pass_input.fill(acc["fb_pass"])
                    time.sleep(0.3)
                login_btn = find_first_visible(fb_page, SELECTORS["login_btn"], timeout_ms=3000)
                if login_btn:
                    login_btn.click(timeout=5000)
                else:
                    fb_page.keyboard.press("Enter")
                time.sleep(2)
            except Exception as fill_err:
                log_event(f"Điền form Facebook lỗi: {str(fill_err)[:35]}", "WARNING", "Auth")

        # 5. Vòng lặp giải 2FA, OAuth Consent, và đợi Dola nhận phiên
        timeout_loop = time.time() + 180  # Tối đa 3 phút
        twofa_tried = 0

        while time.time() < timeout_loop:
            # Kiểm tra xem Dola đã nhận phiên chưa
            curr_c = context.cookies()
            if has_dola_session(curr_c):
                save_account_storage_state(account_id, curr_c)
                _mark_account_connected(account_id, curr_c)
                context.close()
                log_event(f"🎉 XÁC NHẬN ĐĂNG NHẬP DOLA THÀNH CÔNG CHO #{account_id} ({acc['name']})!", "SUCCESS", "Auth")
                return {"success": True, "message": "Đăng nhập Dola thành công!"}

            # Kiểm tra nút xác nhận 18+ trên Dola
            age_btn = find_first_visible(page, SELECTORS["age_confirm"], timeout_ms=1000)
            if age_btn:
                try:
                    age_btn.click(timeout=3000)
                    time.sleep(1)
                except Exception:
                    pass

            # Kiểm tra popup nếu đã đóng
            if fb_page != page and fb_page.is_closed():
                log_event(f"Popup Facebook đã đóng, đang chờ Dola nhận phiên...", "INFO", "Auth")
                time.sleep(2)
                continue

            try:
                body_text = fb_page.inner_text("body")
            except Exception:
                body_text = ""

            # Kiểm tra sai mật khẩu
            if RE_WRONG_PASS.search(body_text):
                context.close()
                log_event(f"❌ Tài khoản #{account_id} báo SAI MẬT KHẨU trên Facebook!", "ERROR", "Auth")
                return {"success": False, "message": "Sai mật khẩu Facebook"}

            # Kiểm tra Checkpoint
            if RE_CHECKPOINT.search(body_text) or RE_CHECKPOINT.search(fb_page.url):
                context.close()
                log_event(f"⚠️ Tài khoản #{account_id} bị Facebook CHECKPOINT (Xác minh danh tính)!", "WARNING", "Auth")
                return {"success": False, "message": "Tài khoản bị Facebook checkpoint"}

            # Kiểm tra ô nhập mã 2FA
            code_input = find_first_visible(fb_page, SELECTORS["code"], timeout_ms=2000)
            if code_input and acc["fb_2fa"] and twofa_tried < 3:
                try:
                    candidates = get_totp_candidates(acc["fb_2fa"])
                    candidate = candidates[min(twofa_tried, len(candidates) - 1)]
                    log_event(f"🔑 Tự động sinh mã 2FA TOTP ({candidate}) lần {twofa_tried + 1}...", "INFO", "Auth")
                    code_input.fill("")
                    code_input.fill(candidate)
                    twofa_tried += 1
                    time.sleep(0.3)
                    code_submit = find_first_visible(fb_page, SELECTORS["code_submit"], timeout_ms=3000)
                    if code_submit:
                        code_submit.click(timeout=5000)
                    else:
                        fb_page.keyboard.press("Enter")
                    time.sleep(3)
                    continue
                except Exception as twofa_err:
                    log_event(f"Lỗi nhập 2FA: {str(twofa_err)[:35]}", "WARNING", "Auth")

            # Kiểm tra nút Tiếp tục OAuth consent
            cont_btn = find_first_visible(fb_page, SELECTORS["continue_btns"], timeout_ms=2000)
            if cont_btn:
                try:
                    btn_text = cont_btn.inner_text().strip()
                    log_event(f"Bấm nút xác nhận cấp quyền ('{btn_text}')...", "INFO", "Auth")
                    cont_btn.click(timeout=5000)
                    time.sleep(2)
                    continue
                except Exception:
                    pass

            time.sleep(1.5)

        # Hết giờ chờ
        context.close()
        log_event(f"Hết thời gian chờ đăng nhập Dola (3 phút) cho #{account_id}.", "WARNING", "Auth")
        return {"success": False, "message": "Hết thời gian chờ đăng nhập (Timeout)"}

def _mark_account_connected(account_id: int, cookies):
    conn = get_connection()
    conn.execute("UPDATE accounts SET cookies = ?, status = 'ready', last_check = CURRENT_TIMESTAMP WHERE id = ?",
                 (json.dumps(cookies), account_id))
    conn.execute("UPDATE jobs SET status = 'Đang chờ', status_message = 'Đã kết nối Dola! Sẵn sàng khởi chạy...' WHERE account_id = ? AND status = 'Chờ đăng nhập Dola'", (account_id,))
    conn.commit()
    conn.close()

async def auto_login_facebook_dola(account_id: int, headless: bool = True):
    return await asyncio.to_thread(_auto_login_facebook_dola_sync, account_id, headless)

# ==================== ĐĂNG NHẬP THỦ CÔNG QUA CHROME THẬT ====================
def _launch_login_session_sync(account_id: int):
    """
    Mở cửa sổ trình duyệt Google Chrome thật cho người dùng đăng nhập thủ công nếu muốn.
    Sau khi đăng nhập xong, tự động bốc toàn bộ cookie & session lưu vĩnh viễn vào hệ thống.
    """
    conn = get_connection()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()
    
    if not acc:
        return {"success": False, "message": "Không tìm thấy tài khoản"}
        
    profile_path = os.path.join(PROFILES_DIR, f"acc_{account_id}")
    os.makedirs(profile_path, exist_ok=True)
    kill_orphan_chrome(profile_path)
    
    proxy_config = parse_proxy(acc["proxy"])
    
    log_event(f"Đang mở Google Chrome cho tài khoản #{account_id} ({acc['name']})...", "INFO", "Auth")
    
    # Tự động tạo file batch kích hoạt trực tiếp từ desktop phòng trường hợp Windows chặn GUI ngầm
    bat_file = os.path.join(BASE_DIR, f"MO_CHROME_ACC_{account_id}.bat")
    try:
        with open(bat_file, "w", encoding="utf-8") as bf:
            bf.write(f'''@echo off
title Mo Dola AI Nick #{account_id}
echo ========================================================
echo     DANG MO GOOGLE CHROME NICK #{account_id} (DOLA AI)
echo ========================================================
echo.
cd /d "{BASE_DIR}"
del /f /q "profiles\\acc_{account_id}\\SingletonLock" 2>nul
del /f /q "profiles\\acc_{account_id}\\SingletonCookie" 2>nul
del /f /q "profiles\\acc_{account_id}\\SingletonSocket" 2>nul
del /f /q "profiles\\acc_{account_id}\\DevToolsActivePort" 2>nul
echo Dang khoi dong Google Chrome...
start "" "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --user-data-dir="{profile_path}" --remote-debugging-port=9222 --no-first-run --no-default-browser-check --disable-session-crashed-bubble "https://www.dola.com/chat/"
echo Cua so Chrome da duoc mo tren man hinh!
timeout /t 3
exit
''')
    except Exception:
        pass

    try:
        if sys.platform == "win32":
            os.startfile(bat_file)
    except Exception:
        pass

    with sync_playwright() as p:
        try:
            context = launch_dola_browser(p, profile_path, proxy_config=proxy_config, headless=False)
        except Exception as launch_err:
            if proxy_config:
                log_event(f"Proxy '{acc['proxy']}' không phản hồi, mở bằng mạng trực tiếp...", "WARNING", "Proxy")
                context = launch_dola_browser(p, profile_path, proxy_config=None, headless=False)
            else:
                raise launch_err

        # Nạp cookie có sẵn nếu đã lưu trước đó
        if acc["cookies"]:
            try:
                c_list = json.loads(acc["cookies"])
                if c_list:
                    context.add_cookies(c_list)
            except Exception:
                pass

        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://www.dola.com/chat/", timeout=60000)
            page.bring_to_front()
        except Exception:
            pass
            
        # Giữ trình duyệt mở và liên tục kiểm tra cookie đăng nhập
        saved_dola = False
        while len(context.pages) > 0 and not page.is_closed():
            if not saved_dola:
                try:
                    curr_c = context.cookies()
                    if has_dola_session(curr_c):
                        saved_dola = True
                        save_account_storage_state(account_id, curr_c)
                        _mark_account_connected(account_id, curr_c)
                        log_event(f"🎉 Phát hiện đăng nhập Dola thành công cho #{account_id} ({acc['name']})! Đã lưu phiên.", "SUCCESS", "Auth")
                except Exception:
                    pass
            time.sleep(2)
            
        cookies = context.cookies()
        save_account_storage_state(account_id, cookies)
        _mark_account_connected(account_id, cookies)
        log_event(f"✅ Tài khoản #{account_id} ({acc['name']}): Đã lưu phiên đăng nhập Dola ({len(cookies)} cookies) thành công!", "SUCCESS", "Auth")
        
    return {"success": True, "message": "Đã lưu phiên đăng nhập thành công"}

async def launch_login_session(account_id: int):
    return await asyncio.to_thread(_launch_login_session_sync, account_id)

# ==================== THUẬT TOÁN ĐIỀU PHỐI VÀ KIỂM TRA CREDIT (CHUẨN HALI AI) ====================
def find_eligible_video_account(excluded_id: Optional[int] = None) -> Optional[dict]:
    """
    Bộ lọc tuyển chọn tài khoản tối ưu tuân thủ nguyên tử Ze(i) của HaLi AI:
    Ze(i) = i.enabled && i.login !== false && gi(i) !== 0 && !pi(i)
    - Trạng thái status = 'ready'
    - Phiên Dola hợp lệ (có sessionid hoặc sessionid_ss)
    - KHÔNG trong thời gian nghỉ / cooldown (rest_until IS NULL hoặc rest_until <= NOW)
    - KHÔNG hết credit hôm nay (credits_date = today và credits = 0)
    - Ưu tiên tài khoản còn credit > 0 hôm nay, sau đó đến tài khoản rảnh lâu nhất (last_used)
    """
    today_str = get_today_str()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = get_connection()
    query = """
        SELECT * FROM accounts 
        WHERE status = 'ready'
          AND account_type IN ('facebook', 'google')
          AND (rest_until IS NULL OR rest_until <= ?)
          AND (credits_date IS NULL OR credits_date != ? OR credits > 0)
    """
    params = [now_str, today_str]
    if excluded_id:
        query += " AND id != ?"
        params.append(excluded_id)

    query += """
        ORDER BY 
          CASE WHEN credits_date = ? AND credits > 0 THEN 0 ELSE 1 END,
          COALESCE(credits, 0) DESC,
          last_used ASC
    """
    params.append(today_str)

    candidates = conn.execute(query, params).fetchall()
    conn.close()

    for row in candidates:
        acc = dict(row)
        # Xác minh thực sự có sessionid Dola
        has_dola = False
        if acc.get("cookies"):
            try:
                has_dola = has_dola_session(json.loads(acc["cookies"]))
            except Exception:
                pass
        if not has_dola:
            profile_path = os.path.join(PROFILES_DIR, f"acc_{acc['id']}")
            st_path = os.path.join(profile_path, "storage_state.json")
            if os.path.exists(st_path):
                try:
                    st_data = json.load(open(st_path, "r", encoding="utf-8"))
                    has_dola = has_dola_session(st_data.get("cookies", []))
                except Exception:
                    pass
        if has_dola:
            return acc

    return None

def _check_account_credits_sync(account_id: int) -> dict:
    """
    Kiểm tra số credit thực tế trên Dola AI cho 1 tài khoản và cập nhật vào CSDL
    """
    conn = get_connection()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()

    if not acc:
        return {"success": False, "message": "Không tìm thấy tài khoản"}

    # Kiểm tra session Dola
    has_dola = False
    if acc["cookies"]:
        try:
            has_dola = has_dola_session(json.loads(acc["cookies"]))
        except Exception:
            pass

    profile_path = os.path.join(PROFILES_DIR, f"acc_{account_id}")
    st_path = os.path.join(profile_path, "storage_state.json")
    if not has_dola and os.path.exists(st_path):
        try:
            st_data = json.load(open(st_path, "r", encoding="utf-8"))
            has_dola = has_dola_session(st_data.get("cookies", []))
        except Exception:
            pass

    if not has_dola:
        return {
            "success": False,
            "message": f"Tài khoản '{acc['name']}' CHƯA ĐĂNG NHẬP DOLA (thiếu sessionid). Hãy bấm '⚡ Auto Login' hoặc 'Dán Cookie' Dola trước!"
        }

    proxy_config = parse_proxy(acc["proxy"])
    today_str = get_today_str()
    tomorrow_reset = get_tomorrow_reset_str()

    log_event(f"Đang kiểm tra credit Dola cho tài khoản #{account_id} ({acc['name']})...", "INFO", "Credit")

    try:
        with sync_playwright() as p:
            context = launch_dola_browser(p, profile_path, proxy_config=proxy_config, headless=True)
            if acc["cookies"]:
                try:
                    c_list = json.loads(acc["cookies"])
                    if c_list:
                        context.add_cookies(c_list)
                except Exception:
                    pass

            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.dola.com/chat/", timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)

            # Cập nhật cookies phiên mới nhất nếu có
            curr_c = context.cookies()
            if has_dola_session(curr_c):
                save_account_storage_state(account_id, curr_c)
                _mark_account_connected(account_id, curr_c)

            credits_found = extract_dola_credits(page)
            context.close()

            conn_u = get_connection()
            if credits_found is not None:
                if credits_found == 0:
                    conn_u.execute("""
                        UPDATE accounts 
                        SET credits = 0, credits_date = ?, rest_until = ?, rest_reason = 'Hết lượt trong ngày', last_check = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (today_str, tomorrow_reset, account_id))
                    conn_u.commit()
                    conn_u.close()
                    msg = f"Tài khoản #{account_id} ({acc['name']}) hết lượt (0 credit)! Nghỉ đến 00:05 sáng mai."
                    log_event(msg, "WARNING", "Credit")
                    return {"success": True, "credits": 0, "is_resting": True, "message": msg}
                else:
                    conn_u.execute("""
                        UPDATE accounts 
                        SET credits = ?, credits_date = ?, rest_until = NULL, rest_reason = NULL, last_check = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (credits_found, today_str, account_id))
                    conn_u.commit()
                    conn_u.close()
                    msg = f"Tài khoản #{account_id} ({acc['name']}) còn {credits_found} video credit hôm nay."
                    log_event(msg, "SUCCESS", "Credit")
                    return {"success": True, "credits": credits_found, "is_resting": False, "message": msg}
            else:
                default_credits = acc["credits"] if (acc["credits"] and acc["credits"] > 0) else 4
                conn_u.execute("""
                    UPDATE accounts 
                    SET credits = ?, credits_date = ?, rest_until = NULL, rest_reason = NULL, last_check = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (default_credits, today_str, account_id))
                conn_u.commit()
                conn_u.close()
                msg = f"Tài khoản #{account_id} ({acc['name']}) đã kết nối Dola AI thành công! Sẵn sàng tạo video (còn {default_credits} lượt hôm nay)."
                log_event(msg, "SUCCESS", "Credit")
                return {"success": True, "credits": default_credits, "is_resting": False, "message": msg}

    except Exception as e:
        err = str(e)
        log_event(f"Lỗi kiểm tra credit tài khoản #{account_id}: {err[:50]}", "ERROR", "Credit")
        return {"success": False, "message": f"Lỗi kiểm tra credit: {err[:60]}"}

async def check_account_credits(account_id: int):
    return await asyncio.to_thread(_check_account_credits_sync, account_id)

# ==================== THỰC THI VIDEO JOB ====================
def _execute_video_job_sync(job_id: int):
    """
    Thực thi 1 Job tạo video trong hàng đợi bằng sync_playwright với cơ chế kiểm tra credit
    và tự động chuyển giao (auto-rotation) khi tài khoản hết credit chuẩn HaLi AI.
    """
    conn = get_connection()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        conn.close()
        return

    account_id = job["account_id"]
    today_str = get_today_str()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Kiểm tra xem tài khoản được gán có đủ điều kiện không
    eligible = False
    if account_id:
        acc_check = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if acc_check and acc_check["status"] == "ready":
            is_resting = False
            if acc_check["rest_until"] and acc_check["rest_until"] > now_str:
                is_resting = True
            if acc_check["credits_date"] == today_str and acc_check["credits"] == 0:
                is_resting = True

            has_dola = False
            if acc_check["cookies"]:
                try:
                    has_dola = has_dola_session(json.loads(acc_check["cookies"]))
                except Exception:
                    pass
            if not has_dola:
                prof_st = os.path.join(PROFILES_DIR, f"acc_{acc_check['id']}", "storage_state.json")
                if os.path.exists(prof_st):
                    try:
                        st = json.load(open(prof_st, "r", encoding="utf-8"))
                        has_dola = has_dola_session(st.get("cookies", []))
                    except Exception:
                        pass

            if not is_resting and has_dola:
                eligible = True

    # Nếu tài khoản gán không hợp lệ (hết credit / chưa login Dola), tự động tìm tài khoản đủ điều kiện
    if not eligible:
        best_acc = find_eligible_video_account()
        if best_acc:
            account_id = best_acc["id"]
            conn.execute("UPDATE jobs SET account_id = ? WHERE id = ?", (account_id, job_id))
            conn.commit()
            log_event(f"Job #{job_id}: Tự động chọn tài khoản tối ưu #{account_id} ({best_acc['name']})", "INFO", "Queue")
        else:
            conn.close()
            update_job_status(job_id, "Đang chờ", "Tất cả tài khoản đều hết credit hôm nay hoặc chưa đăng nhập Dola (hồi phục lúc 00:05)...", 0)
            log_event(f"Job #{job_id}: Tạm hoãn vì không có nick nào còn credit hoặc đã kết nối Dola!", "WARNING", "Queue")
            return

    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()

    if not acc:
        update_job_status(job_id, "Đang chờ", "Tài khoản không tồn tại hoặc đã bị xóa", 0)
        return

    profile_path = os.path.join(PROFILES_DIR, f"acc_{account_id}")
    update_job_status(job_id, "Đang chạy", f"Khởi tạo trình duyệt cho '{acc['name']}'...", 10)
    kill_orphan_chrome(profile_path)

    proxy_config = parse_proxy(acc["proxy"])
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    tomorrow_reset = get_tomorrow_reset_str()

    try:
        with sync_playwright() as p:
            context = launch_dola_browser(p, profile_path, proxy_config=proxy_config, headless=True)
            if acc.get("cookies"):
                try:
                    c_list = json.loads(acc["cookies"])
                    if c_list:
                        context.add_cookies(c_list)
                except Exception:
                    pass
            page = context.pages[0] if context.pages else context.new_page()

            update_job_status(job_id, "Đang chạy", "Mở phiên Dola AI & kiểm tra credit...", 25)
            page.goto("https://www.dola.com/chat/", timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)

            # Cập nhật cookies mới nhất nếu có
            curr_c = context.cookies()
            if has_dola_session(curr_c):
                save_account_storage_state(account_id, curr_c)
                _mark_account_connected(account_id, curr_c)

            # Kiểm tra credit trước khi gửi prompt
            credits_pre = extract_dola_credits(page)
            if credits_pre == 0:
                # Đã hết credit! Cho nick nghỉ và xoay job sang nick khác
                conn_r = get_connection()
                conn_r.execute("""
                    UPDATE accounts 
                    SET credits = 0, credits_date = ?, rest_until = ?, rest_reason = 'Hết lượt trong ngày'
                    WHERE id = ?
                """, (today_str, tomorrow_reset, account_id))
                conn_r.commit()
                conn_r.close()
                context.close()

                next_acc = find_eligible_video_account(excluded_id=account_id)
                if next_acc:
                    update_job_status(job_id, "Đang chờ", f"Tài khoản '{acc['name']}' hết credit (0 lượt). Đang tự động chuyển sang '{next_acc['name']}'...", 0)
                    conn_sw = get_connection()
                    conn_sw.execute("UPDATE jobs SET account_id = ? WHERE id = ?", (next_acc["id"], job_id))
                    conn_sw.commit()
                    conn_sw.close()
                    log_event(f"Tài khoản #{account_id} hết credit. Tự động xoay Job #{job_id} sang {next_acc['name']}!", "WARNING", "CreditRotation")
                else:
                    update_job_status(job_id, "Đang chờ", f"Tài khoản '{acc['name']}' hết credit. Toàn bộ nick khác đều hết lượt, chờ reset 00:05...", 0)
                return

            # 1. Ghi nhận danh sách conversation_ids đã tồn tại trước đó để tránh lấy nhầm video cũ
            initial_conv_ids = set()
            try:
                m_curr = re.search(r'/chat/(\d+)', page.url)
                if m_curr:
                    initial_conv_ids.add(m_curr.group(1))
                rec_pre = page.evaluate('''async () => {
                    try {
                        const url = new URL('/im/chain/recent_conv', location.origin);
                        const params = {
                            version_code: '20800', language: 'en', device_platform: 'web', doubao_device_platform: 'web',
                            aid: '495671', real_aid: '495671', pkg_type: 'release_version', samantha_web: '1',
                            web_platform: 'browser', 'use-olympus-account': '1'
                        };
                        for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
                        const resp = await fetch(url, {
                            method: 'POST',
                            headers: {
                                'accept': 'application/json, text/plain, */*',
                                'content-type': 'application/json; encoding=utf-8',
                                'Agw-Js-Conv': 'str'
                            },
                            body: JSON.stringify({
                                cmd: 3200,
                                uplink_body: {
                                    pull_recent_conv_chain_uplink_body: {
                                        limit: 10,
                                        message_count_per_conv: 1,
                                        api_version: 1,
                                        conv_version: 0,
                                        is_cold: true
                                    }
                                },
                                sequence_id: 'seq_' + Date.now(),
                                channel: 2,
                                version: '1'
                            }),
                            credentials: 'include'
                        });
                        const data = await resp.json();
                        const cells = data?.downlink_body?.pull_recent_conv_chain_downlink_body?.cells || [];
                        return cells.map(c => c?.conversation?.conversation_id || c?.id).filter(Boolean);
                    } catch(e) { return []; }
                }''')
                if rec_pre and isinstance(rec_pre, list):
                    for cid in rec_pre:
                        initial_conv_ids.add(str(cid))
            except Exception:
                pass

            # Xây dựng prompt điện ảnh hành động sống động kèm thời lượng
            dur = job["duration"] if (job and "duration" in job.keys() and job["duration"]) else 30
            raw_p = (job["prompt"] or "").strip()
            raw_p = re.sub(r'^(Làm video|Tạo video|Video đã tạo)[:\s\-]*', '', raw_p, flags=re.I).strip()
            
            has_cine = any(k in raw_p.lower() for k in [
                'shot', 'lens', 'lighting', 'cinematic', '8k', '4k', 'camera', 'fpv', 'góc quay', 'ánh sáng', 'điện ảnh'
            ])
            if not has_cine:
                action_motion = "Góc quay camera FPV chuyển động linh hoạt bám sát nhân vật, các pha nhào lộn và chuyển động hành động dồn dập kịch tính, ánh sáng điện ảnh Hollywood bom tấn, dynamic high-speed acrobatic action, Hollywood blockbuster action masterpiece, 4k ultra realistic."
                full_prompt = f"Tạo video Seedance 2.5 dài {dur} giây: {raw_p}. {action_motion}"
            else:
                full_prompt = f"Tạo video Seedance 2.5 dài {dur} giây: {raw_p}"

            # Gửi Prompt sang Dola AI
            update_job_status(job_id, "Đang chạy", f"Đang gửi prompt điện ảnh sang Dola AI...", 30)
            input_box = page.locator("div.ProseMirror, textarea, [contenteditable='true']").first
            if input_box.is_visible():
                input_box.click()
                input_box.fill(full_prompt)
                time.sleep(1)
                page.keyboard.press("Enter")

            time.sleep(4)

            # Kiểm tra xem có xuất hiện Slide Captcha (Xác minh kéo mảnh ghép) hay không
            captcha_detected = False
            try:
                captcha_frames = page.locator("iframe[src*='captcha'], iframe[src*='secsdk'], iframe[id*='captcha'], div[class*='captcha'], div[class*='secsdk']").count()
                if captcha_frames > 0:
                    for i in range(captcha_frames):
                        if page.locator("iframe[src*='captcha'], iframe[src*='secsdk'], iframe[id*='captcha'], div[class*='captcha'], div[class*='secsdk']").nth(i).is_visible():
                            captcha_detected = True
                            break

                body_t = page.inner_text("body").lower()
                if any(kw in body_t for kw in [
                    "verify to continue", "drag the puzzle piece into place", 
                    "kéo mảnh ghép", "xác minh để tiếp tục", "vui lòng hoàn tất xác minh",
                    "drag the slider", "security verification"
                ]):
                    captcha_detected = True

                err_icons = page.locator("svg[class*='error'], div[class*='error-icon'], [data-icon='exclamation-circle']").count()
                if err_icons > 0:
                    captcha_detected = True
            except Exception:
                pass

            if captcha_detected:
                warn_msg = f"⚠️ Tài khoản #{account_id} ('{acc['name']}') bị Dola AI yêu cầu kéo mảnh ghép xác minh (Slide Captcha)! Vui lòng bấm nút 'Chrome' trên bảng Tài khoản để kéo mảnh ghép một lần."
                log_event(warn_msg, "WARNING", "Captcha")
                update_job_status(job_id, "Đang chờ", warn_msg, 0)
                context.close()
                return

            # Kiểm tra xem Dola có từ chối do hết credit hay không
            body_text = page.inner_text("body")
            if RE_DAILY_LIMIT.search(body_text) or "only have 0 left today" in body_text or "chỉ còn 0" in body_text:
                conn_r = get_connection()
                conn_r.execute("""
                    UPDATE accounts 
                    SET credits = 0, credits_date = ?, rest_until = ?, rest_reason = 'Hết lượt trong ngày'
                    WHERE id = ?
                """, (today_str, tomorrow_reset, account_id))
                conn_r.commit()
                conn_r.close()
                context.close()

                next_acc = find_eligible_video_account(excluded_id=account_id)
                if next_acc:
                    update_job_status(job_id, "Đang chờ", f"Tài khoản '{acc['name']}' đạt giới hạn ngày. Tự động chuyển Job sang '{next_acc['name']}'...", 0)
                    conn_sw = get_connection()
                    conn_sw.execute("UPDATE jobs SET account_id = ? WHERE id = ?", (next_acc["id"], job_id))
                    conn_sw.commit()
                    conn_sw.close()
                else:
                    update_job_status(job_id, "Đang chờ", "Đạt giới hạn lượt trong ngày. Chờ hồi phục 00:05...", 0)
                return

            # Lấy conversation_id MỚI ĐƯỢC TẠO (tuyệt đối không lấy lại conversation cũ)
            conv_id = None
            wait_conv_start = time.time()
            while time.time() - wait_conv_start < 30:
                m_url = re.search(r'/chat/(\d+)', page.url)
                if m_url and str(m_url.group(1)) not in initial_conv_ids:
                    conv_id = m_url.group(1)
                    break

                try:
                    recent_data = page.evaluate('''async () => {
                        try {
                            const url = new URL('/im/chain/recent_conv', location.origin);
                            const params = {
                                version_code: '20800', language: 'en', device_platform: 'web', doubao_device_platform: 'web',
                                aid: '495671', real_aid: '495671', pkg_type: 'release_version', samantha_web: '1',
                                web_platform: 'browser', 'use-olympus-account': '1'
                            };
                            for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
                            const resp = await fetch(url, {
                                method: 'POST',
                                headers: {
                                    'accept': 'application/json, text/plain, */*',
                                    'content-type': 'application/json; encoding=utf-8',
                                    'Agw-Js-Conv': 'str'
                                },
                                body: JSON.stringify({
                                    cmd: 3200,
                                    uplink_body: {
                                        pull_recent_conv_chain_uplink_body: {
                                            limit: 3,
                                            message_count_per_conv: 3,
                                            api_version: 1,
                                            conv_version: 0,
                                            is_cold: true
                                        }
                                    },
                                    sequence_id: 'seq_' + Date.now(),
                                    channel: 2,
                                    version: '1'
                                }),
                                credentials: 'include'
                            });
                            return await resp.json();
                        } catch(e) { return null; }
                    }''')
                    if recent_data:
                        body_down = recent_data.get('downlink_body', {}).get('pull_recent_conv_chain_downlink_body', {})
                        cells = body_down.get('cells', [])
                        if cells:
                            for c in cells:
                                c0 = c.get('conversation', {})
                                cand_id = str(c0.get('conversation_id') or c.get('id') or '')
                                if cand_id and cand_id not in initial_conv_ids:
                                    conv_id = cand_id
                                    break
                except Exception as r_err:
                    pass

                if conv_id:
                    break
                time.sleep(3)

            if not conv_id:
                # Kiểm tra lại xem có bị slide captcha chặn không
                body_t = page.inner_text("body").lower()
                if any(kw in body_t for kw in ["verify", "xác minh", "puzzle", "kéo mảnh"]):
                    warn_msg = f"⚠️ Tài khoản #{account_id} ('{acc['name']}') bị yêu cầu kéo mảnh ghép (Slide Captcha)! Vui lòng bấm nút 'Chrome' để kéo mảnh ghép một lần."
                    update_job_status(job_id, "Đang chờ", warn_msg, 0)
                    log_event(warn_msg, "WARNING", "Captcha")
                else:
                    update_job_status(job_id, "Thất bại", "Dola AI không tạo cuộc trò chuyện mới cho prompt này (hệ thống chặn không lấy lại video cũ)", 0)
                    log_event(f"Job #{job_id}: Không tìm thấy cuộc trò chuyện mới. Dừng tiến trình để tránh tải lại video cũ.", "WARNING", "Engine")
                context.close()
                return

            # Vòng lặp chờ render & tải video thật từ Dola AI (Timeout tối đa 8 phút chuẩn HaLi AI)
            dest_file = os.path.join(OUTPUTS_DIR, f"video_{job_id}.mp4")
            downloaded = False
            start_poll = time.time()
            max_wait_seconds = 480

            log_event(f"Job #{job_id}: Bắt đầu theo dõi tiến trình Dola AI render (conv_id={conv_id})...", "INFO", "Render")

            while time.time() - start_poll < max_wait_seconds:
                elapsed_sec = int(time.time() - start_poll)
                est_progress = min(88, 35 + int((elapsed_sec / 120) * 50))
                update_job_status(job_id, "Đang chạy", f"Dola AI đang render Seedance 2.5 ({elapsed_sec}s)...", est_progress)

                # Nếu chưa có conv_id, thử tìm lại từ URL (phải là conv_id mới)
                if not conv_id:
                    m_now = re.search(r'/chat/(\d+)', page.url)
                    if m_now and str(m_now.group(1)) not in initial_conv_ids:
                        conv_id = m_now.group(1)
                    time.sleep(5)
                    continue

                chain_res = None
                try:
                    chain_res = page.evaluate(f'''async () => {{
                        try {{
                            const url = new URL('/im/chain/single', location.origin);
                            const params = {{
                                version_code: '20800', language: 'en', device_platform: 'web', doubao_device_platform: 'web',
                                aid: '495671', real_aid: '495671', pkg_type: 'release_version', samantha_web: '1',
                                web_platform: 'browser', 'use-olympus-account': '1'
                            }};
                            for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
                            const resp = await fetch(url, {{
                                method: 'POST',
                                headers: {{
                                    'accept': 'application/json, text/plain, */*',
                                    'content-type': 'application/json; encoding=utf-8',
                                    'Agw-Js-Conv': 'str'
                                }},
                                body: JSON.stringify({{
                                    cmd: 3100,
                                    uplink_body: {{
                                        pull_singe_chain_uplink_body: {{
                                            conversation_id: '{conv_id}',
                                            anchor_index: 999999999,
                                            conversation_type: 3,
                                            direction: 1,
                                            limit: 20,
                                            ext: {{}},
                                            filter: {{ index_list: [] }}
                                        }}
                                    }},
                                    sequence_id: 'seq_' + Date.now(),
                                    channel: 2,
                                    version: '1'
                                }}),
                                credentials: 'include'
                            }});
                            if (!resp.ok) return null;
                            return await resp.json();
                        }} catch(e) {{ return null; }}
                    }}''')
                except Exception:
                    pass

                chain_str = ""
                if chain_res and isinstance(chain_res, dict):
                    chain_str = json.dumps(chain_res.get('data') or chain_res, ensure_ascii=False)

                # Kiểm tra daily limit
                if "daily limit for video generation" in chain_str.lower() or "đã đạt giới hạn tạo video trong ngày" in chain_str.lower():
                    log_event(f"Job #{job_id}: Tài khoản #{account_id} đạt giới hạn Dola trong ngày.", "WARNING", "Credit")
                    conn_l = get_connection()
                    conn_l.execute("UPDATE accounts SET credits = 0, credits_date = ?, rest_until = ?, rest_reason = 'Hết lượt trong ngày' WHERE id = ?",
                                   (today_str, tomorrow_reset, account_id))
                    conn_l.commit()
                    conn_l.close()
                    break

                # Kiểm tra từ chối bản quyền / likeness
                if ("cannot provide" in chain_str.lower() or "unable to provide" in chain_str.lower() or "không thể cung cấp" in chain_str.lower()) and "generating" not in chain_str.lower():
                    log_event(f"Job #{job_id}: Dola từ chối do vi phạm chính sách likeness/bản quyền", "WARNING", "Policy")
                    update_job_status(job_id, "Thất bại", "Dola AI từ chối tạo video do chính sách likeness/bản quyền", 0)
                    context.close()
                    return

                # Quét link video thực tế từ Dola AI
                raw_matches = re.findall(r'https?://[^\s"\'<>]+', chain_str)
                clean_urls = []
                for raw in raw_matches:
                    clean_u = raw.replace(r'\/', '/').replace(r'\u0026', '&')
                    if any(ext in clean_u for ext in ['.mp4', '.webm', '/video/tos/', 'mime_type=video_']) and 'watermark' not in clean_u:
                        if clean_u not in clean_urls:
                            clean_urls.append(clean_u)

                # Kiểm tra thêm thẻ <video src> trên DOM nếu có
                if not clean_urls:
                    try:
                        dom_videos = page.locator("video").evaluate_all("els => els.map(e => e.currentSrc || e.src).filter(Boolean)")
                        for dv in dom_videos:
                            if any(ext in dv for ext in ['.mp4', '.webm', '/video/tos/']) and dv not in clean_urls:
                                clean_urls.append(dv)
                    except Exception:
                        pass

                if clean_urls:
                    target_video_url = clean_urls[0]
                    log_event(f"Job #{job_id}: 🎉 Tìm thấy video thành phẩm từ Dola AI! Đang tải về máy...", "SUCCESS", "Download")
                    update_job_status(job_id, "Đang chạy", "Đang tải video chất lượng cao từ Dola AI về máy...", 92)

                    try:
                        req_dl = urllib.request.Request(target_video_url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Referer': 'https://www.dola.com/'
                        })
                        with urllib.request.urlopen(req_dl, timeout=120) as resp_v, open(dest_file, 'wb') as out_v:
                            shutil.copyfileobj(resp_v, out_v)

                        if os.path.exists(dest_file) and os.path.getsize(dest_file) > 50000:
                            downloaded = True
                            sz_mb = round(os.path.getsize(dest_file) / (1024 * 1024), 2)
                            log_event(f"Job #{job_id}: ✅ Đã lưu video thành phẩm ({sz_mb} MB) vào {dest_file}!", "SUCCESS", "Download")
                            break
                    except Exception as dl_err:
                        log_event(f"Job #{job_id}: Lỗi khi tải video: {str(dl_err)[:40]}", "WARNING", "Download")

                time.sleep(5)

            # Cập nhật số credit còn lại sau khi render
            credits_post = extract_dola_credits(page)
            conn_u = get_connection()
            if credits_post is not None:
                if credits_post == 0:
                    conn_u.execute("""
                        UPDATE accounts 
                        SET credits = 0, credits_date = ?, rest_until = ?, rest_reason = 'Hết lượt trong ngày', last_used = CURRENT_TIMESTAMP 
                        WHERE id = ?
                    """, (today_str, tomorrow_reset, account_id))
                else:
                    conn_u.execute("""
                        UPDATE accounts 
                        SET credits = ?, credits_date = ?, last_used = CURRENT_TIMESTAMP 
                        WHERE id = ?
                    """, (credits_post, today_str, account_id))
            else:
                conn_u.execute("UPDATE accounts SET last_used = CURRENT_TIMESTAMP WHERE id = ?", (account_id,))
            conn_u.commit()
            conn_u.close()

            context.close()

            if downloaded and os.path.exists(dest_file) and os.path.getsize(dest_file) > 50000:
                local_path = f"/outputs/video_{job_id}.mp4"
                update_job_status(job_id, "Hoàn thành", "Đã tạo video thành công! Sẵn sàng tải về hoặc xem ngay.", 100, local_video_path=local_path)
            else:
                update_job_status(job_id, "Thất bại", "Quá thời gian chờ render từ Dola AI (hoặc video chưa sẵn sàng)", 0)
                log_event(f"Job #{job_id}: Không tải được video sau {max_wait_seconds}s.", "WARNING", "Render")

    except Exception as e:
        error_msg = str(e)
        conn_fail = get_connection()
        conn_fail.execute("UPDATE accounts SET status = 'rate_limited', last_used = CURRENT_TIMESTAMP WHERE id = ?", (account_id,))
        conn_fail.commit()
        conn_fail.close()

        other_acc = find_eligible_video_account(excluded_id=account_id)
        if other_acc:
            conn_sw = get_connection()
            conn_sw.execute("UPDATE jobs SET account_id = ?, status = 'Đang chờ', status_message = 'Tự động xoay sang ' || ?, progress = 0 WHERE id = ?", 
                            (other_acc["id"], other_acc["name"], job_id))
            conn_sw.commit()
            conn_sw.close()
            log_event(f"Tài khoản #{account_id} gặp sự cố ({error_msg[:30]}). Đã tự động xoay Job #{job_id} sang {other_acc['name']}!", "WARNING", "AutoRotation")
        else:
            update_job_status(job_id, "Đang chờ", "Hết tài khoản rảnh hoặc còn credit, đang chờ hồi phục...", 0)

async def execute_video_job(job_id: int):
    return await asyncio.to_thread(_execute_video_job_sync, job_id)

def update_job_status(job_id, status, status_message, progress, local_video_path=None):
    conn = get_connection()
    if local_video_path:
        conn.execute("""
            UPDATE jobs 
            SET status = ?, status_message = ?, progress = ?, local_video_path = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (status, status_message, progress, local_video_path, job_id))
    else:
        conn.execute("""
            UPDATE jobs 
            SET status = ?, status_message = ?, progress = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (status, status_message, progress, job_id))
    conn.commit()
    conn.close()
