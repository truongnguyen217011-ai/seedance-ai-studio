"""Chẩn đoán nick và gói chẩn đoán gửi hỗ trợ (docs/KIEN_TRUC.md mục 2, 5).

- diagnose_account(account_id): các bước proxy, chrome, fb_cookie, dola_session, credits.
- build_bundle(): zip log 24h, ảnh chụp, settings (bỏ key nhạy cảm), danh sách nick đã che mật.
"""
import glob
import json
import os
import platform
import time
import zipfile
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx

import browser
import config
from account_pool import AccountPool
from constants import NeedsManual
from database import get_connection
from logger import get_logger, log_event

log = get_logger("Diagnose")

IP_CHECK_URL = "https://api.ipify.org?format=json"
IP_TIMEOUT = 15
SENSITIVE_SETTING_WORDS = ("key", "pass")


def _step(key: str, name: str, ok, detail: str) -> dict:
    return {"key": key, "name": name, "ok": ok, "detail": detail}


def mask_proxy(proxy) -> str:
    """Che mật khẩu proxy để hiện/ghi log (BH-33).

    `ip:port:user:pass` → `ip:port:user:***`; `scheme://user:pass@host:port` → `scheme://user:***@host:port`;
    dạng không có mật khẩu (`ip:port`, `scheme://host:port`) giữ nguyên; None/rỗng → "".
    """
    if not proxy:
        return ""
    text = str(proxy).strip()
    if "://" in text:
        scheme, _, rest = text.partition("://")
        if "@" in rest:
            cred, _, host = rest.rpartition("@")
            user = cred.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}" if ":" in cred else f"{scheme}://{user}@{host}"
        return text
    parts = text.split(":")
    if len(parts) >= 4:
        return ":".join(parts[:3] + ["***"])
    return text


def _proxy_url(proxy_cfg: Optional[dict]) -> Optional[str]:
    if not proxy_cfg:
        return None
    server = proxy_cfg.get("server", "")
    user = proxy_cfg.get("username")
    pwd = proxy_cfg.get("password")
    if user and "@" not in server:
        scheme, _, host = server.partition("://")
        return f"{scheme}://{user}:{pwd or ''}@{host}"
    return server


def _fetch_ip(proxy_url: Optional[str]) -> str:
    kwargs = {"timeout": IP_TIMEOUT}
    if proxy_url:
        kwargs["proxy"] = proxy_url
        kwargs["trust_env"] = False
    with httpx.Client(**kwargs) as client:
        resp = client.get(IP_CHECK_URL)
        resp.raise_for_status()
        data = resp.json()
    ip = str(data.get("ip", "")).strip()
    if not ip:
        raise ValueError("Dịch vụ kiểm tra IP không trả về địa chỉ")
    return ip


def _check_proxy(acc: dict) -> dict:
    from dola_service import parse_proxy
    proxy_cfg = parse_proxy(acc.get("proxy"))
    if not proxy_cfg:
        try:
            ip = _fetch_ip(None)
            return _step("proxy", "Proxy", None, f"Không dùng proxy, IP máy: {ip}")
        except Exception as e:  # noqa: BLE001
            return _step("proxy", "Proxy", None, f"Không dùng proxy; không hỏi được IP máy ({str(e)[:80]})")
    try:
        ip = _fetch_ip(_proxy_url(proxy_cfg))
        return _step("proxy", "Proxy", True, f"Proxy phản hồi, IP ra ngoài: {ip}")
    except Exception as e:  # noqa: BLE001
        return _step("proxy", "Proxy", False, f"Proxy '{mask_proxy(acc.get('proxy'))}' không phản hồi: {_scrub_proxy_secret(str(e), proxy_cfg)[:100]}")


def _proxy_password(proxy_cfg: Optional[dict]) -> Optional[str]:
    """Mật khẩu proxy từ cấu hình parse_proxy: cột `password` (dạng ip:port:user:pass) hoặc trong URL server."""
    if not proxy_cfg:
        return None
    pwd = proxy_cfg.get("password")
    if pwd:
        return pwd
    try:
        return urlparse(proxy_cfg.get("server", "")).password or None
    except ValueError:
        return None


def _scrub_proxy_secret(text: str, proxy_cfg: Optional[dict]) -> str:
    """Thay mật khẩu proxy (nếu thư viện mạng nhắc lại URL proxy trong thông điệp lỗi) bằng ***."""
    pwd = _proxy_password(proxy_cfg)
    if pwd and pwd in text:
        text = text.replace(pwd, "***")
    server = (proxy_cfg or {}).get("server") or ""
    if server and server in text:
        text = text.replace(server, mask_proxy(server))
    return text


def _check_chrome() -> dict:
    path = browser.find_chrome(refresh=True)
    if path:
        return _step("chrome", "Chrome", True, f"Tìm thấy Chrome: {path}")
    return _step("chrome", "Chrome", False,
                 "Không tìm thấy Chrome. Cài Google Chrome, hoặc điền chrome_path trong Cài đặt, hoặc chạy 'playwright install chromium'")


def _check_fb_cookie(acc: dict) -> dict:
    raw = acc.get("cookies")
    if not raw:
        return _step("fb_cookie", "Cookie Facebook", None, "Nick không có cookie Facebook (đăng nhập bằng mật khẩu/2FA hoặc cookie Dola)")
    try:
        cookies = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as e:
        return _step("fb_cookie", "Cookie Facebook", False, f"Cột cookies không phải JSON hợp lệ: {str(e)[:60]}")
    fb = [c for c in cookies if isinstance(c, dict) and "facebook" in str(c.get("domain", ""))]
    if not fb:
        return _step("fb_cookie", "Cookie Facebook", None, "Nick không có cookie Facebook")
    now = time.time()
    found = {}
    for c in fb:
        if c.get("name") in ("c_user", "xs") and c.get("value"):
            exp = c.get("expires", c.get("expirationDate"))
            try:
                expired = exp is not None and 0 < float(exp) < now
            except (TypeError, ValueError):
                expired = False
            found[c["name"]] = not expired
    missing = [n for n in ("c_user", "xs") if n not in found]
    if missing:
        return _step("fb_cookie", "Cookie Facebook", False, f"Thiếu cookie {', '.join(missing)}; cần dán lại cookie Facebook")
    expired = [n for n, alive in found.items() if not alive]
    if expired:
        return _step("fb_cookie", "Cookie Facebook", False, f"Cookie {', '.join(expired)} đã hết hạn")
    return _step("fb_cookie", "Cookie Facebook", True, f"Có c_user và xs còn hạn ({len(fb)} cookie Facebook)")


def _check_dola_session(acc: dict) -> dict:
    from dola_service import account_has_dola_session
    if account_has_dola_session(acc):
        return _step("dola_session", "Phiên Dola", True, "Có sessionid Dola còn hạn trong cookie/storage_state")
    return _step("dola_session", "Phiên Dola", False, "Chưa có phiên Dola: bấm Auto Login hoặc dán cookie Dola")


def _check_credits(account_id: int) -> dict:
    from dola_service import diagnose_account_dola
    res = diagnose_account_dola(account_id, pool_held=True)
    if res.get("captcha"):
        return _step("credits", "Credit Dola", False, res.get("detail") or "Dola yêu cầu kéo captcha")
    if not res.get("session_ok"):
        return _step("credits", "Credit Dola", False, res.get("detail") or "Trang Dola không nhận phiên")
    if not res.get("ok"):
        return _step("credits", "Credit Dola", False, res.get("detail") or "Không mở được trang Dola")
    if not res.get("credits_known"):
        return _step("credits", "Credit Dola", None, res.get("detail") or "Không đọc được số credit")
    credits = res.get("credits")
    return _step("credits", "Credit Dola", credits > 0, res.get("detail") or f"Còn {credits} credit")


def diagnose_account(account_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return {"success": False, "steps": [], "summary": f"Không tìm thấy nick #{account_id}"}
    acc = dict(row)

    pool = AccountPool.get()
    if not pool.acquire(account_id, None):
        holder = pool.holder(account_id)
        who = f"job #{holder}" if holder else "thao tác khác"
        return {"success": False, "steps": [], "summary": f"Nick '{acc['name']}' đang bận với {who}, thử lại sau"}

    steps = []
    try:
        log_event(f"Bắt đầu chẩn đoán nick #{account_id} ({acc['name']})", "INFO", "Diagnose", account_id=account_id)
        # Nick không bận (pool vừa giữ) nên được phép dọn Chrome mồ côi của profile này
        try:
            browser.kill_orphan_chrome(os.path.join(config.PROFILES_DIR, f"acc_{account_id}"))
        except Exception as e:  # noqa: BLE001
            log.debug("Dọn Chrome mồ côi lỗi: %s", e, extra={"account_id": account_id})

        checks = [
            ("proxy", lambda: _check_proxy(acc)),
            ("chrome", _check_chrome),
            ("fb_cookie", lambda: _check_fb_cookie(acc)),
            ("dola_session", lambda: _check_dola_session(acc)),
        ]
        names = {"proxy": "Proxy", "chrome": "Chrome", "fb_cookie": "Cookie Facebook", "dola_session": "Phiên Dola"}
        for key, fn in checks:
            try:
                steps.append(fn())
            except Exception as e:  # noqa: BLE001
                steps.append(_step(key, names[key], False, f"Bước kiểm tra lỗi: {str(e)[:120]}"))

        by_key = {s["key"]: s for s in steps}
        if by_key["dola_session"]["ok"] and by_key["chrome"]["ok"]:
            try:
                steps.append(_check_credits(account_id))
            except Exception as e:  # noqa: BLE001
                steps.append(_step("credits", "Credit Dola", False, f"Bước kiểm tra lỗi: {str(e)[:120]}"))
        else:
            why = "chưa có phiên Dola" if not by_key["dola_session"]["ok"] else "không có Chrome"
            steps.append(_step("credits", "Credit Dola", None, f"Bỏ qua vì {why}"))

        _persist(account_id, steps)
        failed = [s["name"] for s in steps if s["ok"] is False]
        passed = sum(1 for s in steps if s["ok"] is True)
        if failed:
            summary = f"{passed}/{len(steps)} bước đạt; lỗi: {', '.join(failed)}"
        else:
            summary = f"{passed}/{len(steps)} bước đạt, nick sẵn sàng" if passed else "Không có bước nào lỗi nhưng chưa xác nhận được credit"
        log_event(f"Chẩn đoán nick #{account_id}: {summary}", "WARNING" if failed else "INFO", "Diagnose", account_id=account_id)
        return {"success": not failed, "steps": steps, "summary": summary}
    finally:
        pool.release(account_id)


def _persist(account_id: int, steps: list) -> None:
    by_key = {s["key"]: s for s in steps}
    fields = {"last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    proxy = by_key.get("proxy")
    if proxy:
        ip = None
        for token in (proxy["detail"] or "").replace(",", " ").split():
            if token.count(".") == 3 and all(p.isdigit() for p in token.split(".")):
                ip = token
        if ip:
            fields["last_ip"] = ip
    chrome = by_key.get("chrome")
    if chrome:
        fields["chrome_ok"] = 1 if chrome["ok"] else 0
    failed = [s for s in steps if s["ok"] is False]
    fields["last_error"] = "; ".join(f"{s['name']}: {s['detail']}" for s in failed) if failed else None
    conn = get_connection()
    try:
        current = conn.execute("SELECT needs_manual FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if proxy and proxy["ok"] is False:
            fields["needs_manual"] = NeedsManual.PROXY
        elif current and current["needs_manual"] == NeedsManual.PROXY and proxy and proxy["ok"] is not False:
            fields["needs_manual"] = None
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", (*fields.values(), account_id))
        conn.commit()
    finally:
        conn.close()


def _mask(value) -> str:
    return "***" if value else ""


def _scrub_last_error(text: str, accounts_proxy=None) -> str:
    """Che chuỗi proxy gốc và mật khẩu proxy nếu lọt vào last_error (BH-33)."""
    from dola_service import parse_proxy
    text = str(text)
    if accounts_proxy:
        raw = str(accounts_proxy).strip()
        if raw and raw in text:
            text = text.replace(raw, mask_proxy(raw))
        text = _scrub_proxy_secret(text, parse_proxy(raw))
    return text


def build_bundle() -> str:
    """Tạo zip chẩn đoán trong LOGS_DIR và trả về đường dẫn."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_path = os.path.join(config.LOGS_DIR, f"chan_doan_{stamp}.zip")
    cutoff = time.time() - 24 * 3600

    conn = get_connection()
    try:
        settings = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings").fetchall()}
        accounts = [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()]
        jobs = [dict(r) for r in conn.execute(
            "SELECT id, batch_id, batch_name, seq, status, status_message, progress, attempts, account_id, "
            "started_at, finished_at, created_at, updated_at FROM jobs ORDER BY id DESC LIMIT 500").fetchall()]
    finally:
        conn.close()

    safe_settings = {k: v for k, v in settings.items() if not any(w in k.lower() for w in SENSITIVE_SETTING_WORDS)}
    safe_accounts = []
    for a_raw in accounts:
        a = dict(a_raw)
        for secret in ("fb_pass", "fb_2fa", "cookies", "otp_key"):
            if secret in a:
                a[secret] = _mask(a[secret])
        # BH-33: proxy và last_error có thể chứa user:pass của proxy
        if "proxy" in a:
            a["proxy"] = mask_proxy(a["proxy"])
        if a.get("last_error"):
            a["last_error"] = _scrub_last_error(a["last_error"], accounts_proxy=a_raw.get("proxy"))
        safe_accounts.append(a)

    info = {
        "version": config.VERSION,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "chrome_path": browser.find_chrome(),
        "dola_base_url": config.DOLA_BASE_URL,
        "data_dir": config.DATA_DIR,
        "active_browsers": browser.active_count(),
        "max_browsers": browser.capacity(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("thong_tin.json", json.dumps(info, ensure_ascii=False, indent=2))
        zf.writestr("settings.json", json.dumps(safe_settings, ensure_ascii=False, indent=2))
        zf.writestr("accounts.json", json.dumps(safe_accounts, ensure_ascii=False, indent=2, default=str))
        zf.writestr("jobs.json", json.dumps(jobs, ensure_ascii=False, indent=2, default=str))
        for path in glob.glob(os.path.join(config.LOGS_DIR, "studio_*.log")):
            try:
                if os.path.getmtime(path) >= cutoff:
                    zf.write(path, os.path.join("logs", os.path.basename(path)))
            except OSError as e:
                log.debug("Bỏ qua file log %s: %s", path, e)
        if os.path.isdir(config.SCREENSHOTS_DIR):
            for name in os.listdir(config.SCREENSHOTS_DIR):
                path = os.path.join(config.SCREENSHOTS_DIR, name)
                try:
                    if os.path.isfile(path) and os.path.getmtime(path) >= cutoff:
                        zf.write(path, os.path.join("screenshots", name))
                except OSError as e:
                    log.debug("Bỏ qua ảnh %s: %s", path, e)

    log_event(f"Đã tạo gói chẩn đoán {os.path.basename(bundle_path)}", "INFO", "Diagnose")
    return bundle_path
