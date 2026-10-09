"""
Test tích hợp: worker thật + dola_service thật + Chromium thật + fake Dola (docs/KIEN_TRUC.md mục 6, 7).

Chạy: python -m pytest tests -q -m integration     (mỗi test ≤ 180s; cần pytest-timeout để cưỡng bức)
Mọi tên API chưa chắc đi qua tests/_helpers.py.
"""
import os
import time

import pytest

from constants import AccountStatus, JobStatus, NeedsManual, Reason
from _helpers import (Sampler, conv_id_in_mp4, get_active_browser_count, log_offsets, new_log_text,
                      wait_jobs_finished, wait_until)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]

for _m in ("logger", "browser", "account_pool", "worker", "dola_service"):
    pytest.importorskip(_m, reason=f"{_m}.py chưa có")

Q8_JOBS = int(os.environ.get("SEEDANCE_TEST_Q8_JOBS", "20"))


@pytest.fixture(autouse=True)
def _require_new_backend(db):
    if not hasattr(db.database, "reset_orphans_on_startup"):
        pytest.skip("database.reset_orphans_on_startup chưa có (backend giai đoạn 1 chưa xong)")
    import dola_service
    import config
    src = open(dola_service.__file__, encoding="utf-8").read()
    if "www.dola.com/chat" in src and "DOLA_CHAT_URL" not in src:
        pytest.skip("dola_service.py vẫn hard-code https://www.dola.com (chưa dùng config.DOLA_CHAT_URL)")
    assert os.path.exists(os.environ["SEEDANCE_CHROME_PATH"]), "thiếu Chromium cho test tích hợp"
    assert config.DOLA_BASE_URL.startswith("http://127.0.0.1:")


def _assert_completed(db, job_ids, timeout):
    jobs = wait_jobs_finished(db, job_ids, timeout)
    bad = {jid: (j["status"], j["status_message"]) for jid, j in jobs.items() if j["status"] != JobStatus.HOAN_THANH}
    assert not bad, f"job không Hoàn thành: {bad}"
    for jid, j in jobs.items():
        path = db.video_file(j)
        assert path, f"job #{jid}: không tìm thấy file video từ local_video_path={j['local_video_path']!r}"
        assert os.path.getsize(path) > 50000, f"job #{jid}: file {path} quá nhỏ"
    return jobs


# ---------------------------------------------------------------- Q1
def test_q1_never_more_than_max_concurrent_chrome(db, fake_dola, worker_runner):
    db.set_setting("max_concurrent_jobs", 2)
    fake_dola.control(render_seconds=2, credits=10)
    for i in range(4):
        db.add_account(f"nick{i + 1}")
    job_ids = [db.add_job(f"Q1 job {i + 1}") for i in range(6)]

    with Sampler(db) as sampler:
        worker_runner.start()
        jobs = _assert_completed(db, job_ids, timeout=170)

    assert sampler.max_running <= 2, f"có lúc {sampler.max_running} job Đang chạy cùng lúc (giới hạn 2)"
    if sampler.active_seen:
        assert sampler.max_active <= 2, f"BrowserSlots.active_count() lên tới {sampler.max_active} (giới hạn 2)"
    st = fake_dola.get_state()
    assert len(st["conversations"]) == 6
    assert st["chat_get_count"] >= 6
    assert len({j["local_video_path"] for j in jobs.values()}) == 6


# ---------------------------------------------------------------- Q2/Q3
def test_q2_q3_one_account_one_job_and_all_accounts_used(db, fake_dola, worker_runner):
    db.set_setting("max_concurrent_jobs", 3)
    fake_dola.control(render_seconds=2, credits=10)
    acc_ids = [db.add_account(f"nick{i + 1}") for i in range(3)]
    job_ids = [db.add_job(f"Q2 job {i + 1}") for i in range(5)]

    with Sampler(db) as sampler:
        worker_runner.start()
        jobs = _assert_completed(db, job_ids, timeout=170)

    assert not sampler.duplicate_account_samples, \
        f"có lúc 2 job Đang chạy cùng account_id: {sampler.duplicate_account_samples[:3]}"
    used = {j["account_id"] for j in jobs.values()}
    assert used == set(acc_ids), f"nick được dùng {used}, kỳ vọng cả 3 nick {acc_ids}"
    assert sampler.max_running <= 3
    # BH-26: nick được trả SAU khi Chrome đóng (worker finally), muộn hơn lúc job ghi Hoàn thành → phải chờ
    wait_until(lambda: all(db.account(a)["busy_job_id"] is None for a in acc_ids), 30,
               what="mọi nick được trả sau khi xong (busy_job_id NULL)")


# ---------------------------------------------------------------- Q4
def test_q4_captcha_pauses_job_and_does_not_reopen_chrome(db, fake_dola, worker_runner, monkeypatch):
    """Captcha hiện sau khi gửi prompt và KHÔNG được giải: chờ tại chỗ CAPTCHA_SOLVE_TIMEOUT_SECONDS (đặt 5 s cho test)
    rồi Tạm dừng + needs_manual='captcha', không mở lại Chrome (BH-04, BH-39)."""
    import config
    monkeypatch.setattr(config, "CAPTCHA_SOLVE_TIMEOUT_SECONDS", 5)
    db.set_setting("max_concurrent_jobs", 2)
    fake_dola.control(mode="captcha")
    acc_id = db.add_account("nick captcha")
    job_id = db.add_job("Q4 job captcha")

    worker_runner.start()
    wait_until(lambda: db.job(job_id)["status"] == JobStatus.TAM_DUNG, 90, what="job về Tạm dừng")
    job = db.job(job_id)
    acc = db.account(acc_id)
    assert acc["needs_manual"] == NeedsManual.CAPTCHA, acc
    assert "captcha" in (job["status_message"] or "").lower() or "mảnh ghép" in (job["status_message"] or ""), job["status_message"]
    assert "captcha_container" in (acc["last_error"] or ""), acc["last_error"]  # BH-38: dấu hiệu thật được ghi
    messages = [r["message"] or "" for r in db.system_logs()]
    assert any("Dola yêu cầu kéo mảnh ghép" in m and "5 giây" in m for m in messages), messages
    assert any("captcha vẫn còn" in m for m in messages), messages
    # BH-26: nick được trả sau khi Chrome đóng, muộn hơn lúc job ghi Tạm dừng → chờ thay vì assert ngay
    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả (busy_job_id NULL)")

    opens_before = fake_dola.get_state()["chat_get_count"]
    assert opens_before >= 1
    time.sleep(20)
    st = fake_dola.get_state()
    assert st["chat_get_count"] == opens_before, "worker vẫn mở Chrome lại sau khi Tạm dừng vì captcha (BH-04)"
    assert db.job(job_id)["status"] == JobStatus.TAM_DUNG
    assert get_active_browser_count() in (0, None)


# ---------------------------------------------------------------- BH-39: captcha được kéo tại chỗ, job chạy tiếp
def test_captcha_solved_in_place_job_completes(db, fake_dola, worker_runner, monkeypatch):
    """Captcha hiện sau khi gửi prompt, người dùng kéo xong sau 6 s (fake tự giải): job KHÔNG Tạm dừng, gửi lại prompt
    một lần, Hoàn thành với mp4 > 50 KB; nick không bị needs_manual.

    Test chạy config.HEADLESS (không có cửa sổ) nên show_window/hide_window thật là no-op trả False; thay bằng
    hàm giả trả True để đi đúng nhánh "cửa sổ đã được đưa ra màn hình" (cửa sổ thật kiểm ở test_browser_hidden_xvfb).
    """
    import dola_service
    calls = {"show": 0, "hide": 0}
    show_kwargs = {}

    def fake_show(context, page, **kwargs):
        calls["show"] += 1
        show_kwargs.update(kwargs)
        return True

    monkeypatch.setattr(dola_service, "show_window", fake_show)
    monkeypatch.setattr(dola_service, "hide_window", lambda context, page: calls.__setitem__("hide", calls["hide"] + 1) or True)
    fake_dola.control(mode="captcha", solve_captcha_after=6, render_seconds=2)
    acc_id = db.add_account("nick kéo captcha")
    job_id = db.add_job("Job captcha giải tại chỗ")

    worker_runner.start()
    jobs = _assert_completed(db, [job_id], timeout=150)
    assert jobs[job_id]["account_id"] == acc_id

    messages = [r["message"] or "" for r in db.system_logs() if r["job_id"] == job_id]
    assert any("cửa sổ Chrome của nick 'nick kéo captcha' đã được đưa ra màn hình" in m for m in messages), messages
    assert any("đã kéo xong mảnh ghép" in m for m in messages), messages
    # BH-45 nhánh (b): fake giữ nguyên chữ trong ô nhập sau khi giải captcha → gửi lại bằng Enter, không gõ lại
    assert any("ô nhập còn nguyên prompt" in m and "gửi lại prompt một lần bằng Enter" in m for m in messages), messages
    assert not any("credit" in m and "KHÔNG gửi lại" in m for m in messages), messages
    assert calls["show"] == 1 and calls["hide"] == 1, calls
    # N-2: dola_service truyền account_id (xếp bậc thang) và tiêu đề có tên nick cho show_window
    assert show_kwargs.get("account_id") == acc_id, show_kwargs
    assert show_kwargs.get("title") == "Nick nick kéo captcha — kéo mảnh ghép", show_kwargs

    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả (busy_job_id NULL)")
    acc = db.account(acc_id)
    assert acc["needs_manual"] is None, acc
    assert acc["last_error"] is None, acc
    st = fake_dola.get_state()
    assert st["mode"] == "normal" and st["captcha_solved_at"] is not None
    assert len(st["conversations"]) == 1, st["conversations"]
    assert st["sent_prompts"] == [next(iter(st["conversations"].values()))["prompt"]]
    assert "Job captcha giải tại chỗ" in st["sent_prompts"][0]
    assert st["chat_get_count"] == 1, "job phải chạy tiếp trong cùng phiên Chrome, không mở lại"
    assert db.job(job_id)["status"] == JobStatus.HOAN_THANH


# ---------------------------------------------------------------- BH-45: Dola tự gửi prompt sau khi giải captcha → không gửi lại
def test_captcha_solved_dola_auto_sends_no_resend(db, fake_dola, worker_runner, monkeypatch):
    """Fake `auto_resend_after_solve`: ngay khi captcha được giải, server tự tạo conversation cho prompt đã gõ
    (như Dola thật đôi khi làm). dola_service thấy conversation trong 15 s đầu nên KHÔNG gửi lại: đúng 1 conversation,
    đúng 1 prompt, không tốn 2 credit."""
    import dola_service
    monkeypatch.setattr(dola_service, "show_window", lambda context, page, **kw: True)
    monkeypatch.setattr(dola_service, "hide_window", lambda context, page: True)
    fake_dola.control(mode="captcha", solve_captcha_after=6, auto_resend_after_solve=True, render_seconds=2, credits=4)
    acc_id = db.add_account("nick dola tự gửi")
    job_id = db.add_job("Job captcha Dola tự gửi")

    worker_runner.start()
    jobs = _assert_completed(db, [job_id], timeout=150)
    assert jobs[job_id]["account_id"] == acc_id

    messages = [r["message"] or "" for r in db.system_logs() if r["job_id"] == job_id]
    assert any("đã kéo xong mảnh ghép" in m for m in messages), messages
    assert not any("gửi lại prompt" in m for m in messages), f"BH-45: không được gửi lại khi Dola đã nhận prompt: {messages}"
    st = fake_dola.get_state()
    assert len(st["conversations"]) == 1, st["conversations"]
    assert len(st["sent_prompts"]) == 1 and "Job captcha Dola tự gửi" in st["sent_prompts"][0], st["sent_prompts"]
    sess = next(s for s in st["sessions"].values() if s.get("captcha_shown"))
    assert sess["credits"] == 3, f"chỉ được trừ đúng 1 credit: {sess}"
    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả (busy_job_id NULL)")
    assert db.account(acc_id)["needs_manual"] is None


# ---------------------------------------------------------------- N-4: không đưa được cửa sổ ra → chờ ngắn rồi Tạm dừng
def test_captcha_window_cannot_be_shown_pauses_quickly(db, fake_dola, worker_runner, monkeypatch):
    """show_window trả False (CDP lỗi / không có cửa sổ) với captcha vĩnh viễn: không chờ đủ 3 phút
    (CAPTCHA_SOLVE_TIMEOUT_SECONDS giữ mặc định 180) mà chỉ CAPTCHA_NO_WINDOW_TIMEOUT_SECONDS (20 s) rồi Tạm dừng,
    thông điệp nói rõ không đưa được cửa sổ ra và bảo bấm nút Chrome."""
    import config
    import dola_service
    assert config.CAPTCHA_SOLVE_TIMEOUT_SECONDS == 180 and config.CAPTCHA_NO_WINDOW_TIMEOUT_SECONDS == 20
    monkeypatch.setattr(dola_service, "show_window", lambda context, page, **kw: False)
    fake_dola.control(mode="captcha")
    acc_id = db.add_account("nick không cửa sổ")
    job_id = db.add_job("Job captcha không cửa sổ")

    worker_runner.start()
    wait_until(lambda: "không đưa được cửa sổ" in (db.job(job_id)["status_message"] or ""), 60,
               what="job báo không đưa được cửa sổ ra màn hình")
    t0 = time.time()
    wait_until(lambda: db.job(job_id)["status"] == JobStatus.TAM_DUNG, 60, what="job về Tạm dừng")
    assert time.time() - t0 < 40, "N-4: không có cửa sổ thì chỉ chờ ~20 s rồi Tạm dừng, không chờ 3 phút"
    assert db.account(acc_id)["needs_manual"] == NeedsManual.CAPTCHA
    messages = [r["message"] or "" for r in db.system_logs() if r["job_id"] == job_id]
    assert any("không đưa được cửa sổ Chrome của nick 'nick không cửa sổ' ra màn hình" in m
               and "bấm nút Chrome để kéo tay" in m and "20 giây" in m for m in messages), messages
    assert any("sau 20 giây captcha vẫn còn" in m for m in messages), messages
    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả (busy_job_id NULL)")


# ---------------------------------------------------------------- Q5
def test_q5_reset_orphans_on_startup(db):
    acc_id = db.add_account("nick mồ côi")
    job_id = db.add_job("Q5 job ma", status=JobStatus.DANG_CHAY, account_id=acc_id, status_message="Dola đang render")
    db.exec("UPDATE accounts SET busy_job_id = ? WHERE id = ?", (job_id, acc_id))
    done_id = db.add_job("Q5 job xong", status=JobStatus.HOAN_THANH, account_id=acc_id)

    db.database.reset_orphans_on_startup()

    job = db.job(job_id)
    assert job["status"] == JobStatus.CHO
    assert job["status_message"] == Reason.APP_RESTARTED
    assert db.account(acc_id)["busy_job_id"] is None
    assert db.job(done_id)["status"] == JobStatus.HOAN_THANH


# ---------------------------------------------------------------- Q7
def test_q7_job_without_account_waits_with_clear_reason_and_no_chrome(db, fake_dola, worker_runner):
    db.add_account("nick chưa login", with_session=False)
    job_id = db.add_job("Q7 job không nick")

    worker_runner.start()
    time.sleep(3)
    first = db.job(job_id)
    assert first["status"] == JobStatus.CHO
    assert Reason.WAITING_ACCOUNT.split(":")[0] in (first["status_message"] or ""), first["status_message"]
    assert "chưa đăng nhập Dola" in first["status_message"]

    time.sleep(4)
    second = db.job(job_id)
    assert second["status"] == JobStatus.CHO
    assert second["status_message"] == first["status_message"]
    assert second["updated_at"] == first["updated_at"], "status_message bị ghi lại liên tục dù nội dung không đổi"

    st = fake_dola.get_state()
    assert st["total_requests"] == 0, f"fake Dola nhận request dù không có nick: {st['request_log']}"
    assert get_active_browser_count() in (0, None)


# ---------------------------------------------------------------- Q8
def test_q8_many_jobs_no_database_locked(db, fake_dola, worker_runner, env_tmp):
    db.set_setting("max_concurrent_jobs", 2)
    fake_dola.control(render_seconds=1, credits=1000)
    db.add_account("nick 1")
    db.add_account("nick 2")
    job_ids = [db.add_job(f"Q8 job {i + 1}", batch_id="batch-q8", seq=i + 1) for i in range(Q8_JOBS)]
    offsets = log_offsets(env_tmp)

    worker_runner.start()
    _assert_completed(db, job_ids, timeout=175)

    text = new_log_text(env_tmp, offsets)
    assert "database is locked" not in text.lower()
    assert not any("database is locked" in (r["message"] or "").lower() for r in db.system_logs())
    assert len(fake_dola.get_state()["conversations"]) == Q8_JOBS


# ---------------------------------------------------------------- T5
def test_t5_picks_new_conversation_not_old_one(db, fake_dola, worker_runner):
    acc_id = db.add_account("nick có lịch sử")
    old = fake_dola.send("prompt cũ từ hôm qua", sessionid=db.account_sessionid(acc_id))
    old_conv = old["conversation_id"]
    fake_dola.control(render_seconds=1)
    job_id = db.add_job("T5 job mới")

    worker_runner.start()
    jobs = _assert_completed(db, [job_id], timeout=120)

    st = fake_dola.get_state()
    convs = {cid: c for cid, c in st["conversations"].items() if cid != old_conv}
    assert len(convs) == 1, f"kỳ vọng đúng 1 conversation mới, có {list(convs)}"
    new_conv = next(iter(convs))
    assert "T5 job mới" in convs[new_conv]["prompt"]
    assert conv_id_in_mp4(db.video_file(jobs[job_id])) == new_conv
    assert conv_id_in_mp4(db.video_file(jobs[job_id])) != old_conv
    assert [d["conv_id"] for d in st["downloads"]] == [new_conv]


# ---------------------------------------------------------------- K4 (một phần)
def test_k4_partial_daily_limit_rests_account_and_requeues_job(db, fake_dola, worker_runner):
    fake_dola.control(mode="daily_limit")
    acc_id = db.add_account("nick hết credit")
    job_id = db.add_job("K4 job")

    worker_runner.start()
    wait_until(lambda: db.account(acc_id)["rest_until"] is not None, 90, what="nick được cho nghỉ (rest_until)")
    acc = db.account(acc_id)
    assert acc["credits"] == 0, acc
    assert acc["rest_until"] is not None

    job = wait_until(lambda: (lambda j: j if j["status"] != JobStatus.DANG_CHAY else None)(db.job(job_id)), 60,
                     what="job rời Đang chạy")
    assert job["status"] == JobStatus.CHO, job
    # BH-34: "Nick ... hết credit hôm nay ..." là thông điệp tạm; sau khi nick được trả, vòng quét kế tiếp
    # hợp lệ ghi đè thành tóm tắt Q7 "Chưa có nick phù hợp: 1 nick đang nghỉ". Chấp nhận cả hai; lý do
    # "hết credit" kiểm chắc chắn qua system_logs (ghi cùng lúc với lúc job về Chờ).
    msg = job["status_message"] or ""
    assert "hết credit" in msg or "nick đang nghỉ" in msg, msg
    assert any("hết credit hôm nay" in (r["message"] or "") and r["job_id"] == job_id for r in db.system_logs()), \
        [r["message"] for r in db.system_logs()]
    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả (busy_job_id NULL)")

    # nick đã nghỉ: worker không mở lại Chrome trên nick đó
    opens = fake_dola.get_state()["chat_get_count"]
    time.sleep(6)
    assert fake_dola.get_state()["chat_get_count"] == opens, "worker mở lại Chrome trên nick đã nghỉ"
    assert db.job(job_id)["status"] == JobStatus.CHO


# ---------------------------------------------------------------- BH-04 / KIEN_TRUC mục 4: tự chạy lại lỗi kỹ thuật
def test_technical_error_auto_retries_then_fails_with_max_attempts(db, fake_dola, worker_runner, monkeypatch):
    """mode=crash (Dola đóng socket): 1 nick, 1 job, MAX_AUTO_RETRIES=2 → thử 3 lần rồi Thất bại, không có lần 4.

    Lỗi kết nối (chưa vào được trang) không đánh dấu nick rate_limited ngay, nên cùng nick được dùng cho cả 3 lần;
    sau lần thứ 3 (> MAX_AUTO_RETRIES) nick mới bị rate_limited (consecutive_errors = 3).
    """
    import config
    monkeypatch.setattr(config, "MAX_AUTO_RETRIES", 2)
    fake_dola.control(mode="crash")
    acc_id = db.add_account("nick dola sập")
    job_id = db.add_job("Job lỗi kỹ thuật")

    worker_runner.start()
    job = wait_until(lambda: (lambda j: j if j["status"] == JobStatus.THAT_BAI else None)(db.job(job_id)), 150,
                     what="job Thất bại sau khi hết lượt tự chạy lại")
    assert job["attempts"] == 3, job
    assert "Đã thử 3 lần" in (job["status_message"] or ""), job["status_message"]
    assert Reason.BROWSER_ERROR.split(":")[0] in job["status_message"], job["status_message"]

    # Hai lần đầu phải đi qua trạng thái Chờ với thông điệp "tự chạy lại lần n/2" (ghi trong system_logs)
    messages = [r["message"] or "" for r in db.system_logs()]
    for n in (1, 2):
        assert any(f"tự chạy lại lần {n}/2" in m for m in messages), f"thiếu log 'tự chạy lại lần {n}/2': {messages}"

    wait_until(lambda: db.account(acc_id)["busy_job_id"] is None, 30, what="nick được trả (busy_job_id NULL)")
    acc = db.account(acc_id)
    assert acc["consecutive_errors"] == 3, acc
    assert acc["status"] == AccountStatus.RATE_LIMITED, acc
    assert acc["last_error"], acc

    # Không có lần thử thứ 4: số lần GET /chat/ không tăng trong 10 giây
    opens = fake_dola.get_state()["chat_get_count"]
    assert opens >= 3, f"kỳ vọng ít nhất 3 lần mở trang Dola, có {opens}"
    time.sleep(10)
    assert fake_dola.get_state()["chat_get_count"] == opens, "worker vẫn mở Chrome lần thứ 4 sau khi đã Thất bại"
    assert db.job(job_id)["status"] == JobStatus.THAT_BAI
    assert get_active_browser_count() in (0, None)
