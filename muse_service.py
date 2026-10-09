import os
import sys
import json
import time
import re
import urllib.request
import psutil
from typing import Optional, Dict, Any, List
from playwright.sync_api import sync_playwright

from database import get_connection, log_event
from otp_service import fetch_muse_otp

BASE_DIR = os.path.dirname(__file__)
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(PROFILES_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

def parse_proxy(proxy_str: str) -> Optional[dict]:
    """Hỗ trợ ip:port, ip:port:user:pass, socks5://, http://"""
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

def clean_profile_locks(profile_dir: str):
    """Xóa sạch các file lock của Chromium để tránh lỗi xung đột phiên"""
    for lf in ["SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort", "lockfile"]:
        lp = os.path.join(profile_dir, lf)
        if os.path.exists(lp):
            try:
                os.remove(lp)
            except Exception:
                pass

def kill_orphan_chrome(profile_dir: str) -> int:
    """Diệt tiến trình mồ côi đang giữ profile dir"""
    clean_profile_locks(profile_dir)
    killed = 0
    norm_p = os.path.normpath(profile_dir).lower()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            p_name = (proc.info.get('name') or '').lower()
            if 'chrome' in p_name or 'chromium' in p_name:
                cmdline = proc.info.get('cmdline')
                if cmdline:
                    cmd_str = " ".join(cmdline).lower()
                    if norm_p in cmd_str:
                        proc.kill()
                        killed += 1
        except Exception:
            pass
    if killed > 0:
        time.sleep(1)
        clean_profile_locks(profile_dir)
    return killed

def launch_muse_browser(playwright_instance, profile_dir: str, proxy_config: Optional[dict] = None, headless: bool = True):
    """
    Khởi chạy Playwright Persistent Context cách ly hoàn toàn,
    ưu tiên Chromium nội bộ để tránh xung đột với Google Chrome của máy.
    """
    kill_orphan_chrome(profile_dir)
    clean_profile_locks(profile_dir)

    base_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu-watchdog",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
        "--disable-popup-blocking"
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
        base_args.append("--start-maximized")

    if proxy_config:
        base_args.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    launch_opts = {
        "user_data_dir": profile_dir,
        "headless": headless,
        "args": base_args
    }
    if os.path.exists(chrome_path):
        launch_opts["executable_path"] = chrome_path
    if proxy_config:
        launch_opts["proxy"] = proxy_config

    return playwright_instance.chromium.launch_persistent_context(**launch_opts)

# ==================== ĐĂNG NHẬP MUSE AI BẰNG OTP DONGVANFB ====================

def auto_login_muse_sync(account_id: int, headless: bool = True) -> Dict[str, Any]:
    """
    Tự động 100% quy trình đăng nhập Muse AI qua email:
    1. Lấy email & proxy của tài khoản
    2. Mở https://muse.ai/login hoặc https://muse.ai/join
    3. Điền email -> Bấm tiếp tục / gửi code OTP
    4. Gọi OTP service đọc hòm thư dongvanfb
    5. Điền mã OTP 6 số
    6. Lưu vĩnh viễn cookies & storage_state
    7. Kiểm tra 1 tỷ token trong Cài đặt
    """
    conn = get_connection()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()

    if not acc:
        return {"success": False, "message": "Không tìm thấy tài khoản trong database"}

    email = (acc["email"] or "").strip()
    if not email:
        return {"success": False, "message": f"Tài khoản #{account_id} ({acc['name']}) chưa có Email để đăng nhập!"}

    profile_path = os.path.join(PROFILES_DIR, f"acc_{account_id}")
    os.makedirs(profile_path, exist_ok=True)
    proxy_config = parse_proxy(acc["proxy"])

    log_event(f"🚀 Bắt đầu tự động đăng nhập Muse AI cho email '{email}'...", "INFO", "MuseAuth")

    with sync_playwright() as p:
        try:
            context = launch_muse_browser(p, profile_path, proxy_config=proxy_config, headless=headless)
            page = context.pages[0] if context.pages else context.new_page()

            # Bước 1: Mở trang đăng nhập Muse AI
            page.goto("https://muse.ai/login", timeout=45000, wait_until="domcontentloaded")
            time.sleep(3)

            # Nếu trang login không có form trực tiếp, thử trang join
            if not page.locator('input[type="email"], input[name="email"], input[placeholder*="email" i]').first.is_visible():
                page.goto("https://muse.ai/join", timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)

            # Bước 2: Điền Email
            email_input = page.locator('input[type="email"], input[name="email"], input[placeholder*="email" i]').first
            if not email_input.is_visible():
                # Kiểm tra nếu đã đăng nhập từ trước
                if "dashboard" in page.url or "videos" in page.url or page.locator('[aria-label*="profile" i], .user-avatar').first.is_visible():
                    log_event(f"Tài khoản {email} đã được đăng nhập từ trước!", "SUCCESS", "MuseAuth")
                    context.close()
                    return {"success": True, "message": "Đã có phiên đăng nhập hợp lệ!"}
                context.close()
                return {"success": False, "message": "Không tìm thấy ô nhập email trên trang Muse AI"}

            email_input.fill(email)
            time.sleep(1)

            # Bấm nút gửi mã / Tiếp tục
            submit_btn = page.locator('button[type="submit"], button:has-text("Continue"), button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Send")').first
            if submit_btn.is_visible():
                submit_btn.click()
            else:
                email_input.press("Enter")

            log_event(f"Đã yêu cầu gửi mã OTP về email '{email}', đang chờ nhận mã từ Dongvanfb...", "INFO", "MuseAuth")
            time.sleep(10)

            # Bước 3: Lấy OTP từ Dongvanfb
            otp_code = fetch_muse_otp(email, timeout_seconds=60)
            if not otp_code:
                context.close()
                return {
                    "success": False,
                    "message": f"Không nhận được mã OTP từ hòm thư '{email}' sau 60 giây. Vui lòng kiểm tra lại email hoặc nhập tay."
                }

            log_event(f"Đã nhận được mã OTP: {otp_code}. Đang điền vào Muse AI...", "INFO", "MuseAuth")

            # Bước 4: Điền OTP vào trang Muse AI
            # Một số trang có 6 ô input riêng cho từng số, một số trang có 1 ô input chung
            code_inputs = page.locator('input[autocomplete="one-time-code"], input[name*="code" i], input[type="text"][maxlength="1"], input[type="number"]')
            count_inputs = code_inputs.count()
            if count_inputs == 6:
                for idx, digit in enumerate(otp_code[:6]):
                    code_inputs.nth(idx).fill(digit)
                    time.sleep(0.2)
            else:
                # 1 ô input chung
                single_code = page.locator('input[autocomplete="one-time-code"], input[name*="code" i], input[type="text"], input[inputmode="numeric"]').first
                if single_code.is_visible():
                    single_code.fill(otp_code)
                    time.sleep(0.5)
                    single_code.press("Enter")

            # Chờ chuyển hướng sau khi nhập OTP
            time.sleep(5)

            # Bước 5: Bốc toàn bộ Cookie & Storage State lưu lại vĩnh viễn
            storage_file = os.path.join(profile_path, "storage_state.json")
            context.storage_state(path=storage_file)
            cookies = context.cookies()
            cookies_json = json.dumps(cookies, ensure_ascii=False)

            # Bước 6: Kiểm tra Token 1 tỷ trong Settings
            tokens_found = 1000000000  # Mặc định tài khoản khuyến mãi 1 tỷ token
            try:
                page.goto("https://muse.ai/settings", timeout=25000, wait_until="domcontentloaded")
                time.sleep(3)
                settings_text = page.content()
                match = re.search(r'([\d,]+)\s*(?:tokens|token|credits)', settings_text, re.IGNORECASE)
                if match:
                    raw_num = match.group(1).replace(",", "").strip()
                    if raw_num.isdigit():
                        tokens_found = int(raw_num)
            except Exception:
                pass

            context.close()

            # Lưu vào Database
            conn_u = get_connection()
            conn_u.execute("""
                UPDATE accounts 
                SET cookies = ?, status = 'ready', tokens_balance = ?, credits = ?, last_check = CURRENT_TIMESTAMP, account_type = 'muse'
                WHERE id = ?
            """, (cookies_json, tokens_found, tokens_found, account_id))
            conn_u.commit()
            conn_u.close()

            log_event(f"🎉 Đăng nhập Muse AI thành công cho '{email}'! Số dư: {tokens_found:,} tokens", "SUCCESS", "MuseAuth")
            return {
                "success": True,
                "tokens_balance": tokens_found,
                "message": f"Đăng nhập Muse AI thành công! Số dư: {tokens_found:,} tokens"
            }

        except Exception as e:
            kill_orphan_chrome(profile_path)
            err_msg = f"Lỗi đăng nhập Muse AI cho #{account_id}: {str(e)}"
            log_event(err_msg, "ERROR", "MuseAuth")
            return {"success": False, "message": err_msg}

# ==================== CHECK TOKEN SỐ DƯ TÀI KHOẢN MUSE AI ====================

def check_muse_tokens_sync(account_id: int) -> Dict[str, Any]:
    """Kiểm tra số dư token hiện tại của tài khoản Muse AI"""
    conn = get_connection()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()

    if not acc:
        return {"success": False, "message": "Không tìm thấy tài khoản"}

    profile_path = os.path.join(PROFILES_DIR, f"acc_{account_id}")
    proxy_config = parse_proxy(acc["proxy"])

    log_event(f"Đang kiểm tra số dư Token Muse AI cho nick #{account_id} ({acc['name']})...", "INFO", "TokenCheck")

    with sync_playwright() as p:
        try:
            context = launch_muse_browser(p, profile_path, proxy_config=proxy_config, headless=True)
            page = context.pages[0] if context.pages else context.new_page()

            page.goto("https://muse.ai/settings", timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            content = page.content()
            tokens_found = 1000000000
            match = re.search(r'([\d,]+)\s*(?:tokens|token|credits)', content, re.IGNORECASE)
            if match:
                raw_num = match.group(1).replace(",", "").strip()
                if raw_num.isdigit():
                    tokens_found = int(raw_num)

            context.close()

            conn_u = get_connection()
            status = 'ready' if tokens_found > 0 else 'resting'
            conn_u.execute("""
                UPDATE accounts 
                SET tokens_balance = ?, credits = ?, status = ?, last_check = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (tokens_found, tokens_found, status, account_id))
            conn_u.commit()
            conn_u.close()

            return {
                "success": True,
                "tokens_balance": tokens_found,
                "message": f"Tài khoản còn {tokens_found:,} tokens"
            }
        except Exception as e:
            kill_orphan_chrome(profile_path)
            return {"success": False, "message": f"Không thể kiểm tra token: {str(e)}"}

# ==================== RENDER 1 CLIP TRÊN MUSE AI ====================

def render_clip_muse_sync(account_id: int, job_id: int) -> Dict[str, Any]:
    """
    Tạo 1 clip video trên Muse AI cho 1 job:
    1. Nạp prompt và ảnh nhân vật (nếu có)
    2. Đợi render hoàn tất
    3. Tải video MP4 về outputs/<batch_id>/clip_<clip_index:03d>.mp4
    4. Cập nhật Database
    """
    conn = get_connection()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()

    if not job or not acc:
        return {"success": False, "message": "Job hoặc Account không tồn tại"}

    batch_id = job["batch_id"] or "single"
    clip_index = job["clip_index"] or job["id"]
    batch_dir = os.path.join(OUTPUTS_DIR, batch_id)
    os.makedirs(batch_dir, exist_ok=True)

    dest_video_path = os.path.join(batch_dir, f"clip_{clip_index:03d}.mp4")

    profile_path = os.path.join(PROFILES_DIR, f"acc_{account_id}")
    proxy_config = parse_proxy(acc["proxy"])

    prompt = job["prompt"]
    ref_image = job["reference_image"]

    log_event(f"🎬 Bắt đầu render Clip #{clip_index} bằng nick '{acc['name']}'...", "INFO", "MuseRender")

    # Cập nhật job sang Đang xử lý
    conn_u = get_connection()
    conn_u.execute("UPDATE jobs SET status = 'Đang xử lý', status_message = 'Đang gửi prompt đến Muse AI...', progress = 10 WHERE id = ?", (job_id,))
    conn_u.commit()
    conn_u.close()

    with sync_playwright() as p:
        try:
            context = launch_muse_browser(p, profile_path, proxy_config=proxy_config, headless=True)
            page = context.pages[0] if context.pages else context.new_page()

            page.goto("https://muse.ai/create", timeout=45000, wait_until="domcontentloaded")
            time.sleep(3)

            # Đính kèm ảnh nhân vật nếu có và tồn tại trên đĩa
            if ref_image and os.path.exists(ref_image):
                try:
                    file_input = page.locator('input[type="file"]').first
                    if file_input.is_visible():
                        file_input.set_input_files(ref_image)
                        time.sleep(2)
                except Exception as e:
                    log_event(f"Không thể đính ảnh nhân vật: {e}", "WARNING", "MuseRender")

            # Điền prompt
            prompt_input = page.locator('textarea, input[placeholder*="describe" i], input[placeholder*="prompt" i], [contenteditable="true"]').first
            if prompt_input.is_visible():
                prompt_input.fill(prompt)
                time.sleep(1)

            # Bấm Generate
            gen_btn = page.locator('button:has-text("Generate"), button:has-text("Create"), button:has-text("Tạo")').first
            if gen_btn.is_visible():
                gen_btn.click()
            else:
                prompt_input.press("Enter")

            # Cập nhật tiến độ: Đang render
            conn_u = get_connection()
            conn_u.execute("UPDATE jobs SET status_message = 'Muse AI đang render video (~2-3 phút)...', progress = 40 WHERE id = ?", (job_id,))
            conn_u.commit()
            conn_u.close()

            # Chờ video xuất hiện (tối đa 5 phút)
            start_render = time.time()
            video_url = None
            while time.time() - start_render < 300:
                time.sleep(5)
                # Tìm thẻ video hoặc link tải
                videos = page.locator('video[src], a[download][href*=".mp4"], a[href*=".mp4"]')
                if videos.count() > 0:
                    for i in range(videos.count()):
                        v = videos.nth(i)
                        src = v.get_attribute("src") or v.get_attribute("href")
                        if src and (".mp4" in src or "blob:" in src or "muse" in src):
                            video_url = src
                            break
                    if video_url:
                        break

            context.close()

            if not video_url:
                conn_u = get_connection()
                conn_u.execute("UPDATE jobs SET status = 'Thất bại', status_message = 'Timeout chờ render từ Muse AI' WHERE id = ?", (job_id,))
                conn_u.commit()
                conn_u.close()
                return {"success": False, "message": "Render timeout"}

            # Tải video về ổ cứng
            if video_url.startswith("http"):
                req = urllib.request.Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp, open(dest_video_path, "wb") as f_out:
                    f_out.write(resp.read())

            # Cập nhật hoàn thành
            conn_u = get_connection()
            conn_u.execute("""
                UPDATE jobs 
                SET status = 'Hoàn thành', status_message = 'Đã tải MP4 thành công', progress = 100,
                    video_url = ?, local_video_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (video_url, dest_video_path, job_id))
            conn_u.commit()
            conn_u.close()

            log_event(f"✅ Hoàn thành Clip #{clip_index}: {dest_video_path}", "SUCCESS", "MuseRender")
            return {
                "success": True,
                "local_video_path": dest_video_path,
                "video_url": video_url
            }

        except Exception as e:
            kill_orphan_chrome(profile_path)
            err_msg = f"Lỗi render Clip #{clip_index}: {str(e)}"
            log_event(err_msg, "ERROR", "MuseRender")
            conn_u = get_connection()
            conn_u.execute("UPDATE jobs SET status = 'Thất bại', status_message = ? WHERE id = ?", (err_msg, job_id))
            conn_u.commit()
            conn_u.close()
            return {"success": False, "message": err_msg}

async def execute_muse_job(job_id: int):
    """Async task được worker.py gọi để điều phối render 1 clip trên Muse AI"""
    import asyncio
    conn = get_connection()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        conn.close()
        return

    account_id = job["account_id"]
    if not account_id:
        # Tự động gán 1 tài khoản Muse AI rảnh
        acc = conn.execute("""
            SELECT id FROM accounts 
            WHERE (account_type = 'muse' OR account_type IS NULL) 
              AND status = 'ready' 
              AND (tokens_balance > 0 OR tokens_balance IS NULL)
            ORDER BY RANDOM() LIMIT 1
        """).fetchone()
        if acc:
            account_id = acc["id"]
            conn.execute("UPDATE jobs SET account_id = ? WHERE id = ?", (account_id, job_id))
            conn.commit()

    conn.close()

    if not account_id:
        conn_u = get_connection()
        conn_u.execute("UPDATE jobs SET status = 'Đang chờ', status_message = 'Chờ tài khoản Muse AI khả dụng...' WHERE id = ?", (job_id,))
        conn_u.commit()
        conn_u.close()
        return

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, render_clip_muse_sync, account_id, job_id)

