"""
Giai đoạn 2 — các lỗi reviewer tìm ra (không Chrome): C-1/BH-56 (socks5 thiếu httpx[socks] → cờ proxy oan),
C-2/BH-57 (phản hồi trả nguyên dòng có mật khẩu), N-3/BH-58 (API tên nick cho dropdown), N-4/BH-59 (ERR_TUNNEL không
đồng nghĩa proxy chết; worker thử lại proxy sau 30 phút), N-5/BH-60 (cột has_dola lệch khi cookie hết hạn), N-6 (cờ
running của quét), N-7 (xóa thư mục profile bền, dọn profile mồ côi), N-8 (last_relogin_at bền), G-1 (cột thừa ngắn
không phải 2FA), G-2 (nick bận khi quét), G-3 (AccountStatus.READY).
"""
from __future__ import annotations

import os
import pathlib
import re
import stat
import threading
import time
from datetime import datetime, timedelta

import httpx
import pytest

import config
import diagnostics
import dola_service
import parser as account_parser
from constants import AccountStatus, JobStatus, NeedsManual
from _helpers import wait_until

ROOT = pathlib.Path(__file__).resolve().parent.parent
fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="cần fastapi + httpx (requirements-dev.txt)")


@pytest.fixture(autouse=True)
def _clean_pool():
    import worker
    from account_pool import AccountPool
    AccountPool.get().clear()
    worker._running_jobs.clear()
    yield
    AccountPool.get().clear()
    worker._running_jobs.clear()


@pytest.fixture
def client(db):
    import app as app_module
    return fastapi_testclient.TestClient(app_module.app)


# ---------------------------------------------------------------- C-1 / BH-56: socks5 + httpx[socks]
def test_bh56_requirements_pin_httpx_socks_extra():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^httpx\[socks\]", req, re.MULTILINE), "BH-56: proxy socks5:// cần httpx[socks] trong requirements.txt"
    pytest.importorskip("socksio", reason="httpx[socks] chưa cài trong môi trường này")


def test_bh56_check_proxy_socks5_via_fake_socks_proxy(db, fake_dola):
    from fake_proxy import start_fake_socks5_proxy
    pytest.importorskip("socksio")
    sp = start_fake_socks5_proxy()
    try:
        acc = {"id": 1, "name": "nick socks", "proxy": sp.address}
        assert dola_service.parse_proxy(sp.address)["server"] == sp.address
        step = diagnostics._check_proxy(acc)
        assert step["ok"] is True and "IP ra ngoài: 127.0.0.1" in step["detail"], step
        assert any(m == "CONNECT" for m, _h, _p in sp.requests), sp.requests
    finally:
        sp.stop()


def test_bh56_config_error_is_not_dead_proxy(db, monkeypatch):
    """ImportError (thiếu socksio) / URL sai → ok=None, không gắn cờ; ConnectError thật → ok=False (proxy chết)."""
    acc_id = db.add_account("nick socks5", proxy="socks5://user:secretpw@1.2.3.4:1080")
    acc = db.account(acc_id)

    def missing_socksio(*args, **kwargs):
        raise ImportError("Using SOCKS proxy, but the 'socksio' package is not installed. Make sure to install httpx using `pip install httpx[socks]`.")

    monkeypatch.setattr(diagnostics, "_fetch_ip", missing_socksio)
    step = diagnostics._check_proxy(acc)
    assert step["ok"] is None, step
    assert "Không kiểm được IP qua proxy" in step["detail"] and "socksio" in step["detail"], step
    assert "secretpw" not in step["detail"] and "user:***@1.2.3.4:1080" in step["detail"], step
    # _persist với ok=None: nick chưa có cờ thì vẫn không có cờ; nick đang có cờ proxy thì giữ nguyên (chưa kết luận)
    diagnostics._persist(acc_id, [step])
    assert db.account(acc_id)["needs_manual"] is None
    db.exec("UPDATE accounts SET needs_manual = ? WHERE id = ?", (NeedsManual.PROXY, acc_id))
    diagnostics._persist(acc_id, [step])
    assert db.account(acc_id)["needs_manual"] == NeedsManual.PROXY
    assert diagnostics.classify_diagnosis({"steps": [step, diagnostics._step("dola_session", "Phiên Dola", False, "x")]}) == "need_login"

    def bad_url(*args, **kwargs):
        raise httpx.UnsupportedProtocol("Request URL has an unsupported protocol 'socks9://'.")

    monkeypatch.setattr(diagnostics, "_fetch_ip", bad_url)
    assert diagnostics._check_proxy(acc)["ok"] is None

    def connect_error(*args, **kwargs):
        raise httpx.ConnectError("[Errno 111] Connection refused")

    monkeypatch.setattr(diagnostics, "_fetch_ip", connect_error)
    step = diagnostics._check_proxy(acc)
    assert step["ok"] is False and "không phản hồi" in step["detail"], step
    diagnostics._persist(acc_id, [step])
    assert db.account(acc_id)["needs_manual"] == NeedsManual.PROXY
    # proxy đạt → gỡ cờ
    monkeypatch.setattr(diagnostics, "_fetch_ip", lambda *a, **k: "9.9.9.9")
    diagnostics._persist(acc_id, [diagnostics._check_proxy(acc)])
    assert db.account(acc_id)["needs_manual"] is None and db.account(acc_id)["last_ip"] == "9.9.9.9"


# ---------------------------------------------------------------- C-2 / BH-57: không trả nguyên dòng
@pytest.mark.parametrize("line, expected", [
    ("61592837492819|Password@2024|ABCD2345EFGH6789|c_user=1; xs=2|1.2.3.4:8080:u:p", "61592837492819|***|***|***|***"),
    ("shop@gmail.com\tGooglePass99\t160.250.166.25:10060", "shop@gmail.com|***|***"),
    ("c_user=10007788990011; xs=secretxs; datr=d;", "c_user=10007788990011;***"),
    ("sessionid=abc123; sessionid_ss=abc123", "***"),
    ("xs=secretxs; datr=d", "***"),
    ("chi-co-mot-cot", "chi-co-mot-cot"),
    ("", ""),
])
def test_bh57_mask_line(line, expected):
    assert account_parser.mask_line(line) == expected


SECRETS = ("Password@2024", "secretxs", "JBSWY3DPEHPK3PXP")


def _secret_lines() -> str:
    return "\n".join([
        "100089274921029|Password@2024|JBSWY3DPEHPK3PXP",          # 1 hợp lệ
        "100089274921029|Password@2024|JBSWY3DPEHPK3PXP",          # 2 trùng dòng 1 → errors
        "61592837492819|Password@2024|ABCD2345EFGH6789",           # 3 2FA sai định dạng → errors
        "xs=secretxs; datr=d",                                     # 4 cookie thiếu c_user → errors
        "100089274921030|Password@2024|Nguyenvan2024",             # 5 hợp lệ, cột thừa → note
    ])


def test_bh57_parse_preview_and_batch_import_never_return_raw_line(client, db):
    r = client.post("/api/accounts/parse-preview", json={"data": _secret_lines()})
    assert r.status_code == 200, r.text
    for secret in SECRETS:
        assert secret not in r.text, f"parse-preview lộ '{secret}': {r.text[:300]}"
    items = {it["line"]: it for it in r.json()["items"]}
    assert items[2]["ok"] is False and items[2]["text"] == "100089274921029|***|***", items[2]
    assert items[3]["text"] == "61592837492819|***|***" and items[4]["text"] == "***", (items[3], items[4])
    assert items[5]["ok"] is True and items[5]["note"] == "Nguyenvan2024"

    r = client.post("/api/accounts/batch-import", json={"data": _secret_lines()})
    assert r.status_code == 200, r.text
    for secret in SECRETS:
        assert secret not in r.text, f"batch-import lộ '{secret}': {r.text[:300]}"
    out = r.json()
    assert out["imported"] == 2 and len(out["errors"]) == 3, out
    assert all("Password@2024" not in (e.get("text") or "") for e in out["errors"])
    # lần hai: mọi dòng "đã có" → errors[].text chỉ là UID
    r = client.post("/api/accounts/batch-import", json={"data": _secret_lines()})
    for secret in SECRETS:
        assert secret not in r.text
    # nhật ký cũng không được chứa dòng gốc
    logs = " ".join((row["message"] or "") for row in db.system_logs())
    for secret in SECRETS:
        assert secret not in logs, f"system_logs lộ '{secret}'"
    assert db.account(out["imported_lines"][0]["id"])["fb_pass"] == "Password@2024", "CSDL vẫn lưu mật khẩu thật để đăng nhập"


def test_bh57_parser_errors_text_is_masked_at_source():
    ok, errors = account_parser.parse_multiple_account_lines(_secret_lines(), strict_2fa=True)
    assert len(ok) == 2 and len(errors) == 3
    for err in errors:
        assert "Password@2024" not in err["text"] and "secretxs" not in err["text"], err
    src = (ROOT / "parser.py").read_text(encoding="utf-8")
    assert '"text": line' not in src, "BH-57: errors[].text phải qua mask_line"


# ---------------------------------------------------------------- N-3 / BH-58: API tên nick
def test_bh58_account_names_endpoint_lists_all_accounts(client, db):
    ids = [db.add_account(f"nick {i}") for i in range(60)]
    db.exec("UPDATE accounts SET account_type = 'google' WHERE id = ?", (ids[0],))
    r = client.get("/api/accounts/names")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["total"] == 60 and len(out["accounts"]) == 60
    assert out["accounts"][0]["id"] == ids[-1], "mới nhất trước, cùng thứ tự bảng"
    assert all(set(a.keys()) == {"id", "name", "account_type"} for a in out["accounts"]), "chỉ trả 3 trường nhẹ"
    by_id = {a["id"]: a for a in out["accounts"]}
    assert by_id[ids[0]]["account_type"] == "google"
    page = client.get("/api/accounts", params={"limit": 50}).json()
    assert len(page["accounts"]) == 50 and page["total"] == 60, "bảng vẫn phân trang 50; dropdown lấy đủ từ /names"
    assert "fetchAccountNames" in (ROOT / "static/js/app.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------- N-4 / BH-59: ERR_TUNNEL ≠ proxy chết
def test_bh59_err_tunnel_with_live_proxy_is_ordinary_technical_failure(db, fake_dola, fake_proxy):
    from fake_proxy import closed_port
    fake_proxy.set_connect_status(502)
    acc_id = db.add_account("nick proxy sống", proxy=fake_proxy.address)
    job_id = db.add_job("job", status=JobStatus.DANG_CHAY, account_id=acc_id, attempts=1)
    err = Exception("page.goto: net::ERR_TUNNEL_CONNECTION_FAILED at https://www.dola.com/chat/")
    dola_service._apply_technical_failure(job_id, db.account(acc_id), err, None, False)
    acc = db.account(acc_id)
    assert acc["needs_manual"] is None, acc
    assert acc["status"] == AccountStatus.READY and acc["consecutive_errors"] == 1
    job = db.job(job_id)
    assert job["status"] == JobStatus.CHO and job["attempts"] == 1 and "tự chạy lại lần 1" in job["status_message"], job
    assert fake_proxy.count("/__ip") == 1, "phải hỏi IP qua proxy trước khi kết luận"
    logs = [r["message"] or "" for r in db.system_logs()]
    assert any("vẫn phản hồi" in m and "không gắn cờ proxy" in m for m in logs), logs

    # ERR_PROXY_CONNECTION_FAILED: không hỏi IP, gắn cờ như cũ
    acc2 = db.add_account("nick proxy chết hẳn", proxy=fake_proxy.address)
    job2 = db.add_job("job 2", status=JobStatus.DANG_CHAY, account_id=acc2, attempts=1)
    dola_service._apply_technical_failure(job2, db.account(acc2), Exception("net::ERR_PROXY_CONNECTION_FAILED"), None, False)
    assert db.account(acc2)["needs_manual"] == NeedsManual.PROXY and fake_proxy.count("/__ip") == 1

    # ERR_TUNNEL + proxy không trả lời IP → vẫn là proxy chết
    acc3 = db.add_account("nick proxy cổng đóng", proxy=f"127.0.0.1:{closed_port()}")
    job3 = db.add_job("job 3", status=JobStatus.DANG_CHAY, account_id=acc3, attempts=1)
    dola_service._apply_technical_failure(job3, db.account(acc3), err, None, False)
    assert db.account(acc3)["needs_manual"] == NeedsManual.PROXY and db.job(job3)["attempts"] == 0


def test_bh59_proxy_confirmed_dead_rules(db, monkeypatch):
    acc = {"id": 1, "name": "n", "proxy": "socks5://u:p@1.2.3.4:1080"}
    calls = []

    def fetch(url, timeout=None):
        calls.append((url, timeout))
        raise ImportError("socksio missing")

    monkeypatch.setattr(diagnostics, "_fetch_ip", fetch)
    assert dola_service.proxy_confirmed_dead(acc, None) is False
    assert dola_service.proxy_confirmed_dead({"id": 2, "name": "n", "proxy": ""}, "ERR_TUNNEL_CONNECTION_FAILED") is False
    assert dola_service.proxy_confirmed_dead(acc, "ERR_PROXY_CONNECTION_FAILED") is True and calls == []
    assert dola_service.proxy_confirmed_dead(acc, "ERR_TUNNEL_CONNECTION_FAILED") is False, "lỗi cấu hình: chưa kết luận"
    assert calls and calls[0][1] == dola_service.PROXY_PROBE_TIMEOUT == 10
    monkeypatch.setattr(diagnostics, "_fetch_ip", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectTimeout("t")))
    assert dola_service.proxy_confirmed_dead(acc, "ERR_TUNNEL_CONNECTION_FAILED") is True
    monkeypatch.setattr(diagnostics, "_fetch_ip", lambda *a, **k: "5.5.5.5")
    assert dola_service.proxy_confirmed_dead(acc, "ERR_TUNNEL_CONNECTION_FAILED") is False


def test_bh59_worker_rechecks_flagged_proxy_after_interval(db, fake_dola, fake_proxy):
    import worker
    from fake_proxy import closed_port
    from database import get_connection
    old = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    alive = db.add_account("nick proxy sống lại", proxy=fake_proxy.address)
    dead = db.add_account("nick proxy vẫn chết", proxy=f"127.0.0.1:{closed_port()}")
    fresh = db.add_account("nick mới gắn cờ", proxy=f"127.0.0.1:{closed_port()}")
    for acc_id, when in ((alive, old), (dead, old), (fresh, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))):
        db.exec("UPDATE accounts SET needs_manual = ?, last_error = 'Proxy chết', last_check = ? WHERE id = ?",
                (NeedsManual.PROXY, when, acc_id))
    conn = get_connection()
    try:
        futures = worker._recheck_dead_proxies(conn)
    finally:
        conn.close()
    assert len(futures) == 2, "chỉ nick quá 30 phút mới được thử lại; nick vừa gắn cờ thì chưa"
    for f in futures:
        f.result(timeout=30)
    a = db.account(alive)
    assert a["needs_manual"] is None and a["last_error"] is None and a["last_ip"] == "127.0.0.1", a
    assert fake_proxy.count("/__ip") == 1
    d = db.account(dead)
    assert d["needs_manual"] == NeedsManual.PROXY and d["last_check"] > old, "giữ cờ, ghi mốc để 30 phút sau thử lại"
    assert db.account(fresh)["needs_manual"] == NeedsManual.PROXY
    logs = [r["message"] or "" for r in db.system_logs()]
    assert any("phản hồi lại" in m and "đã gỡ cờ proxy lỗi" in m for m in logs), logs
    # vòng quét kế tiếp không thử lại ngay nick vẫn chết (last_check vừa ghi) → không mở thêm lần hỏi nào
    conn = get_connection()
    try:
        assert worker._recheck_dead_proxies(conn) == []
    finally:
        conn.close()
    # qua _tick (đường thật) cũng không ném và vẫn trả danh sách rỗng khi không có job
    assert worker._tick() == []


# ---------------------------------------------------------------- N-5 / BH-60: has_dola lệch
def test_bh60_select_account_corrects_has_dola_when_session_gone(db):
    from account_pool import select_account_for_job
    acc_id = db.add_account("nick cookie hết hạn", with_session=False)
    db.exec("UPDATE accounts SET has_dola = 1 WHERE id = ?", (acc_id,))
    chosen, summary = select_account_for_job({"id": 0})
    assert chosen is None and "1 nick chưa đăng nhập Dola" in summary
    assert db.account(acc_id)["has_dola"] == 0, "BH-60: cột cache phải được sửa ngay khi pool thấy không còn phiên"
    # nick có phiên thật không bị đụng
    good = db.add_account("nick còn phiên")
    chosen, _ = select_account_for_job({"id": 0})
    assert chosen["id"] == good and db.account(good)["has_dola"] == 1


def test_bh60_worker_refreshes_has_dola_periodically(db, monkeypatch):
    import worker
    from database import get_connection
    acc_id = db.add_account("nick cookie hết hạn", with_session=False)
    db.exec("UPDATE accounts SET has_dola = 1 WHERE id = ?", (acc_id,))
    worker._last_has_dola_refresh = time.monotonic()
    assert worker._refresh_has_dola_if_due() is None, "chưa tới hạn 10 phút thì không quét"
    assert db.account(acc_id)["has_dola"] == 1
    fut = worker._refresh_has_dola_if_due(force=True)
    assert fut is not None
    fut.result(timeout=30)
    assert db.account(acc_id)["has_dola"] == 0
    # tới hạn → _recover_accounts (đường của _tick) tự quét trên JOB_EXECUTOR
    db.exec("UPDATE accounts SET has_dola = 1 WHERE id = ?", (acc_id,))
    monkeypatch.setattr(config, "HAS_DOLA_REFRESH_INTERVAL_SECONDS", 0)
    conn = get_connection()
    try:
        worker._recover_accounts(conn)
    finally:
        conn.close()
    wait_until(lambda: db.account(acc_id)["has_dola"] == 0 or None, 30, what="has_dola về 0 sau quét định kỳ")
    assert config.HAS_DOLA_REFRESH_INTERVAL_SECONDS == 0  # monkeypatch còn hiệu lực trong test này


# ---------------------------------------------------------------- N-6: cờ running của quét
@pytest.fixture
def scan_finished():
    yield
    deadline = time.time() + 60
    while diagnostics.scan_status()["running"] and time.time() < deadline:
        time.sleep(0.2)


def test_n6_scan_running_cleared_when_executor_submit_raises(db, monkeypatch, scan_finished):
    import worker
    db.add_account("nick 1", with_session=False)
    db.add_account("nick 2", with_session=False)

    class _DeadExecutor:
        def submit(self, *a, **k):
            raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(worker, "JOB_EXECUTOR", _DeadExecutor())
    out = diagnostics.start_scan_all()
    assert out["success"] is True and out["total"] == 2
    st = wait_until(lambda: (lambda s: s if not s["running"] else None)(diagnostics.scan_status()), 20, what="running=False")
    assert st["finished_at"] and st["done"] == 0
    again = diagnostics.start_scan_all()
    assert again["success"] is True, "không được kẹt 'Đang quét dở' sau lỗi submit"
    wait_until(lambda: not diagnostics.scan_status()["running"] or None, 20, what="running=False lần 2")


def test_n6_scan_running_cleared_when_thread_start_raises(db, monkeypatch):
    db.add_account("nick 1", with_session=False)

    class _BoomThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(diagnostics.threading, "Thread", _BoomThread)
    out = diagnostics.start_scan_all()
    assert out["success"] is False and "Không bắt đầu được" in out["message"], out
    assert diagnostics.scan_status()["running"] is False


# ---------------------------------------------------------------- N-7: xóa thư mục bền + dọn profile mồ côi
def test_n7_remove_dir_with_retry_retries_three_times(tmp_path, monkeypatch):
    import browser
    target = tmp_path / "acc_5"
    target.mkdir()
    (target / "lock").write_text("x")
    attempts = []
    sleeps = []
    real = browser._rmtree_once

    def flaky(path):
        attempts.append(path)
        if len(attempts) < 3:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        real(path)

    monkeypatch.setattr(browser, "_rmtree_once", flaky)
    monkeypatch.setattr(browser.time, "sleep", lambda s: sleeps.append(s))
    assert browser.remove_dir_with_retry(str(target)) is True
    assert len(attempts) == 3 and sleeps == [1.0, 1.0]
    assert not target.exists()

    # vẫn không xóa được sau 3 lần → False, không ném
    stubborn = tmp_path / "acc_6"
    stubborn.mkdir()
    monkeypatch.setattr(browser, "_rmtree_once", lambda p: (_ for _ in ()).throw(PermissionError(13, "denied")))
    assert browser.remove_dir_with_retry(str(stubborn)) is False
    assert browser.remove_dir_with_retry(str(tmp_path / "khong_ton_tai")) is True


def test_n7_rm_handler_clears_readonly(tmp_path):
    import browser
    f = tmp_path / "ro.txt"
    f.write_text("x")
    os.chmod(f, stat.S_IREAD)
    calls = []

    def remove(path):
        calls.append(os.stat(path).st_mode & stat.S_IWRITE)
        os.remove(path)

    browser._rm_make_writable(remove, str(f), None)
    assert calls and calls[0], "handler phải gỡ read-only trước khi gọi lại hàm xóa"
    assert not f.exists()


def test_n7_cleanup_on_startup_removes_profiles_of_deleted_accounts(db, env_tmp, monkeypatch, caplog):
    import logging
    import browser
    kept = db.add_account("nick còn")   # tạo profiles/acc_<id>
    stale = os.path.join(config.PROFILES_DIR, "acc_999")
    os.makedirs(stale, exist_ok=True)
    with open(os.path.join(stale, "Preferences"), "w", encoding="utf-8") as f:
        f.write("{}")
    odd = os.path.join(config.PROFILES_DIR, "acc_khong_phai_so")
    os.makedirs(odd, exist_ok=True)
    monkeypatch.setattr(browser, "kill_orphan_chrome", lambda path: 0)
    with caplog.at_level(logging.INFO):
        assert browser.cleanup_profiles_on_startup([kept]) == 0
    assert not os.path.isdir(stale), "thư mục profile của nick không còn trong CSDL phải bị dọn"
    assert os.path.isdir(os.path.join(config.PROFILES_DIR, f"acc_{kept}")) and os.path.isdir(odd)
    assert any("xóa được 1/1" in r.getMessage() for r in caplog.records), [r.getMessage() for r in caplog.records]
    # không truyền danh sách nick → chỉ dọn Chrome, không xóa thư mục nào
    os.makedirs(stale, exist_ok=True)
    browser.cleanup_profiles_on_startup()
    assert os.path.isdir(stale)
    # worker._startup đi qua đường có danh sách nick
    src = (ROOT / "worker.py").read_text(encoding="utf-8")
    assert "cleanup_profiles_on_startup(known_ids)" in src


def test_n7_delete_account_uses_retrying_rmtree(client, db, monkeypatch):
    import browser
    acc_id = db.add_account("nick xóa")
    seen = []
    real = browser.remove_dir_with_retry

    def spy(path, *a, **k):
        seen.append(path)
        return real(path, *a, **k)

    monkeypatch.setattr(browser, "remove_dir_with_retry", spy)
    out = client.delete(f"/api/accounts/{acc_id}").json()
    assert out["success"] is True and out["profile_removed"] is True
    assert seen == [os.path.join(config.PROFILES_DIR, f"acc_{acc_id}")]
    assert "shutil.rmtree" not in (ROOT / "app.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- N-8: last_relogin_at trong CSDL
def test_n8_relogin_interval_persisted_in_accounts_table(db, monkeypatch):
    assert "last_relogin_at" in db.columns("accounts"), "migration N-8 phải thêm cột accounts.last_relogin_at"
    assert "_RELOGIN_LAST_AT" not in (ROOT / "dola_service.py").read_text(encoding="utf-8")
    acc_id = db.add_account("nick mất phiên", fb_pass="Matkhau123")
    job_id = db.add_job("job", status=JobStatus.CHO, account_id=acc_id)
    calls = []
    monkeypatch.setattr(dola_service, "_auto_login_locked", lambda acc, headless: (calls.append(acc["id"]) or {"success": False, "message": "fake"}))

    dola_service._relogin_after_session_lost(job_id, db.account(acc_id))
    assert calls == [acc_id]
    stamp = db.account(acc_id)["last_relogin_at"]
    assert stamp and abs((datetime.now() - datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S")).total_seconds()) < 60

    # "khởi động lại app" = không còn gì trong RAM; mốc trong CSDL vẫn chặn lần hai trong 30 phút
    dola_service._relogin_after_session_lost(job_id, db.account(acc_id))
    assert calls == [acc_id], "không được tự đăng nhập lại lần hai trong RELOGIN_MIN_INTERVAL_SECONDS"
    logs = [r["message"] or "" for r in db.system_logs()]
    assert any("không lặp" in m for m in logs), logs
    assert db.account(acc_id)["last_relogin_at"] == stamp

    # quá 30 phút → được thử lại và ghi mốc mới
    old = (datetime.now() - timedelta(seconds=config.RELOGIN_MIN_INTERVAL_SECONDS + 60)).strftime("%Y-%m-%d %H:%M:%S")
    db.exec("UPDATE accounts SET last_relogin_at = ? WHERE id = ?", (old, acc_id))
    dola_service._relogin_after_session_lost(job_id, db.account(acc_id))
    assert calls == [acc_id, acc_id] and db.account(acc_id)["last_relogin_at"] > old


# ---------------------------------------------------------------- G-1: cột thừa ngắn không phải 2FA
@pytest.mark.parametrize("item, bad", [
    ("ABCD2345EFGH6789", True),      # 16 ký tự có 8/9
    ("jbswy3dpehpk3pxp1", True),     # 17 ký tự
    ("JBSWY3DPEHPK3P", True),        # 14 ký tự Base32 thuần (cắt cụt)
    ("Nguyenvan2024", False),        # tên + năm, lẫn hoa/thường, 13 ký tự
    ("nguyenvan2024", False),        # 13 ký tự < 14
    ("Nguyenvanan2024", False),      # 15 ký tự nhưng lẫn hoa/thường
    ("NGUYENVAN20249", True),        # 14 ký tự, toàn hoa, 2 ký tự lạ (0, 9)
    ("NGUYENVAN00189", False),       # 14 ký tự nhưng 4 ký tự lạ
    ("ghichu", False),
    ("1234567890123", False),        # toàn số không phải 2FA
])
def test_g1_looks_like_bad_twofa(item, bad):
    assert account_parser.looks_like_bad_twofa(item) is bad


def test_g1_short_extra_column_goes_to_note_not_error(client, db):
    data = "\n".join([
        "100089274921029|Pass1|Nguyenvan2024",
        "61592837492819|Pass2|ABCD2345EFGH6789",
    ])
    parsed = account_parser.parse_single_account_line("100089274921029|Pass1|Nguyenvan2024")
    assert parsed["twofa"] is None and parsed["twofa_invalid"] is None and parsed["note"] == "Nguyenvan2024"
    r = client.post("/api/accounts/parse-preview", json={"data": data}).json()
    items = {it["line"]: it for it in r["items"]}
    assert items[1]["ok"] is True and items[1]["note"] == "Nguyenvan2024" and items[1]["reason"] == ""
    assert items[2]["ok"] is False and "2FA" in items[2]["reason"] and "sai định dạng" in items[2]["reason"]
    out = client.post("/api/accounts/batch-import", json={"data": data}).json()
    assert out["imported"] == 1 and out["imported_lines"][0]["line"] == 1 and len(out["errors"]) == 1
    assert "Bỏ qua cột thừa" in (ROOT / "static/js/app.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------- G-2: nick bận khi quét
def _spy_diagnose(monkeypatch, on_call=None):
    counts = {}
    real = diagnostics.diagnose_account

    def spy(account_id):
        counts[account_id] = counts.get(account_id, 0) + 1
        if on_call:
            on_call(account_id, counts[account_id])
        return real(account_id)

    monkeypatch.setattr(diagnostics, "diagnose_account", spy)
    return counts


def _wait_scan_done(timeout=60):
    return wait_until(lambda: (lambda s: s if not s["running"] else None)(diagnostics.scan_status()), timeout, what="quét xong")


def test_g2_busy_account_retried_once_then_counted_as_busy(db, fake_dola, monkeypatch, scan_finished):
    from account_pool import AccountPool
    monkeypatch.setattr(diagnostics, "SCAN_BUSY_RETRY_DELAY", 0.5)
    busy = db.add_account("nick bận", with_session=False)
    free = db.add_account("nick rảnh", with_session=False)
    counts = _spy_diagnose(monkeypatch)
    pool = AccountPool.get()
    assert pool.acquire(busy, 7)
    try:
        out = diagnostics.start_scan_all([busy, free])
        assert out["success"] is True and out["total"] == 2
        st = _wait_scan_done()
    finally:
        pool.release(busy)
    assert st["done"] == 2 and st["summary"]["busy"] == 1 and st["summary"]["error"] == 0, st["summary"]
    assert st["results"][str(busy)]["category"] == "busy" and "đang bận" in st["results"][str(busy)]["summary"]
    assert st["results"][str(free)]["category"] == "need_login"
    assert counts[busy] == 2, "nick bận phải được xếp lại cuối hàng và thử đúng một lần nữa"
    assert counts[free] == 1
    assert diagnostics.classify_diagnosis({"success": False, "busy": True, "steps": [], "summary": "x"}) == "busy"
    assert "busy" in diagnostics.SCAN_CATEGORIES
    logs = [r["message"] or "" for r in db.system_logs()]
    assert any("Quét tất cả nick xong" in m and "đang bận 1" in m for m in logs), logs


def test_g2_busy_account_free_on_retry_is_scanned_normally(db, fake_dola, monkeypatch, scan_finished):
    from account_pool import AccountPool
    monkeypatch.setattr(diagnostics, "SCAN_BUSY_RETRY_DELAY", 0.5)
    busy = db.add_account("nick bận rồi rảnh", with_session=False)
    other = db.add_account("nick khác", with_session=False)
    pool = AccountPool.get()
    assert pool.acquire(busy, 7)

    def release_after_first(account_id, n):
        if account_id == busy and n == 2:
            pool.release(busy)

    counts = _spy_diagnose(monkeypatch, release_after_first)
    try:
        assert diagnostics.start_scan_all([busy, other])["success"] is True
        st = _wait_scan_done()
    finally:
        if pool.is_busy(busy):
            pool.release(busy)
    assert counts[busy] == 2 and st["done"] == 2
    assert st["summary"]["busy"] == 0 and st["results"][str(busy)]["category"] == "need_login", st
    assert "busy" in (ROOT / "static/js/app.js").read_text(encoding="utf-8").split("SCAN_LABELS")[1][:600]


# ---------------------------------------------------------------- G-3
def test_g3_app_uses_account_status_constant_not_literal():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    sql_lines = [l for l in src.splitlines() if "'ready'" in l and ("status" in l.lower()) and "ACCOUNT_STATUS_FILTERS" not in l
                 and 'status == "ready"' not in l and "if status == 'ready'" not in l]
    assert not sql_lines, "G-3: SQL trong app.py phải dùng AccountStatus.READY:\n" + "\n".join(sql_lines)
    assert "AccountStatus.READY" in src
