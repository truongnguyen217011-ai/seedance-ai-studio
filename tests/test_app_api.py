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


# ---------------------------------------------------------------- Giai đoạn 4: Đạo diễn AI (director.py, BH-41)
def _add_asset(db, name, code, desc):
    return db.exec("INSERT INTO assets (name, character_code, image_url, description, tags) VALUES (?, ?, '', ?, '')",
                   (name, code, desc))


def test_director_preview_returns_composed_prompts_without_creating_jobs(client, db):
    _add_asset(db, "Tiểu Vũ", "TV01", "cô gái 20 tuổi áo dài trắng")
    r = client.post("/api/director/preview", json={
        "prompts": ["Tiểu Vũ nói chuyện với mẹ trong bếp", "", "Cao bồi cưỡi ngựa qua sa mạc"],
        "duration": "15 giây", "model": "Seedance 2.5",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True and data["director_enabled"] is True
    items = data["items"]
    assert [it["prompt"] for it in items] == ["Tiểu Vũ nói chuyện với mẹ trong bếp", "Cao bồi cưỡi ngựa qua sa mạc"]
    assert items[0]["archetype_code"] == "T1" and items[0]["characters"] == ["Tiểu Vũ"]
    assert "Nhân vật: Tiểu Vũ: cô gái 20 tuổi áo dài trắng." in items[0]["prompt_final"]
    assert items[0]["prompt_final"].startswith("Tạo video Seedance 2.5 dài 15 giây. Tiểu Vũ nói chuyện với mẹ trong bếp.")
    assert items[1]["archetype_code"] == "W1"
    assert db.jobs() == [], "preview không được tạo job"

    # ép trường phái cho cả lô
    r = client.post("/api/director/preview", json={"prompts": ["Cao bồi cưỡi ngựa"], "style_code": "F1"})
    assert r.json()["items"][0]["archetype_code"] == "F1"
    # mã lạ → lỗi tiếng Việt, không 500
    r = client.post("/api/director/preview", json={"prompts": ["x"], "style_code": "ZZ9"})
    assert r.status_code == 200 and r.json()["success"] is False
    assert "không có trong bộ mẫu" in r.json()["message"]
    # tắt đạo diễn theo yêu cầu → chỉ câu mở đầu + prompt
    r = client.post("/api/director/preview", json={"prompts": ["Cao bồi cưỡi ngựa"], "director": False})
    it = r.json()["items"][0]
    assert it["prompt_final"] == "Tạo video Seedance 2.5 dài 30 giây. Cao bồi cưỡi ngựa." and it["archetype_code"] == ""


def test_batch_jobs_store_prompt_final_and_archetype(client, db):
    _add_asset(db, "Lão Trần", "LT02", "ông lão râu bạc")
    db.set_setting("director_default_style", "")
    r = client.post("/api/jobs/batch", json={
        "prompts": ["01. Lão Trần chống gậy qua đồng lúa", "Bão biển cuồng nộ"], "model": "Seedance 2.5", "duration": "30 giây",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True and data["created"] == 2
    assert [j["archetype"] for j in data["jobs"]] == ["Cine-Master", "A1"]
    rows = db.jobs()
    assert len(rows) == 2
    assert rows[0]["prompt"] == "01. Lão Trần chống gậy qua đồng lúa"
    assert rows[0]["prompt_final"] == data["jobs"][0]["prompt_final"]
    assert rows[0]["prompt_final"].startswith("Tạo video Seedance 2.5 dài 30 giây. Lão Trần chống gậy qua đồng lúa. Nhân vật: Lão Trần: ông lão râu bạc.")
    assert rows[0]["archetype_code"] == "Cine-Master" and rows[1]["archetype_code"] == "A1"
    assert "Hollywood blockbuster action masterpiece" not in rows[0]["prompt_final"]

    # style_code ép cho cả lô + director=False bỏ qua mẫu
    r = client.post("/api/jobs/batch", json={"prompts": ["Cảnh phố"], "style_code": "C2"})
    assert db.job(r.json()["jobs"][0]["id"])["archetype_code"] == "C2"
    r = client.post("/api/jobs/batch", json={"prompts": ["Cảnh phố"], "director": False})
    j = db.job(r.json()["jobs"][0]["id"])
    assert j["archetype_code"] == "" and j["prompt_final"] == "Tạo video Seedance 2.5 dài 30 giây. Cảnh phố."

    # setting director_enabled=0 → mặc định tắt cho job đơn lẻ
    db.set_setting("director_enabled", "0")
    r = client.post("/api/jobs", json={"prompt": "Cô gái cười", "duration": "15 giây"})
    j = db.job(r.json()["id"])
    assert j["prompt_final"] == "Tạo video Seedance 2.5 dài 15 giây. Cô gái cười."
    db.set_setting("director_enabled", "1")
    r = client.post("/api/jobs", json={"prompt": "Cô gái cười", "duration": "15 giây"})
    j = db.job(r.json()["id"])
    assert j["archetype_code"] == "P1" and "85mm Portrait Lens" in j["prompt_final"]


def test_put_prompt_final_refused_while_running(client, db):
    import worker
    acc_id = db.add_account("nick chạy")
    running = db.add_job("đang chạy", status=JobStatus.DANG_CHAY, account_id=acc_id, prompt_final="cũ")
    r = client.put(f"/api/jobs/{running}/prompt_final", json={"prompt_final": "mới"})
    assert r.status_code == 200, r.text
    assert r.json()["success"] is False
    assert "đang ở trạng thái 'Đang chạy'" in r.json()["message"] and "không sửa được" in r.json()["message"]
    assert db.job(running)["prompt_final"] == "cũ"

    done = db.add_job("xong", status=JobStatus.HOAN_THANH, prompt_final="cũ")
    assert client.put(f"/api/jobs/{done}/prompt_final", json={"prompt_final": "mới"}).json()["success"] is False

    waiting = db.add_job("chờ", status=JobStatus.CHO, prompt_final="cũ")
    worker._running_jobs.add(waiting)   # vừa điều phối, CSDL chưa kịp đổi trạng thái
    try:
        assert client.put(f"/api/jobs/{waiting}/prompt_final", json={"prompt_final": "mới"}).json()["success"] is False
    finally:
        worker._running_jobs.discard(waiting)

    for status in (JobStatus.CHO, JobStatus.THAT_BAI, JobStatus.TAM_DUNG):
        jid = db.add_job("sửa được", status=status, prompt_final="cũ")
        r = client.put(f"/api/jobs/{jid}/prompt_final", json={"prompt_final": "  prompt người dùng sửa tay  "})
        assert r.json()["success"] is True, (status, r.text)
        assert db.job(jid)["prompt_final"] == "prompt người dùng sửa tay"
    assert client.put(f"/api/jobs/{jid}/prompt_final", json={"prompt_final": "   "}).json()["success"] is False
    assert client.put("/api/jobs/999999/prompt_final", json={"prompt_final": "x"}).json()["success"] is False


def test_settings_expose_director_keys(client, db):
    s = client.get("/api/settings").json()
    for k in ("director_enabled", "director_layer_camera", "director_layer_lighting", "director_layer_palette",
              "director_layer_character", "director_default_style"):
        assert k in s, k
    r = client.post("/api/settings", json={"director_layer_palette": "0", "director_default_style": "S1"})
    assert r.json()["success"] is True
    s = client.get("/api/settings").json()
    assert s["director_layer_palette"] == "0" and s["director_default_style"] == "S1"
    it = client.post("/api/director/preview", json={"prompts": ["Chiếc xe qua cầu"]}).json()["items"][0]
    assert it["archetype_code"] == "S1" and "palette" not in it["layers_added"]


def test_jobs_api_returns_archetype_code_and_frontend_uses_it(client, db):
    jid = db.add_job("x", prompt_final="pf", archetype_code="F1")
    jobs = client.get("/api/jobs").json()["jobs"]
    assert jobs[0]["id"] == jid and jobs[0]["archetype_code"] == "F1" and jobs[0]["prompt_final"] == "pf"
    js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "j.archetype_code" in js and "openJobPromptModal(" in js and "/prompt_final" in js
    assert "/api/director/preview" in js
    # BH-41: giao diện không còn tự ghép mẫu bằng JS rồi ghi đè ô nhập
    start = js.index("function autoDetectAndEnhanceBructa(")
    body = js[start:start + 400]
    assert "previewDirectorPrompts" in body and "textarea.value =" not in body
