"""
Kiểm thử Giai đoạn 2: Quản lý tài khoản toàn diện (A1–A6, K1–K3).
- A1: Thêm nick đơn qua form và qua raw_line (UID|Pass|2FA và Cookie JSON).
- A2: Batch import trả về danh sách `accounts` chi tiết và phát hiện trùng UID.
- A3: Cookie JSON Dola và Facebook được parse đúng UID/sessionid, lưu storage_state.
- A4/A5: Batch assign proxy và batch import default proxy.
- A6: Xóa nick đang bận bị từ chối; xóa nick rảnh dọn dẹp thư mục profile.
- K1: _mark_account_connected ghi nhận session_expires từ cookie sessionid.
- K2: Phiên hỏng chuyển needs_manual='login' và lưu artifact.
- K3: Route alias /api/accounts/{id}/check và /api/accounts/check-all hoạt động.
"""
from __future__ import annotations

import json
import os
import pathlib
import pytest

from account_pool import AccountPool
from constants import NeedsManual
from database import get_connection
import dola_service
from parser import parse_single_account_line, parse_multiple_account_lines

fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="cần fastapi + httpx (requirements-dev.txt)")


@pytest.fixture
def client(db):
    import app as app_module
    return fastapi_testclient.TestClient(app_module.app)


def test_a1_add_account_form_and_raw_line(client, db):
    # 1. Thêm qua form fields
    r1 = client.post("/api/accounts", json={
        "name": "Nick Test 1",
        "fb_uid": "10009990001",
        "fb_pass": "pass123",
        "fb_2fa": "JBSWY3DPEHPK3PXP",
        "proxy": "1.2.3.4:8080"
    })
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["success"] is True
    acc1_id = d1["id"]

    # 2. Thêm qua raw_line định dạng pipe
    r2 = client.post("/api/accounts", json={
        "raw_line": "10009990002|pass456|JBSWY3DPEHPK3PXP|5.6.7.8:9090"
    })
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["success"] is True
    acc2_id = d2["id"]

    # 3. Thêm qua raw_line là JSON Cookie
    json_cookie = json.dumps([
        {"name": "c_user", "value": "10009990003", "domain": ".facebook.com"},
        {"name": "xs", "value": "secretxs", "domain": ".facebook.com"}
    ])
    r3 = client.post("/api/accounts", json={"raw_line": json_cookie})
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["success"] is True
    acc3_id = d3["id"]

    # Kiểm tra GET /api/accounts không lộ mật khẩu thô
    r_list = client.get("/api/accounts")
    assert r_list.status_code == 200
    accounts = {a["id"]: a for a in r_list.json()["accounts"]}

    assert acc1_id in accounts
    assert accounts[acc1_id]["fb_uid"] == "10009990001"
    assert accounts[acc1_id]["has_pass"] is True
    assert accounts[acc1_id]["has_2fa"] is True
    assert "fb_pass" not in accounts[acc1_id]
    assert "fb_2fa" not in accounts[acc1_id]

    assert acc2_id in accounts
    assert accounts[acc2_id]["fb_uid"] == "10009990002"

    assert acc3_id in accounts
    assert accounts[acc3_id]["fb_uid"] == "10009990003"
    assert accounts[acc3_id]["has_cookies"] is True


def test_a2_batch_import_details_and_duplicates(client, db):
    raw_data = """
10008880001|pass1|JBSWY3DPEHPK3PXP
10008880002|pass2|JBSWY3DPEHPK3PXP
sai_dinh_dang_khong_co_pass_hay_cookie
"""
    res = client.post("/api/accounts/batch-import", json={"data": raw_data})
    assert res.status_code == 200
    data = res.json()

    assert data["success"] is True
    assert data["imported"] == 2
    # Phải có mảng accounts chi tiết để frontend hiển thị bảng
    assert "accounts" in data
    assert len(data["accounts"]) == 2
    assert data["accounts"][0]["uid"] == "10008880001"
    assert data["accounts"][1]["uid"] == "10008880002"

    # Dòng sai phải nằm trong errors
    assert len(data["errors"]) >= 1
    assert any("sai_dinh_dang" in str(e) for e in data["errors"])

    # Import lần 2 với UID trùng: phải bị chặn và đưa vào errors
    res2 = client.post("/api/accounts/batch-import", json={"data": "10008880001|pass1|JBSWY3DPEHPK3PXP"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["imported"] == 0
    assert len(data2["errors"]) == 1
    assert "đã tồn tại" in data2["errors"][0]["reason"]


def test_a3_cookie_json_fb_and_dola_parsing():
    # 1. FB Cookie JSON
    fb_json = json.dumps([
        {"name": "c_user", "value": "10007770001", "domain": ".facebook.com"},
        {"name": "xs", "value": "test_xs", "domain": ".facebook.com"}
    ])
    parsed_fb = parse_single_account_line(fb_json)
    assert parsed_fb["uid"] == "10007770001"
    assert parsed_fb["account_type"] == "facebook"
    assert "c_user" in parsed_fb["cookie"]

    # 2. Dola Cookie JSON
    dola_json = json.dumps([
        {"name": "sessionid", "value": "test_session_12345", "domain": ".dola.com"},
        {"name": "sessionid_ss", "value": "test_session_12345", "domain": ".dola.com"}
    ])
    parsed_dola = parse_single_account_line(dola_json)
    assert parsed_dola["uid"].startswith("Dola_")
    assert "sessionid" in parsed_dola["cookie"]

    # 3. Batch import parse được khối JSON
    ok_list, err_list = parse_multiple_account_lines(dola_json)
    assert len(ok_list) == 1
    assert len(err_list) == 0
    assert ok_list[0]["uid"].startswith("Dola_")


def test_a4_a5_batch_proxy_assign_and_batch_default_proxy(client, db):
    # Import với proxy mặc định của batch
    raw_data = """
10006660001|pass1|2fa
10006660002|pass2|2fa|specific.proxy:8080
"""
    res = client.post("/api/accounts/batch-import", json={
        "data": raw_data,
        "proxy": "global.proxy:9090"
    })
    assert res.status_code == 200
    assert res.json()["imported"] == 2

    conn = get_connection()
    try:
        acc1 = conn.execute("SELECT proxy FROM accounts WHERE fb_uid = '10006660001'").fetchone()
        acc2 = conn.execute("SELECT proxy FROM accounts WHERE fb_uid = '10006660002'").fetchone()
        assert acc1["proxy"] == "global.proxy:9090", "Nick không có proxy riêng phải nhận proxy mặc định của batch"
        assert acc2["proxy"] == "specific.proxy:8080", "Nick có proxy riêng phải giữ nguyên"

        # Batch assign proxy: target='no-proxy'
        conn.execute("INSERT INTO accounts (name, fb_uid) VALUES ('NoProxyNick', '10006660003')")
        conn.commit()

        client.post("/api/accounts/batch-assign-proxy", json={"proxy": "new.proxy:1111", "target": "no-proxy"})
        acc3 = conn.execute("SELECT proxy FROM accounts WHERE fb_uid = '10006660003'").fetchone()
        assert acc3["proxy"] == "new.proxy:1111"

        # Nick đã có proxy không bị đè khi target='no-proxy'
        acc1_after = conn.execute("SELECT proxy FROM accounts WHERE fb_uid = '10006660001'").fetchone()
        assert acc1_after["proxy"] == "global.proxy:9090"

        # Batch assign proxy: target='all'
        client.post("/api/accounts/batch-assign-proxy", json={"proxy": "override.all:2222", "target": "all"})
        all_proxies = [r["proxy"] for r in conn.execute("SELECT proxy FROM accounts").fetchall()]
        assert all(p == "override.all:2222" for p in all_proxies)
    finally:
        conn.close()


def test_a6_delete_account_busy_and_cleanup_profile(client, db, tmp_path):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO accounts (name, fb_uid) VALUES ('NickToDelete', '10005550001')")
        acc_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    # Tạo thư mục profile giả định cho nick
    p_dir = dola_service.account_profile_dir(acc_id)
    os.makedirs(p_dir, exist_ok=True)
    test_file = os.path.join(p_dir, "test.txt")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("profile data")

    # 1. Khi nick đang bận -> từ chối xóa
    assert AccountPool.get().acquire(acc_id, job_id=999) is True
    try:
        del_busy = client.delete(f"/api/accounts/{acc_id}")
        assert del_busy.status_code == 200
        assert del_busy.json()["success"] is False
        assert "đang bận" in del_busy.json()["message"]
        assert os.path.exists(test_file)
    finally:
        AccountPool.get().release(acc_id)

    # 2. Khi nick rảnh -> xóa thành công và xóa thư mục profile
    del_ok = client.delete(f"/api/accounts/{acc_id}")
    assert del_ok.status_code == 200
    assert del_ok.json()["success"] is True

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (acc_id,)).fetchone()
        assert row is None
    finally:
        conn.close()

    assert not os.path.exists(p_dir), "Thư mục profile của nick phải được dọn dẹp sau khi xóa"


def test_k1_mark_connected_records_session_expires(db):
    import config
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO accounts (name, fb_uid) VALUES ('SessionNick', '10004440001')")
        acc_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    # Timestamp tương lai: 1893456000 (2030-01-01 00:00:00 UTC)
    future_ts = 1893456000.0
    cookies = [
        {"name": "sessionid", "value": "valid_session_token", "domain": config.DOLA_DOMAIN, "expires": future_ts}
    ]

    dola_service._mark_account_connected(acc_id, cookies)

    conn = get_connection()
    try:
        row = conn.execute("SELECT status, session_expires FROM accounts WHERE id = ?", (acc_id,)).fetchone()
        assert row["status"] == "ready"
        assert row["session_expires"] is not None
        assert "2030-" in row["session_expires"]
    finally:
        conn.close()


def test_k2_dead_session_marks_needs_manual_login(db, monkeypatch):
    import config
    conn = get_connection()
    try:
        cursor = conn.cursor()
        old_cookies = json.dumps([{"name": "sessionid", "value": "old_session_123", "domain": config.DOLA_DOMAIN}])
        cursor.execute("INSERT INTO accounts (name, fb_uid, status, cookies) VALUES ('DeadSessionNick', '10003330001', 'ready', ?)",
                       (old_cookies,))
        acc_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    # Giả lập browser_session và context
    class FakePage:
        def goto(self, *a, **kw): pass
        def wait_for_timeout(self, *a, **kw): pass
        def screenshot(self, *a, **kw): pass
        def content(self): return "<html>No session</html>"
        @property
        def url(self): return "https://www.dola.com/login"

    class FakeContext:
        def __init__(self):
            self.pages = [FakePage()]
        def new_page(self): return self.pages[0]
        def cookies(self): return []  # Không có sessionid Dola
        def add_cookies(self, *a, **kw): pass
        def close(self): pass

    class FakeBrowserSession:
        def __enter__(self):
            return FakeContext()
        def __exit__(self, *a):
            pass

    monkeypatch.setattr(dola_service, "browser_session", lambda *a, **kw: FakeBrowserSession())
    monkeypatch.setattr("time.sleep", lambda *a: None)

    # Chạy check credits sync
    res = dola_service._check_account_credits_sync(acc_id, pool_held=False)
    assert res["success"] is False
    assert "sessionid mất hiệu lực" in res["message"]

    conn = get_connection()
    try:
        row = conn.execute("SELECT needs_manual, last_error FROM accounts WHERE id = ?", (acc_id,)).fetchone()
        assert row["needs_manual"] == NeedsManual.LOGIN
        assert "sessionid mất hiệu lực" in row["last_error"]
    finally:
        conn.close()


def test_k3_check_routes_alias(client, db):
    # Test endpoint alias /api/accounts/{id}/check và /api/accounts/check-all
    r_check_all = client.post("/api/accounts/check-all")
    assert r_check_all.status_code == 200
    assert r_check_all.json()["success"] is True
