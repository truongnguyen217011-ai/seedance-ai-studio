import os
import re
import time
import json
import urllib.request
import urllib.parse
from typing import Optional
from database import get_connection, log_event

def get_dongvan_api_key() -> str:
    """Lấy API Key Dongvanfb từ bảng settings nếu có"""
    try:
        conn = get_connection()
        row = conn.execute("SELECT value FROM settings WHERE key = 'dongvan_api_key'").fetchone()
        conn.close()
        return row["value"].strip() if row and row["value"] else ""
    except Exception:
        return ""

def get_otp_via_api(email: str, api_key: str) -> Optional[str]:
    """Gọi trực tiếp API dongvanfb để lấy OTP"""
    if not api_key or not email:
        return None
    try:
        url = f"https://api.dongvanfb.net/user/get_code_mail_domain?apikey={urllib.parse.quote(api_key)}&email={urllib.parse.quote(email)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # API dongvanfb thường trả về dạng {"status": true, "code": "123456"} hoặc data
            if isinstance(data, dict):
                code = data.get("code") or data.get("data", {}).get("code")
                if code:
                    return str(code).strip()
                # Thử tìm trong content / message
                msg = str(data.get("message") or data.get("data") or "")
                match = re.search(r'\b(\d{6})\b', msg)
                if match:
                    return match.group(1)
    except Exception as e:
        log_event(f"Dongvan API error for {email}: {e}", "WARNING", "OTP")
    return None

def get_otp_via_web_mailbox(email: str, timeout_seconds: int = 60) -> Optional[str]:
    """
    Tự động truy cập https://dongvanfb.net/read_mail_box/ bằng Playwright ngầm
    để nhập email và đọc mã OTP Muse AI trong hộp thư đến.
    """
    from playwright.sync_api import sync_playwright

    log_event(f"Đang mở hòm thư dongvanfb.net để chờ mã OTP cho '{email}'...", "INFO", "OTP")
    start_time = time.time()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            page = browser.new_page()
            page.goto("https://dongvanfb.net/read_mail_box/", timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            # Tìm ô input email
            input_sel = page.locator('input[type="text"], input[placeholder*="mail" i], input').first
            if input_sel.is_visible():
                input_sel.fill(email)
                time.sleep(0.5)

            # Bấm nút đọc hòm thư
            btn_sel = page.locator('button:has-text("Đọc"), button:has-text("Kiểm tra"), button:has-text("Read")').first
            if btn_sel.is_visible():
                btn_sel.click()

            # Vòng lặp chờ email mới trong vòng timeout_seconds
            while time.time() - start_time < timeout_seconds:
                time.sleep(4)
                # Bấm lại nút đọc để refresh hộp thư nếu có
                try:
                    if btn_sel.is_visible():
                        btn_sel.click()
                except Exception:
                    pass

                text_content = page.content()
                
                # Tìm mã 6 chữ số gắn với Muse AI hoặc từ khóa code/OTP
                # Ưu tiên các khối văn bản nhắc đến Muse hoặc code
                muse_matches = re.findall(r'(?:muse|verification|code|mã)[\s\S]{0,100}?\b(\d{6})\b', text_content, re.IGNORECASE)
                if muse_matches:
                    code = muse_matches[-1]
                    log_event(f"Tìm thấy mã OTP Muse AI cho '{email}': {code}", "SUCCESS", "OTP")
                    browser.close()
                    return code

                # Tìm bất kỳ mã 6 số nào xuất hiện trong các hàng bảng hoặc card
                generic_matches = re.findall(r'\b(\d{6})\b', text_content)
                if generic_matches:
                    code = generic_matches[-1]
                    log_event(f"Lấy được mã OTP '{code}' cho email {email}", "SUCCESS", "OTP")
                    browser.close()
                    return code

            browser.close()
    except Exception as e:
        log_event(f"Lỗi khi đọc hộp thư dongvanfb cho '{email}': {e}", "ERROR", "OTP")

    return None

def fetch_muse_otp(email: str, timeout_seconds: int = 60) -> Optional[str]:
    """
    Hàm tổng hợp lấy mã OTP Muse AI:
    1. Ưu tiên gọi API nhanh nếu có apikey
    2. Fallback sang đọc web mailbox dongvanfb.net
    """
    api_key = get_dongvan_api_key()
    if api_key:
        log_event(f"Thử lấy OTP qua Dongvan API key cho {email}...", "INFO", "OTP")
        start = time.time()
        while time.time() - start < min(timeout_seconds, 30):
            code = get_otp_via_api(email, api_key)
            if code:
                log_event(f"Lấy OTP thành công qua API: {code}", "SUCCESS", "OTP")
                return code
            time.sleep(3)

    # Nếu không có key hoặc API chưa ra code -> dùng Web reader
    return get_otp_via_web_mailbox(email, timeout_seconds=timeout_seconds)

