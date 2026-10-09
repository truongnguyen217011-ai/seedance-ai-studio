"""Toàn bộ thao tác trên Dola AI: auto login, đăng nhập tay, kiểm tra credit, chạy job, chẩn đoán.

Luật (docs/KIEN_TRUC.md mục 1): Chrome chỉ mở qua browser.browser_session; nick phải được
AccountPool giữ trước khi đụng profile; không giết Chrome; trạng thái job lấy từ constants.JobStatus.
"""
import json
import os
import re
import shutil
import sys
import time
import asyncio
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as _policy_err:  # noqa: BLE001 - chỉ ảnh hưởng subprocess trên Windows
        print(f"[dola_service] Không đặt được WindowsProactorEventLoopPolicy: {_policy_err}", flush=True)

from playwright.sync_api import sync_playwright

import config
from account_pool import AccountPool
from browser import ChromeNotFoundError, browser_session
from constants import AccountStatus, JobStatus, NeedsManual, Reason
from database import get_connection
from diagnostics import mask_proxy
from logger import artifact_suffix, get_logger, log_event, save_failure_artifacts
from twofa import get_totp_candidates

log = get_logger("Dola")

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

CAPTCHA_SELECTOR = "iframe[src*='captcha'], iframe[src*='secsdk'], iframe[id*='captcha'], div[class*='captcha'], div[class*='secsdk']"
CAPTCHA_KEYWORDS = [
    "verify to continue", "drag the puzzle piece into place",
    "kéo mảnh ghép", "xác minh để tiếp tục", "vui lòng hoàn tất xác minh",
    "drag the slider", "security verification",
]

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

# ==================== CƠ CHẾ KIỂM TRA CREDIT (CHUẨN HALI AI) ====================
RE_CREDITS_LEFT = re.compile(r'have\s+(\d+)\s+video\s+credits?\s+left', re.IGNORECASE)
RE_CREDITS_MATCH_EN = re.compile(r'will use (\d+) video credits?[\s\S]{0,80}?only have (\d+) left today', re.IGNORECASE)
RE_CREDITS_MATCH_VI = re.compile(r'cần dùng (\d+) điểm tín dụng(?: video)?[\s\S]{0,120}?chỉ còn (\d+)', re.IGNORECASE)
RE_DAILY_LIMIT = re.compile(r'reached the daily limit for video generation|đã đạt giới hạn|hết lượt trong ngày', re.IGNORECASE)
RE_NO_CREDIT_FAIL = re.compile(r'did\s?n[\'’]?t\s+use\s+any\s+credits?', re.IGNORECASE)
RE_CREDITS_VI = re.compile(r'còn\s+(\d+)\s+(?:điểm|lượt|credit)', re.IGNORECASE)
RE_CREDITS_VI_2 = re.compile(r'(\d+)\s+lượt\s+tạo\s+video', re.IGNORECASE)

CREDIT_UNREADABLE = "Không đọc được số credit trên trang"


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


def _safe_body_text(page) -> str:
    try:
        return page.inner_text("body") or ""
    except Exception as e:  # noqa: BLE001 - trang có thể đang chuyển hướng
        log.debug("Không đọc được body trang: %s", e)
        return ""


def extract_dola_credits(page) -> Optional[int]:
    """Bóc tách số credit còn lại từ DOM Dola AI. Trả về None nếu không đọc được (không bịa số)."""
    body_text = _safe_body_text(page)
    if not body_text:
        return None

    # 1. Daily limit = 0 credit
    if RE_DAILY_LIMIT.search(body_text):
        return 0

    patterns = [
        (RE_CREDITS_LEFT, 1),       # 'have X video credits left'
        (RE_CREDITS_MATCH_EN, 2),   # 'will use X ... only have Y left today'
        (RE_CREDITS_MATCH_VI, 2),
        (RE_CREDITS_VI, 1),
        (RE_CREDITS_VI_2, 1),
    ]
    for regex, group in patterns:
        m = regex.search(body_text)
        if m:
            try:
                return int(m.group(group))
            except (TypeError, ValueError) as e:
                log.debug("Chuỗi credit '%s' không phải số: %s", m.group(group), e)
    return None


# ==================== COOKIE, PHIÊN DOLA ====================
def _cookie_domain_matches(cookie_domain: str, host: str) -> bool:
    """Cookie domain '.dola.com' / 'www.dola.com' / '127.0.0.1' có áp dụng cho host không."""
    cd = (cookie_domain or "").strip().lower().lstrip(".")
    h = (host or "").strip().lower()
    if not cd or not h:
        return False
    return h == cd or h.endswith("." + cd) or cd.endswith("." + h)


def default_dola_cookie_domain() -> str:
    """Domain gán cho cookie Dola dán tay: '.dola.com' với host www.dola.com; giữ nguyên với IP/localhost."""
    host = config.DOLA_DOMAIN
    if re.fullmatch(r"[\d.]+", host) or host == "localhost" or "." not in host:
        return host
    parts = host.split(".")
    return "." + ".".join(parts[-2:])


def has_dola_session(cookies_list) -> bool:
    """Danh sách cookie có sessionid/sessionid_ss còn hạn thuộc config.DOLA_DOMAIN không."""
    if not cookies_list or not isinstance(cookies_list, list):
        return False
    session_names = {"sessionid", "sessionid_ss"}
    now_ts = time.time()
    for c in cookies_list:
        if not isinstance(c, dict) or c.get("name") not in session_names or not c.get("value"):
            continue
        if not _cookie_domain_matches(c.get("domain", ""), config.DOLA_DOMAIN):
            continue
        exp = c.get("expires", c.get("expirationDate"))
        try:
            if exp is not None and 0 < float(exp) < now_ts:
                continue
        except (TypeError, ValueError) as e:
            log.debug("Cookie %s có expires lạ (%r): %s", c.get("name"), exp, e)
        return True
    return False


def parse_proxy(proxy_str):
    """Hỗ trợ: ip:port | ip:port:user:pass | http://user:pass@ip:port | socks5://user:pass@ip:port"""
    if not proxy_str or not proxy_str.strip():
        return None
    proxy_str = proxy_str.strip()
    if proxy_str.startswith(("http://", "https://", "socks5://")):
        return {"server": proxy_str}
    parts = proxy_str.split(":")
    if len(parts) == 2:
        return {"server": f"http://{parts[0]}:{parts[1]}"}
    if len(parts) == 4:
        return {"server": f"http://{parts[0]}:{parts[1]}", "username": parts[2], "password": parts[3]}
    return {"server": f"http://{proxy_str}"}


def parse_cookie_string(cookie_str: str, domain: str = ".facebook.com"):
    """Chuyển chuỗi cookie / JSON thành danh sách cookie Playwright theo domain yêu cầu."""
    if "dola" in (domain or "") or _cookie_domain_matches(domain, config.DOLA_DOMAIN):
        return parse_dola_cookies(cookie_str)
    return _parse_raw_cookie_for_domain(cookie_str, domain)


def _parse_raw_cookie_for_domain(cookie_str: str, domain: str):
    if not cookie_str or not cookie_str.strip():
        return []
    cookie_str = cookie_str.strip()
    if cookie_str.startswith("[") and cookie_str.endswith("]"):
        try:
            return json.loads(cookie_str)
        except json.JSONDecodeError as e:
            log.debug("Cookie dạng JSON không hợp lệ, thử dạng chuỗi: %s", e)

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
    """Bóc tách cookie Dola từ JSON (Cookie-Editor/J2TEAM/storageState), Netscape, hoặc chuỗi header."""
    if not raw_text or not raw_text.strip():
        return []

    t = raw_text.strip()
    raw_cookies = []
    default_domain = default_dola_cookie_domain()

    if t.startswith('[') or t.startswith('{'):
        try:
            data = json.loads(t)
            if isinstance(data, list):
                raw_cookies = data
            elif isinstance(data, dict):
                raw_cookies = data.get("cookies", [])
        except json.JSONDecodeError as e:
            log.debug("Cookie Dola dạng JSON không hợp lệ, thử định dạng khác: %s", e)

    if not raw_cookies and '\t' in t:
        for line in t.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cols = line.split('\t')
            if len(cols) >= 7:
                try:
                    exp = float(cols[4])
                except ValueError:
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
                    raw_cookies.append({"name": k, "value": v, "domain": default_domain, "path": "/"})

    normalized = []
    for c in raw_cookies:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        value = str(c.get("value", "")).strip()
        if not name:
            continue
        domain = str(c.get("domain", default_domain)).strip() or default_domain

        item = {"name": name, "value": value, "domain": domain, "path": str(c.get("path", "/"))}

        ss = str(c.get("sameSite", "")).strip().lower()
        if ss in ("strict", "lax"):
            item["sameSite"] = ss.capitalize()
        elif ss in ("none", "no_restriction"):
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
            except (TypeError, ValueError) as e:
                log.debug("Bỏ qua expires lạ của cookie %s: %s", name, e)

        normalized.append(item)

    return normalized


# ==================== PROFILE & TÀI KHOẢN ====================
def account_profile_dir(account_id: int) -> str:
    return os.path.join(config.PROFILES_DIR, f"acc_{account_id}")


def save_account_storage_state(account_id: int, cookies_list):
    """Ghi storage_state.json (và dola-cookies.json dự phòng) vào profile của nick."""
    profile_path = account_profile_dir(account_id)
    os.makedirs(profile_path, exist_ok=True)
    state_file = os.path.join(profile_path, "storage_state.json")
    dola_backup = os.path.join(profile_path, "dola-cookies.json")

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies_list, "origins": []}, f, ensure_ascii=False, indent=2)

    dola_only = [c for c in cookies_list if _cookie_domain_matches(c.get("domain", ""), config.DOLA_DOMAIN)]
    if dola_only:
        with open(dola_backup, "w", encoding="utf-8") as f:
            json.dump(dola_only, f, ensure_ascii=False, indent=2)


def _load_cookies_json(raw, account_id=None) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (TypeError, json.JSONDecodeError) as e:
        log.debug("Cột cookies của nick #%s không phải JSON: %s", account_id, e, extra={"account_id": account_id})
        return []


def _load_storage_state_cookies(account_id: int) -> list:
    st_path = os.path.join(account_profile_dir(account_id), "storage_state.json")
    if not os.path.exists(st_path):
        return []
    try:
        with open(st_path, "r", encoding="utf-8") as f:
            return json.load(f).get("cookies", []) or []
    except (OSError, json.JSONDecodeError, AttributeError) as e:
        log.debug("storage_state.json của nick #%s hỏng: %s", account_id, e, extra={"account_id": account_id})
        return []


def account_has_dola_session(acc) -> bool:
    """Nick có phiên Dola (trên cột cookies hoặc storage_state.json) không."""
    acc = dict(acc)
    acc_id = acc.get("id")
    if has_dola_session(_load_cookies_json(acc.get("cookies"), acc_id)):
        return True
    return has_dola_session(_load_storage_state_cookies(acc_id))


def _load_account(account_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _load_job(job_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _set_account_fields(account_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn = get_connection()
    try:
        conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", (*fields.values(), account_id))
        conn.commit()
    finally:
        conn.close()


def _inject_cookies(context, acc: dict, only_facebook: bool = False) -> int:
    c_list = _load_cookies_json(acc.get("cookies"), acc.get("id"))
    if only_facebook:
        c_list = [c for c in c_list if "facebook" in str(c.get("domain", ""))]
    if not c_list:
        return 0
    # Playwright bắt buộc cookie có url hoặc cặp domain/path; cookie dán tay hay thiếu path
    c_list = [dict(c, path=c.get("path") or "/") for c in c_list if isinstance(c, dict) and c.get("domain")]
    if not c_list:
        return 0
    try:
        context.add_cookies(c_list)
        return len(c_list)
    except Exception as e:  # noqa: BLE001 - cookie lỗi định dạng không được chặn luồng
        log.warning("Nạp cookie vào trình duyệt thất bại: %s", e, extra={"account_id": acc.get("id")})
        return 0


def _mark_account_connected(account_id: int, cookies):
    """Nick vào được trang Dola có phiên: cookie mới nhất, ready, và đếm lại lỗi kết nối liên tiếp từ 0."""
    _set_account_fields(
        account_id,
        cookies=json.dumps(cookies),
        status=AccountStatus.READY,
        last_check=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        consecutive_errors=0,
    )


def _mark_no_credit(account_id: int) -> None:
    _set_account_fields(
        account_id,
        credits=0,
        credits_date=get_today_str(),
        rest_until=get_tomorrow_reset_str(),
        rest_reason="Hết lượt trong ngày",
        last_used=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def _record_credits(account_id: int, credits: Optional[int], touch_last_used: bool = False) -> None:
    """Ghi credit đọc được; None → credits NULL + last_error (không bịa số)."""
    fields = {"last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if touch_last_used:
        fields["last_used"] = fields["last_check"]
    if credits is None:
        fields.update(credits=None, last_error=CREDIT_UNREADABLE)
    elif credits == 0:
        fields.update(credits=0, credits_date=get_today_str(), rest_until=get_tomorrow_reset_str(),
                      rest_reason="Hết lượt trong ngày", last_error=None)
    else:
        fields.update(credits=credits, credits_date=get_today_str(), rest_until=None, rest_reason=None, last_error=None)
    _set_account_fields(account_id, **fields)


def find_first_visible(page, selectors, timeout_ms=5000):
    """Tìm phần tử đầu tiên hiển thị trên trang từ danh sách selector"""
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    return loc
            except Exception as e:  # noqa: BLE001 - selector không khớp là chuyện thường
                log.debug("Selector '%s' lỗi: %s", sel, str(e)[:80])
        time.sleep(0.3)
    return None


def _click_if_visible(page, selectors, timeout_ms, what: str, account_id=None) -> bool:
    btn = find_first_visible(page, selectors, timeout_ms=timeout_ms)
    if not btn:
        return False
    try:
        btn.click(timeout=3000)
        time.sleep(1)
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("Bấm %s thất bại: %s", what, str(e)[:80], extra={"account_id": account_id})
        return False


def _detect_captcha(page) -> bool:
    """Có khung/chữ yêu cầu kéo mảnh ghép (slide captcha) đang HIỂN THỊ trên trang không.

    BH-36: chỉ tính khung captcha đang hiện hoặc câu chữ đặc trưng của captcha; icon lỗi ẩn
    trong DOM hay chữ "verify" nằm trong từ khác (verified) KHÔNG phải captcha.
    """
    try:
        frames = page.locator(CAPTCHA_SELECTOR)
        for i in range(frames.count()):
            el = frames.nth(i)
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if box and box["width"] >= 40 and box["height"] >= 40:
                return True
        body_t = _safe_body_text(page).lower()
        if any(kw in body_t for kw in CAPTCHA_KEYWORDS):
            return True
    except Exception as e:  # noqa: BLE001
        log.debug("Kiểm tra captcha lỗi: %s", str(e)[:80])
    return False


def _busy_message(acc_name: str, account_id: int) -> str:
    holder = AccountPool.get().holder(account_id)
    if holder:
        return f"Nick '{acc_name}' đang bận với job #{holder}"
    return f"Nick '{acc_name}' đang bận (đang đăng nhập hoặc chẩn đoán)"


# ==================== TỰ ĐỘNG HOÁ ĐĂNG NHẬP FACEBOOK ──► DOLA ====================
def _auto_login_facebook_dola_sync(account_id: int, headless: bool = True):
    acc = _load_account(account_id)
    if not acc:
        return {"success": False, "message": "Không tìm thấy tài khoản"}

    pool = AccountPool.get()
    if not pool.acquire(account_id, None):
        return {"success": False, "message": _busy_message(acc["name"], account_id)}
    try:
        return _auto_login_locked(acc, headless)
    finally:
        pool.release(account_id)


def _open_with_proxy_fallback(stack, p, acc: dict, headless: bool):
    """Mở browser_session; nếu proxy làm Chrome không mở được thì thử lại không proxy."""
    profile_path = account_profile_dir(acc["id"])
    proxy_config = parse_proxy(acc.get("proxy"))
    try:
        return stack.enter_context(browser_session(p, profile_path, proxy=proxy_config, headless=headless, account_id=acc["id"]))
    except ChromeNotFoundError:
        raise
    except Exception as launch_err:  # noqa: BLE001 - Playwright ném Error chung
        if not proxy_config:
            raise
        log_event(f"Proxy '{mask_proxy(acc.get('proxy'))}' làm Chrome không mở được ({str(launch_err)[:60]}), thử kết nối trực tiếp",
                  "WARNING", "Proxy", account_id=acc["id"])
        return stack.enter_context(browser_session(p, profile_path, proxy=None, headless=headless, account_id=acc["id"]))


def _auto_login_locked(acc: dict, headless: bool):
    from contextlib import ExitStack
    account_id = acc["id"]
    log_event(f"Bắt đầu tự động đăng nhập Dola cho nick #{account_id} ({acc['name']})", "INFO", "Auth", account_id=account_id)

    with sync_playwright() as p, ExitStack() as stack:
        context = _open_with_proxy_fallback(stack, p, acc, headless)

        injected = _inject_cookies(context, acc, only_facebook=True)
        if injected:
            log_event(f"Đã nạp {injected} cookie Facebook vào phiên", "INFO", "Auth", account_id=account_id)

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(45000)

        try:
            log_event(f"Mở trang Dola ({config.DOLA_CHAT_URL})", "INFO", "Auth", account_id=account_id)
            page.goto(config.DOLA_CHAT_URL, timeout=60000, wait_until="domcontentloaded")
            time.sleep(2)
        except Exception as e:  # noqa: BLE001
            log_event(f"Tải trang Dola gặp lỗi mạng: {str(e)[:60]}, tiếp tục kiểm tra", "WARNING", "Auth", account_id=account_id)

        if has_dola_session(context.cookies()):
            cookies = context.cookies()
            save_account_storage_state(account_id, cookies)
            _mark_account_connected(account_id, cookies)
            _set_account_fields(account_id, needs_manual=None)
            log_event(f"Nick #{account_id} ({acc['name']}) đã có sẵn phiên Dola hợp lệ", "SUCCESS", "Auth", account_id=account_id)
            return {"success": True, "message": "Đã có sẵn phiên Dola hợp lệ"}

        _click_if_visible(page, SELECTORS["dola_login_btn"], 8000, "nút Đăng nhập Dola", account_id)

        fb_btn = find_first_visible(page, SELECTORS["fb_provider"], timeout_ms=10000)
        fb_page = page
        if fb_btn:
            log_event("Bấm nút 'Tiếp tục với Facebook'", "INFO", "Auth", account_id=account_id)
            try:
                with context.expect_page(timeout=15000) as new_page_info:
                    fb_btn.click(timeout=5000)
                fb_page = new_page_info.value
            except Exception as e:  # noqa: BLE001 - không mở popup mà chuyển hướng cùng tab
                log.debug("Facebook không mở popup, dùng cùng tab: %s", str(e)[:80], extra={"account_id": account_id})
                fb_page = page

        _click_if_visible(page, SELECTORS["age_confirm"], 3000, "nút xác nhận 18+", account_id)

        time.sleep(2)
        log_event("Đang tương tác trang Facebook", "INFO", "Auth", account_id=account_id)

        email_input = find_first_visible(fb_page, SELECTORS["email"], timeout_ms=10000)
        if email_input and acc.get("fb_uid") and acc.get("fb_pass") and acc["fb_pass"] != "cookie_login":
            log_event(f"Tự động điền UID ({acc['fb_uid']}) và mật khẩu", "INFO", "Auth", account_id=account_id)
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
            except Exception as fill_err:  # noqa: BLE001
                log_event(f"Điền form Facebook lỗi: {str(fill_err)[:60]}", "WARNING", "Auth", account_id=account_id)

        timeout_loop = time.time() + config.LOGIN_TIMEOUT_SECONDS
        twofa_tried = 0

        while time.time() < timeout_loop:
            curr_c = context.cookies()
            if has_dola_session(curr_c):
                save_account_storage_state(account_id, curr_c)
                _mark_account_connected(account_id, curr_c)
                _set_account_fields(account_id, needs_manual=None)
                log_event(f"Đăng nhập Dola thành công cho nick #{account_id} ({acc['name']})", "SUCCESS", "Auth", account_id=account_id)
                return {"success": True, "message": "Đăng nhập Dola thành công!"}

            _click_if_visible(page, SELECTORS["age_confirm"], 1000, "nút xác nhận 18+", account_id)

            if fb_page != page and fb_page.is_closed():
                log_event("Popup Facebook đã đóng, đang chờ Dola nhận phiên", "INFO", "Auth", account_id=account_id)
                time.sleep(2)
                continue

            body_text = _safe_body_text(fb_page)

            if RE_WRONG_PASS.search(body_text):
                log_event(f"Nick #{account_id} báo SAI MẬT KHẨU trên Facebook", "ERROR", "Auth", account_id=account_id)
                _set_account_fields(account_id, needs_manual=NeedsManual.LOGIN, last_error="Sai mật khẩu Facebook")
                return {"success": False, "message": "Sai mật khẩu Facebook"}

            if RE_CHECKPOINT.search(body_text) or RE_CHECKPOINT.search(fb_page.url):
                log_event(f"Nick #{account_id} bị Facebook CHECKPOINT (xác minh danh tính)", "WARNING", "Auth", account_id=account_id)
                _set_account_fields(account_id, needs_manual=NeedsManual.LOGIN, last_error="Tài khoản bị Facebook checkpoint")
                return {"success": False, "message": "Tài khoản bị Facebook checkpoint"}

            code_input = find_first_visible(fb_page, SELECTORS["code"], timeout_ms=2000)
            if code_input and acc.get("fb_2fa") and twofa_tried < 3:
                try:
                    candidates = get_totp_candidates(acc["fb_2fa"])
                    candidate = candidates[min(twofa_tried, len(candidates) - 1)]
                    log_event(f"Tự sinh mã 2FA TOTP lần {twofa_tried + 1}", "INFO", "Auth", account_id=account_id)
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
                except Exception as twofa_err:  # noqa: BLE001
                    log_event(f"Lỗi nhập 2FA: {str(twofa_err)[:60]}", "WARNING", "Auth", account_id=account_id)

            cont_btn = find_first_visible(fb_page, SELECTORS["continue_btns"], timeout_ms=2000)
            if cont_btn:
                try:
                    btn_text = cont_btn.inner_text().strip()
                    log_event(f"Bấm nút xác nhận cấp quyền ('{btn_text}')", "INFO", "Auth", account_id=account_id)
                    cont_btn.click(timeout=5000)
                    time.sleep(2)
                    continue
                except Exception as e:  # noqa: BLE001
                    log.debug("Bấm nút tiếp tục OAuth lỗi: %s", str(e)[:80], extra={"account_id": account_id})

            time.sleep(1.5)

        arts = save_failure_artifacts(fb_page if not fb_page.is_closed() else page, "login_timeout", account_id=account_id)
        msg = f"Hết thời gian chờ đăng nhập Dola ({config.LOGIN_TIMEOUT_SECONDS}s) cho nick #{account_id}" + artifact_suffix(arts)
        log_event(msg, "WARNING", "Auth", account_id=account_id)
        _set_account_fields(account_id, last_error=msg)
        return {"success": False, "message": "Hết thời gian chờ đăng nhập (Timeout)"}


def _run_in_job_executor(fn, *args):
    """Thao tác mở Chrome chạy trên worker.JOB_EXECUTOR (BH-32), không dùng executor mặc định của asyncio.
    Import muộn vì worker.py import module này ở đầu file."""
    from worker import run_in_job_executor
    return run_in_job_executor(fn, *args)


async def auto_login_facebook_dola(account_id: int, headless: bool = True):
    return await _run_in_job_executor(_auto_login_facebook_dola_sync, account_id, headless)


# ==================== ĐĂNG NHẬP THỦ CÔNG QUA CHROME THẬT ====================
def _launch_login_session_sync(account_id: int):
    """Mở một cửa sổ Chrome (không ẩn) cho người dùng tự đăng nhập / kéo captcha; tự lưu phiên khi thấy sessionid."""
    acc = _load_account(account_id)
    if not acc:
        return {"success": False, "message": "Không tìm thấy tài khoản"}

    pool = AccountPool.get()
    if not pool.acquire(account_id, None):
        return {"success": False, "message": _busy_message(acc["name"], account_id)}

    from contextlib import ExitStack
    try:
        log_event(f"Mở Chrome cho nick #{account_id} ({acc['name']})", "INFO", "Auth", account_id=account_id)
        with sync_playwright() as p, ExitStack() as stack:
            context = _open_with_proxy_fallback(stack, p, acc, headless=False)
            _inject_cookies(context, acc)

            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(config.DOLA_CHAT_URL, timeout=60000)
                page.bring_to_front()
            except Exception as e:  # noqa: BLE001
                log.debug("Mở trang Dola trong Chrome tay lỗi: %s", str(e)[:80], extra={"account_id": account_id})

            saved_dola = False
            while len(context.pages) > 0 and not page.is_closed():
                if not saved_dola:
                    try:
                        curr_c = context.cookies()
                        if has_dola_session(curr_c):
                            saved_dola = True
                            save_account_storage_state(account_id, curr_c)
                            _mark_account_connected(account_id, curr_c)
                            log_event(f"Phát hiện đăng nhập Dola thành công cho nick #{account_id} ({acc['name']}), đã lưu phiên",
                                      "SUCCESS", "Auth", account_id=account_id)
                    except Exception as e:  # noqa: BLE001
                        log.debug("Đọc cookie trong lúc chờ lỗi: %s", str(e)[:80], extra={"account_id": account_id})
                time.sleep(2)

            try:
                cookies = context.cookies()
            except Exception as e:  # noqa: BLE001 - người dùng đã đóng Chrome
                log.debug("Chrome đã đóng, không đọc được cookie cuối: %s", str(e)[:80], extra={"account_id": account_id})
                cookies = []
            if cookies:
                save_account_storage_state(account_id, cookies)
                _mark_account_connected(account_id, cookies)
            if has_dola_session(cookies):
                # Người dùng vừa mở Chrome tay: coi như captcha/đăng nhập đã được xử lý
                _set_account_fields(account_id, needs_manual=None)
            log_event(f"Nick #{account_id} ({acc['name']}): đã lưu phiên ({len(cookies)} cookie) sau khi đóng Chrome",
                      "SUCCESS", "Auth", account_id=account_id)
        return {"success": True, "message": "Đã lưu phiên đăng nhập thành công"}
    except ChromeNotFoundError as e:
        log_event(str(e), "ERROR", "Auth", account_id=account_id)
        return {"success": False, "message": str(e)}
    except Exception as e:  # noqa: BLE001
        log_event(f"Mở Chrome cho nick #{account_id} thất bại: {str(e)[:120]}", "ERROR", "Auth", account_id=account_id)
        return {"success": False, "message": f"Mở Chrome thất bại: {str(e)[:120]}"}
    finally:
        pool.release(account_id)


async def launch_login_session(account_id: int):
    return await _run_in_job_executor(_launch_login_session_sync, account_id)


# ==================== KIỂM TRA CREDIT ====================
def _check_account_credits_sync(account_id: int, pool_held: bool = False) -> dict:
    """Mở Dola, đọc số credit và ghi vào CSDL. Không đọc được → credits NULL, is_known=False."""
    acc = _load_account(account_id)
    if not acc:
        return {"success": False, "message": "Không tìm thấy tài khoản"}

    if not account_has_dola_session(acc):
        return {
            "success": False, "is_known": False,
            "message": f"Nick '{acc['name']}' chưa đăng nhập Dola (thiếu sessionid). Hãy bấm Auto Login hoặc dán cookie Dola trước",
        }

    pool = AccountPool.get()
    if not pool_held and not pool.acquire(account_id, None):
        return {"success": False, "is_known": False, "message": _busy_message(acc["name"], account_id)}

    try:
        log_event(f"Đang kiểm tra credit Dola cho nick #{account_id} ({acc['name']})", "INFO", "Credit", account_id=account_id)
        with sync_playwright() as p:
            with browser_session(p, account_profile_dir(account_id), proxy=parse_proxy(acc.get("proxy")),
                                 headless=True, account_id=account_id) as context:
                _inject_cookies(context, acc)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(config.DOLA_CHAT_URL, timeout=60000, wait_until="domcontentloaded")
                time.sleep(3)

                curr_c = context.cookies()
                if has_dola_session(curr_c):
                    save_account_storage_state(account_id, curr_c)
                    _mark_account_connected(account_id, curr_c)

                if _detect_captcha(page):
                    arts = save_failure_artifacts(page, "captcha", account_id=account_id)
                    _set_account_fields(account_id, needs_manual=NeedsManual.CAPTCHA, last_error="Dola yêu cầu kéo captcha")
                    msg = Reason.CAPTCHA.format(name=acc["name"]) + artifact_suffix(arts)
                    log_event(msg, "WARNING", "Captcha", account_id=account_id)
                    return {"success": False, "is_known": False, "captcha": True, "message": msg}

                credits_found = extract_dola_credits(page)
                if credits_found is None:
                    arts = save_failure_artifacts(page, "credit_unreadable", account_id=account_id)
                    _record_credits(account_id, None)
                    msg = f"Nick #{account_id} ({acc['name']}): {CREDIT_UNREADABLE}" + artifact_suffix(arts)
                    log_event(msg, "WARNING", "Credit", account_id=account_id)
                    return {"success": True, "is_known": False, "credits": None, "is_resting": False, "message": msg}

        _record_credits(account_id, credits_found)
        if credits_found == 0:
            msg = f"Nick #{account_id} ({acc['name']}) hết lượt (0 credit), nghỉ đến 00:05 sáng mai"
            log_event(msg, "WARNING", "Credit", account_id=account_id)
            return {"success": True, "is_known": True, "credits": 0, "is_resting": True, "message": msg}
        msg = f"Nick #{account_id} ({acc['name']}) còn {credits_found} video credit hôm nay"
        log_event(msg, "SUCCESS", "Credit", account_id=account_id)
        return {"success": True, "is_known": True, "credits": credits_found, "is_resting": False, "message": msg}

    except ChromeNotFoundError as e:
        log_event(str(e), "ERROR", "Credit", account_id=account_id)
        return {"success": False, "is_known": False, "message": str(e)}
    except Exception as e:  # noqa: BLE001
        err = str(e)[:120]
        _set_account_fields(account_id, last_error=f"Kiểm tra credit lỗi: {err}")
        log_event(f"Lỗi kiểm tra credit nick #{account_id}: {err}", "ERROR", "Credit", account_id=account_id)
        return {"success": False, "is_known": False, "message": f"Lỗi kiểm tra credit: {err}"}
    finally:
        if not pool_held:
            pool.release(account_id)


async def check_account_credits(account_id: int):
    return await _run_in_job_executor(_check_account_credits_sync, account_id)


def diagnose_account_dola(account_id: int, pool_held: bool = False) -> dict:
    """Dùng cho diagnostics: mở trang Dola, kiểm tra phiên, đọc credit, phát hiện captcha.

    Trả về {ok, session_ok, credits, credits_known, captcha, detail, screenshot}.
    """
    acc = _load_account(account_id)
    if not acc:
        return {"ok": False, "session_ok": False, "credits": None, "credits_known": False, "captcha": False,
                "detail": "Không tìm thấy tài khoản"}

    pool = AccountPool.get()
    if not pool_held and not pool.acquire(account_id, None):
        return {"ok": False, "session_ok": False, "credits": None, "credits_known": False, "captcha": False,
                "detail": _busy_message(acc["name"], account_id)}
    result = {"ok": False, "session_ok": False, "credits": None, "credits_known": False, "captcha": False,
              "detail": "", "screenshot": None}
    try:
        with sync_playwright() as p:
            with browser_session(p, account_profile_dir(account_id), proxy=parse_proxy(acc.get("proxy")),
                                 headless=True, account_id=account_id) as context:
                _inject_cookies(context, acc)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(config.DOLA_CHAT_URL, timeout=60000, wait_until="domcontentloaded")
                time.sleep(3)

                curr_c = context.cookies()
                result["session_ok"] = has_dola_session(curr_c)
                if result["session_ok"]:
                    save_account_storage_state(account_id, curr_c)
                    _mark_account_connected(account_id, curr_c)

                if _detect_captcha(page):
                    result["captcha"] = True
                    arts = save_failure_artifacts(page, "captcha", account_id=account_id)
                    result["screenshot"] = arts.get("png_name")
                    _set_account_fields(account_id, needs_manual=NeedsManual.CAPTCHA, last_error="Dola yêu cầu kéo captcha")
                    result["detail"] = "Dola đang yêu cầu kéo mảnh ghép (captcha); mở Chrome của nick để kéo" + artifact_suffix(arts)
                    return result

                if acc.get("needs_manual") == NeedsManual.CAPTCHA:
                    _set_account_fields(account_id, needs_manual=None)

                if not result["session_ok"]:
                    arts = save_failure_artifacts(page, "no_session", account_id=account_id)
                    result["screenshot"] = arts.get("png_name")
                    result["detail"] = "Trang Dola không nhận phiên đăng nhập (sessionid mất hiệu lực), cần đăng nhập lại" + artifact_suffix(arts)
                    _set_account_fields(account_id, needs_manual=NeedsManual.LOGIN, last_error=result["detail"])
                    return result

                credits = extract_dola_credits(page)
                _record_credits(account_id, credits)
                result["credits"] = credits
                result["credits_known"] = credits is not None
                if credits is None:
                    arts = save_failure_artifacts(page, "credit_unreadable", account_id=account_id)
                    result["screenshot"] = arts.get("png_name")
                    result["detail"] = CREDIT_UNREADABLE + artifact_suffix(arts)
                    result["ok"] = True
                else:
                    result["ok"] = True
                    result["detail"] = f"Phiên Dola hợp lệ, còn {credits} credit hôm nay" if credits > 0 else "Phiên Dola hợp lệ nhưng đã hết credit hôm nay"
                return result
    except ChromeNotFoundError as e:
        result["detail"] = str(e)
        return result
    except Exception as e:  # noqa: BLE001
        result["detail"] = f"Mở trang Dola lỗi: {str(e)[:150]}"
        _set_account_fields(account_id, last_error=result["detail"])
        log_event(f"Chẩn đoán Dola nick #{account_id} lỗi: {str(e)[:120]}", "WARNING", "Diagnose", account_id=account_id)
        return result
    finally:
        if not pool_held:
            pool.release(account_id)


# ==================== THỰC THI VIDEO JOB ====================
_DOLA_API_PARAMS = """{
    version_code: '20800', language: 'en', device_platform: 'web', doubao_device_platform: 'web',
    aid: '495671', real_aid: '495671', pkg_type: 'release_version', samantha_web: '1',
    web_platform: 'browser', 'use-olympus-account': '1'
}"""

_JS_RECENT_CONV_IDS = """async () => {
    try {
        const url = new URL('/im/chain/recent_conv', location.origin);
        const params = %s;
        for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
        const resp = await fetch(url, {
            method: 'POST',
            headers: {'accept': 'application/json, text/plain, */*', 'content-type': 'application/json; encoding=utf-8', 'Agw-Js-Conv': 'str'},
            body: JSON.stringify({
                cmd: 3200,
                uplink_body: { pull_recent_conv_chain_uplink_body: { limit: %d, message_count_per_conv: %d, api_version: 1, conv_version: 0, is_cold: true } },
                sequence_id: 'seq_' + Date.now(), channel: 2, version: '1'
            }),
            credentials: 'include'
        });
        const data = await resp.json();
        const cells = data?.downlink_body?.pull_recent_conv_chain_downlink_body?.cells || [];
        return cells.map(c => c?.conversation?.conversation_id || c?.id).filter(Boolean).map(String);
    } catch(e) { return []; }
}"""

_JS_SINGLE_CHAIN = """async () => {
    try {
        const url = new URL('/im/chain/single', location.origin);
        const params = %s;
        for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
        const resp = await fetch(url, {
            method: 'POST',
            headers: {'accept': 'application/json, text/plain, */*', 'content-type': 'application/json; encoding=utf-8', 'Agw-Js-Conv': 'str'},
            body: JSON.stringify({
                cmd: 3100,
                uplink_body: { pull_singe_chain_uplink_body: { conversation_id: '%s', anchor_index: 999999999, conversation_type: 3, direction: 1, limit: 20, ext: {}, filter: { index_list: [] } } },
                sequence_id: 'seq_' + Date.now(), channel: 2, version: '1'
            }),
            credentials: 'include'
        });
        if (!resp.ok) return null;
        return await resp.json();
    } catch(e) { return null; }
}"""


def _fetch_recent_conv_ids(page, limit: int, per_conv: int, job_id=None) -> list:
    try:
        ids = page.evaluate(_JS_RECENT_CONV_IDS % (_DOLA_API_PARAMS, limit, per_conv))
        return [str(x) for x in ids] if isinstance(ids, list) else []
    except Exception as e:  # noqa: BLE001
        log.debug("Gọi recent_conv lỗi: %s", str(e)[:80], extra={"job_id": job_id})
        return []


def _fetch_single_chain(page, conv_id: str, job_id=None):
    try:
        return page.evaluate(_JS_SINGLE_CHAIN % (_DOLA_API_PARAMS, conv_id))
    except Exception as e:  # noqa: BLE001
        log.debug("Gọi chain/single lỗi: %s", str(e)[:80], extra={"job_id": job_id})
        return None


def build_full_prompt(job: dict) -> str:
    """Prompt cuối cùng gửi Dola (giữ nguyên công thức cũ)."""
    dur = job.get("duration") or 30
    raw_p = (job.get("prompt") or "").strip()
    raw_p = re.sub(r'^(Làm video|Tạo video|Video đã tạo)[:\s\-]*', '', raw_p, flags=re.I).strip()
    has_cine = any(k in raw_p.lower() for k in [
        'shot', 'lens', 'lighting', 'cinematic', '8k', '4k', 'camera', 'fpv', 'góc quay', 'ánh sáng', 'điện ảnh'
    ])
    if not has_cine:
        action_motion = ("Góc quay camera FPV chuyển động linh hoạt bám sát nhân vật, các pha nhào lộn và chuyển động "
                         "hành động dồn dập kịch tính, ánh sáng điện ảnh Hollywood bom tấn, dynamic high-speed acrobatic action, "
                         "Hollywood blockbuster action masterpiece, 4k ultra realistic.")
        return f"Tạo video Seedance 2.5 dài {dur} giây: {raw_p}. {action_motion}"
    return f"Tạo video Seedance 2.5 dài {dur} giây: {raw_p}"


def update_job_status(job_id, status, status_message, progress, local_video_path=None, **fields):
    """Cập nhật trạng thái job. status phải là một giá trị của constants.JobStatus."""
    if status not in JobStatus.ALL:
        raise ValueError(f"Trạng thái job không hợp lệ: {status!r}")
    if local_video_path is not None:
        fields["local_video_path"] = local_video_path
    extra_cols = "".join(f", {k} = ?" for k in fields)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE jobs SET status = ?, status_message = ?, progress = ?, updated_at = CURRENT_TIMESTAMP{extra_cols} WHERE id = ?",
            (status, status_message, progress, *fields.values(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _set_job_fields(job_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn = get_connection()
    try:
        conn.execute(f"UPDATE jobs SET {cols}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (*fields.values(), job_id))
        conn.commit()
    finally:
        conn.close()


def _fail_job(job_id: int, account_id: int, status: str, reason: str, page=None, tag: str = "job_failed",
              level: str = "WARNING", module: str = "Job") -> None:
    """Đặt job Thất bại / Tạm dừng kèm ảnh chụp (nếu có page) và ghi log có job_id/account_id."""
    arts = save_failure_artifacts(page, tag, job_id=job_id, account_id=account_id) if page is not None else {}
    msg = reason + artifact_suffix(arts)
    fields = {"finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")} if status in JobStatus.FINISHED else {}
    update_job_status(job_id, status, msg, 0, **fields)
    log_event(f"Job #{job_id}: {msg}", level, module, job_id=job_id, account_id=account_id)


def _fail_technical(job_id: int, acc: dict, reason: str, page=None, tag: str = "job_failed",
                    module: str = "Job") -> None:
    """Lỗi kỹ thuật (Chrome/mạng/render timeout/tải video): tự chạy lại tối đa config.MAX_AUTO_RETRIES lần
    (docs/KIEN_TRUC.md mục 4, BH-04). `attempts` đã được worker tăng khi nhặt job, nên attempts = số lần đã thử.

    attempts <= MAX_AUTO_RETRIES → job về Chờ kèm "tự chạy lại lần n/N" (worker nhặt lại, chọn nick theo pool);
    ngược lại → Thất bại với Reason.MAX_ATTEMPTS + lý do gốc. Ảnh chụp luôn nối ở cuối.
    """
    current = _load_job(job_id) or {}
    attempts = int(current.get("attempts") or 0)
    max_retries = int(config.MAX_AUTO_RETRIES)
    if attempts <= max_retries:
        msg = f"{reason} · tự chạy lại lần {attempts}/{max_retries}"
        _fail_job(job_id, acc["id"], JobStatus.CHO, msg, page, tag, level="WARNING", module=module)
    else:
        msg = f"{Reason.MAX_ATTEMPTS.format(n=attempts)}. {reason}"
        _fail_job(job_id, acc["id"], JobStatus.THAT_BAI, msg, page, tag, level="ERROR", module=module)


class _NoCredit(Exception):
    """Nick hết credit giữa chừng: job về Chờ để worker chọn nick khác."""


def _handle_no_credit(job_id: int, acc: dict) -> None:
    _mark_no_credit(acc["id"])
    # Không tính là một lần thử của job vì lỗi thuộc về nick, không phải job
    _set_job_fields(job_id, attempts=max(0, int(_load_job(job_id).get("attempts") or 0) - 1))
    msg = Reason.NO_CREDIT_WAIT.format(name=acc["name"])
    update_job_status(job_id, JobStatus.CHO, msg, 0)
    log_event(f"Job #{job_id}: {msg}", "WARNING", "Credit", job_id=job_id, account_id=acc["id"])


def _handle_captcha(job_id: int, acc: dict, page) -> None:
    _set_account_fields(acc["id"], needs_manual=NeedsManual.CAPTCHA, last_error="Dola yêu cầu kéo captcha")
    _fail_job(job_id, acc["id"], JobStatus.TAM_DUNG, Reason.CAPTCHA.format(name=acc["name"]), page, "captcha", module="Captcha")


def _download_video(url: str, dest_file: str, job_id: int) -> bool:
    req_dl = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': config.DOLA_BASE_URL + '/',
    })
    with urllib.request.urlopen(req_dl, timeout=120) as resp_v, open(dest_file, 'wb') as out_v:
        shutil.copyfileobj(resp_v, out_v)
    if os.path.exists(dest_file) and os.path.getsize(dest_file) > 50000:
        return True
    log.warning("File video tải về quá nhỏ (%s byte), bỏ qua", os.path.getsize(dest_file) if os.path.exists(dest_file) else 0,
                extra={"job_id": job_id})
    return False


def _run_job_in_browser(job: dict, acc: dict, context, page, state: Optional[dict] = None) -> None:
    """Toàn bộ tương tác Dola cho một job; mọi trạng thái cuối đều được ghi trong hàm này.

    `state["page_reached"]` được bật ngay khi goto trang Dola thành công, để _apply_technical_failure
    phân biệt lỗi kết nối (chưa vào được trang) với lỗi sau khi đã có phiên.
    """
    job_id = job["id"]
    account_id = acc["id"]
    today_str = get_today_str()
    state = state if state is not None else {}

    update_job_status(job_id, JobStatus.DANG_CHAY, f"Mở phiên Dola bằng nick '{acc['name']}' và kiểm tra credit", 25)
    page.goto(config.DOLA_CHAT_URL, timeout=60000, wait_until="domcontentloaded")
    state["page_reached"] = True
    time.sleep(3)

    curr_c = context.cookies()
    if has_dola_session(curr_c):
        save_account_storage_state(account_id, curr_c)
        _mark_account_connected(account_id, curr_c)
    else:
        arts = save_failure_artifacts(page, "no_session", job_id=job_id, account_id=account_id)
        _set_account_fields(account_id, needs_manual=NeedsManual.LOGIN, last_error="Phiên Dola mất hiệu lực, cần đăng nhập lại")
        _set_job_fields(job_id, attempts=max(0, int(job.get("attempts") or 0) - 1))
        msg = f"Nick '{acc['name']}' mất phiên Dola, cần đăng nhập lại; job chờ nick khác" + artifact_suffix(arts)
        update_job_status(job_id, JobStatus.CHO, msg, 0)
        log_event(f"Job #{job_id}: {msg}", "WARNING", "Auth", job_id=job_id, account_id=account_id)
        return

    if _detect_captcha(page):
        _handle_captcha(job_id, acc, page)
        return

    credits_pre = extract_dola_credits(page)
    if credits_pre == 0:
        _handle_no_credit(job_id, acc)
        return
    if credits_pre is None:
        _set_account_fields(account_id, credits=None, last_error=CREDIT_UNREADABLE)
        log.warning("%s, vẫn thử gửi prompt", CREDIT_UNREADABLE, extra={"job_id": job_id, "account_id": account_id})
    else:
        _record_credits(account_id, credits_pre)

    # 1. Ghi nhận conversation đã có để không lấy nhầm video cũ
    initial_conv_ids = set()
    m_curr = re.search(r'/chat/(\d+)', page.url)
    if m_curr:
        initial_conv_ids.add(m_curr.group(1))
    initial_conv_ids.update(_fetch_recent_conv_ids(page, 10, 1, job_id))

    # 2. Gửi prompt
    full_prompt = build_full_prompt(job)
    _set_job_fields(job_id, prompt_final=full_prompt)
    update_job_status(job_id, JobStatus.DANG_CHAY, "Đang gửi prompt sang Dola", 30)
    input_box = page.locator("div.ProseMirror, textarea, [contenteditable='true']").first
    if input_box.is_visible():
        input_box.click()
        input_box.fill(full_prompt)
        time.sleep(1)
        page.keyboard.press("Enter")
    else:
        _fail_job(job_id, account_id, JobStatus.THAT_BAI, "Không thấy ô nhập prompt trên trang Dola", page, "no_input")
        return
    time.sleep(4)

    if _detect_captcha(page):
        _handle_captcha(job_id, acc, page)
        return

    body_text = _safe_body_text(page)
    if RE_DAILY_LIMIT.search(body_text) or "only have 0 left today" in body_text or "chỉ còn 0" in body_text:
        _handle_no_credit(job_id, acc)
        return

    # 3. Lấy conversation_id MỚI
    conv_id = None
    wait_conv_start = time.time()
    while time.time() - wait_conv_start < 30:
        m_url = re.search(r'/chat/(\d+)', page.url)
        if m_url and m_url.group(1) not in initial_conv_ids:
            conv_id = m_url.group(1)
            break
        for cand_id in _fetch_recent_conv_ids(page, 3, 3, job_id):
            if cand_id and cand_id not in initial_conv_ids:
                conv_id = cand_id
                break
        if conv_id:
            break
        time.sleep(3)

    if not conv_id:
        if _detect_captcha(page):
            _handle_captcha(job_id, acc, page)
        else:
            _fail_job(job_id, account_id, JobStatus.THAT_BAI, Reason.NO_NEW_CONV, page, "no_new_conv", module="Engine")
        return

    # 4. Chờ render & tải video
    dest_file = os.path.join(config.OUTPUTS_DIR, f"video_{job_id}.mp4")
    downloaded = False
    download_error = None
    start_poll = time.time()
    max_wait_seconds = config.RENDER_TIMEOUT_SECONDS
    log_event(f"Job #{job_id}: theo dõi Dola render (conv_id={conv_id})", "INFO", "Render", job_id=job_id, account_id=account_id)

    while time.time() - start_poll < max_wait_seconds:
        elapsed_sec = int(time.time() - start_poll)
        est_progress = min(88, 35 + int((elapsed_sec / 120) * 50))
        update_job_status(job_id, JobStatus.DANG_CHAY, f"Dola đang render Seedance 2.5 ({elapsed_sec}s)", est_progress)

        chain_res = _fetch_single_chain(page, conv_id, job_id)
        chain_str = ""
        if chain_res and isinstance(chain_res, dict):
            chain_str = json.dumps(chain_res.get('data') or chain_res, ensure_ascii=False)
        chain_lower = chain_str.lower()

        if "daily limit for video generation" in chain_lower or "đã đạt giới hạn tạo video trong ngày" in chain_lower:
            _handle_no_credit(job_id, acc)
            return

        if ("cannot provide" in chain_lower or "unable to provide" in chain_lower or "không thể cung cấp" in chain_lower) \
                and "generating" not in chain_lower:
            _fail_job(job_id, account_id, JobStatus.THAT_BAI, Reason.POLICY_REFUSED, page, "policy", module="Policy")
            return

        clean_urls = []
        for raw in re.findall(r'https?://[^\s"\'<>]+', chain_str):
            clean_u = raw.replace(r'\/', '/').replace(r'&', '&')
            if any(ext in clean_u for ext in ['.mp4', '.webm', '/video/tos/', 'mime_type=video_']) and 'watermark' not in clean_u:
                if clean_u not in clean_urls:
                    clean_urls.append(clean_u)

        if not clean_urls:
            try:
                dom_videos = page.locator("video").evaluate_all("els => els.map(e => e.currentSrc || e.src).filter(Boolean)")
                for dv in dom_videos:
                    if any(ext in dv for ext in ['.mp4', '.webm', '/video/tos/']) and dv not in clean_urls:
                        clean_urls.append(dv)
            except Exception as e:  # noqa: BLE001
                log.debug("Quét thẻ <video> lỗi: %s", str(e)[:80], extra={"job_id": job_id})

        if clean_urls:
            target_video_url = clean_urls[0]
            log_event(f"Job #{job_id}: tìm thấy video thành phẩm, đang tải về máy", "SUCCESS", "Download", job_id=job_id, account_id=account_id)
            update_job_status(job_id, JobStatus.DANG_CHAY, "Đang tải video từ Dola về máy", 92)
            try:
                downloaded = _download_video(target_video_url, dest_file, job_id)
                if downloaded:
                    sz_mb = round(os.path.getsize(dest_file) / (1024 * 1024), 2)
                    log_event(f"Job #{job_id}: đã lưu video ({sz_mb} MB) vào {dest_file}", "SUCCESS", "Download", job_id=job_id, account_id=account_id)
                    break
            except Exception as dl_err:  # noqa: BLE001
                download_error = str(dl_err)[:100]
                log_event(f"Job #{job_id}: tải video lỗi: {download_error}", "WARNING", "Download", job_id=job_id, account_id=account_id)

        time.sleep(5)

    # 5. Credit còn lại sau render
    credits_post = extract_dola_credits(page)
    _record_credits(account_id, credits_post, touch_last_used=True)

    if downloaded and os.path.exists(dest_file) and os.path.getsize(dest_file) > 50000:
        update_job_status(job_id, JobStatus.HOAN_THANH, "Đã tạo video thành công, sẵn sàng xem hoặc tải về", 100,
                          local_video_path=f"/outputs/video_{job_id}.mp4",
                          finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        log_event(f"Job #{job_id}: hoàn thành bằng nick '{acc['name']}'", "SUCCESS", "Job", job_id=job_id, account_id=account_id)
    elif download_error:
        _fail_technical(job_id, acc, Reason.DOWNLOAD_FAILED.format(error=download_error), page, "download_failed", module="Download")
    else:
        _fail_technical(job_id, acc, Reason.RENDER_TIMEOUT.format(seconds=max_wait_seconds), page, "render_timeout", module="Render")


# Job chờ chỗ mở Chrome tối đa chừng này (G-2); bình thường worker chỉ điều phối khi còn slot nên hiếm khi phải chờ
JOB_SLOT_TIMEOUT_SECONDS = 120


def execute_video_job(job_id: int, account_id: int) -> None:
    """Chạy một job trên nick đã được worker chọn và khóa. Hàm sync, worker gọi trong thread.

    Không tự chọn/đổi nick: hết credit, mất phiên → job về Chờ để worker chọn nick khác;
    captcha → Tạm dừng + needs_manual; lỗi kỹ thuật → Thất bại kèm ảnh chụp.
    """
    job = _load_job(job_id)
    if not job:
        log_event(f"Job #{job_id} không còn trong CSDL, bỏ qua", "WARNING", "Job", job_id=job_id)
        return
    acc = _load_account(account_id)
    if not acc:
        _fail_job(job_id, account_id, JobStatus.THAT_BAI, f"Nick #{account_id} không tồn tại hoặc đã bị xóa")
        return

    update_job_status(job_id, JobStatus.DANG_CHAY, f"Khởi tạo trình duyệt cho nick '{acc['name']}'", 10)

    page = None
    state = {"page_reached": False}  # bật trong _run_job_in_browser khi goto trang Dola xong
    def _on_wait_slot(message: str) -> None:
        update_job_status(job_id, JobStatus.DANG_CHAY, message, 5)

    try:
        with sync_playwright() as p:
            with browser_session(p, account_profile_dir(account_id), proxy=parse_proxy(acc.get("proxy")),
                                 headless=True, account_id=account_id,
                                 slot_timeout=JOB_SLOT_TIMEOUT_SECONDS, on_wait=_on_wait_slot) as context:
                _inject_cookies(context, acc)
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    _run_job_in_browser(job, acc, context, page, state)
                except Exception as inner:  # noqa: BLE001 - chụp ảnh khi trang còn mở rồi xử lý bên dưới
                    _apply_technical_failure(job_id, acc, inner, page, state["page_reached"])
    except ChromeNotFoundError as e:
        _apply_technical_failure(job_id, acc, e, None, False)
    except Exception as e:  # noqa: BLE001
        if _job_already_finalized(job_id):
            log.debug("Lỗi sau khi job đã kết thúc (bỏ qua): %s", str(e)[:120], extra={"job_id": job_id})
        else:
            _apply_technical_failure(job_id, acc, e, None, state["page_reached"])


def _job_already_finalized(job_id: int) -> bool:
    job = _load_job(job_id)
    return bool(job) and job.get("status") != JobStatus.DANG_CHAY


def _apply_technical_failure(job_id: int, acc: dict, error: Exception, page, page_reached: bool) -> None:
    """Lỗi trình duyệt/mạng trong lúc chạy job (docs/KIEN_TRUC.md mục 4, BH-24).

    Nick:
    - đã vào được trang Dola rồi mới lỗi → lỗi thuộc về phiên/proxy của nick → `rate_limited` ngay
      (worker tự mở lại sau 30 phút), job sẽ được gán nick khác nếu có;
    - chưa vào được trang (không mở được Chrome, goto thất bại) → chỉ tăng `consecutive_errors`;
      nick vẫn ready để job tự chạy lại; quá MAX_AUTO_RETRIES lần liên tiếp (lần thứ 3) mới `rate_limited`.
      `consecutive_errors` về 0 khi nick vào được trang (_mark_account_connected).
    Job: đi qua _fail_technical (Chờ + "tự chạy lại lần n/N", hoặc Thất bại + MAX_ATTEMPTS).
    """
    account_id = acc["id"]
    err_text = str(error).strip().splitlines()[0][:160] if str(error).strip() else error.__class__.__name__
    reason = Reason.BROWSER_ERROR.format(error=err_text)
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fields = {"last_error": err_text if page_reached else f"Không vào được trang Dola: {err_text}"}
    if isinstance(error, ChromeNotFoundError):
        fields["chrome_ok"] = 0
    if page_reached:
        fields.update(status=AccountStatus.RATE_LIMITED, last_used=now_s)
    else:
        fresh = _load_account(account_id) or {}
        streak = int(fresh.get("consecutive_errors") or 0) + 1
        fields["consecutive_errors"] = streak
        if streak > int(config.MAX_AUTO_RETRIES):
            fields.update(status=AccountStatus.RATE_LIMITED, last_used=now_s)
            log_event(f"Nick '{acc['name']}' lỗi kết nối Dola {streak} lần liên tiếp, cho nghỉ 30 phút (rate_limited)",
                      "WARNING", "Job", job_id=job_id, account_id=account_id)
    _set_account_fields(account_id, **fields)
    _fail_technical(job_id, acc, reason, page, "browser_error", module="Job")
