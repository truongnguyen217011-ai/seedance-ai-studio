"""REST API + mount static (docs/KIEN_TRUC.md mục 5). Không chứa logic nghiệp vụ."""
import asyncio
import json
import os
import shutil
import sys
import time
from datetime import datetime
from typing import List, Optional

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import browser
import config
import director
from account_pool import AccountPool
from batch_dispatcher import get_batch_progress, import_b3_batch
from constants import (DEFAULT_DURATION, DEFAULT_RATIO, JobStatus, NeedsManual, Reason, duration_label,
                       normalize_duration, normalize_ratio)
from database import get_connection, init_db, log_event
from diagnostics import build_bundle, diagnose_account, scan_status, start_scan_all
from dola_service import (
    account_has_dola_session,
    account_profile_dir,
    auto_login_facebook_dola,
    check_account_credits,
    has_dola_session,
    launch_login_session,
    parse_cookies_by_content,
    save_account_storage_state,
)
from logger import get_logger
from parser import (COOKIE_KIND_DOLA, COOKIE_KIND_FACEBOOK, detect_cookie_kind, parse_multiple_account_lines,
                    parse_single_account_line)
from worker import MUSE_UNSUPPORTED, run_in_job_executor, running_job_ids, track_task, worker_alive, worker_loop

log = get_logger("App")
app = FastAPI(title="Seedance AI Studio", version=config.VERSION)

STATIC_DIR = config.STATIC_DIR
OUTPUTS_DIR = config.OUTPUTS_DIR

# Đảm bảo database đã khởi tạo (migration chạy ở đây)
init_db()

# Đường dẫn tĩnh (docs/KIEN_TRUC.md mục 5): /static, /outputs, /logs/screenshots. KHÔNG mount cả /logs:
# file studio_*.log chứa tên nick, lỗi, proxy, không được lộ qua web (BH-31).
os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")
# Ảnh/HTML chụp lúc lỗi nằm ở logs/screenshots/; app.js dựng link "/logs/screenshots/<tên>" từ "[ảnh: <tên>]"
app.mount("/logs/screenshots", StaticFiles(directory=config.SCREENSHOTS_DIR), name="screenshots")


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
    data: str
    auto_login: Optional[bool] = False
    proxy: Optional[str] = ""       # proxy chung gán cho dòng không có proxy riêng (modal thêm nick nhiều dòng)


class ParsePreviewRequest(BaseModel):
    data: str
    proxy: Optional[str] = ""


class PasteCookieRequest(BaseModel):
    cookies: str


class BatchAssignProxyRequest(BaseModel):
    proxy: str
    target: Optional[str] = "no-proxy"


class CreateJobRequest(BaseModel):
    title: Optional[str] = ""
    prompt: str
    model: Optional[str] = "Seedance 2.5"
    duration: Optional[str] = None      # None = setting default_duration; ngoài 4-15 giây bị ép về 15 + warnings (BH-46)
    ratio: Optional[str] = None         # "16:9" | "9:16"; None = setting default_ratio
    account_id: Optional[int] = None
    reference_image: Optional[str] = ""


class BatchJobsRequest(BaseModel):
    prompts: List[str]
    model: Optional[str] = "Seedance 2.5"
    duration: Optional[str] = None
    ratio: Optional[str] = None
    style_code: Optional[str] = ""      # "" = tự nhận diện; mã trong director.ARCHETYPE_BY_CODE để ép trường phái
    director: Optional[bool] = None     # None = theo setting director_enabled


class DirectorPreviewRequest(BaseModel):
    prompts: List[str]
    style_code: Optional[str] = ""
    duration: Optional[str] = None
    ratio: Optional[str] = None
    model: Optional[str] = None
    director: Optional[bool] = None


class PromptFinalRequest(BaseModel):
    prompt_final: str


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


def _count_accounts() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
    finally:
        conn.close()


@app.on_event("startup")
async def startup_event():
    # BH-29: find_chrome có thể hỏi Playwright Sync API → không được gọi trên luồng event loop
    chrome = await asyncio.to_thread(browser.find_chrome)
    log_event(
        f"Khởi động Seedance AI Studio v{config.VERSION} | Chrome: {chrome or 'KHÔNG TÌM THẤY'} | "
        f"{_count_accounts()} nick | Dola: {config.DOLA_BASE_URL} | dữ liệu: {config.DATA_DIR}",
        "INFO", "System",
    )
    track_task(asyncio.create_task(worker_loop()))


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Seedance AI Studio</h1>")


# --- API HỆ THỐNG ---
@app.get("/api/version")
async def get_version():
    return {
        "version": config.VERSION,
        "chrome_path": await asyncio.to_thread(browser.find_chrome),
        "active_browsers": browser.active_count(),
        "max_browsers": browser.capacity(),
    }


@app.get("/api/health")
async def get_health():
    db_ok = True
    try:
        conn = get_connection()
        try:
            conn.execute("SELECT 1 FROM settings LIMIT 1").fetchone()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        db_ok = False
        log.error("Kiểm tra CSDL lỗi: %s", e)
    chrome = await asyncio.to_thread(browser.find_chrome)
    alive = worker_alive()
    return {
        "ok": bool(db_ok and chrome and alive),
        "db_ok": db_ok,
        "chrome_found": bool(chrome),
        "chrome_path": chrome,
        "active_browsers": browser.active_count(),
        "max_browsers": browser.capacity(),
        "worker_alive": alive,
        "version": config.VERSION,
    }


@app.get("/api/stats")
async def get_stats():
    conn = get_connection()
    try:
        total_accounts = conn.execute("SELECT COUNT(*) as c FROM accounts").fetchone()["c"]
        running_jobs = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = ?", (JobStatus.DANG_CHAY,)).fetchone()["c"]
        total_jobs = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]
        completed_jobs = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = ?", (JobStatus.HOAN_THANH,)).fetchone()["c"]
        total_images = conn.execute("SELECT COUNT(*) as c FROM images").fetchone()["c"]
        total_assets = conn.execute("SELECT COUNT(*) as c FROM assets").fetchone()["c"]
    finally:
        conn.close()
    return {
        "status": "connected",
        "running_jobs": running_jobs,
        "total_jobs": total_jobs,
        "total_accounts": total_accounts,
        "completed_jobs": completed_jobs,
        "total_images": total_images,
        "total_assets": total_assets,
        "active_browsers": browser.active_count(),
        "max_browsers": browser.capacity(),
    }


# --- API ACCOUNTS ---
_ACCOUNT_SECRET_COLUMNS = ("fb_pass", "fb_2fa", "cookies", "otp_key")


def _public_account(row) -> dict:
    d = dict(row)
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # A7: cột has_dola được ghi mỗi khi phiên được lưu và quét một lần lúc khởi động; chỉ nick chưa quét (NULL)
    # mới phải đọc file ở đây
    d["has_dola"] = bool(d["has_dola"]) if d.get("has_dola") is not None else account_has_dola_session(d)
    d["has_pass"] = bool(d.get("fb_pass"))
    d["has_2fa"] = bool(d.get("fb_2fa"))
    d["has_cookies"] = bool(d.get("cookies"))
    d["fb_pass_masked"] = "••••••••" if d["has_pass"] else ""
    is_resting = bool(d.get("rest_until") and d["rest_until"] > now_str)
    if d.get("credits_date") == today_str and d.get("credits") == 0:
        is_resting = True
    d["is_resting"] = is_resting
    d["credits_today"] = d.get("credits") if d.get("credits_date") == today_str else None
    d["is_busy"] = d.get("busy_job_id") is not None
    for col in _ACCOUNT_SECRET_COLUMNS:
        d.pop(col, None)
    return d


ACCOUNT_STATUS_FILTERS = ("ready", "needs_manual", "resting", "busy", "no_dola", "no_proxy")


def _accounts_where(q: str, status: str, account_type: str):
    """Mệnh đề WHERE + tham số cho GET /api/accounts (A7): tìm theo tên/UID/email, lọc trạng thái, loại nick."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clauses, params = [], []
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append("(name LIKE ? OR fb_uid LIKE ? OR email LIKE ?)")
        params.extend([like, like, like])
    account_type = (account_type or "").strip()
    if account_type and account_type != "all":
        clauses.append("account_type = ?")
        params.append(account_type)
    status = (status or "").strip()
    # COALESCE: cột NULL (chưa check credit) phải cho FALSE rõ ràng, nếu không `NOT (... OR NULL)` = NULL và nick bị lọc mất
    resting = "((rest_until IS NOT NULL AND rest_until > ?) OR (COALESCE(credits_date, '') = ? AND COALESCE(credits, -1) = 0))"
    if status == "ready":
        clauses.append(f"has_dola = 1 AND status = 'ready' AND needs_manual IS NULL AND NOT {resting}")
        params.extend([now_str, today_str])
    elif status == "needs_manual":
        clauses.append("needs_manual IS NOT NULL")
    elif status == "resting":
        clauses.append(resting)
        params.extend([now_str, today_str])
    elif status == "busy":
        clauses.append("busy_job_id IS NOT NULL")
    elif status == "no_dola":
        clauses.append("(has_dola IS NULL OR has_dola = 0)")
    elif status == "no_proxy":
        clauses.append("(proxy IS NULL OR TRIM(proxy) = '')")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@app.get("/api/accounts")
async def get_accounts(limit: int = 0, offset: int = 0, q: str = "", status: str = "", account_type: str = ""):
    """A7: phân trang (limit=0 = tất cả), tìm q theo tên/UID/email, lọc status ∈ ACCOUNT_STATUS_FILTERS, account_type.
    Trả {accounts, total, limit, offset}; không đọc storage_state.json của từng nick (cột has_dola)."""
    if status and status not in ACCOUNT_STATUS_FILTERS:
        return JSONResponse({"success": False, "message": f"Bộ lọc trạng thái '{status}' không hợp lệ; chọn một trong "
                                                          f"{', '.join(ACCOUNT_STATUS_FILTERS)}"}, status_code=400)
    limit = max(0, min(int(limit), 5000))
    offset = max(0, int(offset))
    where, params = _accounts_where(q, status, account_type)
    conn = get_connection()
    try:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM accounts{where}", params).fetchone()["c"]
        sql = f"SELECT * FROM accounts{where} ORDER BY id DESC"
        if limit:
            sql += " LIMIT ? OFFSET ?"
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        else:
            rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return {"accounts": [_public_account(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@app.post("/api/accounts")
async def add_account(req: AddAccountRequest, background_tasks: BackgroundTasks):
    name = req.name
    acc_type = req.account_type or "facebook"
    email = req.email
    fb_uid = req.fb_uid
    fb_pass = req.fb_pass
    fb_2fa = req.fb_2fa
    proxy = req.proxy
    raw_cookies = req.cookies

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
        except Exception as parse_err:  # noqa: BLE001 - parser ném ValueError với thông điệp người dùng
            return {"success": False, "message": f"Lỗi định dạng dòng: {parse_err}"}

    if not name:
        if fb_uid:
            name = f"FB {fb_uid[-6:]}" if len(fb_uid) >= 6 else f"FB {fb_uid}"
        elif email:
            name = email.split('@')[0]
        else:
            name = f"Nick_{int(time.time()) % 10000}"

    # K3 (BH-11): domain cookie nhận diện theo NỘI DUNG (sessionid → Dola, c_user → Facebook), không theo loại nick
    parsed_cookies = parse_cookies_by_content(raw_cookies, _fallback_cookie_domain(acc_type)) if raw_cookies else []

    cookies_json = json.dumps(parsed_cookies) if parsed_cookies else ""
    login_method = 'facebook' if acc_type == 'facebook' else 'google'
    has_dola = 1 if has_dola_session(parsed_cookies) else 0

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO accounts (name, account_type, email, fb_uid, fb_pass, fb_2fa, proxy, cookies, status, login_method, has_dola)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
        """, (name, acc_type, email, fb_uid, fb_pass, fb_2fa, proxy, cookies_json, login_method, has_dola))
        new_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    if parsed_cookies:
        save_account_storage_state(new_id, parsed_cookies)

    log_event(f"Thêm nick #{new_id} ({name} - {acc_type.upper()}) | UID: {fb_uid} | 2FA: {bool(fb_2fa)} | "
              f"Cookie: {detect_cookie_kind(raw_cookies) or 'không'} | phiên Dola: {'có' if has_dola else 'chưa'}",
              "SUCCESS", "Account", account_id=new_id)

    if req.auto_login:
        background_tasks.add_task(auto_login_facebook_dola, new_id, True)
        return {"success": True, "id": new_id, "auto_login": True, "message": "Đang tự động đăng nhập Dola ngầm..."}
    if req.auto_launch:
        background_tasks.add_task(launch_login_session, new_id)
        return {"success": True, "id": new_id, "launched_browser": True, "message": "Đang mở Chrome..."}
    return {"success": True, "id": new_id, "launched_browser": False}


def _fallback_cookie_domain(acc_type: str) -> str:
    return ".google.com" if acc_type == "google" else ".facebook.com"


def _existing_account_index(cursor) -> dict:
    """{uid_hoặc_email: (id, name)} của mọi nick đang có, để nhận ra dòng 'đã có' (A2: so UID hoặc email)."""
    index = {}
    for r in cursor.execute("SELECT id, name, fb_uid, email FROM accounts").fetchall():
        if r["fb_uid"]:
            index.setdefault(r["fb_uid"], (r["id"], r["name"]))
        if r["email"]:
            index.setdefault(r["email"], (r["id"], r["name"]))
    return index


def _duplicate_reason(item: dict, index: dict):
    """Lý do 'đã có' nếu UID/email của dòng trùng nick trong CSDL, kèm id nick cũ; None nếu mới."""
    for key in (item.get("uid"), item.get("email")):
        if key and key in index:
            old_id, old_name = index[key]
            return f"Nick đã có: trùng {'email' if '@' in str(key) else 'UID'} {key} với nick #{old_id} ({old_name}), bỏ qua", old_id
    return None, None


@app.post("/api/accounts/parse-preview")
async def parse_preview_accounts(req: ParsePreviewRequest):
    """A3: tách từng dòng dán vào để người dùng xác nhận TRƯỚC khi lưu. Không ghi CSDL, không trả mật khẩu."""
    ok_list, err_list = parse_multiple_account_lines(req.data, strict_2fa=True)
    conn = get_connection()
    try:
        index = _existing_account_index(conn.cursor())
    finally:
        conn.close()
    items = []
    global_proxy = (req.proxy or "").strip()
    for item in ok_list:
        dup_reason, old_id = _duplicate_reason(item, index)
        proxy = item.get("proxy") or global_proxy or ""
        items.append({
            "line": item.get("line"), "ok": dup_reason is None, "uid": item["uid"], "name": item["name"],
            "email": item.get("email"), "account_type": item["account_type"],
            "has_pass": bool(item.get("pass")) and item.get("pass") != "cookie_login",
            "has_2fa": bool(item.get("twofa")), "has_cookie": bool(item.get("cookie")),
            "cookie_kind": item.get("cookie_kind"), "proxy": proxy,
            "exists": dup_reason is not None, "existing_id": old_id, "reason": dup_reason or "",
        })
    for err in err_list:
        items.append({"line": err.get("line"), "ok": False, "uid": "", "name": "", "email": None, "account_type": "",
                      "has_pass": False, "has_2fa": False, "has_cookie": False, "cookie_kind": None, "proxy": "",
                      "exists": False, "existing_id": None, "reason": err.get("reason", ""), "text": err.get("text", "")})
    items.sort(key=lambda it: (it.get("line") or 0))
    n_ok = sum(1 for it in items if it["ok"])
    n_dup = sum(1 for it in items if it["exists"])
    return {"success": True, "items": items,
            "summary": {"total": len(items), "ok": n_ok, "duplicates": n_dup, "errors": len(items) - n_ok - n_dup}}


@app.post("/api/accounts/batch-import")
async def batch_import_accounts(req: BatchImportRequest, background_tasks: BackgroundTasks):
    """A1/A2: thêm từng dòng; trả imported_lines (dòng đã thêm, id mới) + errors (trùng, thiếu pass, 2FA sai định dạng...)."""
    ok_list, err_list = parse_multiple_account_lines(req.data, strict_2fa=True)
    if not ok_list and not err_list:
        return {"success": False, "message": "Dữ liệu trống hoặc không có dòng nào hợp lệ."}
    global_proxy = (req.proxy or "").strip()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        index = _existing_account_index(cursor)
        cookie_count = 0
        added = []           # (new_id, parsed_cookies)
        imported_lines = []

        for item in ok_list:
            dup_reason, old_id = _duplicate_reason(item, index)
            if dup_reason:
                err_list.append({"line": item.get("line", 0), "text": item["uid"], "reason": dup_reason, "existing_id": old_id})
                continue

            raw_c = item.get("cookie")
            parsed_cookies = parse_cookies_by_content(raw_c, _fallback_cookie_domain(item["account_type"])) if raw_c else []
            cookies_json = json.dumps(parsed_cookies) if parsed_cookies else ""
            if parsed_cookies:
                cookie_count += 1
            proxy = item.get("proxy") or global_proxy or None
            has_dola = 1 if has_dola_session(parsed_cookies) else 0

            cursor.execute("""
                INSERT INTO accounts (name, account_type, email, fb_uid, fb_pass, fb_2fa, proxy, cookies, status, login_method, has_dola)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
            """, (item["name"], item["account_type"], item.get("email"), item["uid"], item["pass"], item.get("twofa"),
                  proxy, cookies_json, "facebook" if item["account_type"] == "facebook" else "google", has_dola))
            new_id = cursor.lastrowid
            added.append((new_id, parsed_cookies))
            index[item["uid"]] = (new_id, item["name"])
            if item.get("email"):
                index[item["email"]] = (new_id, item["name"])
            imported_lines.append({
                "line": item.get("line"), "id": new_id, "name": item["name"], "uid": item["uid"],
                "account_type": item["account_type"], "has_2fa": bool(item.get("twofa")),
                "has_cookie": bool(parsed_cookies), "cookie_kind": item.get("cookie_kind"), "has_dola": bool(has_dola),
                "proxy": proxy or "",
            })
        conn.commit()
    finally:
        conn.close()

    for new_id, parsed_cookies in added:
        if parsed_cookies:
            save_account_storage_state(new_id, parsed_cookies)

    err_list.sort(key=lambda e: e.get("line") or 0)
    count = len(imported_lines)
    log_event(f"Nhập {count} nick ({cookie_count} nick có cookie sẵn, {len(err_list)} dòng bỏ qua/lỗi)",
              "SUCCESS" if count else "WARNING", "Account")
    for new in imported_lines:
        log_event(f"Thêm nick #{new['id']} ({new['name']}) từ dòng {new['line']} | UID: {new['uid']} | 2FA: {new['has_2fa']} | "
                  f"Cookie: {new['cookie_kind'] or 'không'} | Proxy: {'có' if new['proxy'] else 'không'}",
                  "INFO", "Account", account_id=new["id"])

    if req.auto_login:
        for new_id, _ in added:
            background_tasks.add_task(auto_login_facebook_dola, new_id, True)

    return {"success": True, "imported": count, "with_cookies": cookie_count, "imported_lines": imported_lines,
            "errors": err_list, "auto_login_queued": bool(req.auto_login)}


@app.post("/api/accounts/scan-all")
async def api_scan_all_accounts():
    """K9: quét tất cả nick nền (chẩn đoán từng nick qua pool, không vượt giới hạn Chrome)."""
    return await asyncio.to_thread(start_scan_all)


@app.get("/api/accounts/scan-status")
async def api_scan_status():
    return scan_status()


@app.post("/api/accounts/{account_id}/auto-login")
async def trigger_auto_login(account_id: int, background_tasks: BackgroundTasks):
    log_event(f"Yêu cầu tự động đăng nhập Dola cho nick #{account_id}", "INFO", "Auth", account_id=account_id)
    background_tasks.add_task(auto_login_facebook_dola, account_id, True)
    return {"success": True, "message": "Đang chạy tự động đăng nhập ngầm qua Facebook và Dola..."}


@app.post("/api/accounts/{account_id}/cookies")
async def paste_account_cookies(account_id: int, req: PasteCookieRequest):
    """Modal Dán Cookie: domain theo nội dung (K3); không nhận ra thì coi là cookie Dola (modal này dành cho Dola)."""
    from dola_service import default_dola_cookie_domain
    cookies = parse_cookies_by_content(req.cookies, default_dola_cookie_domain())
    if not cookies:
        return {"success": False, "message": "Không tìm thấy cookie nào hợp lệ trong dữ liệu bạn vừa dán."}
    kind = detect_cookie_kind(req.cookies)
    has_session = has_dola_session(cookies)

    conn = get_connection()
    try:
        acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not acc:
            return {"success": False, "message": "Tài khoản không tồn tại."}
        conn.execute("UPDATE accounts SET cookies = ?, status = 'ready', last_check = CURRENT_TIMESTAMP, has_dola = ?, "
                     "needs_manual = CASE WHEN needs_manual = ? AND ? = 1 THEN NULL ELSE needs_manual END WHERE id = ?",
                     (json.dumps(cookies), 1 if has_session else 0, NeedsManual.LOGIN, 1 if has_session else 0, account_id))
        conn.commit()
    finally:
        conn.close()
    save_account_storage_state(account_id, cookies)
    label = {COOKIE_KIND_DOLA: "Dola", COOKIE_KIND_FACEBOOK: "Facebook"}.get(kind, "theo domain trong JSON" if kind else "không rõ dịch vụ")
    log_event(f"Đã nạp {len(cookies)} cookie ({label}) cho nick #{account_id} ({acc['name']}); phiên Dola: {'có' if has_session else 'chưa'}",
              "SUCCESS" if has_session else "WARNING", "Auth", account_id=account_id)
    message = (f"Đã nạp {len(cookies)} cookie {label}. " +
               ("Phiên Dola hợp lệ, nick sẵn sàng tạo video." if has_session else
                "Chưa thấy sessionid Dola trong cookie: nick vẫn cần Auto Login hoặc dán cookie Dola (sessionid=...)."))
    return {"success": True, "count": len(cookies), "has_session": has_session, "cookie_kind": kind, "message": message}


@app.post("/api/accounts/batch-assign-proxy")
async def batch_assign_proxy(req: BatchAssignProxyRequest):
    from diagnostics import mask_proxy
    conn = get_connection()
    try:
        # Đổi proxy thì cờ "proxy lỗi" (A5) của nick đó không còn đúng → gỡ để worker/chẩn đoán thử proxy mới
        if req.target == "no-proxy":
            cur = conn.execute("UPDATE accounts SET proxy = ?, needs_manual = CASE WHEN needs_manual = ? THEN NULL ELSE needs_manual END "
                               "WHERE proxy IS NULL OR proxy = ''", (req.proxy, NeedsManual.PROXY))
        else:
            cur = conn.execute("UPDATE accounts SET proxy = ?, needs_manual = CASE WHEN needs_manual = ? THEN NULL ELSE needs_manual END",
                               (req.proxy, NeedsManual.PROXY))
        changed = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    log_event(f"Đã gán proxy '{mask_proxy(req.proxy)}' cho {changed} nick ({req.target})", "SUCCESS", "Account")
    return {"success": True, "updated": changed}


@app.post("/api/accounts/{account_id}/login")
async def login_account(account_id: int, background_tasks: BackgroundTasks):
    if AccountPool.get().is_busy(account_id):
        holder = AccountPool.get().holder(account_id)
        return {"success": False, "message": f"Nick #{account_id} đang bận" + (f" với job #{holder}" if holder else "")}
    log_event(f"Mở Chrome đăng nhập cho nick #{account_id}", "INFO", "Auth", account_id=account_id)
    background_tasks.add_task(launch_login_session, account_id)
    return {"success": True, "message": "Đang mở Chrome đăng nhập..."}


@app.get("/api/accounts/{account_id}/check-dola")
async def check_account_dola(account_id: int):
    conn = get_connection()
    try:
        acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    finally:
        conn.close()
    if not acc:
        return {"connected": False, "message": "Không tìm thấy tài khoản"}
    if account_has_dola_session(acc):
        return {"connected": True, "status": "ready",
                "message": f"Nick '{acc['name']}' đã đăng nhập Dola (có sessionid hợp lệ) và sẵn sàng tạo video"}
    return {"connected": False, "status": "need_login",
            "message": f"Nick '{acc['name']}' chưa đăng nhập Dola (thiếu sessionid). Bấm Auto Login hoặc dán cookie Dola"}


@app.post("/api/accounts/{account_id}/check-credits")
async def api_check_account_credits(account_id: int):
    return await check_account_credits(account_id)


@app.post("/api/accounts/check-all-credits")
async def api_check_all_credits(background_tasks: BackgroundTasks):
    conn = get_connection()
    try:
        accounts = conn.execute("SELECT * FROM accounts WHERE status = 'ready'").fetchall()
    finally:
        conn.close()
    checked_ids = [acc["id"] for acc in accounts if account_has_dola_session(acc)]
    for acc_id in checked_ids:
        background_tasks.add_task(check_account_credits, acc_id)
    log_event(f"Bắt đầu kiểm tra credit cho {len(checked_ids)} nick đã kết nối Dola", "INFO", "Credit")
    return {"success": True, "count": len(checked_ids), "account_ids": checked_ids}


@app.post("/api/accounts/{account_id}/diagnose")
async def api_diagnose_account(account_id: int):
    # Mở Chrome → chạy trên JOB_EXECUTOR (BH-32)
    return await run_in_job_executor(diagnose_account, account_id)


@app.get("/api/diagnostics/bundle")
async def api_diagnostics_bundle():
    path = await asyncio.to_thread(build_bundle)
    return FileResponse(path, media_type="application/zip", filename=os.path.basename(path))


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int):
    """A6: không xóa khi nick bận; job đang gán nick về Chờ với lý do rõ; gỡ liên kết job/ảnh cũ (khóa ngoại, BH-52);
    xóa thư mục profiles/acc_{id}."""
    pool = AccountPool.get()
    if pool.is_busy(account_id):
        holder = pool.holder(account_id)
        return {"success": False, "message": f"Nick #{account_id} đang bận" + (f" với job #{holder}" if holder else "") + ", không xóa được"}
    conn = get_connection()
    try:
        acc = conn.execute("SELECT id, name FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not acc:
            return {"success": False, "message": f"Nick #{account_id} không tồn tại"}
        name = acc["name"]
        cur = conn.execute(
            """UPDATE jobs SET status = ?, status_message = ?, progress = 0, account_id = NULL, updated_at = CURRENT_TIMESTAMP
               WHERE account_id = ? AND status IN (?, ?, ?)""",
            (JobStatus.CHO, Reason.ACCOUNT_DELETED.format(name=name), account_id, JobStatus.CHO, JobStatus.DANG_CHAY, JobStatus.TAM_DUNG),
        )
        requeued = cur.rowcount
        # Job đã xong/thất bại và ảnh chỉ còn tham chiếu lịch sử: gỡ khóa ngoại để xóa được nick (BH-52)
        conn.execute("UPDATE jobs SET account_id = NULL WHERE account_id = ?", (account_id,))
        conn.execute("UPDATE images SET account_id = NULL WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()
    finally:
        conn.close()
    profile_dir = account_profile_dir(account_id)
    profile_removed = False
    if os.path.isdir(profile_dir):
        try:
            await asyncio.to_thread(shutil.rmtree, profile_dir)
            profile_removed = True
        except OSError as e:
            log.warning("Không xóa được thư mục profile %s: %s", profile_dir, e, extra={"account_id": account_id})
    log_event(f"Đã xóa nick #{account_id} ({name}); {requeued} job về '{JobStatus.CHO}' chờ nick khác; "
              f"thư mục profile {'đã xóa' if profile_removed else 'không có hoặc không xóa được'}",
              "WARNING", "Account", account_id=account_id)
    return {"success": True, "requeued_jobs": requeued, "profile_removed": profile_removed}


# --- API JOBS (VIDEO) ---
@app.get("/api/jobs")
async def get_jobs(limit: int = 500):
    limit = max(1, min(int(limit), 5000))
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT j.*, a.name as account_name, a.proxy as account_proxy
            FROM jobs j LEFT JOIN accounts a ON j.account_id = a.id
            ORDER BY j.id DESC LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()
    return {"jobs": [dict(r) for r in rows]}


# --- Đạo diễn AI (director.py, docs/KIEN_TRUC.md mục 8): prompt_final được ghép LÚC TẠO JOB, không phải lúc gửi Dola ---
def _load_settings_dict() -> dict:
    conn = get_connection()
    try:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings").fetchall()}
    finally:
        conn.close()


def _load_assets() -> list:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, character_code, image_url, description FROM assets").fetchall()]
    finally:
        conn.close()


def _director_context(director_flag: Optional[bool], model: Optional[str], duration: Optional[str],
                      ratio: Optional[str] = None) -> dict:
    """Đọc settings + assets một lần cho cả lô; director_flag (True/False) ghi đè setting director_enabled.

    Thời lượng và tỷ lệ là tham số thật của job (BH-46): thời lượng ngoài 4-15 giây bị ép về biên (thường 15)
    và tỷ lệ lạ về mặc định; mỗi lần ép sinh một dòng trong ctx["warnings"] để trả về giao diện.
    """
    settings = _load_settings_dict()
    options = director.options_from_settings(settings)
    if director_flag is not None:
        options["director_enabled"] = "1" if director_flag else "0"
    seconds, dur_warning = normalize_duration(duration or settings.get("default_duration") or DEFAULT_DURATION)
    ratio_value, ratio_warning = normalize_ratio(ratio or settings.get("default_ratio") or DEFAULT_RATIO)
    return {
        "options": options,
        "assets": _load_assets(),
        "model": model or settings.get("default_model") or "Seedance 2.5",
        "duration": duration_label(seconds),
        "ratio": ratio_value,
        "warnings": [w for w in (dur_warning, ratio_warning) if w],
    }


def _compose_for_job(prompt: str, ctx: dict, style_code: Optional[str]) -> dict:
    return director.compose(prompt, duration_label=ctx["duration"], ratio=ctx["ratio"], model=ctx["model"],
                            options=ctx["options"], assets=ctx["assets"], style_override=style_code)


@app.post("/api/director/preview")
async def director_preview(req: DirectorPreviewRequest):
    """Xem trước prompt đã đạo diễn, KHÔNG tạo job. Trả về một mục cho mỗi dòng prompt không rỗng."""
    ctx = _director_context(req.director, req.model, req.duration, req.ratio)
    items = []
    try:
        for p in req.prompts:
            p = (p or "").strip()
            if not p:
                continue
            r = _compose_for_job(p, ctx, req.style_code)
            items.append({
                "prompt": p,
                "prompt_final": r["prompt_final"],
                "archetype_code": r["archetype_code"],
                "archetype_name": r["archetype_name"],
                "layers_added": r["layers_added"],
                "existing_layers": r["existing_layers"],
                "characters": r["characters"],
                "reference_image": r["reference_image"],
            })
    except ValueError as e:  # mã trường phái lạ
        return {"success": False, "message": str(e), "items": []}
    return {"success": True, "items": items, "director_enabled": director.is_enabled(ctx["options"]),
            "duration": ctx["duration"], "ratio": ctx["ratio"], "warnings": ctx["warnings"]}


@app.post("/api/jobs")
async def create_job(req: CreateJobRequest):
    title = req.title if req.title else req.prompt[:40] + "..."
    ctx = _director_context(None, req.model, req.duration, req.ratio)
    try:
        composed = _compose_for_job(req.prompt, ctx, None)
    except ValueError as e:
        return {"success": False, "message": str(e)}
    reference_image = req.reference_image or composed["reference_image"] or ""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO jobs (account_id, title, prompt, prompt_final, archetype_code, model, duration, ratio, status,
                              status_message, progress, reference_image, attempts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0)
        """, (req.account_id, title, req.prompt, composed["prompt_final"], composed["archetype_code"], ctx["model"],
              ctx["duration"], ctx["ratio"], JobStatus.CHO, "Chờ worker nhặt", reference_image))
        new_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    log_event(f"Tạo job video #{new_id} ({title}) · trường phái {composed['archetype_code'] or 'tắt đạo diễn'}",
              "INFO", "Queue", job_id=new_id)
    return {"success": True, "id": new_id, "prompt": req.prompt, "prompt_final": composed["prompt_final"],
            "archetype": composed["archetype_code"], "duration": ctx["duration"], "ratio": ctx["ratio"],
            "warnings": ctx["warnings"]}


@app.post("/api/jobs/batch")
async def create_batch_jobs(req: BatchJobsRequest):
    ctx = _director_context(req.director, req.model, req.duration, req.ratio)
    try:
        prepared = []
        for seq, p in enumerate(req.prompts, 1):
            p = (p or "").strip()
            if not p:
                continue
            prepared.append((seq, p, _compose_for_job(p, ctx, req.style_code)))
    except ValueError as e:
        return {"success": False, "message": str(e), "created": 0, "jobs": []}

    created = []
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for seq, p, composed in prepared:
            cursor.execute("""
                INSERT INTO jobs (title, prompt, prompt_final, archetype_code, model, duration, ratio, status,
                                  status_message, progress, seq, reference_image, attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0)
            """, (p[:40] + "...", p, composed["prompt_final"], composed["archetype_code"], ctx["model"], ctx["duration"],
                  ctx["ratio"], JobStatus.CHO, "Chờ worker nhặt", seq, composed["reference_image"] or ""))
            created.append({"id": cursor.lastrowid, "prompt": p, "prompt_final": composed["prompt_final"],
                            "archetype": composed["archetype_code"], "characters": composed["characters"]})
        conn.commit()
    finally:
        conn.close()
    codes = sorted({c["archetype"] for c in created if c["archetype"]})
    log_event(f"Nạp {len(created)} prompt vào hàng đợi video ({ctx['duration']}, {ctx['ratio']}) · Đạo diễn AI: "
              + (", ".join(codes) if codes else "tắt"), "SUCCESS", "Queue")
    for w in ctx["warnings"]:
        log_event(f"Nạp lô prompt: {w}", "WARNING", "Queue")
    return {"success": True, "created": len(created), "jobs": created, "duration": ctx["duration"],
            "ratio": ctx["ratio"], "warnings": ctx["warnings"]}


@app.put("/api/jobs/{job_id}/prompt_final")
async def update_job_prompt_final(job_id: int, req: PromptFinalRequest):
    """Người dùng sửa tay prompt đã đạo diễn; chỉ khi job chưa chạy (Chờ, Thất bại, Tạm dừng)."""
    job = _load_job_row(job_id)
    if not job:
        return {"success": False, "message": f"Không tìm thấy job #{job_id}"}
    editable = (JobStatus.CHO, JobStatus.THAT_BAI, JobStatus.TAM_DUNG)
    if job["status"] not in editable or job_id in running_job_ids():
        return {"success": False, "status": job["status"],
                "message": f"Job #{job_id} đang ở trạng thái '{job['status']}', không sửa được prompt. "
                           f"Chỉ sửa được khi job {', '.join(editable)}"}
    text = (req.prompt_final or "").strip()
    if not text:
        return {"success": False, "message": "Prompt đã đạo diễn không được để trống"}
    conn = get_connection()
    try:
        conn.execute("UPDATE jobs SET prompt_final = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (text, job_id))
        conn.commit()
    finally:
        conn.close()
    log_event(f"Job #{job_id}: người dùng sửa tay prompt đã đạo diễn ({len(text)} ký tự)", "INFO", "Queue", job_id=job_id)
    return {"success": True, "prompt_final": text}


def _load_job_row(job_id: int):
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: int):
    job = _load_job_row(job_id)
    if not job:
        return {"success": False, "message": f"Không tìm thấy job #{job_id}"}
    if job["status"] not in (JobStatus.THAT_BAI, JobStatus.TAM_DUNG):
        return {"success": False, "status": job["status"],
                "message": f"Job #{job_id} đang ở trạng thái '{job['status']}', chỉ chạy lại được job Thất bại hoặc Tạm dừng"}
    conn = get_connection()
    try:
        conn.execute("""UPDATE jobs SET status = ?, status_message = ?, progress = 0, attempts = 0,
                        started_at = NULL, finished_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                     (JobStatus.CHO, Reason.USER_RETRY, job_id))
        conn.commit()
    finally:
        conn.close()
    log_event(f"Job #{job_id}: {Reason.USER_RETRY}", "INFO", "Queue", job_id=job_id, account_id=job["account_id"])
    return {"success": True, "status": JobStatus.CHO}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: int):
    job = _load_job_row(job_id)
    if not job:
        return {"success": False, "message": f"Không tìm thấy job #{job_id}"}
    if job["status"] != JobStatus.TAM_DUNG:
        return {"success": False, "message": f"Job #{job_id} không ở trạng thái '{JobStatus.TAM_DUNG}'"}
    conn = get_connection()
    try:
        conn.execute("UPDATE jobs SET status = ?, status_message = ?, progress = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (JobStatus.CHO, "Người dùng bấm Tiếp tục", job_id))
        if job["account_id"]:
            conn.execute("UPDATE accounts SET needs_manual = NULL WHERE id = ?", (job["account_id"],))
        conn.commit()
    finally:
        conn.close()
    log_event(f"Job #{job_id}: người dùng bấm Tiếp tục, đã xóa cờ can thiệp tay của nick", "INFO", "Queue",
              job_id=job_id, account_id=job["account_id"])
    return {"success": True}


@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id: int):
    job = _load_job_row(job_id)
    if not job:
        return {"success": False, "message": f"Không tìm thấy job #{job_id}"}
    if job["status"] != JobStatus.CHO:
        return {"success": False, "message": f"Chỉ tạm dừng được job đang '{JobStatus.CHO}' (job #{job_id} đang '{job['status']}')"}
    conn = get_connection()
    try:
        conn.execute("UPDATE jobs SET status = ?, status_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = ?",
                     (JobStatus.TAM_DUNG, Reason.USER_PAUSED, job_id, JobStatus.CHO))
        conn.commit()
    finally:
        conn.close()
    log_event(f"Job #{job_id}: {Reason.USER_PAUSED}", "INFO", "Queue", job_id=job_id)
    return {"success": True}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: int):
    job = _load_job_row(job_id)
    if not job:
        return {"success": False, "message": f"Không tìm thấy job #{job_id}"}
    if job["status"] == JobStatus.DANG_CHAY or job_id in running_job_ids():
        return {"success": False, "status": job["status"],
                "message": f"Job #{job_id} đang chạy trên nick #{job['account_id']}, không xóa được. "
                           f"Chờ job xong hoặc Tạm dừng rồi xóa"}
    conn = get_connection()
    try:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()
    log_event(f"Đã xóa job #{job_id} (trạng thái '{job['status']}')", "INFO", "Queue", job_id=job_id)
    return {"success": True}


@app.get("/api/download-video/{filename}")
async def download_video(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(OUTPUTS_DIR, safe_name)
    if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
        return FileResponse(file_path, media_type="video/mp4", filename=safe_name,
                            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})
    return JSONResponse(status_code=404, content={"error": "File video chưa sẵn sàng hoặc đang render"})


@app.get("/api/jobs/{job_id}/stream")
async def stream_job_video(job_id: int):
    job = _load_job_row(job_id)
    filename = f"video_{job_id}.mp4"
    if job and job["local_video_path"]:
        filename = os.path.basename(job["local_video_path"])
    file_path = os.path.join(OUTPUTS_DIR, filename)
    if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
        return FileResponse(file_path, media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "Video đang được tạo hoặc chưa sẵn sàng"})


# --- API TẠO ẢNH (IMAGES) — giữ nguyên, giai đoạn 5 mới gỡ ---
@app.get("/api/images")
async def get_images():
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT img.*, a.name as account_name FROM images img
            LEFT JOIN accounts a ON img.account_id = a.id ORDER BY img.id DESC
        """).fetchall()
    finally:
        conn.close()
    return {"images": [dict(r) for r in rows]}


@app.post("/api/images")
async def create_image(req: CreateImageRequest):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        image_url = f"https://images.unsplash.com/photo-{1578632767115 if 'cyber' in req.prompt.lower() else 1618005182384}?w=800"
        cursor.execute("""
            INSERT INTO images (account_id, prompt, model, aspect_ratio, style, status, image_url)
            VALUES (?, ?, ?, ?, ?, 'Hoàn thành', ?)
        """, (req.account_id, req.prompt, req.model, req.aspect_ratio, req.style, image_url))
        new_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    log_event(f"Tạo ảnh AI #{new_id} hoàn tất ({req.style})", "SUCCESS", "ImageEngine")
    return {"success": True, "id": new_id, "image_url": image_url}


@app.delete("/api/images/{image_id}")
async def delete_image(image_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
        conn.commit()
    finally:
        conn.close()
    return {"success": True}


# --- API KHO NHÂN VẬT & ASSETS ---
@app.get("/api/assets")
async def get_assets():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM assets ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    return {"assets": [dict(r) for r in rows]}


@app.post("/api/assets")
async def add_asset(req: CreateAssetRequest):
    code = req.character_code if req.character_code else f"CHAR_{int(time.time())}"
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO assets (name, character_code, image_url, description, tags) VALUES (?, ?, ?, ?, ?)",
                       (req.name, code, req.image_url, req.description, req.tags))
        new_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    log_event(f"Lưu nhân vật mới '{req.name}' vào kho asset", "SUCCESS", "Asset")
    return {"success": True, "id": new_id}


@app.delete("/api/assets/{asset_id}")
async def delete_asset(asset_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        conn.commit()
    finally:
        conn.close()
    return {"success": True}


# --- API CHECK ẢNH/VIDEO NICK ---
@app.get("/api/nick-media")
async def get_nick_media(account_id: Optional[int] = None):
    conn = get_connection()
    try:
        if account_id:
            jobs = conn.execute("SELECT * FROM jobs WHERE account_id = ? ORDER BY id DESC", (account_id,)).fetchall()
            images = conn.execute("SELECT * FROM images WHERE account_id = ? ORDER BY id DESC", (account_id,)).fetchall()
        else:
            jobs = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 50").fetchall()
            images = conn.execute("SELECT * FROM images ORDER BY id DESC LIMIT 50").fetchall()
    finally:
        conn.close()
    return {"videos": [dict(j) for j in jobs], "images": [dict(i) for i in images]}


# --- API XỬ LÝ ÂM THANH (AUDIO / TTS) — giữ nguyên, giai đoạn 5 mới gỡ ---
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
async def get_logs(limit: int = 500, job_id: Optional[int] = None, account_id: Optional[int] = None, level: Optional[str] = None):
    limit = max(1, min(int(limit), 5000))
    where = []
    params = []
    if job_id is not None:
        where.append("job_id = ?")
        params.append(job_id)
    if account_id is not None:
        where.append("account_id = ?")
        params.append(account_id)
    if level:
        where.append("UPPER(level) = ?")
        params.append(level.upper())
    sql = "SELECT id, level, module, message, job_id, account_id, created_at FROM system_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return {"logs": [dict(r) for r in rows]}


@app.delete("/api/logs")
async def clear_logs():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM system_logs")
        conn.commit()
    finally:
        conn.close()
    return {"success": True}


# --- API SETTINGS ---
@app.get("/api/settings")
async def get_settings():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    finally:
        conn.close()
    return {r["key"]: r["value"] for r in rows}


@app.post("/api/settings")
async def update_settings(req: dict):
    warnings = []
    req = dict(req)
    if "default_duration" in req:  # BH-46: chỉ nhận thời lượng Dola hỗ trợ (4-15 giây)
        seconds, w = normalize_duration(req["default_duration"])
        req["default_duration"] = duration_label(seconds)
        if w:
            warnings.append(w)
    if "default_ratio" in req:
        req["default_ratio"], w = normalize_ratio(req["default_ratio"])
        if w:
            warnings.append(w)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for k, v in req.items():
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
        conn.commit()
    finally:
        conn.close()
    if "chrome_path" in req:
        browser.refresh_chrome()
    log_event("Cập nhật cài đặt hệ thống", "INFO", "Settings")
    return {"success": True, "warnings": warnings}


# --- API MUSE AI (không còn hỗ trợ: không mở Chrome ngoài slot/pool; muse_service.py gỡ ở giai đoạn 5) & BATCH B3 ---
@app.post("/api/accounts/login_muse")
async def login_muse_account(req: dict):
    return {"success": False, "message": MUSE_UNSUPPORTED}


@app.post("/api/accounts/check_muse_token")
async def check_muse_token_account(req: dict):
    return {"success": False, "message": MUSE_UNSUPPORTED}


@app.post("/api/batch/import_b3")
async def import_b3_prompts(req: ImportBatchRequest):
    try:
        return import_b3_batch(req.file_path, req.title)
    except Exception as e:  # noqa: BLE001 - trả lỗi về giao diện
        log.warning("Import B3 lỗi: %s", e)
        return {"success": False, "message": str(e)}


@app.get("/api/batch/progress/{batch_id}")
async def get_batch_status(batch_id: str):
    return get_batch_progress(batch_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000)
