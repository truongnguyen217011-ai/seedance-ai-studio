"""
Giai đoạn 2 — API nick qua TestClient (không Chrome): A1/A2/A3 (nhập nhiều dòng, xem trước), K3 (cookie theo nội dung),
A6 (xóa nick), A7 (200 nick, phân trang, tìm, lọc), K9 (trạng thái quét ban đầu).
"""
from __future__ import annotations

import json
import os
import time

import pytest

from constants import JobStatus, NeedsManual, Reason

fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="cần fastapi + httpx (requirements-dev.txt)")

UID = "100089274921029"
TWOFA = "JBSWY3DPEHPK3PXP"
FB_COOKIE = "c_user=100089274921029; xs=abcd123; datr=xyz"
DOLA_COOKIE = "sessionid=abc123def456; sessionid_ss=abc123def456"


@pytest.fixture
def client(db):
    import app as app_module
    return fastapi_testclient.TestClient(app_module.app)


def _ten_lines() -> str:
    lines = []
    for i in range(10):
        uid = f"1000{i:011d}"
        lines.append(f"{uid}|Pass{i}|{TWOFA}|103.151.246.{i + 1}:8080")
    return "\n".join(lines)


# ---------------------------------------------------------------- A1 / A2
def test_a1_batch_import_reports_each_line_with_new_id(client, db):
    r = client.post("/api/accounts/batch-import", json={"data": _ten_lines(), "auto_login": False})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True and data["imported"] == 10 and data["errors"] == []
    lines = data["imported_lines"]
    assert len(lines) == 10
    assert [ln["line"] for ln in lines] == list(range(1, 11))
    for ln in lines:
        assert isinstance(ln["id"], int) and ln["has_2fa"] is True and ln["has_cookie"] is False
        assert ln["proxy"].startswith("103.151.246.") and ln["uid"].startswith("1000") and ln["name"]
    assert len({ln["id"] for ln in lines}) == 10
    assert len(db.accounts()) == 10
    assert db.account(lines[0]["id"])["fb_2fa"] == TWOFA


def test_a2_batch_import_again_skips_all_as_existing(client, db):
    client.post("/api/accounts/batch-import", json={"data": _ten_lines()})
    r = client.post("/api/accounts/batch-import", json={"data": _ten_lines()})
    data = r.json()
    assert data["success"] is True and data["imported"] == 0 and data["imported_lines"] == []
    assert len(data["errors"]) == 10
    for err in data["errors"]:
        assert "đã có" in err["reason"] and err["existing_id"], err
    assert len(db.accounts()) == 10, "không được tạo nick trùng"

    # Trùng theo email (nick Google) cũng bị bỏ qua
    client.post("/api/accounts/batch-import", json={"data": "shop@gmail.com|Pass1|160.250.166.25:10060"})
    r = client.post("/api/accounts/batch-import", json={"data": "shop@gmail.com|Pass2"})
    assert r.json()["imported"] == 0 and "email shop@gmail.com" in r.json()["errors"][0]["reason"]


def test_a1_batch_import_reasons_missing_pass_and_bad_2fa(client, db):
    data = "\n".join([
        f"{UID}",                                   # thiếu pass
        "61592837492819|Password@2024|ABCD2345EFGH6789",   # 2FA sai định dạng (có 8/9)
        "61592837492820|Password@2024|JBSW Y3DP EHPK 3PXP",  # 2FA có khoảng trắng → hợp lệ
    ])
    r = client.post("/api/accounts/batch-import", json={"data": data})
    out = r.json()
    assert out["imported"] == 1 and out["imported_lines"][0]["line"] == 3 and out["imported_lines"][0]["has_2fa"] is True
    reasons = {e["line"]: e["reason"] for e in out["errors"]}
    assert "Thiếu mật khẩu" in reasons[1], reasons
    assert "2FA" in reasons[2] and "sai định dạng" in reasons[2] and "ABCD2345EFGH6789" in reasons[2], reasons
    assert len(db.accounts()) == 1


# ---------------------------------------------------------------- A3: định dạng + xem trước
def test_a3_parse_preview_shows_each_line_before_saving(client, db):
    db.add_account("đã có", fb_uid=UID)
    data = "\n".join([
        f"{UID}|Pass123456|{TWOFA}",                               # 1 trùng
        f"61592837492819|Pass1|{TWOFA}|103.151.246.12:8080",       # 2 UID|Pass|2FA|Proxy
        f"61592837492820|Pass2|{FB_COOKIE}",                       # 3 UID|Pass|Cookie
        f"61592837492821|Pass3|{TWOFA}|{FB_COOKIE}|103.151.246.13:8080",  # 4 đủ 5 cột
        f"61592837492822\tPass4\t{TWOFA}\t103.151.246.14:8080",    # 5 tab Excel
        DOLA_COOKIE,                                               # 6 cookie thô Dola
        "c_user=10007788990011; xs=secretxs; datr=d;",             # 7 cookie thô Facebook
        "chi-co-mot-cot",                                          # 8 lỗi
    ])
    r = client.post("/api/accounts/parse-preview", json={"data": data, "proxy": "9.9.9.9:9999"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["success"] is True
    items = {it["line"]: it for it in out["items"]}
    assert len(items) == 8 and db.accounts()[0]["name"] == "đã có" and len(db.accounts()) == 1, "preview không được lưu"
    assert items[1]["exists"] is True and items[1]["ok"] is False and "đã có" in items[1]["reason"]
    assert items[2]["ok"] and items[2]["has_pass"] and items[2]["has_2fa"] and items[2]["proxy"] == "103.151.246.12:8080"
    assert items[3]["has_cookie"] and items[3]["cookie_kind"] == "facebook" and items[3]["has_2fa"] is False
    assert items[3]["proxy"] == "9.9.9.9:9999", "dòng không có proxy riêng nhận proxy chung"
    assert items[4]["has_2fa"] and items[4]["has_cookie"] and items[4]["proxy"] == "103.151.246.13:8080"
    assert items[5]["uid"] == "61592837492822" and items[5]["has_2fa"] and items[5]["proxy"] == "103.151.246.14:8080"
    assert items[6]["cookie_kind"] == "dola" and items[6]["uid"].startswith("Dola_") and items[6]["has_pass"] is False
    assert items[7]["cookie_kind"] == "facebook" and items[7]["uid"] == "10007788990011"
    assert items[8]["ok"] is False and items[8]["reason"]
    assert out["summary"] == {"total": 8, "ok": 6, "duplicates": 1, "errors": 1}
    for it in out["items"]:
        assert "pass" not in it and "fb_pass" not in it, "preview không trả mật khẩu"

    # Lưu đúng những gì đã xem trước; cookie thô Dola → nick có phiên Dola ngay
    r = client.post("/api/accounts/batch-import", json={"data": data, "proxy": "9.9.9.9:9999"})
    out = r.json()
    assert out["imported"] == 6 and len(out["errors"]) == 2
    by_line = {ln["line"]: ln for ln in out["imported_lines"]}
    assert by_line[6]["has_dola"] is True and by_line[6]["cookie_kind"] == "dola"
    assert by_line[7]["has_dola"] is False and by_line[7]["cookie_kind"] == "facebook"
    assert db.account(by_line[3]["id"])["proxy"] == "9.9.9.9:9999"
    acc6 = db.account(by_line[6]["id"])
    assert acc6["has_dola"] == 1
    import config
    cookies = json.loads(acc6["cookies"])
    assert all(c["domain"] == config.DOLA_DOMAIN for c in cookies), cookies
    # dán lại cùng cookie Dola → "đã có" (UID băm ổn định, BH-51)
    r = client.post("/api/accounts/batch-import", json={"data": DOLA_COOKIE})
    assert r.json()["imported"] == 0 and "đã có" in r.json()["errors"][0]["reason"]


# ---------------------------------------------------------------- K3: cookie theo nội dung ở mọi ô
def test_k3_dola_cookie_pasted_in_add_account_form_gives_has_dola(client, db):
    import config
    r = client.post("/api/accounts", json={"name": "nick dán cookie Dola", "account_type": "facebook",
                                           "fb_uid": UID, "cookies": DOLA_COOKIE})
    assert r.json()["success"] is True, r.text
    acc_id = r.json()["id"]
    acc = db.account(acc_id)
    assert acc["has_dola"] == 1
    cookies = json.loads(acc["cookies"])
    assert {c["name"] for c in cookies} == {"sessionid", "sessionid_ss"}
    assert all(c["domain"] == config.DOLA_DOMAIN for c in cookies), cookies
    listed = {a["id"]: a for a in client.get("/api/accounts").json()["accounts"]}
    assert listed[acc_id]["has_dola"] is True and listed[acc_id]["has_cookies"] is True
    state_file = os.path.join(config.PROFILES_DIR, f"acc_{acc_id}", "storage_state.json")
    assert os.path.exists(state_file)

    # Cookie Facebook dán vào form nick Google vẫn về .facebook.com, không có phiên Dola
    r = client.post("/api/accounts", json={"name": "nick google", "account_type": "google", "email": "a@gmail.com",
                                           "cookies": FB_COOKIE})
    acc = db.account(r.json()["id"])
    assert acc["has_dola"] == 0
    assert all(c["domain"] == ".facebook.com" for c in json.loads(acc["cookies"]))


def test_k3_paste_cookie_modal_detects_domain_from_content(client, db):
    import config
    acc_id = db.add_account("nick chưa có phiên", with_session=False)
    r = client.post(f"/api/accounts/{acc_id}/cookies", json={"cookies": FB_COOKIE})
    out = r.json()
    assert out["success"] is True and out["has_session"] is False and out["cookie_kind"] == "facebook"
    assert "Chưa thấy sessionid Dola" in out["message"]
    assert db.account(acc_id)["has_dola"] == 0
    assert all(c["domain"] == ".facebook.com" for c in json.loads(db.account(acc_id)["cookies"]))

    db.exec("UPDATE accounts SET needs_manual = ? WHERE id = ?", (NeedsManual.LOGIN, acc_id))
    r = client.post(f"/api/accounts/{acc_id}/cookies", json={"cookies": DOLA_COOKIE})
    out = r.json()
    assert out["success"] is True and out["has_session"] is True and out["cookie_kind"] == "dola"
    acc = db.account(acc_id)
    assert acc["has_dola"] == 1 and acc["needs_manual"] is None
    assert all(c["domain"] == config.DOLA_DOMAIN for c in json.loads(acc["cookies"]))

    # JSON Cookie-Editor có domain riêng → giữ nguyên
    raw = json.dumps([{"name": "sessionid", "value": "v", "domain": ".dola.com", "path": "/"},
                      {"name": "c_user", "value": "1", "domain": ".facebook.com", "path": "/"}])
    r = client.post(f"/api/accounts/{acc_id}/cookies", json={"cookies": raw})
    doms = {c["name"]: c["domain"] for c in json.loads(db.account(acc_id)["cookies"])}
    assert doms == {"sessionid": ".dola.com", "c_user": ".facebook.com"}


# ---------------------------------------------------------------- A6: xóa nick
def test_a6_delete_account_removes_profile_and_requeues_jobs(client, db):
    import config
    acc_id = db.add_account("nick sắp xóa")
    profile = os.path.join(config.PROFILES_DIR, f"acc_{acc_id}")
    with open(os.path.join(profile, "storage_state.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    waiting = db.add_job("job chờ", status=JobStatus.CHO, account_id=acc_id)
    paused = db.add_job("job tạm dừng", status=JobStatus.TAM_DUNG, account_id=acc_id)
    done = db.add_job("job xong", status=JobStatus.HOAN_THANH, account_id=acc_id)
    failed = db.add_job("job thất bại", status=JobStatus.THAT_BAI, account_id=acc_id)
    db.exec("INSERT INTO images (account_id, prompt) VALUES (?, 'ảnh')", (acc_id,))

    r = client.delete(f"/api/accounts/{acc_id}")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["success"] is True and out["requeued_jobs"] == 2 and out["profile_removed"] is True, out
    assert db.account(acc_id) is None
    assert not os.path.exists(profile)
    for jid in (waiting, paused):
        j = db.job(jid)
        assert j["status"] == JobStatus.CHO and j["account_id"] is None
        assert j["status_message"] == Reason.ACCOUNT_DELETED.format(name="nick sắp xóa"), j["status_message"]
    assert db.job(done)["status"] == JobStatus.HOAN_THANH and db.job(done)["account_id"] is None
    assert db.job(failed)["status"] == JobStatus.THAT_BAI
    assert client.delete(f"/api/accounts/{acc_id}").json()["success"] is False


def test_a6_delete_busy_account_refused(client, db):
    from account_pool import AccountPool
    acc_id = db.add_account("nick bận")
    pool = AccountPool.get()
    assert pool.acquire(acc_id, 7)
    try:
        out = client.delete(f"/api/accounts/{acc_id}").json()
        assert out["success"] is False and "đang bận" in out["message"] and "job #7" in out["message"]
        assert db.account(acc_id) is not None
    finally:
        pool.release(acc_id)


# ---------------------------------------------------------------- A7: 200 nick
def test_a7_two_hundred_accounts_paginated_fast(client, db):
    from _helpers import future_ts
    ids = []
    for i in range(200):
        ids.append(db.add_account(f"nick số {i + 1}", with_session=(i % 4 != 0)))
    db.exec("UPDATE accounts SET needs_manual = ? WHERE id = ?", (NeedsManual.PROXY, ids[1]))
    db.exec("UPDATE accounts SET rest_until = ?, rest_reason = 'Hết lượt trong ngày' WHERE id = ?", (future_ts(60), ids[2]))
    db.exec("UPDATE accounts SET busy_job_id = 5 WHERE id = ?", (ids[3],))
    db.exec("UPDATE accounts SET proxy = '1.2.3.4:8080' WHERE id IN (?, ?)", (ids[5], ids[6]))

    t0 = time.monotonic()
    r = client.get("/api/accounts", params={"limit": 50, "offset": 0})
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    out = r.json()
    assert elapsed < 1.0, f"GET /api/accounts với 200 nick mất {elapsed:.2f}s"
    assert out["total"] == 200 and len(out["accounts"]) == 50 and out["limit"] == 50 and out["offset"] == 0
    assert out["accounts"][0]["id"] == ids[-1], "mới nhất trước"

    page4 = client.get("/api/accounts", params={"limit": 50, "offset": 150}).json()
    assert len(page4["accounts"]) == 50 and page4["accounts"][-1]["id"] == ids[0]
    assert client.get("/api/accounts", params={"limit": 50, "offset": 200}).json()["accounts"] == []
    all_rows = client.get("/api/accounts").json()
    assert all_rows["total"] == 200 and len(all_rows["accounts"]) == 200

    found = client.get("/api/accounts", params={"q": "nick số 17", "limit": 50}).json()
    assert found["total"] == 11, "17, 170..179"
    found = client.get("/api/accounts", params={"q": "nick số 170"}).json()
    assert found["total"] == 1 and found["accounts"][0]["name"] == "nick số 170"
    by_uid = client.get("/api/accounts", params={"q": db.account(ids[9])["fb_uid"]}).json()
    assert by_uid["total"] == 1 and by_uid["accounts"][0]["id"] == ids[9]

    assert client.get("/api/accounts", params={"status": "needs_manual"}).json()["total"] == 1
    assert client.get("/api/accounts", params={"status": "resting"}).json()["total"] == 1
    assert client.get("/api/accounts", params={"status": "busy"}).json()["total"] == 1
    assert client.get("/api/accounts", params={"status": "no_dola"}).json()["total"] == 50
    assert client.get("/api/accounts", params={"status": "no_proxy"}).json()["total"] == 198
    ready = client.get("/api/accounts", params={"status": "ready"}).json()
    # 150 nick có phiên trừ nick proxy lỗi (#2, không có phiên vì i=1 → có phiên) và nick nghỉ (#3)
    expected_ready = sum(1 for i in range(200) if i % 4 != 0) - sum(1 for i in (1, 2) if i % 4 != 0)
    assert ready["total"] == expected_ready, (ready["total"], expected_ready)
    assert client.get("/api/accounts", params={"status": "lạ"}).status_code == 400


def test_a7_has_dola_column_not_file_reads(client, db, monkeypatch):
    """GET /api/accounts không mở storage_state.json của từng nick (cột has_dola); nick chưa quét (NULL) mới đọc file."""
    import app as app_module
    import dola_service
    for i in range(5):
        db.add_account(f"nick {i}")
    calls = []
    real = dola_service.account_has_dola_session

    def spy(acc):
        calls.append(acc.get("id"))
        return real(acc)

    monkeypatch.setattr(app_module, "account_has_dola_session", spy)
    out = client.get("/api/accounts").json()
    assert all(a["has_dola"] is True for a in out["accounts"])
    assert calls == [], "không được đọc file khi cột has_dola đã có"
    db.exec("UPDATE accounts SET has_dola = NULL")
    out = client.get("/api/accounts").json()
    assert len(calls) == 5 and all(a["has_dola"] is True for a in out["accounts"])
    # quét lúc khởi động điền lại cột
    assert dola_service.refresh_has_dola_flags() == 5
    assert all(a["has_dola"] == 1 for a in db.accounts())


# ---------------------------------------------------------------- K9: trạng thái quét ban đầu
def test_k9_scan_status_initial_and_empty_scan(client, db):
    st = client.get("/api/accounts/scan-status").json()
    for key in ("running", "done", "total", "summary"):
        assert key in st
    for key in ("ready", "no_credit", "need_login", "proxy_dead"):
        assert key in st["summary"]
    out = client.post("/api/accounts/scan-all").json()
    assert out["success"] is False and "Chưa có nick" in out["message"]


# ---------------------------------------------------------------- A5: gán proxy mới gỡ cờ proxy lỗi
def test_a5_batch_assign_proxy_clears_proxy_flag(client, db):
    acc_id = db.add_account("nick proxy chết", proxy="1.2.3.4:1")
    db.exec("UPDATE accounts SET needs_manual = ?, last_error = 'Proxy chết' WHERE id = ?", (NeedsManual.PROXY, acc_id))
    other = db.add_account("nick captcha")
    db.exec("UPDATE accounts SET needs_manual = ? WHERE id = ?", (NeedsManual.CAPTCHA, other))
    r = client.post("/api/accounts/batch-assign-proxy", json={"proxy": "5.6.7.8:8080:u:p", "target": "all"})
    assert r.json()["success"] is True and r.json()["updated"] == 2
    assert db.account(acc_id)["needs_manual"] is None and db.account(acc_id)["proxy"] == "5.6.7.8:8080:u:p"
    assert db.account(other)["needs_manual"] == NeedsManual.CAPTCHA, "cờ khác proxy giữ nguyên"
    logs = [r["message"] for r in db.system_logs()]
    assert any("5.6.7.8:8080:u:***" in m for m in logs) and not any(":u:p'" in m for m in logs), logs
