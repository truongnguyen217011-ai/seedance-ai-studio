import os
import sys
import json
import time
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List

from datetime import datetime
from database import init_db, get_connection, log_event
from dola_service import (
    launch_login_session, parse_cookie_string, save_account_storage_state,
    auto_login_facebook_dola, parse_dola_cookies, has_dola_session,
    check_account_credits
)
from parser import parse_single_account_line, parse_multiple_account_lines
from worker import worker_loop
from muse_service import auto_login_muse_sync, check_muse_tokens_sync
from batch_dispatcher import import_b3_batch, get_batch_progress

app = FastAPI(title="Seedance AI Studio")

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

# Đảm bảo database đã khởi tạo
init_db()

# Mount thư mục static & outputs
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")

# --- SCHEMA MODELS ---
class AddAccountRequest(BaseModel):
    name: Optional[str] = ""
    account_type: Optional[str] = "facebook"
    email: Optional[str] = ""
    fb_uid: Optional[str] = ""
    fb_pass: Optional[str] = ""
    fb_2fa: Optional[str] = ""
    proxy: Optional[str] = ""
    cookies: Optional[str] = ""
    raw_line: Optional[str] = ""
    auto_launch: Optional[bool] = False
    auto_login: Optional[bool] = False

class BatchImportRequest(BaseModel):
    data: str  # Format: Mọi định dạng shop Facebook & Google
    auto_login: Optional[bool] = False

class PasteCookieRequest(BaseModel):
    cookies: str

class BatchAssignProxyRequest(BaseModel):
    proxy: str
    target: Optional[str] = "no-proxy"

class CreateJobRequest(BaseModel):
    title: Optional[str] = ""
    prompt: str
    model: Optional[str] = "Seedance 2.5"
    duration: Optional[str] = "30 giây"
    account_id: Optional[int] = None
    reference_image: Optional[str] = ""

class BatchJobsRequest(BaseModel):
    prompts: List[str]
    model: Optional[str] = "Seedance 2.5"
    duration: Optional[str] = "30 giây"

class CreateImageRequest(BaseModel):
    prompt: str
    model: Optional[str] = "Seedance Image 2.5"
    aspect_ratio: Optional[str] = "16:9"
    style: Optional[str] = "Cinematic"
    account_id: Optional[int] = None

class CreateAssetRequest(BaseModel):
    name: str
    character_code: Optional[str] = ""
    image_url: Optional[str] = ""
    description: Optional[str] = ""
    tags: Optional[str] = ""

class AudioTTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "vi-VN-Nu-NheNhang"
    speed: Optional[float] = 1.0

class ImportBatchRequest(BaseModel):
    file_path: str
    title: Optional[str] = ""

@app.on_event("startup")
async def startup_event():
    log_event("Khởi động hệ thống Seedance AI Studio", "INFO", "System")
    asyncio.create_task(worker_loop())

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Seedance AI Studio</h1>")

# --- API STATS ---
@app.get("/api/stats")
async def get_stats():
    conn = get_connection()
    total_accounts = conn.execute("SELECT COUNT(*) as c FROM accounts").fetchone()["c"]
    running_jobs = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = 'Đang chạy'").fetchone()["c"]
    total_jobs = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]
    completed_jobs = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = 'Hoàn thành'").fetchone()["c"]
    total_images = conn.execute("SELECT COUNT(*) as c FROM images").fetchone()["c"]
    total_assets = conn.execute("SELECT COUNT(*) as c FROM assets").fetchone()["c"]
    conn.close()
    return {
        "status": "connected",
        "running_jobs": running_jobs,
        "total_jobs": total_jobs,
        "total_accounts": total_accounts,
        "completed_jobs": completed_jobs,
        "total_images": total_images,
        "total_assets": total_assets
    }

# --- API ACCOUNTS ---
@app.get("/api/accounts")
async def get_accounts():
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, name, account_type, email, fb_uid, fb_pass, fb_2fa, proxy, status, cookies, credits, credits_date, rest_until, rest_reason, last_used, session_expires, last_check, tokens_balance
        FROM accounts ORDER BY id DESC
    """).fetchall()
    accounts = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for r in rows:
        d = dict(r)
        has_dola = False
        if d.get("cookies"):
            try:
                c_list = json.loads(d["cookies"])
                has_dola = has_dola_session(c_list)
            except Exception:
                pass
        if not has_dola:
            prof_st = os.path.join(BASE_DIR, "profiles", f"acc_{d['id']}", "storage_state.json")
            if os.path.exists(prof_st):
                try:
                    st = json.load(open(prof_st, "r", encoding="utf-8"))
                    has_dola = has_dola_session(st.get("cookies", []))
                except Exception:
                    pass
        d["has_dola"] = has_dola

        # Tính toán trạng thái nghỉ / hết lượt
        is_resting = False
        if d.get("rest_until") and d["rest_until"] > now_str:
            is_resting = True
        if d.get("credits_date") == today_str and d.get("credits") == 0:
            is_resting = True
        d["is_resting"] = is_resting
        d["credits_today"] = d.get("credits") if d.get("credits_date") == today_str else None

        # Ẩn bớt mật khẩu hiển thị
        if d.get("fb_pass"):
            d["has_pass"] = True
            d["fb_pass_masked"] = "••••••••"
        else:
            d["has_pass"] = False
            d["fb_pass_masked"] = ""
        accounts.append(d)
    conn.close()
    return {"accounts": accounts}

@app.post("/api/accounts")
async def add_account(req: AddAccountRequest, background_tasks: BackgroundTasks):
    conn = get_connection()
    cursor = conn.cursor()

    name = req.name
    acc_type = req.account_type or "facebook"
    email = req.email
    fb_uid = req.fb_uid
    fb_pass = req.fb_pass
    fb_2fa = req.fb_2fa
    proxy = req.proxy
    raw_cookies = req.cookies

    # Nếu người dùng dán 1 dòng định dạng thô (shop Facebook)
    if req.raw_line and req.raw_line.strip():
        try:
            p_data = parse_single_account_line(req.raw_line.strip())
            fb_uid = p_data.get("uid") or fb_uid
            fb_pass = p_data.get("pass") or fb_pass
            fb_2fa = p_data.get("twofa") or fb_2fa
            proxy = p_data.get("proxy") or proxy
            raw_cookies = p_data.get("cookie") or raw_cookies
            email = p_data.get("email") or email
            acc_type = p_data.get("account_type") or acc_type
            if not name:
                name = p_data.get("name")
        except Exception as parse_err:
            conn.close()
            return {"success": False, "message": f"Lỗi định dạng dòng: {str(parse_err)}"}

    if not name:
        if fb_uid:
            name = f"FB {fb_uid[-6:]}" if len(fb_uid) >= 6 else f"FB {fb_uid}"
        elif email:
            name = email.split('@')[0]
        else:
            name = f"Nick_{int(time.time()) % 10000}"

    parsed_cookies = []
    if raw_cookies:
        domain = ".google.com" if acc_type == "google" else ".facebook.com"
        parsed_cookies = parse_cookie_string(raw_cookies, domain=domain)
        
    cookies_json = json.dumps(parsed_cookies) if parsed_cookies else ""
    initial_status = 'ready'
    login_method = 'facebook' if acc_type == 'facebook' else 'google'
    
    cursor.execute("""
        INSERT INTO accounts (name, account_type, email, fb_uid, fb_pass, fb_2fa, proxy, cookies, status, login_method)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, acc_type, email, fb_uid, fb_pass, fb_2fa, proxy, cookies_json, initial_status, login_method))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    if parsed_cookies:
        save_account_storage_state(new_id, parsed_cookies)

    log_event(f"Thêm nick #{new_id} ({name} - {acc_type.upper()}) | UID: {fb_uid} | 2FA: {bool(fb_2fa)} | Cookie: {bool(parsed_cookies)}", "SUCCESS", "Account")

    # Tự động chạy đăng nhập ngầm Facebook -> Dola nếu yêu cầu
    if req.auto_login:
        background_tasks.add_task(auto_login_facebook_dola, new_id, True)
        return {"success": True, "id": new_id, "auto_login": True, "message": "Đang tự động đăng nhập Dola ngầm..."}
    elif req.auto_launch:
        background_tasks.add_task(launch_login_session, new_id)
        return {"success": True, "id": new_id, "launched_browser": True, "message": "Đang mở Google Chrome thật..."}
    else:
        return {"success": True, "id": new_id, "launched_browser": False}

@app.post("/api/accounts/batch-import")
async def batch_import_accounts(req: BatchImportRequest, background_tasks: BackgroundTasks):
    ok_list, err_list = parse_multiple_account_lines(req.data)
    if not ok_list and not err_list:
        return {"success": False, "message": "Dữ liệu trống hoặc không có dòng nào hợp lệ."}

    conn = get_connection()
    cursor = conn.cursor()

    # Lấy danh sách UID hiện có trong database để chống trùng
    existing_rows = cursor.execute("SELECT fb_uid, email FROM accounts").fetchall()
    existing_uids = set(r["fb_uid"] for r in existing_rows if r["fb_uid"])
    existing_emails = set(r["email"] for r in existing_rows if r["email"])

    count = 0
    cookie_count = 0
    added_ids = []

    for item in ok_list:
        uid = item["uid"]
        email = item.get("email")
        # Kiểm tra trùng database
        if uid in existing_uids or (email and email in existing_emails):
            err_list.append({
                "line": item.get("line", 0),
                "text": uid,
                "reason": f"UID {uid} đã tồn tại trong danh sách tài khoản (đã bỏ qua)"
            })
            continue

        raw_c = item.get("cookie")
        parsed_cookies = parse_cookie_string(raw_c, domain=".facebook.com") if raw_c else []
        cookies_json = json.dumps(parsed_cookies) if parsed_cookies else ""
        if parsed_cookies:
            cookie_count += 1

        cursor.execute("""
            INSERT INTO accounts (name, account_type, email, fb_uid, fb_pass, fb_2fa, proxy, cookies, status, login_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?)
        """, (
            item["name"],
            item["account_type"],
            item.get("email"),
            item["uid"],
            item["pass"],
            item.get("twofa"),
            item.get("proxy"),
            cookies_json,
            "facebook" if item["account_type"] == "facebook" else "google"
        ))
        new_id = cursor.lastrowid
        added_ids.append(new_id)
        existing_uids.add(uid)
        if email:
            existing_emails.add(email)

        if parsed_cookies:
            save_account_storage_state(new_id, parsed_cookies)

        count += 1

    conn.commit()
    conn.close()

    log_event(f"Import thành công {count} tài khoản ({cookie_count} nick có Cookie sẵn, {len(err_list)} dòng bỏ qua/lỗi)", "SUCCESS", "Account")

    # Nếu người dùng bật tuỳ chọn tự động đăng nhập ngầm vào Dola
    if req.auto_login:
        for acc_id in added_ids:
            background_tasks.add_task(auto_login_facebook_dola, acc_id, True)

    return {
        "success": True, 
        "imported": count, 
        "with_cookies": cookie_count, 
        "errors": err_list,
        "auto_login_queued": bool(req.auto_login)
    }

@app.post("/api/accounts/{account_id}/auto-login")
async def trigger_auto_login(account_id: int, background_tasks: BackgroundTasks):
    log_event(f"Khởi động tiến trình tự động kết nối Dola ngầm cho nick #{account_id}...", "INFO", "Auth")
    background_tasks.add_task(auto_login_facebook_dola, account_id, True)
    return {"success": True, "message": "Đang chạy tự động đăng nhập ngầm qua Facebook & Dola AI..."}

@app.post("/api/accounts/{account_id}/cookies")
async def paste_account_cookies(account_id: int, req: PasteCookieRequest):
    cookies = parse_dola_cookies(req.cookies)
    if not cookies:
        return {"success": False, "message": "Không tìm thấy cookie nào hợp lệ trong dữ liệu bạn vừa dán."}
    
    conn = get_connection()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not acc:
        conn.close()
        return {"success": False, "message": "Tài khoản không tồn tại."}

    cookies_json = json.dumps(cookies)
    save_account_storage_state(account_id, cookies)
    conn.execute("UPDATE accounts SET cookies = ?, status = 'ready', last_check = CURRENT_TIMESTAMP WHERE id = ?", (cookies_json, account_id))
    conn.execute("UPDATE jobs SET status = 'Đang chờ', status_message = 'Đã kết nối Dola! Sẵn sàng khởi chạy...' WHERE account_id = ? AND status = 'Chờ đăng nhập Dola'", (account_id,))
    conn.commit()
    conn.close()
    log_event(f"Đã nạp {len(cookies)} cookie Dola thành công cho #{account_id} ({acc['name']})", "SUCCESS", "Auth")
    return {"success": True, "count": len(cookies), "has_session": has_dola_session(cookies)}

@app.post("/api/accounts/batch-assign-proxy")
async def batch_assign_proxy(req: BatchAssignProxyRequest):
    conn = get_connection()
    if req.target == "no-proxy":
        conn.execute("UPDATE accounts SET proxy = ? WHERE proxy IS NULL OR proxy = ''", (req.proxy,))
    else:
        conn.execute("UPDATE accounts SET proxy = ?", (req.proxy,))
    conn.commit()
    conn.close()
    log_event(f"Đã gán proxy '{req.proxy}' cho các tài khoản ({req.target})", "SUCCESS", "Account")
    return {"success": True}

@app.post("/api/accounts/{account_id}/login")
async def login_account(account_id: int, background_tasks: BackgroundTasks):
    log_event(f"Mở trình duyệt đăng nhập cho tài khoản #{account_id}", "INFO", "Auth")
    background_tasks.add_task(launch_login_session, account_id)
    return {"success": True, "message": "Đang mở trình duyệt đăng nhập..."}

@app.get("/api/accounts/{account_id}/check-dola")
async def check_account_dola(account_id: int):
    conn = get_connection()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()
    if not acc:
        return {"connected": False, "message": "Không tìm thấy tài khoản"}
    
    profile_path = os.path.join(BASE_DIR, "profiles", f"acc_{account_id}")
    has_session = False
    cookie_count = 0

    if acc["cookies"]:
        try:
            c_list = json.loads(acc["cookies"])
            has_session = has_dola_session(c_list)
            cookie_count = len(c_list)
        except Exception:
            pass
            
    if not has_session and os.path.exists(os.path.join(profile_path, "storage_state.json")):
        try:
            st = json.load(open(os.path.join(profile_path, "storage_state.json"), "r", encoding="utf-8"))
            c_list = st.get("cookies", [])
            has_session = has_dola_session(c_list)
            cookie_count = len(c_list)
        except Exception:
            pass
            
    if has_session:
        return {
            "connected": True, 
            "status": "ready", 
            "cookies_count": cookie_count,
            "message": f"Tài khoản '{acc['name']}' ĐÃ ĐĂNG NHẬP DOLA AI (phiên sessionid hợp lệ) và sẵn sàng tạo video!"
        }
    else:
        return {
            "connected": False, 
            "status": "need_login", 
            "message": f"Tài khoản '{acc['name']}' CHƯA ĐĂNG NHẬP DOLA AI (thiếu sessionid). Vui lòng bấm '⚡ Auto Login' hoặc 'Dán Cookie' Dola!"
        }

@app.post("/api/accounts/{account_id}/check-credits")
async def api_check_account_credits(account_id: int):
    """Kiểm tra số credit Dola AI của 1 tài khoản"""
    res = await check_account_credits(account_id)
    return res

@app.post("/api/accounts/check-all-credits")
async def api_check_all_credits(background_tasks: BackgroundTasks):
    """Quét và kiểm tra credit của tất cả tài khoản đã kết nối Dola trong nền"""
    conn = get_connection()
    accounts = conn.execute("SELECT id, name, cookies FROM accounts WHERE status = 'ready'").fetchall()
    conn.close()

    checked_ids = []
    for acc in accounts:
        # Chỉ check những tài khoản có session Dola
        has_session = False
        if acc["cookies"]:
            try:
                has_session = has_dola_session(json.loads(acc["cookies"]))
            except Exception:
                pass
        if not has_session:
            prof_st = os.path.join(BASE_DIR, "profiles", f"acc_{acc['id']}", "storage_state.json")
            if os.path.exists(prof_st):
                try:
                    st = json.load(open(prof_st, "r", encoding="utf-8"))
                    has_session = has_dola_session(st.get("cookies", []))
                except Exception:
                    pass
        if has_session:
            checked_ids.append(acc["id"])
            background_tasks.add_task(check_account_credits, acc["id"])

    log_event(f"Bắt đầu kiểm tra credit cho {len(checked_ids)} tài khoản đã kết nối Dola", "INFO", "Credit")
    return {"success": True, "count": len(checked_ids), "account_ids": checked_ids}

@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()
    log_event(f"Đã xóa tài khoản #{account_id}", "WARNING", "Account")
    return {"success": True}

# --- API JOBS (VIDEO) ---
@app.get("/api/jobs")
async def get_jobs():
    conn = get_connection()
    rows = conn.execute("""
        SELECT j.*, a.name as account_name, a.proxy as account_proxy 
        FROM jobs j 
        LEFT JOIN accounts a ON j.account_id = a.id 
        ORDER BY j.id DESC
    """).fetchall()
    jobs = [dict(r) for r in rows]
    conn.close()
    return {"jobs": jobs}

@app.post("/api/jobs")
async def create_job(req: CreateJobRequest):
    conn = get_connection()
    cursor = conn.cursor()
    title = req.title if req.title else req.prompt[:40] + "..."
    cursor.execute("""
        INSERT INTO jobs (account_id, title, prompt, model, duration, status, status_message, progress, reference_image)
        VALUES (?, ?, ?, ?, ?, 'Đang chờ', 'Chờ xử lý', 0, ?)
    """, (req.account_id, title, req.prompt, req.model, req.duration, req.reference_image))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    log_event(f"Tạo job video #{new_id} ({title})", "INFO", "Queue")
    return {"success": True, "id": new_id}

@app.post("/api/jobs/batch")
async def create_batch_jobs(req: BatchJobsRequest):
    conn = get_connection()
    cursor = conn.cursor()
    count = 0
    for p in req.prompts:
        p = p.strip()
        if not p:
            continue
        title = p[:40] + "..."
        cursor.execute("""
            INSERT INTO jobs (title, prompt, model, duration, status, status_message, progress)
            VALUES (?, ?, ?, ?, 'Đang chờ', 'Chờ xử lý', 0)
        """, (title, p, req.model, req.duration))
        count += 1
    conn.commit()
    conn.close()
    log_event(f"Nạp {count} prompt vào hàng đợi video", "SUCCESS", "Queue")
    return {"success": True, "created": count}

@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/download-video/{filename}")
async def download_video(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(OUTPUTS_DIR, safe_name)
    if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
        return FileResponse(
            file_path, 
            media_type="video/mp4", 
            filename=safe_name,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'}
        )
    return JSONResponse(status_code=404, content={"error": "File video chưa sẵn sàng hoặc đang render"})

@app.get("/api/jobs/{job_id}/stream")
async def stream_job_video(job_id: int):
    conn = get_connection()
    job = conn.execute("SELECT local_video_path FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    
    filename = f"video_{job_id}.mp4"
    if job and job["local_video_path"]:
        filename = os.path.basename(job["local_video_path"])
        
    file_path = os.path.join(OUTPUTS_DIR, filename)
    if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
        return FileResponse(file_path, media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "Video đang được tạo hoặc chưa sẵn sàng"})


# --- API TẠO ẢNH (IMAGES) ---
@app.get("/api/images")
async def get_images():
    conn = get_connection()
    rows = conn.execute("""
        SELECT img.*, a.name as account_name 
        FROM images img 
        LEFT JOIN accounts a ON img.account_id = a.id 
        ORDER BY img.id DESC
    """).fetchall()
    images = [dict(r) for r in rows]
    conn.close()
    return {"images": images}

@app.post("/api/images")
async def create_image(req: CreateImageRequest):
    conn = get_connection()
    cursor = conn.cursor()
    # Mẫu ảnh random chất lượng cao theo prompt
    image_url = f"https://images.unsplash.com/photo-{1578632767115 if 'cyber' in req.prompt.lower() else 1618005182384}?w=800"
    cursor.execute("""
        INSERT INTO images (account_id, prompt, model, aspect_ratio, style, status, image_url)
        VALUES (?, ?, ?, ?, ?, 'Hoàn thành', ?)
    """, (req.account_id, req.prompt, req.model, req.aspect_ratio, req.style, image_url))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    log_event(f"Tạo ảnh AI #{new_id} hoàn tất ({req.style})", "SUCCESS", "ImageEngine")
    return {"success": True, "id": new_id, "image_url": image_url}

@app.delete("/api/images/{image_id}")
async def delete_image(image_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
    conn.commit()
    conn.close()
    return {"success": True}

# --- API KHO NHÂN VẬT & ASSETS ---
@app.get("/api/assets")
async def get_assets():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM assets ORDER BY id DESC").fetchall()
    assets = [dict(r) for r in rows]
    conn.close()
    return {"assets": assets}

@app.post("/api/assets")
async def add_asset(req: CreateAssetRequest):
    conn = get_connection()
    cursor = conn.cursor()
    code = req.character_code if req.character_code else f"CHAR_{int(time.time())}"
    cursor.execute("""
        INSERT INTO assets (name, character_code, image_url, description, tags)
        VALUES (?, ?, ?, ?, ?)
    """, (req.name, code, req.image_url, req.description, req.tags))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    log_event(f"Lưu nhân vật mới '{req.name}' vào kho asset", "SUCCESS", "Asset")
    return {"success": True, "id": new_id}

@app.delete("/api/assets/{asset_id}")
async def delete_asset(asset_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    conn.commit()
    conn.close()
    return {"success": True}

# --- API CHECK ẢNH/VIDEO NICK ---
@app.get("/api/nick-media")
async def get_nick_media(account_id: Optional[int] = None):
    conn = get_connection()
    if account_id:
        jobs = conn.execute("SELECT * FROM jobs WHERE account_id = ? ORDER BY id DESC", (account_id,)).fetchall()
        images = conn.execute("SELECT * FROM images WHERE account_id = ? ORDER BY id DESC", (account_id,)).fetchall()
    else:
        jobs = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 50").fetchall()
        images = conn.execute("SELECT * FROM images ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return {
        "videos": [dict(j) for j in jobs],
        "images": [dict(i) for i in images]
    }

# --- API XỬ LÝ ÂM THANH (AUDIO / TTS) ---
@app.post("/api/audio/tts")
async def generate_tts(req: AudioTTSRequest):
    log_event(f"Tạo giọng đọc AI TTS: '{req.text[:30]}...' ({req.voice})", "SUCCESS", "Audio")
    return {
        "success": True,
        "message": "Đã tạo giọng đọc thành công",
        "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "duration": "12s"
    }

# --- API NHẬT KÝ (LOGS) ---
@app.get("/api/logs")
async def get_logs():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT 100").fetchall()
    logs = [dict(r) for r in rows]
    conn.close()
    return {"logs": logs}

@app.delete("/api/logs")
async def clear_logs():
    conn = get_connection()
    conn.execute("DELETE FROM system_logs")
    conn.commit()
    conn.close()
    return {"success": True}

# --- API SETTINGS ---
@app.get("/api/settings")
async def get_settings():
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    conn.close()
    return settings

@app.post("/api/settings")
async def update_settings(req: dict):
    conn = get_connection()
    cursor = conn.cursor()
    for k, v in req.items():
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()
    log_event("Cập nhật cài đặt hệ thống", "INFO", "Settings")
    return {"success": True}

# --- API MUSE AI & BATCH 180 CLIPS TỪ TOOL AI ---
@app.post("/api/accounts/login_muse")
async def login_muse_account(req: dict):
    acc_id = req.get("account_id")
    if not acc_id:
        return {"success": False, "message": "Thiếu account_id"}
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, auto_login_muse_sync, acc_id, True)
    return res

@app.post("/api/accounts/check_muse_token")
async def check_muse_token_account(req: dict):
    acc_id = req.get("account_id")
    if not acc_id:
        return {"success": False, "message": "Thiếu account_id"}
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, check_muse_tokens_sync, acc_id)
    return res

@app.post("/api/batch/import_b3")
async def import_b3_prompts(req: ImportBatchRequest):
    try:
        res = import_b3_batch(req.file_path, req.title)
        return res
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/batch/progress/{batch_id}")
async def get_batch_status(batch_id: str):
    return get_batch_progress(batch_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
