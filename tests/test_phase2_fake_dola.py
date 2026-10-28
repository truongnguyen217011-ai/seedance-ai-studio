"""
Giai đoạn 2 — test tích hợp (worker thật + Chromium + fake Dola + fake proxy): A4 (proxy theo nick), A5 (proxy chết),
K4 (đọc credit từ văn bản chain), K7 (mất phiên giữa job → tự đăng nhập lại một lần), K9 (quét tất cả không vượt
giới hạn Chrome).
"""
from __future__ import annotations

import os
import time

import pytest

from constants import JobStatus, NeedsManual, Reason
from _helpers import Sampler, TODAY, get_active_browser_count, log_offsets, new_log_text, wait_jobs_finished, wait_until

pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]

for _m in ("logger", "browser", "account_pool", "worker", "dola_service"):
    pytest.importorskip(_m, reason=f"{_m}.py chưa có")


def _assert_completed(db, job_ids, timeout):
    jobs = wait_jobs_finished(db, job_ids, timeout)
    bad = {jid: (j["status"], j["status_message"]) for jid, j in jobs.items() if j["status"] != JobStatus.HOAN_THANH}
    assert not bad, f"job không Hoàn thành: {bad}"
    for jid, j in jobs.items():
        path = db.video_file(j)
        assert path and os.path.getsize(path) > 50000, f"job #{jid}: video thiếu/quá nhỏ"
    return jobs


# ---------------------------------------------------------------- A4
def test_a4_job_check_credit_and_diagnose_go_through_account_proxy(db, fake_dola, fake_proxy, worker_runner):
    import dola_service
    fake_dola.control(render_seconds=2, credits=4)
    acc_id = db.add_account("nick có proxy", proxy=fake_proxy.address)
    job_id = db.add_job("A4 job qua proxy")

    worker_runner.start()
    jobs = _assert_completed(db, [job_id], timeout=120)
    assert jobs[job_id]["account_id"] == acc_id
    assert fake_proxy.count("/chat/", "GET") >= 1, fake_proxy.requests
    assert fake_proxy.count("/im/chain/single", "POST") >= 1, "poll chain phải đi qua proxy"
    assert fake_proxy.count("/video/tos/", "GET") == 1, "tải video phải đi qua proxy của nick (A4)"
    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả")
    assert db.account(acc_id)["credits"] == 3

    # Check credit tay cũng qua proxy
    before = fake_proxy.count("/chat/", "GET")
    res = dola_service._check_account_credits_sync(acc_id)
    assert res["success"] is True and res["credits"] == 3, res
    assert fake_proxy.count("/chat/", "GET") == before + 1

    # Chẩn đoán: bước proxy hỏi IP qua proxy (ghi last_ip), bước credit mở Chrome qua proxy
    import diagnostics
    ip_before = fake_proxy.count("/__ip")
    before = fake_proxy.count("/chat/", "GET")
    out = diagnostics.diagnose_account(acc_id)
    steps = {s["key"]: s for s in out["steps"]}
    assert steps["proxy"]["ok"] is True and "IP ra ngoài" in steps["proxy"]["detail"], steps["proxy"]
    assert steps["credits"]["ok"] is True, steps["credits"]
    assert fake_proxy.count("/__ip") == ip_before + 1
    assert fake_proxy.count("/chat/", "GET") == before + 1
    acc = db.account(acc_id)
    assert acc["last_ip"] == "127.0.0.1" and acc["needs_manual"] is None
    assert fake_dola.get_state()["chat_get_count"] >= 3


# ---------------------------------------------------------------- A5
def test_a5_dead_proxy_flags_account_job_waits_then_other_account_runs(db, fake_dola, worker_runner):
    from fake_proxy import closed_port
    fake_dola.control(render_seconds=2, credits=4)
    dead_id = db.add_account("nick proxy chết", proxy=f"127.0.0.1:{closed_port()}")
    job_id = db.add_job("A5 job")
    offsets = log_offsets(worker_runner.env)

    worker_runner.start()
    wait_until(lambda: db.account(dead_id)["needs_manual"] == NeedsManual.PROXY, 90, what="nick bị gắn cờ proxy")
    job = wait_until(lambda: (lambda j: j if j["status"] != JobStatus.DANG_CHAY else None)(db.job(job_id)), 60,
                     what="job rời Đang chạy")
    assert job["status"] == JobStatus.CHO, job
    assert "proxy" in (job["status_message"] or "").lower(), job["status_message"]
    assert job["attempts"] == 0, "lỗi proxy là lỗi của nick, không tính lượt của job"
    acc = db.account(dead_id)
    assert "ERR_PROXY" in (acc["last_error"] or "") or "không phản hồi" in (acc["last_error"] or ""), acc["last_error"]
    logs = [r["message"] or "" for r in db.system_logs()]
    assert any(m.startswith("Job #%d: Proxy của nick 'nick proxy chết' không phản hồi" % job_id) for m in logs), logs
    assert not any("kết nối trực tiếp" in m for m in logs), "BH-50: không được chuyển lặng lẽ sang kết nối trực tiếp"
    assert fake_dola.get_state()["chat_get_count"] == 0, "nick proxy chết không được chạm tới Dola bằng IP thật"
    wait_until(lambda: db.account(dead_id)["busy_job_id"] is None, 30, what="nick được trả")
    time.sleep(6)
    assert db.job(job_id)["status"] == JobStatus.CHO
    assert fake_dola.get_state()["chat_get_count"] == 0
    assert "proxy lỗi" in (db.job(job_id)["status_message"] or "") or "Proxy của nick" in (db.job(job_id)["status_message"] or "")
    assert "thử kết nối trực tiếp" not in new_log_text(worker_runner.env, offsets)

    # Thêm nick tốt → worker chọn nick khác, job hoàn thành; nick proxy chết vẫn giữ cờ
    good_id = db.add_account("nick tốt")
    jobs = _assert_completed(db, [job_id], timeout=120)
    assert jobs[job_id]["account_id"] == good_id
    assert db.account(dead_id)["needs_manual"] == NeedsManual.PROXY
    assert fake_dola.get_state()["chat_get_count"] == 1


# ---------------------------------------------------------------- K4
def test_k4_credits_after_render_read_from_chain_text(db, fake_dola, worker_runner, monkeypatch):
    """Trang không đọc được credit (giả lập) nhưng chain có "will use 1 video credits ... only have N left today"
    → credits/credits_date ghi theo chain; câu đó không bị coi là Dola trả lời bằng chữ."""
    import dola_service
    fake_dola.control(render_seconds=2, credits=4, credits_in_chain=True)
    monkeypatch.setattr(dola_service, "extract_dola_credits", lambda page: None)
    acc_id = db.add_account("nick credit chain")
    job_id = db.add_job("K4 job")
    offsets = log_offsets(worker_runner.env)

    worker_runner.start()
    jobs = _assert_completed(db, [job_id], timeout=120)
    assert jobs[job_id]["dola_reply"] is None, jobs[job_id]["dola_reply"]
    acc = wait_until(lambda: (lambda a: a if a["credits"] is not None else None)(db.account(acc_id)), 30, what="credit được ghi")
    assert acc["credits"] == 3 and acc["credits_date"] == TODAY, acc
    assert acc["last_error"] is None, acc["last_error"]
    assert "Đọc credit còn lại từ văn bản chain: 3" in new_log_text(worker_runner.env, offsets)


# ---------------------------------------------------------------- K7
def test_k7_session_lost_mid_job_auto_relogin_once(db, fake_dola, worker_runner, monkeypatch):
    """Fake Dola không nhận phiên (xóa cookie sessionid) → job về Chờ, nick needs_manual='login', tool tự Auto Login
    đúng một lần (fake không có Facebook → thất bại trong LOGIN_TIMEOUT), cờ vẫn còn, không lặp."""
    import config
    monkeypatch.setattr(config, "LOGIN_TIMEOUT_SECONDS", 6)
    fake_dola.control(session_valid=False, credits=4)
    acc_id = db.add_account("nick mất phiên", fb_pass="Matkhau123")
    job_id = db.add_job("K7 job")

    worker_runner.start()
    wait_until(lambda: db.account(acc_id)["needs_manual"] == NeedsManual.LOGIN, 90, what="nick cần đăng nhập lại")
    job = wait_until(lambda: (lambda j: j if j["status"] != JobStatus.DANG_CHAY else None)(db.job(job_id)), 60,
                     what="job rời Đang chạy")
    assert job["status"] == JobStatus.CHO and job["attempts"] == 0, job
    assert "mất phiên" in (job["status_message"] or "") or "cần đăng nhập lại" in (job["status_message"] or ""), job["status_message"]
    assert db.account(acc_id)["has_dola"] == 0

    def _relogin_done():
        msgs = [r["message"] or "" for r in db.system_logs() if r["account_id"] == acc_id]
        return msgs if any("tự đăng nhập lại thất bại" in m or "tự đăng nhập lại thành công" in m for m in msgs) else None

    msgs = wait_until(_relogin_done, 120, what="log tự đăng nhập lại")
    assert any("tự đăng nhập lại một lần" in m for m in msgs), msgs
    assert sum("tự đăng nhập lại một lần" in m for m in msgs) == 1, msgs
    assert any("tự đăng nhập lại thất bại" in m for m in msgs), msgs
    acc = db.account(acc_id)
    assert acc["needs_manual"] == NeedsManual.LOGIN and acc["has_dola"] == 0, acc
    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả")
    opens = fake_dola.get_state()["chat_get_count"]
    assert opens == 2, f"1 lần của job + 1 lần auto login, có {opens}"
    time.sleep(8)
    assert fake_dola.get_state()["chat_get_count"] == opens, "không được lặp job ↔ auto login"
    assert db.job(job_id)["status"] == JobStatus.CHO
    assert "cần đăng nhập lại" in (db.job(job_id)["status_message"] or ""), db.job(job_id)["status_message"]
    assert get_active_browser_count() in (0, None)


# ---------------------------------------------------------------- K9
@pytest.fixture
def scan_finished():
    """Dù test đỏ giữa chừng, không để đợt quét nền chạy sang test sau (giữ pool/CSDL của test khác)."""
    import diagnostics
    yield
    deadline = time.time() + 120
    while diagnostics.scan_status()["running"] and time.time() < deadline:
        time.sleep(0.5)


def test_k9_scan_all_respects_chrome_limit_and_finishes(db, fake_dola, worker_runner, scan_finished):
    import browser
    import diagnostics
    db.set_setting("max_concurrent_jobs", 2)
    browser.SLOTS.resize(2)
    fake_dola.control(credits=4)
    ids = [db.add_account(f"nick quét {i + 1}") for i in range(8)]

    with Sampler(db) as sampler:
        out = diagnostics.start_scan_all()
        assert out["success"] is True and out["total"] == 8 and out["workers"] == 2, out
        again = diagnostics.start_scan_all()
        assert again["success"] is False and "Đang quét dở" in again["message"], again
        st = wait_until(lambda: (lambda s: s if not s["running"] else None)(diagnostics.scan_status()), 170,
                        what="quét xong (running=False)")
    assert st["done"] == 8 and st["total"] == 8 and st["finished_at"], st
    assert st["summary"]["ready"] == 8, st["summary"]
    assert st["summary"]["proxy_dead"] == 0 and st["summary"]["need_login"] == 0 and st["summary"]["no_credit"] == 0
    assert set(map(int, st["results"].keys())) == set(ids)
    assert sampler.active_seen and sampler.max_active <= 2, f"active_count lên tới {sampler.max_active} (giới hạn 2)"
    for acc_id in ids:
        acc = db.account(acc_id)
        assert acc["credits"] == 4 and acc["last_check"] and acc["busy_job_id"] is None, acc
    assert fake_dola.get_state()["chat_get_count"] == 8
    assert any("Quét tất cả nick xong: 8 nick" in (r["message"] or "") for r in db.system_logs())


# ---------------------------------------------------------------- N-4 / BH-59: ERR_TUNNEL với proxy còn sống
@pytest.mark.timeout(170)
def test_bh59_err_tunnel_with_live_proxy_does_not_flag_proxy(db, fake_dola, fake_proxy, worker_runner, monkeypatch):
    """Fake proxy trả 502 cho CONNECT (Chromium báo net::ERR_TUNNEL_CONNECTION_FAILED khi mở Dola qua https) trong khi
    GET http /__ip qua proxy vẫn OK → proxy SỐNG, lỗi ở Dola/đường ra: nick KHÔNG needs_manual='proxy', job đi đường
    lỗi kỹ thuật thường ("tự chạy lại lần n/N") rồi Thất bại sau 3 lượt."""
    import config
    fake_dola.control(render_seconds=2, credits=4)
    fake_proxy.set_connect_status(502)
    # Dola "https" để Chromium phải CONNECT qua proxy (fake Dola chỉ nói http nên CONNECT luôn bị 502 → ERR_TUNNEL_*)
    monkeypatch.setattr(config, "DOLA_CHAT_URL", f"https://127.0.0.1:{fake_dola.port}/chat/")
    acc_id = db.add_account("nick proxy sống", proxy=fake_proxy.address)
    job_id = db.add_job("BH-59 job")

    worker_runner.start()
    job = wait_until(lambda: (lambda j: j if j["status"] == JobStatus.THAT_BAI else None)(db.job(job_id)), 150,
                     what="job Thất bại sau 3 lượt tự chạy lại")
    assert "ERR_TUNNEL_CONNECTION_FAILED" in (job["status_message"] or ""), job["status_message"]
    assert "Đã thử 3 lần" in job["status_message"] and job["attempts"] == 3, job
    acc = db.account(acc_id)
    assert acc["needs_manual"] is None, f"BH-59: proxy còn trả lời IP thì không được gắn cờ proxy: {acc}"
    assert fake_proxy.count("", "CONNECT") >= 3, fake_proxy.requests
    assert fake_proxy.count("/__ip") >= 3, "mỗi lần lỗi phải hỏi IP qua proxy trước khi kết luận"
    logs = [r["message"] or "" for r in db.system_logs()]
    assert any("vẫn phản hồi" in m and "không gắn cờ proxy" in m for m in logs), logs
    assert not any("Proxy của nick 'nick proxy sống' không phản hồi" in m for m in logs), logs
    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả")
