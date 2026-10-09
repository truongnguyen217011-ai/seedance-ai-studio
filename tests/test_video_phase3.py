"""
Kiểm thử Giai đoạn 3: Tạo video & Tương tác Dola chuyên sâu (T1–T5).
- T1: Đính kèm ảnh tham chiếu (reference_image) khi file tồn tại, bỏ qua an toàn khi file không tồn tại.
- T2: Xác thực tính hợp lệ của file video tải về (_is_valid_video_file): loại bỏ file nhỏ (<50KB), từ chối phản hồi lỗi HTML/JSON giả dạng mp4.
- T3: Tự động dọn dẹp file hỏng nếu quá trình tải thất bại (_download_video).
- T4: Truyền header Cookie của nick khi tải video từ host Dola.
- T5: Endpoint /api/download-video và /api/jobs/{id}/stream phục vụ video chính xác.
"""
from __future__ import annotations

import os
import pathlib
import pytest

import config
from database import get_connection
import dola_service

fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="cần fastapi + httpx (requirements-dev.txt)")


@pytest.fixture
def client(db):
    import app as app_module
    return fastapi_testclient.TestClient(app_module.app)


def test_t1_reference_image_attached_when_file_exists(tmp_path):
    img_file = tmp_path / "character.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    class FakeLocator:
        def __init__(self):
            self.uploaded = []
        def count(self):
            return 1
        @property
        def first(self):
            return self
        def set_input_files(self, path):
            self.uploaded.append(path)

    fake_locator = FakeLocator()

    class FakePage:
        def locator(self, selector):
            return fake_locator

    page = FakePage()

    # 1. File tồn tại -> đính kèm thành công
    res = dola_service._attach_reference_image(page, str(img_file), job_id=101)
    assert res is True
    assert fake_locator.uploaded == [str(img_file)]

    # 2. File không tồn tại -> trả về False an toàn, không raise
    res_missing = dola_service._attach_reference_image(page, str(tmp_path / "non_existent.png"), job_id=102)
    assert res_missing is False

    # 3. Đường dẫn rỗng -> trả về False
    assert dola_service._attach_reference_image(page, "", job_id=103) is False


def test_t2_video_file_validation(tmp_path):
    # 1. File không tồn tại
    assert dola_service._is_valid_video_file(str(tmp_path / "none.mp4")) is False

    # 2. File nhỏ (< 50KB)
    small_file = tmp_path / "small.mp4"
    small_file.write_bytes(b"small video content" * 100)
    assert dola_service._is_valid_video_file(str(small_file)) is False

    # 3. File lớn (> 50KB) nhưng là trang HTML lỗi Cloudflare/CDN 403
    html_file = tmp_path / "fake_html.mp4"
    html_content = b"<!DOCTYPE html><html><head><title>403 Forbidden</title></head><body>Error</body></html>"
    html_file.write_bytes(html_content + b" " * 60000)
    assert dola_service._is_valid_video_file(str(html_file)) is False

    # 4. File lớn (> 50KB) nhưng là JSON error
    json_file = tmp_path / "fake_json.mp4"
    json_file.write_bytes(b'{"error": "unauthorized", "message": "token expired"}' + b" " * 60000)
    assert dola_service._is_valid_video_file(str(json_file)) is False

    # 5. File FAKEMP4 hợp lệ (> 50KB)
    fake_mp4 = tmp_path / "valid_fake.mp4"
    fake_mp4.write_bytes(b"FAKEMP4;conv=123;" + b"\x00" * 60000)
    assert dola_service._is_valid_video_file(str(fake_mp4)) is True

    # 6. File MP4 thật hợp lệ chứa ftyp box
    real_mp4 = tmp_path / "real.mp4"
    real_mp4.write_bytes(b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 60000)
    assert dola_service._is_valid_video_file(str(real_mp4)) is True


def test_t3_download_video_cleans_corrupt_files(tmp_path, monkeypatch):
    import io
    dest = tmp_path / "video_test_corrupt.mp4"

    class FakeResponse(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    bad_data = b"<!DOCTYPE html><html>403 Access Denied</html>" + b" " * 60000
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=120: FakeResponse(bad_data))

    ok = dola_service._download_video("http://example.com/video.mp4", str(dest), job_id=202)
    assert ok is False
    assert not dest.exists(), "File video lỗi phải bị xóa sạch khỏi thư mục đích"


def test_t4_download_video_cookie_header(tmp_path, monkeypatch):
    import io
    dest = tmp_path / "video_test_cookie.mp4"
    captured_headers = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    valid_data = b"FAKEMP4;conv=999;" + b"\x00" * 60000

    def fake_urlopen(req, timeout=120):
        captured_headers.update(req.headers)
        return FakeResponse(valid_data)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    cookies = [
        {"name": "sessionid", "value": "my_secret_session_token"},
        {"name": "sessionid_ss", "value": "my_secret_session_token"}
    ]

    ok = dola_service._download_video("http://example.com/video.mp4", str(dest), job_id=303, cookies_list=cookies)
    assert ok is True
    assert "Cookie" in captured_headers or "cookie" in captured_headers
    cookie_str = captured_headers.get("Cookie") or captured_headers.get("cookie")
    assert "sessionid=my_secret_session_token" in cookie_str


def test_t5_download_and_stream_endpoints(client, db):
    # Tạo video giả lập trong OUTPUTS_DIR
    os.makedirs(config.OUTPUTS_DIR, exist_ok=True)
    video_filename = "video_9999.mp4"
    video_path = os.path.join(config.OUTPUTS_DIR, video_filename)
    with open(video_path, "wb") as f:
        f.write(b"FAKEMP4;test_endpoint;" + b"\x00" * 60000)

    try:
        # 1. Download video qua /api/download-video/{filename}
        res_dl = client.get(f"/api/download-video/{video_filename}")
        assert res_dl.status_code == 200
        assert res_dl.headers.get("content-type") == "video/mp4"
        assert f'filename="{video_filename}"' in res_dl.headers.get("content-disposition", "")

        # 2. File không tồn tại -> 404
        res_missing = client.get("/api/download-video/non_existent_99999.mp4")
        assert res_missing.status_code == 404

        # 3. Stream video qua /api/jobs/{id}/stream
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO jobs (id, title, prompt, local_video_path, status) VALUES (9999, 'Stream Job', 'Prompt', ?, 'Hoàn thành')",
                           (f"/outputs/{video_filename}",))
            conn.commit()
        finally:
            conn.close()

        res_stream = client.get("/api/jobs/9999/stream")
        assert res_stream.status_code == 200
        assert res_stream.headers.get("content-type") == "video/mp4"

        # Stream job không có video -> 404
        res_no_stream = client.get("/api/jobs/8888/stream")
        assert res_no_stream.status_code == 404
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
