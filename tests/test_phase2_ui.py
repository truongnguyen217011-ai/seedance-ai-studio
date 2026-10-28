"""
Giao diện với dữ liệu giả qua Playwright `page.route` (không cần server): BH-58 — dropdown chọn nick phải có đủ
mọi nick (60) dù bảng nick chỉ hiện trang 50 đầu. CDN (Tailwind, lucide) bị chặn như BH-19.
"""
from __future__ import annotations

import json
import os
import pathlib
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHROME = os.environ.get("SEEDANCE_CHROME_PATH")
N_ACCOUNTS = 60
PAGE_SIZE = 50


def _fake_account(i: int) -> dict:
    return {
        "id": i, "name": f"nick số {i}", "account_type": "google" if i % 10 == 0 else "facebook", "email": None,
        "fb_uid": f"1000{i:011d}", "proxy": "", "status": "ready", "credits": None, "credits_today": None,
        "credits_date": None, "last_used": None, "last_check": None, "has_dola": True, "has_pass": True,
        "has_2fa": False, "has_cookies": True, "fb_pass_masked": "••••••••", "is_resting": False, "is_busy": False,
        "busy_job_id": None, "needs_manual": None, "last_error": None, "last_ip": None, "rest_until": None,
    }


def _route_handler(route):
    url = urlparse(route.request.url)
    path = url.path
    if url.hostname != "seedance.test":
        return route.abort()   # CDN Tailwind/lucide bị chặn: app.js vẫn phải chạy (BH-19)
    if path == "/":
        return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                             body=(ROOT / "static/index.html").read_text(encoding="utf-8"))
    if path.startswith("/static/js/app.js"):
        return route.fulfill(status=200, content_type="application/javascript; charset=utf-8",
                             body=(ROOT / "static/js/app.js").read_text(encoding="utf-8"))
    body: dict
    if path == "/api/accounts/names":
        body = {"accounts": [{"id": i, "name": f"nick số {i}", "account_type": "google" if i % 10 == 0 else "facebook"}
                             for i in range(N_ACCOUNTS, 0, -1)], "total": N_ACCOUNTS}
    elif path == "/api/accounts":
        body = {"accounts": [_fake_account(i) for i in range(N_ACCOUNTS, N_ACCOUNTS - PAGE_SIZE, -1)],
                "total": N_ACCOUNTS, "limit": PAGE_SIZE, "offset": 0}
    elif path == "/api/jobs":
        body = {"jobs": []}
    elif path == "/api/stats":
        body = {"total_jobs": 0, "completed": 0, "running": 0, "pending": 0, "failed": 0, "total_accounts": N_ACCOUNTS}
    elif path == "/api/health":
        body = {"ok": True, "db_ok": True, "chrome_found": True, "chrome_path": "/x", "active_browsers": 0,
                "max_browsers": 6, "worker_alive": True, "version": "test"}
    elif path == "/api/settings":
        body = {}
    elif path == "/api/accounts/scan-status":
        body = {"running": False, "done": 0, "total": 0, "summary": {}, "current": [], "results": {}}
    elif path == "/api/logs":
        body = {"logs": []}
    else:
        body = {}
    return route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


@pytest.mark.timeout(90)
def test_bh58_nick_dropdowns_list_every_account_not_only_first_page():
    with sync_playwright() as p:
        kw = {"headless": True, "args": ["--no-sandbox"]}
        if CHROME:
            kw["executable_path"] = CHROME
        browser = p.chromium.launch(**kw)
        try:
            page = browser.new_page()
            page.route("**/*", _route_handler)
            page.goto("http://seedance.test/", wait_until="domcontentloaded")
            page.wait_for_function(
                f"document.querySelectorAll('#filterNickMediaSelect option').length >= {N_ACCOUNTS + 1}", timeout=20000)
            n_filter = page.evaluate("document.querySelectorAll('#filterNickMediaSelect option').length")
            n_image = page.evaluate("document.querySelectorAll('#imageAccountSelect option').length")
            assert n_filter == N_ACCOUNTS + 1, f"dropdown lọc ảnh/video có {n_filter - 1} nick, cần {N_ACCOUNTS}"
            assert n_image == N_ACCOUNTS + 1, f"dropdown chọn nick tạo ảnh có {n_image - 1} nick, cần {N_ACCOUNTS}"
            # nick số 1 nằm ngoài trang 50 đầu của bảng nhưng vẫn phải có trong dropdown
            assert page.evaluate("!!document.querySelector('#filterNickMediaSelect option[value=\"1\"]')")
            assert page.evaluate("!!document.querySelector('#imageAccountSelect option[value=\"1\"]')")
            # bảng vẫn chỉ hiện trang 50
            page.wait_for_function("document.querySelectorAll('#accountsTableBody tr').length >= 50", timeout=20000)
            assert page.evaluate("document.querySelectorAll('#accountsTableBody tr').length") == PAGE_SIZE
            # lựa chọn người dùng được giữ qua các lần làm mới (refreshData mỗi 3 s)
            page.select_option("#filterNickMediaSelect", "1")
            page.wait_for_timeout(3500)
            assert page.evaluate("document.getElementById('filterNickMediaSelect').value") == "1"
        finally:
            browser.close()
