"""
Giai đoạn 2 — test đơn vị (không Chrome): A5 (proxy chết), K2 (sai mật khẩu/checkpoint), K3 (cookie theo nội dung),
K4 (đọc credit từ văn bản chain), K6 (hết rest_until → worker gỡ cờ), K8 (chờ tới khi không còn tab), K9 (xếp loại),
BH-50 (không còn chuyển lặng lẽ sang kết nối trực tiếp).
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

import config
import diagnostics
import dola_service
from constants import AccountStatus, JobStatus, NeedsManual, Reason

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_pool():
    """Pool nick và _running_jobs là singleton trong tiến trình: dọn trước/sau mỗi test để không dính test khác."""
    import worker
    from account_pool import AccountPool
    AccountPool.get().clear()
    worker._running_jobs.clear()
    yield
    AccountPool.get().clear()
    worker._running_jobs.clear()


# ---------------------------------------------------------------- A5 / BH-50
def test_bh50_no_silent_proxy_fallback_in_source():
    src = (ROOT / "dola_service.py").read_text(encoding="utf-8")
    assert "_open_with_proxy_fallback" not in src, "BH-50: không được lặng lẽ chuyển sang kết nối trực tiếp khi proxy hỏng"
    assert "thử kết nối trực tiếp" not in src
    assert re.search(r"proxy=None", src) is None, "không mở Chrome của nick với proxy=None khi nick có proxy"


@pytest.mark.parametrize("text, code", [
    ("page.goto: net::ERR_PROXY_CONNECTION_FAILED at http://127.0.0.1:1/chat/", "ERR_PROXY_CONNECTION_FAILED"),
    ("net::ERR_TUNNEL_CONNECTION_FAILED", "ERR_TUNNEL_CONNECTION_FAILED"),
    ("net::ERR_SOCKS_CONNECTION_FAILED", "ERR_SOCKS_CONNECTION_FAILED"),
    ("net::ERR_EMPTY_RESPONSE", None),
    ("Timeout 60000ms exceeded", None),
])
def test_a5_proxy_error_text(text, code):
    assert dola_service.proxy_error_text(Exception(text)) == code


def test_a5_proxy_dead_marks_account_and_requeues_job_without_counting_attempt(db):
    acc_id = db.add_account("nick proxy chết", proxy="1.2.3.4:8080:user:secretpw")
    job_id = db.add_job("job", status=JobStatus.DANG_CHAY, account_id=acc_id, attempts=1)
    acc = db.account(acc_id)
    dola_service._apply_technical_failure(job_id, acc, Exception("page.goto: net::ERR_PROXY_CONNECTION_FAILED at x"), None, False)
    job = db.job(job_id)
    assert job["status"] == JobStatus.CHO and job["attempts"] == 0
    assert job["status_message"] == Reason.PROXY_DEAD.format(name="nick proxy chết", error="ERR_PROXY_CONNECTION_FAILED")
    acc = db.account(acc_id)
    assert acc["needs_manual"] == NeedsManual.PROXY and acc["status"] == AccountStatus.READY
    assert "ERR_PROXY_CONNECTION_FAILED" in acc["last_error"] and "1.2.3.4:8080:user:***" in acc["last_error"]
    assert "secretpw" not in acc["last_error"]
    # nick không được chọn cho job
    from account_pool import select_account_for_job
    chosen, summary = select_account_for_job(db.job(job_id))
    assert chosen is None and "1 nick proxy lỗi" in summary
    # lỗi proxy ở nick KHÔNG có proxy → đi đường lỗi kỹ thuật thường (không gán cờ proxy)
    acc2_id = db.add_account("nick không proxy")
    job2 = db.add_job("job 2", status=JobStatus.DANG_CHAY, account_id=acc2_id, attempts=1)
    dola_service._apply_technical_failure(job2, db.account(acc2_id), Exception("net::ERR_PROXY_CONNECTION_FAILED"), None, False)
    assert db.account(acc2_id)["needs_manual"] is None and "tự chạy lại lần 1" in db.job(job2)["status_message"]


def test_a5_diagnostics_proxy_step_via_fake_proxy_and_dead_port(db, fake_dola, fake_proxy):
    from fake_proxy import closed_port
    acc = {"id": 1, "name": "n", "proxy": fake_proxy.address}
    step = diagnostics._check_proxy(acc)
    assert step["ok"] is True and "IP ra ngoài: 127.0.0.1" in step["detail"], step
    assert fake_proxy.count("/__ip") == 1, fake_proxy.requests
    dead = {"id": 2, "name": "n2", "proxy": f"127.0.0.1:{closed_port()}"}
    step = diagnostics._check_proxy(dead)
    assert step["ok"] is False and "không phản hồi" in step["detail"], step
    none = diagnostics._check_proxy({"id": 3, "name": "n3", "proxy": ""})
    assert none["ok"] is None and "IP máy: 127.0.0.1" in none["detail"], none


def test_a4_parse_proxy_carries_bypass_from_config(monkeypatch):
    monkeypatch.setattr(config, "PROXY_BYPASS_LIST", "<-loopback>")
    cfg = dola_service.parse_proxy("1.2.3.4:8080:u:p")
    assert cfg == {"server": "http://1.2.3.4:8080", "username": "u", "password": "p", "bypass": "<-loopback>"}
    monkeypatch.setattr(config, "PROXY_BYPASS_LIST", "")
    assert "bypass" not in dola_service.parse_proxy("1.2.3.4:8080")
    assert dola_service.parse_proxy("") is None


# ---------------------------------------------------------------- K2
@pytest.mark.parametrize("text", [
    "The password you've entered is incorrect. Forgot password?",
    "Mật khẩu bạn đã nhập không đúng",
    "The email or mobile number you entered isn't connected to an account",
])
def test_k2_wrong_password_regex(text):
    assert dola_service.RE_WRONG_PASS.search(text)


@pytest.mark.parametrize("text", [
    "https://www.facebook.com/checkpoint/1501092823525282/",
    "Confirm your identity to continue",
    "Tài khoản của bạn đã bị khóa",
    "Please upload a photo of your ID",
])
def test_k2_checkpoint_regex(text):
    assert dola_service.RE_CHECKPOINT.search(text)


def test_k2_normal_page_not_flagged():
    for text in ("Welcome to Facebook. Log in to continue", "Tiếp tục dưới tên Nguyễn Văn A"):
        assert not dola_service.RE_WRONG_PASS.search(text) and not dola_service.RE_CHECKPOINT.search(text)


def test_k2_mark_login_blocked_sets_flag_and_pool_skips(db):
    from account_pool import select_account_for_job
    acc_id = db.add_account("nick sai pass")
    acc = db.account(acc_id)
    msg = dola_service._mark_login_blocked(acc, "Sai mật khẩu Facebook", None, "wrong_password")
    row = db.account(acc_id)
    assert row["needs_manual"] == NeedsManual.LOGIN and row["last_error"].startswith("Sai mật khẩu Facebook") and row["last_check"]
    assert msg.startswith("Sai mật khẩu Facebook")
    chosen, summary = select_account_for_job(db.job(db.add_job("j")))
    assert chosen is None and "1 nick cần đăng nhập lại" in summary
    assert any("Sai mật khẩu Facebook" in r["message"] and r["account_id"] == acc_id for r in db.system_logs())


def test_k1_auto_login_timeout_updates_last_check_source():
    src = (ROOT / "dola_service.py").read_text(encoding="utf-8")
    i = src.index('"login_timeout"')
    assert "last_check=_now_str()" in src[i:i + 600], "K1: hết giờ đăng nhập vẫn phải cập nhật last_check"


# ---------------------------------------------------------------- K3
def test_k3_parse_cookies_by_content():
    dola = config.DOLA_DOMAIN
    out = dola_service.parse_cookies_by_content("sessionid=abc; sessionid_ss=abc", ".facebook.com")
    assert {c["domain"] for c in out} == {dola} and {c["name"] for c in out} == {"sessionid", "sessionid_ss"}
    assert dola_service.has_dola_session(out)
    out = dola_service.parse_cookies_by_content("c_user=1; xs=2; datr=3", dola)
    assert {c["domain"] for c in out} == {".facebook.com"} and not dola_service.has_dola_session(out)
    mixed = {c["name"]: c["domain"] for c in dola_service.parse_cookies_by_content("c_user=1; xs=2; sessionid=abc; foo=bar", ".facebook.com")}
    assert mixed == {"c_user": ".facebook.com", "xs": ".facebook.com", "sessionid": dola, "foo": dola}  # có sessionid → chuỗi là Dola
    unknown = dola_service.parse_cookies_by_content("foo=bar; baz=1", ".google.com")
    assert {c["domain"] for c in unknown} == {".google.com"}
    raw = json.dumps([{"name": "sessionid", "value": "v", "domain": ".dola.com"}, {"name": "c_user", "value": "1", "domain": ".facebook.com"}])
    kept = {c["name"]: c["domain"] for c in dola_service.parse_cookies_by_content(raw, ".facebook.com")}
    assert kept == {"sessionid": ".dola.com", "c_user": ".facebook.com"}
    assert dola_service.parse_cookies_by_content("", ".facebook.com") == []


def test_k3_detect_cookie_kind():
    from parser import detect_cookie_kind
    assert detect_cookie_kind("sessionid=abc; sid_tt=x") == "dola"
    assert detect_cookie_kind("c_user=1; xs=2") == "facebook"
    assert detect_cookie_kind(json.dumps([{"name": "sessionid", "value": "v", "domain": ".dola.com"}])) == "dola"
    assert detect_cookie_kind(json.dumps([{"name": "foo", "value": "v", "domain": ".x.com"}])) == "json"
    assert detect_cookie_kind("foo=bar") is None and detect_cookie_kind("") is None


# ---------------------------------------------------------------- K4
@pytest.mark.parametrize("text, expected", [
    ("This will use 1 video credits, you only have 3 left today", 3),
    ("This will use 2 video credits. Note: you only have 0 left today.", 0),
    ("You have 4 video credits left", 4),
    ("you have 2 credits remaining", 2),
    ("Bạn cần dùng 1 điểm tín dụng video, hiện chỉ còn 5", 5),
    ("You have reached the daily limit for video generation", 0),
    ("Generating video...", None),
    ("", None),
])
def test_k4_extract_credits_from_text(text, expected):
    assert dola_service.extract_credits_from_text(text) == expected


def test_k4_credit_info_text_not_treated_as_reply():
    assert dola_service._is_credit_info_text("This will use 1 video credits, you only have 3 left today")
    assert not dola_service._is_credit_info_text("Which aspect ratio would you like? You have 3 credits left?")
    assert not dola_service._is_credit_info_text("I cannot create that video")


# ---------------------------------------------------------------- K6
def test_k6_worker_tick_clears_expired_rest(db):
    import worker
    from account_pool import AccountPool, select_account_for_job
    worker._running_jobs.clear()
    AccountPool.get().clear()
    acc_id = db.add_account("nick nghỉ xong")
    db.exec("UPDATE accounts SET rest_until = '2000-01-01 00:05:00', rest_reason = 'Hết lượt trong ngày', "
            "credits = 0, credits_date = '2000-01-01' WHERE id = ?", (acc_id,))
    assert db.account(acc_id)["rest_until"] is not None
    worker._tick()  # một vòng quét là đủ gỡ cờ nghỉ đã hết hạn (_recover_accounts)
    acc = db.account(acc_id)
    assert acc["rest_until"] is None and acc["rest_reason"] is None
    chosen, _ = select_account_for_job({"id": 0})
    assert chosen is not None and chosen["id"] == acc_id


# ---------------------------------------------------------------- K8
class _FakePage:
    def __init__(self, closed):
        self._closed = closed

    def is_closed(self):
        return self._closed


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages


def test_k8_context_has_open_page_until_last_tab_closed():
    assert dola_service._context_has_open_page(_FakeContext([_FakePage(True), _FakePage(False)]))
    assert not dola_service._context_has_open_page(_FakeContext([]))
    assert not dola_service._context_has_open_page(_FakeContext([_FakePage(True)]))

    class _Broken:
        @property
        def pages(self):
            raise RuntimeError("Target closed")

    assert not dola_service._context_has_open_page(_Broken())
    src = (ROOT / "dola_service.py").read_text(encoding="utf-8")
    i = src.index("def _launch_login_session_sync(")
    body = src[i:src.index("def _context_has_open_page(")]
    assert "while _context_has_open_page(context):" in body
    assert "not page.is_closed()" not in body, "K8: không thoát khi chỉ tab đầu đóng"


# ---------------------------------------------------------------- K9
def _res(proxy_ok, session_ok, credits_ok, credits_detail=""):
    steps = [{"key": "proxy", "name": "Proxy", "ok": proxy_ok, "detail": ""},
             {"key": "chrome", "name": "Chrome", "ok": True, "detail": ""},
             {"key": "dola_session", "name": "Phiên Dola", "ok": session_ok, "detail": ""}]
    if credits_ok != "missing":
        steps.append({"key": "credits", "name": "Credit Dola", "ok": credits_ok, "detail": credits_detail})
    return {"success": True, "steps": steps, "summary": ""}


def test_k9_classify_diagnosis():
    assert diagnostics.classify_diagnosis(_res(None, True, True, "còn 3 credit")) == "ready"
    assert diagnostics.classify_diagnosis(_res(False, True, True)) == "proxy_dead"
    assert diagnostics.classify_diagnosis(_res(None, False, None, "Bỏ qua vì chưa có phiên Dola")) == "need_login"
    assert diagnostics.classify_diagnosis(_res(True, True, False, "Phiên Dola hợp lệ nhưng đã hết credit hôm nay")) == "no_credit"
    assert diagnostics.classify_diagnosis(_res(True, True, False, "Dola đang yêu cầu kéo mảnh ghép (captcha)")) == "captcha"
    assert diagnostics.classify_diagnosis(_res(True, True, False, "Trang Dola không nhận phiên đăng nhập")) == "need_login"
    assert diagnostics.classify_diagnosis(_res(True, True, False, "Proxy '1.2.3.4:1' không phản hồi (ERR_PROXY_CONNECTION_FAILED)")) == "proxy_dead"
    assert diagnostics.classify_diagnosis(_res(True, True, None, "Không đọc được số credit")) == "unknown"
    assert diagnostics.classify_diagnosis(_res(True, True, "missing")) == "unknown"
    assert diagnostics.classify_diagnosis({"success": False, "steps": [], "summary": "bận"}) == "error"


# ---------------------------------------------------------------- A7: has_dola theo đường ghi phiên
def test_a7_has_dola_written_with_storage_state_and_connected(db):
    acc_id = db.add_account("nick", with_session=False)
    assert db.account(acc_id)["has_dola"] == 0
    cookies = json.loads(db.fake_cookies("sid-1"))
    dola_service.save_account_storage_state(acc_id, cookies)
    assert db.account(acc_id)["has_dola"] == 1
    dola_service.save_account_storage_state(acc_id, [{"name": "foo", "value": "x", "domain": ".x.com", "path": "/"}])
    assert db.account(acc_id)["has_dola"] == 0
    dola_service._mark_account_connected(acc_id, cookies)
    assert db.account(acc_id)["has_dola"] == 1 and db.account(acc_id)["consecutive_errors"] == 0
    dola_service._mark_session_lost(db.account(acc_id), None, None)
    row = db.account(acc_id)
    assert row["has_dola"] == 0 and row["needs_manual"] == NeedsManual.LOGIN
