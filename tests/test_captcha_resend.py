"""
BH-45: sau khi kéo xong captcha, dola_service._conv_after_captcha_solved chỉ được gửi lại prompt (tốn credit)
khi có bằng chứng lần gửi trước KHÔNG thành công. Test đơn vị với trang giả (không Chrome, không CSDL).

Các nhánh:
(a) credit giảm so với trước captcha → KHÔNG gửi lại, chờ thêm conversation (45 s);
(b) ô nhập còn nguyên prompt → gửi lại bằng Enter (không gõ lại);
(c1) ô trống, credit đọc được và không giảm → gõ lại + Enter ngay;
(c2) ô trống, credit không đọc được → chờ thêm 15 s rồi mới gõ lại + Enter.
"""
from __future__ import annotations

import pytest

import dola_service

JOB = {"id": 7}
ACC = {"id": 3, "name": "nick A"}
PROMPT = "Tạo video Seedance 2.5 dài 30 giây. Hai người ngồi đối thoại trong quán cà phê, cô gái trả lời."


class Harness:
    """Thay mọi hàm chạm Chrome/CSDL bằng hàm ghi lại lời gọi."""

    def __init__(self, monkeypatch, *, credits_now, box_text, conv_after_waits):
        self.waits = []          # các khoảng chờ conversation đã gọi (giây)
        self.logs = []
        self.statuses = []
        self.enter_calls = 0
        self.fill_calls = 0
        self.failed = []
        self._conv_after_waits = list(conv_after_waits)  # giá trị trả về của _wait_new_conversation theo thứ tự gọi

        def wait_conv(page, initial, seconds, job_id):
            self.waits.append(seconds)
            return self._conv_after_waits.pop(0) if self._conv_after_waits else None

        monkeypatch.setattr(dola_service, "_wait_new_conversation", wait_conv)
        monkeypatch.setattr(dola_service, "extract_dola_credits", lambda page: credits_now)
        monkeypatch.setattr(dola_service, "_input_box_text", lambda page: box_text)
        monkeypatch.setattr(dola_service, "_resend_with_enter", lambda page: self._enter())
        monkeypatch.setattr(dola_service, "_send_prompt", lambda page, text: self._fill(text))
        monkeypatch.setattr(dola_service, "_detect_captcha", lambda page: False)
        monkeypatch.setattr(dola_service, "log_event", lambda msg, *a, **k: self.logs.append(msg))
        monkeypatch.setattr(dola_service, "update_job_status", lambda jid, st, msg, prog, **k: self.statuses.append(msg))
        monkeypatch.setattr(dola_service, "_fail_job", lambda *a, **k: self.failed.append(a))
        monkeypatch.setattr(dola_service.time, "sleep", lambda s: None)

    def _enter(self):
        self.enter_calls += 1
        return True

    def _fill(self, text):
        self.fill_calls += 1
        assert text == PROMPT
        return True

    def run(self, credits_pre):
        return dola_service._conv_after_captcha_solved(JOB, ACC, object(), set(), PROMPT, credits_pre)


def test_conv_found_in_first_wait_sends_nothing(monkeypatch):
    h = Harness(monkeypatch, credits_now=4, box_text=PROMPT, conv_after_waits=["111"])
    assert h.run(credits_pre=4) == ("111", False)
    assert h.waits == [dola_service.CONV_WAIT_AFTER_CAPTCHA_SECONDS]
    assert h.enter_calls == 0 and h.fill_calls == 0


def test_a_credit_decreased_means_prompt_was_accepted_no_resend(monkeypatch):
    h = Harness(monkeypatch, credits_now=3, box_text="", conv_after_waits=[None, "222"])
    assert h.run(credits_pre=4) == ("222", False)
    assert h.waits == [dola_service.CONV_WAIT_AFTER_CAPTCHA_SECONDS, dola_service.CONV_WAIT_CREDIT_SPENT_SECONDS]
    assert h.enter_calls == 0 and h.fill_calls == 0, "BH-45: credit đã trừ thì không được gửi lại"
    assert any("4 → 3" in m and "KHÔNG gửi lại" in m for m in h.logs), h.logs


def test_a_credit_decreased_even_if_box_still_has_prompt(monkeypatch):
    """Credit là bằng chứng mạnh hơn ô nhập: ô còn chữ nhưng credit đã trừ → vẫn không gửi lại."""
    h = Harness(monkeypatch, credits_now=3, box_text=PROMPT, conv_after_waits=[None, None])
    assert h.run(credits_pre=4) == (None, False)
    assert h.enter_calls == 0 and h.fill_calls == 0


def test_b_box_still_holds_prompt_resends_with_enter_only(monkeypatch):
    h = Harness(monkeypatch, credits_now=4, box_text=PROMPT + "\n", conv_after_waits=[None, "333"])
    assert h.run(credits_pre=4) == ("333", False)
    assert h.enter_calls == 1 and h.fill_calls == 0, "ô còn nguyên prompt thì chỉ Enter, không gõ lại (tránh nhân đôi)"
    assert h.waits == [dola_service.CONV_WAIT_AFTER_CAPTCHA_SECONDS, dola_service.CONV_WAIT_SECONDS]
    assert any("ô nhập còn nguyên prompt" in m and "gửi lại prompt một lần bằng Enter" in m for m in h.logs), h.logs


def test_b_box_check_uses_first_40_chars_only(monkeypatch):
    """Ô nhập có thể cắt bớt/đổi cuối prompt (ProseMirror); chỉ cần 40 ký tự đầu khớp."""
    h = Harness(monkeypatch, credits_now=None, box_text=PROMPT[:40] + " ...", conv_after_waits=[None, "444"])
    assert h.run(credits_pre=None) == ("444", False)
    assert h.enter_calls == 1 and h.fill_calls == 0


def test_c1_box_empty_credit_unchanged_refills_immediately(monkeypatch):
    h = Harness(monkeypatch, credits_now=4, box_text="", conv_after_waits=[None, "555"])
    assert h.run(credits_pre=4) == ("555", False)
    assert h.fill_calls == 1 and h.enter_calls == 0
    assert h.waits == [dola_service.CONV_WAIT_AFTER_CAPTCHA_SECONDS, dola_service.CONV_WAIT_SECONDS]
    assert any("credit không giảm (4 → 4)" in m and "gửi lại prompt một lần" in m for m in h.logs), h.logs


def test_c2_box_empty_credit_unreadable_waits_more_before_resend(monkeypatch):
    h = Harness(monkeypatch, credits_now=None, box_text="", conv_after_waits=[None, None, "666"])
    assert h.run(credits_pre=4) == ("666", False)
    assert h.waits == [dola_service.CONV_WAIT_AFTER_CAPTCHA_SECONDS, dola_service.CONV_WAIT_NO_EVIDENCE_SECONDS,
                       dola_service.CONV_WAIT_SECONDS]
    assert h.fill_calls == 1 and h.enter_calls == 0
    assert any("không đọc được credit" in m and "chờ thêm 15s" in m for m in h.logs), h.logs


def test_c2_conversation_appears_during_extra_wait_sends_nothing(monkeypatch):
    h = Harness(monkeypatch, credits_now=None, box_text=None, conv_after_waits=[None, "777"])
    assert h.run(credits_pre=None) == ("777", False)
    assert h.fill_calls == 0 and h.enter_calls == 0


def test_no_input_box_when_resending_fails_job(monkeypatch):
    h = Harness(monkeypatch, credits_now=4, box_text="", conv_after_waits=[None])
    monkeypatch.setattr(dola_service, "_send_prompt", lambda page, text: False)
    conv_id, finalized = h.run(credits_pre=4)
    assert conv_id is None and finalized is True
    assert len(h.failed) == 1


def test_run_job_passes_credits_pre_to_conv_after_captcha():
    src = open(dola_service.__file__, encoding="utf-8").read()
    calls = [ln for ln in src.splitlines() if "_conv_after_captcha_solved(job, acc, page" in ln]
    assert len(calls) == 2, calls
    assert all("credits_pre)" in ln for ln in calls), "BH-45: mọi lời gọi phải truyền credits_pre"
