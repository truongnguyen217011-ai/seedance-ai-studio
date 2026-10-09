"""
Test API qua TestClient (không chạy lifespan → không khởi động worker, không mở Chrome):
BH-31 (chỉ mount /logs/screenshots), N-1 (Muse không còn hỗ trợ), N-2 (không xóa job đang chạy).
"""
from __future__ import annotations

import os
import pathlib

import pytest

from constants import JobStatus

ROOT = pathlib.Path(__file__).resolve().parent.parent

fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="cần fastapi + httpx (requirements-dev.txt)")


@pytest.fixture
def client(db):
    import app as app_module
    return fastapi_testclient.TestClient(app_module.app)


# ---------------------------------------------------------------- BH-31
def test_bh31_screenshots_served_but_logs_not(client, env_tmp):
    import config
    os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
    png = os.path.join(config.SCREENSHOTS_DIR, "job_failed_1_test.png")
    with open(png, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    log_path = os.path.join(config.LOGS_DIR, "studio_test-bh31.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("nick 'bi mat' proxy 1.2.3.4:8080:user:pass\n")
    try:
        r = client.get("/logs/screenshots/job_failed_1_test.png")
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"\x89PNG")

        r = client.get("/logs/studio_test-bh31.log")
        assert r.status_code == 404, "BH-31: file log không được lộ qua web"
        r = client.get("/logs/")
        assert r.status_code == 404
        r = client.get("/logs/screenshots/../studio_test-bh31.log")
        assert r.status_code in (400, 404)
    finally:
        for p in (png, log_path):
            try:
                os.remove(p)
            except OSError:
                pass


def test_bh31_no_broad_logs_mount():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'app.mount("/logs"' not in src, "BH-31: không mount cả /logs (lộ file log)"
    assert 'app.mount("/logs/screenshots"' in src
    assert "config.SCREENSHOTS_DIR" in src
    js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "/logs/screenshots/" in js


# ---------------------------------------------------------------- N-1
def test_n1_muse_routes_unsupported(client, db):
    acc_id = db.add_account("nick muse")
    for path in ("/api/accounts/login_muse", "/api/accounts/check_muse_token"):
        r = client.post(path, json={"account_id": acc_id})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["success"] is False
        assert "Muse AI không còn được hỗ trợ" in data["message"], data
    import re
    for name in ("app.py", "worker.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import muse_service|from muse_service)", src, re.MULTILINE), f"{name} vẫn import muse_service"


# ---------------------------------------------------------------- N-2
def test_n2_delete_running_job_refused(client, db):
    import worker
    acc_id = db.add_account("nick chạy")
    running = db.add_job("job đang chạy", status=JobStatus.DANG_CHAY, account_id=acc_id)
    r = client.delete(f"/api/jobs/{running}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is False
    assert "đang chạy" in data["message"].lower() and "không xóa" in data["message"], data
    assert db.job(running) is not None, "job đang chạy đã bị xóa"

    # job còn trong worker.running_job_ids() (CSDL chưa kịp cập nhật) cũng không xóa được
    pending = db.add_job("job vừa điều phối", status=JobStatus.CHO)
    worker._running_jobs.add(pending)
    try:
        r = client.delete(f"/api/jobs/{pending}")
        assert r.json()["success"] is False
        assert db.job(pending) is not None
    finally:
        worker._running_jobs.discard(pending)

    # job Chờ bình thường thì xóa được
    r = client.delete(f"/api/jobs/{pending}")
    assert r.json()["success"] is True, r.text
    assert db.job(pending) is None

    r = client.delete("/api/jobs/999999")
    assert r.json()["success"] is False


def test_n2_frontend_shows_delete_refusal():
    js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    start = js.index("async function deleteJob(")
    body = js[start:start + 900]
    assert "data.success === false" in body and "showToast(" in body and "data.message" in body, body


# ---------------------------------------------------------------- N-8: /api/health vẫn trả đủ trường sau khi đổi executor
def test_health_contract(client):
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("ok", "db_ok", "chrome_found", "chrome_path", "active_browsers", "max_browsers", "worker_alive", "version"):
        assert key in data, (key, data)
    assert data["db_ok"] is True
    assert data["worker_alive"] is False  # TestClient không chạy lifespan → worker chưa khởi động
