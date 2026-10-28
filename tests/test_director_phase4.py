"""
Kiểm thử Giai đoạn 4: Đạo diễn AI & Quản lý lô nâng cao (Director AI Phase 4).
- Endpoint GET /api/director/styles trả về 14 trường phái điện ảnh.
- POST /api/jobs/batch hỗ trợ batch_name và gán đúng vào CSDL.
- PUT /api/jobs/{id}/prompt_final cho phép sửa khi job Chờ/Tạm dừng/Thất bại và từ chối khi Đang chạy.
- POST /api/director/preview hiển thị đầy đủ các lớp và nhân vật.
"""
from __future__ import annotations

import pytest

from constants import JobStatus
from database import get_connection
import director

fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="cần fastapi + httpx (requirements-dev.txt)")


@pytest.fixture
def client(db):
    import app as app_module
    return fastapi_testclient.TestClient(app_module.app)


def test_get_director_styles_endpoint(client):
    res = client.get("/api/director/styles")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "styles" in data
    styles = data["styles"]
    assert len(styles) == 14
    codes = [s["code"] for s in styles]
    assert codes[0] == "T1"
    assert "Cine-Master" in codes
    assert "F1" in codes
    assert "F2" in codes


def test_batch_jobs_with_batch_name(client, db):
    res = client.post("/api/jobs/batch", json={
        "prompts": ["Cảnh 1 chiến binh", "Cảnh 2 phù thủy"],
        "batch_name": "Lô Hành Động Phép Thuật",
        "duration": "15 giây",
        "ratio": "16:9"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["created"] == 2
    assert data["batch_name"] == "Lô Hành Động Phép Thuật"

    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, seq, batch_name, prompt, prompt_final, duration, ratio FROM jobs ORDER BY id ASC").fetchall()
        assert len(rows) >= 2
        j1, j2 = rows[-2], rows[-1]
        assert j1["seq"] == 1
        assert j2["seq"] == 2
        assert j1["batch_name"] == "Lô Hành Động Phép Thuật"
        assert j2["batch_name"] == "Lô Hành Động Phép Thuật"
        assert "Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang)" in j1["prompt_final"]
    finally:
        conn.close()


def test_update_prompt_final_and_rejections(client, db):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO jobs (title, prompt, prompt_final, status) VALUES ('Job1', 'Prompt1', 'PromptFinal1', ?)",
                       (JobStatus.CHO,))
        id_waiting = cursor.lastrowid
        cursor.execute("INSERT INTO jobs (title, prompt, prompt_final, status) VALUES ('Job2', 'Prompt2', 'PromptFinal2', ?)",
                       (JobStatus.DANG_CHAY,))
        id_running = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    # 1. Sửa khi job Chờ -> thành công
    res_ok = client.put(f"/api/jobs/{id_waiting}/prompt_final", json={"prompt_final": "Prompt đã sửa tay"})
    assert res_ok.status_code == 200
    assert res_ok.json()["success"] is True

    conn = get_connection()
    try:
        row = conn.execute("SELECT prompt_final FROM jobs WHERE id = ?", (id_waiting,)).fetchone()
        assert row["prompt_final"] == "Prompt đã sửa tay"
    finally:
        conn.close()

    # 2. Sửa khi job Đang chạy -> từ chối
    res_refused = client.put(f"/api/jobs/{id_running}/prompt_final", json={"prompt_final": "Prompt cố sửa"})
    assert res_refused.status_code == 200
    assert res_refused.json()["success"] is False
    assert "Đang chạy" in res_refused.json()["message"]

    # 3. Sửa chuỗi rỗng -> từ chối
    res_empty = client.put(f"/api/jobs/{id_waiting}/prompt_final", json={"prompt_final": "   "})
    assert res_empty.status_code == 200
    assert res_empty.json()["success"] is False
    assert "không được để trống" in res_empty.json()["message"]


def test_director_preview_with_assets_and_style_override(client, db):
    # Thêm nhân vật vào kho assets
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO assets (name, character_code, description) VALUES ('Linh Đan', 'NV01', 'cô gái tóc ngắn cá tính')")
        conn.commit()
    finally:
        conn.close()

    res = client.post("/api/director/preview", json={
        "prompts": ["Hai người Linh Đan và bạn trò chuyện trong quán trà"],
        "style_code": "T1",
        "duration": "10 giây",
        "ratio": "9:16"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["archetype_code"] == "T1"
    assert "Linh Đan" in item["characters"]
    assert "Nhân vật: Linh Đan: cô gái tóc ngắn cá tính" in item["prompt_final"]
    assert "dài 10 giây, tỷ lệ khung hình 9:16 (dọc)" in item["prompt_final"]
