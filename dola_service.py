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
import director  # hàm thuần (HEADER_RE, parse_header, fix_header), không import ngược module này
from account_pool import AccountPool
from browser import ChromeNotFoundError, browser_session, hide_window, show_window
from constants import (DEFAULT_DURATION, DEFAULT_RATIO, AccountStatus, JobStatus, NeedsManual, Reason,
                       duration_label, normalize_duration, normalize_ratio)
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

# `#captcha_container`: lớp phủ thật của Dola (div có id, KHÔNG có class, position:fixed phủ cả trang, bên trong là
# iframe bdcaptcha.html của ByteDance) xuất hiện ngay sau khi gửi prompt (BH-39). Các mẫu còn lại là dự phòng.
CAPTCHA_SELECTOR = ("#captcha_container, iframe[src*='captcha'], iframe[src*='secsdk'], iframe[id*='captcha'], "
                    "div[class*='captcha'], div[class*='secsdk']")
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
    if cookie_str and ("sessionid=" in cookie_str or "sessionid_ss=" in cookie_str) and "c_user=" not in cookie_str:
        return parse_dola_cookies(cookie_str)
    return _parse_raw_cookie_for_domain(cookie_str, domain)


def _parse_raw_cookie_for_domain(cookie_str: str, domain: str):
    if not cookie_str or not cookie_str.strip():
        return []
    cookie_str = cookie_str.strip()
    if (cookie_str.startswith("[") and cookie_str.endswith("]")) or (cookie_str.startswith("{") and cookie_str.endswith("}")):
        try:
            data = json.loads(cookie_str)
            raw_list = data if isinstance(data, list) else (data.get("cookies", []) if isinstance(data, dict) else [])
            if raw_list and isinstance(raw_list, list):
                result = []
                for c in raw_list:
                    if isinstance(c, dict) and c.get("name") and c.get("value"):
                        c_dict = dict(c)
                        if not c_dict.get("domain"):
                            c_dict["domain"] = domain
                        if not c_dict.get("path"):
                            c_dict["path"] = "/"
                        result.append(c_dict)
                if result:
                    return result
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
    """Nick vào được trang Dola có phiên: cookie mới nhất, ready, đếm lại lỗi kết nối liên tiếp từ 0, lưu hạn phiên."""
    fields = {
        "cookies": json.dumps(cookies),
        "status": AccountStatus.READY,
        "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "consecutive_errors": 0,
    }
    if isinstance(cookies, list):
        for c in cookies:
            if isinstance(c, dict) and c.get("name") in ("sessionid", "sessionid_ss") and c.get("value"):
                exp = c.get("expires", c.get("expirationDate"))
                if exp is not None:
                    try:
                        exp_f = float(exp)
                        if exp_f > 0:
                            fields["session_expires"] = datetime.fromtimestamp(exp_f).strftime("%Y-%m-%d %H:%M:%S")
                            break
                    except (ValueError, OSError, OverflowError):
                        pass
    _set_account_fields(account_id, **fields)


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


def _captcha_evidence(page) -> str:
    """Trả về dấu hiệu captcha đang HIỂN THỊ (chuỗi mô tả) hoặc "" nếu không có.

    BH-36: chỉ tính khung captcha đang hiện và có kích thước, hoặc câu chữ nguyên văn của
    captcha; icon lỗi ẩn hay chữ "verify" nằm trong từ khác (verified) KHÔNG phải captcha.
    BH-38: luôn ghi rõ dấu hiệu nào kích hoạt để người dùng và lập trình viên đối chiếu ảnh.
    """
    try:
        frames = page.locator(CAPTCHA_SELECTOR)
        for i in range(frames.count()):
            el = frames.nth(i)
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if box and box["width"] >= 40 and box["height"] >= 40:
                desc = el.evaluate("e => (e.tagName + ' ' + (e.id ? '#' + e.id : '') + ' .' + String(e.className).slice(0, 80))")
                return f"khung {desc.strip()} ({int(box['width'])}x{int(box['height'])}px)"
        body_t = _safe_body_text(page).lower()
        for kw in CAPTCHA_KEYWORDS:
            if kw in body_t:
                return f'chữ "{kw}"'
    except Exception as e:  # noqa: BLE001
        log.debug("Kiểm tra captcha lỗi: %s", str(e)[:80])
    return ""


def _detect_captcha(page) -> bool:
    """Có khung/chữ yêu cầu kéo mảnh ghép (slide captcha) đang HIỂN THỊ trên trang không."""
    return bool(_captcha_evidence(page))


def _captcha_gone(page) -> bool:
    """True khi trang còn mở và KHÔNG còn phần tử captcha nào hiển thị (người dùng đã kéo xong).

    Trang đã đóng/crash không được coi là "hết captcha" (sẽ lộ ra ở bước sau như lỗi kỹ thuật, không phải "đã giải").
    """
    try:
        if page.is_closed():
            return False
        return _captcha_evidence(page) == ""
    except Exception as e:  # noqa: BLE001
        log.debug("Kiểm tra captcha đã biến mất lỗi: %s", str(e)[:80])
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
                else:
                    arts = save_failure_artifacts(page, "no_session", account_id=account_id)
                    msg = f"Trang Dola không nhận phiên đăng nhập của nick '{acc['name']}' (sessionid mất hiệu lực), cần đăng nhập lại" + artifact_suffix(arts)
                    _set_account_fields(account_id, needs_manual=NeedsManual.LOGIN, last_error=msg)
                    log_event(msg, "WARNING", "Auth", account_id=account_id)
                    return {"success": False, "is_known": False, "message": msg}

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


def _load_settings_dict() -> dict:
    conn = get_connection()
    try:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings").fetchall()}
    finally:
        conn.close()


def job_video_params(job: dict, settings: Optional[dict] = None) -> tuple:
    """(số giây đã ép vào 4-15, tỷ lệ khung hình, cảnh báo thời lượng | None) của một job (BH-46).

    Job cũ còn duration "30 giây" trong hàng đợi → 15 giây kèm cảnh báo; ratio rỗng → setting default_ratio.
    """
    settings = settings if settings is not None else _load_settings_dict()
    seconds, warning = normalize_duration(job.get("duration") or settings.get("default_duration") or DEFAULT_DURATION)
    ratio, _ = normalize_ratio(job.get("ratio") or settings.get("default_ratio") or DEFAULT_RATIO)
    return seconds, ratio, warning


def build_full_prompt(job: dict) -> str:
    """Prompt cuối cùng gửi Dola = prompt đã đạo diễn (jobs.prompt_final, BH-42).

    Job tạo trước khi có Đạo diễn AI chưa có prompt_final → ghép bằng director.compose với
    cài đặt và kho nhân vật hiện tại. Không còn câu "FPV bom tấn" cố định.
    BH-46: thời lượng ngoài 4-15 giây (job cũ "30 giây") bị ép về 15 và câu mở đầu được viết lại
    (director.fix_header) để luôn nêu số giây hợp lệ + tỷ lệ khung hình; jobs.duration/ratio được ghi lại.
    BH-49: câu mở đầu đã hợp lệ (giây 4-15 + tỷ lệ) thì giữ nguyên văn và ghi ngược jobs.duration/ratio theo nó.
    """
    settings = _load_settings_dict()
    ready = (job.get("prompt_final") or "").strip()
    header = director.parse_header(ready) if ready else None
    if header and header["valid"]:
        # BH-49: câu mở đầu đã có số giây 4-15 và tỷ lệ hợp lệ (người dùng có thể đã sửa tay "8 giây"/"9:16")
        # → header thắng, không ghi đè; đọc ngược để jobs.duration/ratio khớp với thứ thật sự gửi Dola
        seconds, ratio, warning = header["seconds"], header["ratio"], None
    else:
        seconds, ratio, warning = job_video_params(job, settings)
    label = duration_label(seconds)
    fields = {}
    if (job.get("duration") or "") != label:
        fields["duration"] = label
    if (job.get("ratio") or "") != ratio:
        fields["ratio"] = ratio
    if warning:
        log_event(f"Job #{job['id']}: {warning}", "WARNING", "Job", job_id=job["id"], account_id=job.get("account_id"))
    if fields:
        _set_job_fields(job["id"], **fields)
        job.update(fields)

    if ready:
        return director.fix_header(ready, label, ratio)
    conn = get_connection()
    try:
        assets = [dict(r) for r in conn.execute(
            "SELECT id, name, character_code, image_url, description FROM assets").fetchall()]
    finally:
        conn.close()
    res = director.compose(
        job.get("prompt") or "",
        duration_label=label,
        ratio=ratio,
        model=job.get("model") or settings.get("default_model") or "Seedance 2.5",
        options=director.options_from_settings(settings),
        assets=assets,
    )
    return res["prompt_final"]


# ==================== ĐỌC CÂU TRẢ LỜI CỦA DOLA TRONG LÚC CHỜ RENDER (BH-47) ====================
_REPLY_KEYS = ("content", "text", "message")
_RE_URL = re.compile(r"https?://", re.IGNORECASE)
_QUESTION_PHRASES = ("which option", "would you like", "aspect ratio", "duration", "confirm",
                     "bạn muốn", "tỷ lệ", "thời lượng", "lựa chọn", "chọn")
# Chữ Dola/fake hiện trong lúc đang render: không phải "trả lời bằng chữ"
_GENERATING_MARKERS = ("generating", "đang tạo")
REPLY_MIN_CHARS = 20
# Văn bản trả lời giống lời TỪ CHỐI/GIẢI THÍCH (không phải câu hỏi) mà sau chừng này giây vẫn không có video/không
# "generating" → Thất bại sớm (N-1). Văn bản khác (Dola nói gì đó nhưng không rõ là từ chối) chờ lâu hơn.
REPLY_NO_VIDEO_SECONDS = 60
# Văn bản trả lời bất kỳ (không câu hỏi, không từ chối) mà quá chừng này giây vẫn không video/không "generating" → Thất bại
REPLY_NO_VIDEO_HARD_SECONDS = 120
_RE_REFUSAL = re.compile(r"cannot|can't|unable|sorry|not able|not support|không thể|không hỗ trợ|xin lỗi|không được phép",
                         re.IGNORECASE)
# Dola hỏi lại mà không thấy ô nhập để trả lời: thử lại ở vòng poll sau, tối đa chừng này lần (N-3)
AUTO_ANSWER_MAX_TRIES = 3
# Giá trị của role/user_type/sender/from đánh dấu tin nhắn do NGƯỜI DÙNG (tức tool) gửi trong chain (BH-48)
_USER_ROLE_KEYS = ("role", "user_type", "sender", "from")
_USER_ROLE_VALUES = ("user", "human", "1", "me", "self")
# Sau khi tự trả lời câu hỏi của Dola, mốc chờ render được đặt lại nhưng tổng không quá RENDER_TIMEOUT + chừng này
REPLY_EXTRA_RENDER_SECONDS = 120


def _maybe_json(value: str):
    """Chuỗi trông như JSON ({...} / [...]) → đối tượng; không phải → None."""
    v = value.strip()
    if len(v) < 2 or v[0] not in "{[" or v[-1] not in "}]":
        return None
    try:
        return json.loads(v)
    except ValueError:
        return None


def _own_text_head(text: str) -> str:
    """40 ký tự đầu của một tin tool đã gửi, tính SAU câu mở đầu cố định (director.HEADER_RE) nếu có (N-2).

    Câu mở đầu "Tạo video ... dài N giây, tỷ lệ ..." giống nhau ở mọi job và Dola hay trích lại nó khi từ chối
    ("You asked: 'Tạo video ...' but I cannot ..."); lấy 40 ký tự đầu của prompt làm dấu hiệu "tin của mình" sẽ
    bỏ nhầm câu từ chối đó. Phần sau header mới là nội dung riêng của job.
    """
    norm = " ".join((text or "").split())
    m = director.HEADER_RE.match(norm)
    body = norm[m.end():].lstrip() if m else norm
    return body[:PROMPT_PREFIX_CHECK_CHARS]


def _is_user_node(node: dict) -> bool:
    """Tin nhắn trong chain có role/user_type/sender/from là người dùng (tức do tool gửi) → bỏ cả nhánh (BH-48)."""
    for key in _USER_ROLE_KEYS:
        if key in node:
            v = node[key]
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and int(v) == 1:
                return True
            if isinstance(v, str) and v.strip().lower() in _USER_ROLE_VALUES:
                return True
            if isinstance(v, dict) and _is_user_node(v):   # sender: {role: "user"}
                return True
    return False


def _assistant_texts(chain_json, sent_prompt: str = "", own_texts=()) -> list:
    """Trích các đoạn văn bản TRỢ LÝ trả lời từ JSON chain/single của Dola.

    Duyệt đệ quy mọi dict/list; chuỗi JSON lồng trong chuỗi (Dola để `content` là một chuỗi JSON chứa `text`)
    được parse và duyệt tiếp. Lấy chuỗi > REPLY_MIN_CHARS ký tự ở các khóa content/text/message; bỏ chuỗi chứa URL
    (đó là video/ảnh). Thứ tự xuất hiện, không trùng.
    BH-48: chain của Dola (thật lẫn fake) chứa CẢ tin nhắn tool đã gửi (prompt, câu tự trả lời, bản gửi lại sau
    captcha), nên (a) mọi tin trong `sent_prompt` + `own_texts` bị loại: so nguyên văn, bản bị cắt ngắn (chuỗi con
    của tin đã gửi) và 40 ký tự đầu SAU câu mở đầu cố định (`_own_text_head`, N-2); (b) node có role/user_type/
    sender/from = user bị bỏ cả nhánh, không cần so chữ.
    """
    out: list = []
    seen: set = set()
    own_norm = [" ".join(t.split()) for t in [sent_prompt or "", *(own_texts or ())] if t and t.strip()]
    own_heads = [h for h in (_own_text_head(t) for t in own_norm) if len(h) >= 20]

    def is_own_text(text: str) -> bool:
        t = " ".join(text.split())
        return any(t == o or t in o for o in own_norm) or any(h in t for h in own_heads)

    def add(text: str) -> None:
        t = text.strip()
        if len(t) <= REPLY_MIN_CHARS or _RE_URL.search(t) or is_own_text(t) or t in seen:
            return
        seen.add(t)
        out.append(t)

    def walk(node, key: Optional[str] = None, depth: int = 0) -> None:
        if depth > 12:
            return
        if isinstance(node, dict):
            if _is_user_node(node):
                return
            for k, v in node.items():
                walk(v, str(k), depth + 1)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v, key, depth + 1)
        elif isinstance(node, str):
            nested = _maybe_json(node)
            if nested is not None:
                walk(nested, key, depth + 1)
            elif key and key.lower() in _REPLY_KEYS:
                add(node)

    walk(chain_json)
    return out


def _looks_like_question(text: str) -> bool:
    """Dola hỏi lại (tỷ lệ, thời lượng, lựa chọn A/B/C) thay vì tạo video."""
    t = (text or "").lower()
    return "?" in t and any(phrase in t for phrase in _QUESTION_PHRASES)


def _is_generating_text(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _GENERATING_MARKERS)


def _looks_like_refusal(text: str) -> bool:
    """Dola từ chối/giải thích ("I cannot...", "Sorry...", "không thể...") thay vì tạo video (N-1)."""
    return bool(_RE_REFUSAL.search(text or ""))


def _reply_should_fail(reply: str, waited_seconds: float, generating: bool) -> bool:
    """Văn bản trả lời (không phải câu hỏi) đã treo `waited_seconds` giây: dừng sớm hay chờ tiếp? (N-1)

    Đang "generating" → chờ. Giống lời từ chối → dừng sau REPLY_NO_VIDEO_SECONDS (60 s). Văn bản khác → chỉ dừng
    sau REPLY_NO_VIDEO_HARD_SECONDS (120 s) không video; còn lại chờ tới RENDER_TIMEOUT (lý do kèm nguyên văn).
    """
    if generating:
        return False
    if _looks_like_refusal(reply) and waited_seconds >= REPLY_NO_VIDEO_SECONDS:
        return True
    return waited_seconds >= REPLY_NO_VIDEO_HARD_SECONDS


def _auto_answer_step(send_fn, answer: str, tries_so_far: int) -> tuple:
    """Một lần thử gửi câu tự trả lời cho Dola (N-3). Trả về (sent, tries, answered).

    `answered` = coi như đã trả lời: gửi được, HOẶC đã thử đủ AUTO_ANSWER_MAX_TRIES lần mà không thấy ô nhập
    (không thử nữa). Gửi hỏng mà chưa đủ số lần → answered False, vòng poll sau thử lại.
    """
    tries = tries_so_far + 1
    sent = bool(send_fn(answer))
    return sent, tries, sent or tries >= AUTO_ANSWER_MAX_TRIES


def _auto_answer_text(seconds: int, ratio: str) -> str:
    return f"{seconds} giây, tỷ lệ {ratio}. Hãy tạo video ngay, không cần hỏi thêm."


def _short(text: str, n: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n]


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
    log_event(f"Job #{job_id}: {msg}", "WARNING", "Credit", job_id=job_id, account_id=acc["id"])
    update_job_status(job_id, JobStatus.CHO, msg, 0)


def _handle_captcha(job_id: int, acc: dict, page) -> None:
    evidence = _captcha_evidence(page) or "không rõ"
    _set_account_fields(acc["id"], needs_manual=NeedsManual.CAPTCHA, last_error=f"Dola yêu cầu kéo captcha (dấu hiệu: {evidence})")
    _fail_job(job_id, acc["id"], JobStatus.TAM_DUNG,
              Reason.CAPTCHA.format(name=acc["name"]) + f" (dấu hiệu: {evidence})",
              page, "captcha", module="Captcha")


def _captcha_timeout_text(seconds: int) -> str:
    return f"{seconds // 60} phút" if seconds >= 60 and seconds % 60 == 0 else f"{seconds} giây"


def _wait_user_solve_captcha(job_id: int, acc: dict, context, page) -> bool:
    """Captcha giữa chừng job: đưa cửa sổ Chrome của nick ra màn hình, chờ người dùng kéo mảnh ghép tại chỗ
    (tối đa config.CAPTCHA_SOLVE_TIMEOUT_SECONDS) rồi ẩn cửa sổ lại. Trả True nếu captcha đã biến mất.

    Không đổi trạng thái job (vẫn Đang chạy) và không đặt needs_manual trong lúc chờ: nick vẫn do job này giữ,
    người dùng thao tác trực tiếp trên cửa sổ đang mở. Hết giờ → False, người gọi _handle_captcha (Tạm dừng).
    """
    account_id = acc["id"]
    timeout = int(config.CAPTCHA_SOLVE_TIMEOUT_SECONDS)
    evidence = _captcha_evidence(page) or "không rõ"
    job = _load_job(job_id) or {}
    progress = int(job.get("progress") or 30)
    shown = show_window(context, page, account_id=account_id, title=f"Nick {acc['name']} — kéo mảnh ghép")
    if shown:
        msg = (f"Dola yêu cầu kéo mảnh ghép: cửa sổ Chrome của nick '{acc['name']}' đã được đưa ra màn hình, "
               f"hãy kéo mảnh ghép trong {_captcha_timeout_text(timeout)}")
    else:
        # N-4: người dùng không thấy cửa sổ nào để kéo → không chờ đủ 3 phút vô ích, chỉ chờ ngắn rồi Tạm dừng
        timeout = min(timeout, int(config.CAPTCHA_NO_WINDOW_TIMEOUT_SECONDS))
        msg = (f"Dola yêu cầu kéo mảnh ghép nhưng không đưa được cửa sổ Chrome của nick '{acc['name']}' ra màn hình, "
               f"hãy bấm nút Chrome để kéo tay; job chờ thêm {_captcha_timeout_text(timeout)} rồi Tạm dừng")
    update_job_status(job_id, JobStatus.DANG_CHAY, msg, progress)
    arts = save_failure_artifacts(page, "captcha_shown", job_id=job_id, account_id=account_id)
    log_event(f"Job #{job_id}: {msg} (dấu hiệu: {evidence}){artifact_suffix(arts)}", "WARNING", "Captcha",
              job_id=job_id, account_id=account_id)

    started = time.time()
    solved = False
    while time.time() - started < timeout:
        time.sleep(2)
        if _captcha_gone(page):
            solved = True
            break
    elapsed = int(time.time() - started)
    hide_window(context, page)
    if not solved:
        log_event(f"Job #{job_id}: sau {_captcha_timeout_text(timeout)} captcha vẫn còn trên nick '{acc['name']}', "
                  f"tạm dừng job để kéo tay", "WARNING", "Captcha", job_id=job_id, account_id=account_id)
        return False
    _set_account_fields(account_id, needs_manual=None, last_error=None)
    update_job_status(job_id, JobStatus.DANG_CHAY, f"Đã kéo xong mảnh ghép trên nick '{acc['name']}', tiếp tục job", progress)
    log_event(f"Job #{job_id}: người dùng đã kéo xong mảnh ghép trên nick '{acc['name']}' sau {elapsed}s, "
              f"cửa sổ đã ẩn lại, tiếp tục job", "SUCCESS", "Captcha", job_id=job_id, account_id=account_id)
    return True


def _send_prompt(page, full_prompt: str) -> bool:
    """Gõ prompt vào ô nhập và Enter. False nếu không thấy ô nhập."""
    input_box = page.locator("div.ProseMirror, textarea, [contenteditable='true']").first
    if not input_box.is_visible():
        return False
    input_box.click()
    input_box.fill(full_prompt)
    time.sleep(1)
    page.keyboard.press("Enter")
    return True


def _wait_new_conversation(page, initial_conv_ids: set, seconds: float, job_id: int) -> Optional[str]:
    """Chờ tối đa `seconds` cho tới khi URL hoặc recent_conv có conversation KHÔNG nằm trong initial_conv_ids."""
    started = time.time()
    while True:
        m_url = re.search(r'/chat/(\d+)', page.url)
        if m_url and m_url.group(1) not in initial_conv_ids:
            return m_url.group(1)
        for cand_id in _fetch_recent_conv_ids(page, 3, 3, job_id):
            if cand_id and cand_id not in initial_conv_ids:
                return cand_id
        if time.time() - started >= seconds:
            return None
        time.sleep(3)


# Sau khi người dùng kéo xong captcha: chờ chừng này giây xem prompt đã gửi có tạo conversation không, rồi gửi lại 1 lần
CONV_WAIT_AFTER_CAPTCHA_SECONDS = 15
CONV_WAIT_SECONDS = 30
# BH-45: credit đã bị trừ sau captcha = Dola đã nhận prompt → KHÔNG gửi lại, chỉ chờ thêm conversation chừng này giây
CONV_WAIT_CREDIT_SPENT_SECONDS = 45
# Ô nhập trống mà không đọc được credit: chưa có bằng chứng gì → chờ thêm chừng này giây rồi mới gửi lại
CONV_WAIT_NO_EVIDENCE_SECONDS = 15
PROMPT_PREFIX_CHECK_CHARS = 40

_INPUT_BOX_SELECTOR = "div.ProseMirror, textarea, [contenteditable='true']"


def _input_box_text(page) -> Optional[str]:
    """Nội dung hiện có trong ô nhập prompt ("" nếu trống); None nếu không đọc được / không thấy ô."""
    try:
        box = page.locator(_INPUT_BOX_SELECTOR).first
        if not box.is_visible():
            return None
        tag = (box.evaluate("e => e.tagName") or "").lower()
        text = box.input_value() if tag == "textarea" else box.inner_text()
        return (text or "").strip()
    except Exception as e:  # noqa: BLE001
        log.debug("Không đọc được ô nhập prompt: %s", str(e)[:80])
        return None


def _resend_with_enter(page) -> bool:
    """Ô nhập còn nguyên prompt: chỉ bấm Enter (không gõ lại, tránh nhân đôi nội dung). False nếu không thấy ô."""
    box = page.locator(_INPUT_BOX_SELECTOR).first
    if not box.is_visible():
        return False
    box.click()
    time.sleep(0.5)
    page.keyboard.press("Enter")
    return True


def _conv_after_captcha_solved(job: dict, acc: dict, page, initial_conv_ids: set, full_prompt: str,
                               credits_pre: Optional[int] = None):
    """Captcha vừa được giải: chờ 15 s cho conversation mới; chưa có thì KIỂM BẰNG CHỨNG rồi mới gửi lại (BH-45).

    Gửi lại prompt tốn credit, nên trước khi lặp lại phải chắc lần gửi trước KHÔNG thành công:
    (a) credit đọc được và đã giảm so với trước captcha → Dola đã nhận prompt: không gửi lại, chỉ chờ thêm
        conversation tối đa CONV_WAIT_CREDIT_SPENT_SECONDS;
    (b) ô nhập còn nguyên prompt (chứa 40 ký tự đầu) → chưa gửi: gửi lại bằng Enter (không gõ lại);
    (c) ô nhập trống: credit đọc được (không giảm) → coi như chưa gửi, gõ lại + Enter; credit không đọc được →
        chờ thêm CONV_WAIT_NO_EVIDENCE_SECONDS rồi mới gõ lại + Enter.
    Nhánh được chọn ghi rõ trong nhật ký. Trả về (conv_id | None, finalized): finalized=True nghĩa là trạng thái
    cuối của job đã được ghi (captcha lại, không thấy ô nhập) và người gọi phải return ngay.
    """
    job_id, account_id = job["id"], acc["id"]
    conv_id = _wait_new_conversation(page, initial_conv_ids, CONV_WAIT_AFTER_CAPTCHA_SECONDS, job_id)
    if conv_id:
        return conv_id, False

    credits_now = extract_dola_credits(page)
    if credits_now is not None and credits_pre is not None and credits_now < credits_pre:
        # (a) đã mất credit → prompt đã được Dola nhận, gửi lại sẽ tốn thêm 1 credit cho video thứ hai
        msg = (f"credit của nick '{acc['name']}' đã giảm {credits_pre} → {credits_now} sau khi kéo captcha, "
               f"Dola đã nhận prompt nên KHÔNG gửi lại; chờ thêm conversation tối đa {CONV_WAIT_CREDIT_SPENT_SECONDS}s")
        log_event(f"Job #{job_id}: {msg}", "INFO", "Engine", job_id=job_id, account_id=account_id)
        update_job_status(job_id, JobStatus.DANG_CHAY, "Đã kéo xong mảnh ghép, Dola đã nhận prompt, chờ cuộc trò chuyện mới", 30)
        return _wait_new_conversation(page, initial_conv_ids, CONV_WAIT_CREDIT_SPENT_SECONDS, job_id), False

    box_text = _input_box_text(page)
    prefix = full_prompt[:PROMPT_PREFIX_CHECK_CHARS]
    if box_text and prefix in box_text:
        # (b) prompt vẫn nằm trong ô nhập → lần gửi lúc captcha hiện không đi, chỉ cần Enter
        log_event(f"Job #{job_id}: {CONV_WAIT_AFTER_CAPTCHA_SECONDS}s sau khi kéo xong captcha vẫn chưa có conversation "
                  f"mới, ô nhập còn nguyên prompt (credit {credits_pre} → {credits_now}), gửi lại prompt một lần bằng Enter",
                  "INFO", "Engine", job_id=job_id, account_id=account_id)
        update_job_status(job_id, JobStatus.DANG_CHAY, "Đã kéo xong mảnh ghép, gửi lại prompt sang Dola (Enter)", 30)
        sent = _resend_with_enter(page)
    else:
        if credits_now is None:
            # (c2) không có bằng chứng nào: chờ thêm rồi mới gõ lại
            log_event(f"Job #{job_id}: sau khi kéo xong captcha ô nhập trống và không đọc được credit, chưa rõ prompt "
                      f"đã gửi chưa; chờ thêm {CONV_WAIT_NO_EVIDENCE_SECONDS}s trước khi gửi lại",
                      "INFO", "Engine", job_id=job_id, account_id=account_id)
            conv_id = _wait_new_conversation(page, initial_conv_ids, CONV_WAIT_NO_EVIDENCE_SECONDS, job_id)
            if conv_id:
                return conv_id, False
            branch = "ô nhập trống, credit không đọc được, đã chờ thêm vẫn chưa có conversation"
        else:
            # (c1) credit không giảm, ô trống (trang xóa ô dù không gửi) → chưa gửi
            branch = f"ô nhập trống nhưng credit không giảm ({credits_pre} → {credits_now})"
        log_event(f"Job #{job_id}: {branch}, gửi lại prompt một lần", "INFO", "Engine",
                  job_id=job_id, account_id=account_id)
        update_job_status(job_id, JobStatus.DANG_CHAY, "Đã kéo xong mảnh ghép, gửi lại prompt sang Dola", 30)
        sent = _send_prompt(page, full_prompt)
    if not sent:
        _fail_job(job_id, account_id, JobStatus.THAT_BAI, "Không thấy ô nhập prompt trên trang Dola sau khi kéo captcha",
                  page, "no_input")
        return None, True
    time.sleep(4)
    if _detect_captcha(page):
        # Dola đòi captcha lần thứ hai ngay sau khi vừa giải: không chờ tại chỗ nữa, Tạm dừng để người dùng xem
        _handle_captcha(job_id, acc, page)
        return None, True
    return _wait_new_conversation(page, initial_conv_ids, CONV_WAIT_SECONDS, job_id), False


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

    if _detect_captcha(page) and not _wait_user_solve_captcha(job_id, acc, context, page):
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
    if (job.get("prompt_final") or "").strip() != full_prompt:
        _set_job_fields(job_id, prompt_final=full_prompt)
    update_job_status(job_id, JobStatus.DANG_CHAY, "Đang gửi prompt sang Dola", 30)
    if not _send_prompt(page, full_prompt):
        _fail_job(job_id, account_id, JobStatus.THAT_BAI, "Không thấy ô nhập prompt trên trang Dola", page, "no_input")
        return
    time.sleep(4)

    # Dola (chống bot) thường chèn captcha NGAY SAU khi gửi prompt (BH-39): chờ người dùng kéo tại chỗ,
    # hết giờ mới Tạm dừng. Prompt gửi lúc captcha hiện không tạo conversation → sau khi giải phải gửi lại.
    captcha_solved = False
    if _detect_captcha(page):
        if not _wait_user_solve_captcha(job_id, acc, context, page):
            _handle_captcha(job_id, acc, page)
            return
        captcha_solved = True

    body_text = _safe_body_text(page)
    if RE_DAILY_LIMIT.search(body_text) or "only have 0 left today" in body_text or "chỉ còn 0" in body_text:
        _handle_no_credit(job_id, acc)
        return

    # 3. Lấy conversation_id MỚI
    if captcha_solved:
        conv_id, finalized = _conv_after_captcha_solved(job, acc, page, initial_conv_ids, full_prompt, credits_pre)
        if finalized:
            return
    else:
        conv_id = _wait_new_conversation(page, initial_conv_ids, CONV_WAIT_SECONDS, job_id)
        if not conv_id and _detect_captcha(page):
            # captcha xuất hiện muộn (sau khi đã chờ conversation)
            if not _wait_user_solve_captcha(job_id, acc, context, page):
                _handle_captcha(job_id, acc, page)
                return
            conv_id, finalized = _conv_after_captcha_solved(job, acc, page, initial_conv_ids, full_prompt, credits_pre)
            if finalized:
                return

    if not conv_id:
        _fail_job(job_id, account_id, JobStatus.THAT_BAI, Reason.NO_NEW_CONV, page, "no_new_conv", module="Engine")
        return

    # 4. Chờ render & tải video. BH-47: đọc mọi câu trả lời bằng chữ của Dola trong lúc chờ; Dola hỏi lại
    # (tỷ lệ/thời lượng) → tự trả lời đúng MỘT lần; hỏi lần hai hoặc trả lời bằng chữ mà không render → Thất bại sớm.
    dest_file = os.path.join(config.OUTPUTS_DIR, f"video_{job_id}.mp4")
    downloaded = False
    download_error = None
    start_poll = time.time()
    max_wait_seconds = int(config.RENDER_TIMEOUT_SECONDS)
    render_deadline = start_poll + max_wait_seconds
    hard_deadline = start_poll + max_wait_seconds + REPLY_EXTRA_RENDER_SECONDS
    duration_seconds, ratio, _ = job_video_params(job)
    seen_replies: list = []          # mọi câu trả lời bằng chữ đã thấy (theo thứ tự)
    pending_reply: Optional[str] = None   # câu trả lời mới nhất chưa được xử lý
    pending_since = 0.0
    auto_answered = False
    answer_tries = 0
    own_texts: list = [full_prompt]  # BH-48: mọi tin tool đã gửi trong conversation này, để không đọc nhầm thành Dola nói
    log_event(f"Job #{job_id}: theo dõi Dola render (conv_id={conv_id}, {duration_seconds} giây, tỷ lệ {ratio})",
              "INFO", "Render", job_id=job_id, account_id=account_id)

    while time.time() < min(render_deadline, hard_deadline):
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

        # Câu trả lời bằng chữ mới của trợ lý (bỏ "Generating video..." và prompt của chính mình)
        new_replies = [t for t in _assistant_texts(chain_res, full_prompt, own_texts)
                       if t not in seen_replies and not _is_generating_text(t)]
        if new_replies:
            seen_replies.extend(new_replies)
            pending_reply = new_replies[-1]
            pending_since = time.time()
            log.debug("Dola trả lời bằng chữ: '%s'", _short(pending_reply, 160), extra={"job_id": job_id, "account_id": account_id})
            _set_job_fields(job_id, dola_reply=pending_reply)

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
        elif pending_reply:
            if _looks_like_question(pending_reply):
                if auto_answered:
                    _fail_job(job_id, account_id, JobStatus.THAT_BAI,
                              Reason.DOLA_REPLIED_TEXT.format(text=_short(pending_reply, 200)) + " (đã tự trả lời một lần, Dola vẫn hỏi lại)",
                              page, "dola_replied_text", module="Render")
                    return
                answer = _auto_answer_text(duration_seconds, ratio)
                # N-3: chỉ coi là đã trả lời khi gửi được; không thấy ô nhập thì thử lại ở vòng poll sau, tối đa 3 lần
                sent, answer_tries, auto_answered = _auto_answer_step(lambda a: _send_prompt(page, a), answer, answer_tries)
                if sent:
                    own_texts.append(answer)  # BH-48: câu này sẽ xuất hiện trong chain, không phải Dola nói
                    msg = f"Dola hỏi lại: '{_short(pending_reply, 80)}' → đã tự trả lời \"{answer}\""
                    log_event(f"Job #{job_id}: {msg}", "WARNING", "Render", job_id=job_id, account_id=account_id)
                    update_job_status(job_id, JobStatus.DANG_CHAY, msg, est_progress)
                    pending_reply = None
                    # Dola bắt đầu render từ lúc này: đặt lại mốc chờ, tổng không quá RENDER_TIMEOUT + 120 s
                    start_poll = time.time()
                    render_deadline = min(start_poll + max_wait_seconds, hard_deadline)
                elif auto_answered:
                    _fail_job(job_id, account_id, JobStatus.THAT_BAI,
                              Reason.DOLA_REPLIED_TEXT.format(text=_short(pending_reply, 200))
                              + f" (không thấy ô nhập để tự trả lời sau {answer_tries} lần)",
                              page, "dola_replied_text", module="Render")
                    return
                else:
                    msg = (f"Dola hỏi lại: '{_short(pending_reply, 80)}' nhưng không thấy ô nhập để trả lời "
                           f"(lần {answer_tries}/{AUTO_ANSWER_MAX_TRIES}, sẽ thử lại)")
                    log_event(f"Job #{job_id}: {msg}", "WARNING", "Render", job_id=job_id, account_id=account_id)
                    update_job_status(job_id, JobStatus.DANG_CHAY, msg, est_progress)
            elif _reply_should_fail(pending_reply, time.time() - pending_since,
                                    "generating" in chain_lower or "đang tạo" in chain_lower):
                # N-1: từ chối/giải thích → dừng sau 60 s; văn bản khác → 120 s; đang generating → chờ tiếp
                _fail_job(job_id, account_id, JobStatus.THAT_BAI,
                          Reason.DOLA_REPLIED_TEXT.format(text=_short(pending_reply, 200)), page, "dola_replied_text",
                          module="Render")
                return

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
    elif seen_replies:
        # BH-47: hết giờ mà Dola có nói gì thì lý do phải kèm nguyên văn (200 ký tự) để người dùng biết vì sao
        _fail_technical(job_id, acc, Reason.RENDER_TIMEOUT_WITH_REPLY.format(seconds=max_wait_seconds, text=_short(seen_replies[-1], 200)),
                        page, "render_timeout", module="Render")
    else:
        _fail_technical(job_id, acc, Reason.RENDER_TIMEOUT.format(seconds=max_wait_seconds), page, "render_timeout", module="Render")


# Job chờ chỗ mở Chrome tối đa chừng này (G-2); bình thường worker chỉ điều phối khi còn slot nên hiếm khi phải chờ
JOB_SLOT_TIMEOUT_SECONDS = 120


def execute_video_job(job_id: int, account_id: int) -> None:
    """Chạy một job trên nick đã được worker chọn và khóa. Hàm sync, worker gọi trong thread.

    Không tự chọn/đổi nick: hết credit, mất phiên → job về Chờ để worker chọn nick khác;
    captcha → đưa cửa sổ Chrome ra màn hình chờ người dùng kéo (CAPTCHA_SOLVE_TIMEOUT_SECONDS), hết giờ mới
    Tạm dừng + needs_manual; lỗi kỹ thuật → Thất bại kèm ảnh chụp.
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
