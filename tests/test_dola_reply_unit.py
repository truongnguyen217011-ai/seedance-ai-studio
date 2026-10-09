"""
BH-46/BH-47: tham số video gửi Dola (thời lượng 4-15 giây, tỷ lệ khung hình) và đọc câu trả lời bằng chữ của Dola
trong lúc chờ render. Test đơn vị, không Chrome.
"""
from __future__ import annotations

import json

import pytest

import constants
import director
import dola_service

ASK = ("Video generation currently supports durations from 4 to 15 seconds. I can generate it at the nearest supported "
       "duration of 15 seconds. I also need to confirm the aspect ratio you want: A. 16:9 cinematic wide screen "
       "B. 9:16 vertical short video C. 2.39:1 anamorphic film look. Which option would you like?")
PROMPT = f"{director.build_header()} người nhện đánh nhau với robot. Hình ảnh: chuẩn điện ảnh Hollywood Masterpiece."


# ---------------------------------------------------------------- constants: thời lượng / tỷ lệ
@pytest.mark.parametrize("label,seconds,warned", [
    ("30 giây", 15, True), ("15 giây", 15, False), ("10 giây", 10, False), ("5 giây", 5, False), ("4", 4, False),
    (15, 15, False), ("3 giây", 4, True), ("25 giây", 15, True), ("", 15, False), (None, 15, False), ("abc", 15, True),
])
def test_normalize_duration_clamps_to_dola_range(label, seconds, warned):
    got, warning = constants.normalize_duration(label)
    assert got == seconds
    assert bool(warning) is warned, warning
    if warned and label not in ("abc",):
        assert "4-15" in warning and f"{seconds} giây" in warning
    assert constants.DURATION_MIN_SECONDS <= got <= constants.DURATION_MAX_SECONDS


def test_duration_and_ratio_choices_are_within_dola_support():
    assert constants.DEFAULT_DURATION in constants.DURATION_CHOICES
    assert constants.DEFAULT_RATIO == "16:9" and constants.RATIO_CHOICES == ("16:9", "9:16")
    for label in constants.DURATION_CHOICES:
        assert constants.normalize_duration(label)[1] is None, label
    assert constants.normalize_ratio("9:16") == ("9:16", None)
    assert constants.normalize_ratio("Dọc") == ("9:16", None)
    assert constants.normalize_ratio("Ngang") == ("16:9", None)
    assert constants.normalize_ratio("") == ("16:9", None)
    ratio, warning = constants.normalize_ratio("2.39:1")
    assert ratio == "16:9" and "2.39:1" in warning


# ---------------------------------------------------------------- _assistant_texts
def _chain(*messages):
    return {"data": {"messages": list(messages)}}


def _msg(role, text, nested=True):
    content = json.dumps({"text": text}, ensure_ascii=False) if nested else text
    return {"content_type": "text", "role": role, "content": content}


def test_assistant_texts_parses_nested_json_strings_and_skips_prompt_and_urls():
    chain = _chain(
        _msg("user", PROMPT),
        _msg("assistant", ASK),
        {"content_type": "video", "content": "http://127.0.0.1:1/video/tos/1.mp4"},
        {"content": json.dumps({"text": "see https://example.com/video.mp4 for the result"})},
        {"message": "short"},
        {"text": "Đây là một câu trả lời tiếng Việt không có URL và dài hơn hai mươi ký tự"},
        {"other_key": "This key is not a reply key so it must be ignored, even if long"},
    )
    texts = dola_service._assistant_texts(chain, PROMPT)
    assert texts == [ASK, "Đây là một câu trả lời tiếng Việt không có URL và dài hơn hai mươi ký tự"]


def test_assistant_texts_json_string_inside_json_string():
    inner = json.dumps({"text": ASK}, ensure_ascii=False)
    outer = json.dumps({"content": inner}, ensure_ascii=False)
    chain = {"data": {"message_list": [{"payload": outer}], "status": "ok"}}
    assert dola_service._assistant_texts(chain) == [ASK]


def test_assistant_texts_excludes_user_prompt_even_when_stored_plain():
    chain = _chain(_msg("user", PROMPT, nested=False), _msg("assistant", "I cannot create that video, sorry.", nested=False))
    assert dola_service._assistant_texts(chain, PROMPT) == ["I cannot create that video, sorry."]
    # prompt bị cắt ngắn trong lịch sử (Dola hiện 40 ký tự đầu) vẫn bị loại
    chain = _chain(_msg("user", PROMPT[:60]), _msg("assistant", "I cannot create that video, sorry."))
    assert dola_service._assistant_texts(chain, PROMPT) == ["I cannot create that video, sorry."]


def test_assistant_texts_ignores_generating_and_garbage():
    assert dola_service._assistant_texts({"data": {"status": "generating", "text": "Generating video..."}}) == []
    assert dola_service._assistant_texts(None) == []
    assert dola_service._assistant_texts("not json at all but a long enough string") == []
    assert dola_service._assistant_texts({"content": "{not valid json but long enough to count as text}"}) == \
        ["{not valid json but long enough to count as text}"]
    # không trùng lặp
    chain = _chain(_msg("assistant", ASK), _msg("assistant", ASK))
    assert dola_service._assistant_texts(chain) == [ASK]


# ---------------------------------------------------------------- _looks_like_question
@pytest.mark.parametrize("text", [
    ASK,
    "Which option would you like?",
    "Could you confirm the duration?",
    "What aspect ratio do you want: 16:9 or 9:16?",
    "Bạn muốn tỷ lệ khung hình nào?",
    "Thời lượng bao nhiêu giây?",
    "Hãy chọn một lựa chọn: A hoặc B?",
])
def test_looks_like_question_positive(text):
    assert dola_service._looks_like_question(text)


@pytest.mark.parametrize("text", [
    "Generating video...",
    "I cannot create that video.",
    "Here is your video, hope you like it?",   # có "?" nhưng không có cụm hỏi tham số
    "Would you like",                           # cụm hỏi nhưng không có dấu hỏi
    "",
    None,
])
def test_looks_like_question_negative(text):
    assert not dola_service._looks_like_question(text)


def test_auto_answer_text_names_seconds_and_ratio():
    assert dola_service._auto_answer_text(15, "16:9") == "15 giây, tỷ lệ 16:9. Hãy tạo video ngay, không cần hỏi thêm."


# ---------------------------------------------------------------- build_full_prompt: job cũ "30 giây" bị ép về 15
def test_build_full_prompt_clamps_old_30s_job_and_rewrites_header(db):
    old_pf = "Tạo video Seedance 2.5 dài 30 giây. Cô gái cười. Hình ảnh: abc."
    job_id = db.add_job("Cô gái cười", duration="30 giây", prompt_final=old_pf)
    job = db.job(job_id)
    assert job["ratio"] is None
    full = dola_service.build_full_prompt(job)
    assert full == f"{director.build_header('Seedance 2.5', '15 giây', '16:9')} Cô gái cười. Hình ảnh: abc."
    after = db.job(job_id)
    assert after["duration"] == "15 giây" and after["ratio"] == "16:9"
    assert any("30 giây" in (r["message"] or "") and "15 giây" in (r["message"] or "") and r["job_id"] == job_id
               for r in db.system_logs())
    assert dola_service.job_video_params(after) == (15, "16:9", None)


def test_build_full_prompt_keeps_valid_job_and_uses_default_ratio_setting(db):
    db.set_setting("default_ratio", "9:16")
    job_id = db.add_job("Cô gái cười", duration="10 giây", prompt_final="Prompt tay viết hoàn toàn, không câu mở đầu.")
    full = dola_service.build_full_prompt(db.job(job_id))
    assert full == "Prompt tay viết hoàn toàn, không câu mở đầu."
    after = db.job(job_id)
    assert after["duration"] == "10 giây" and after["ratio"] == "9:16"
    assert dola_service.job_video_params(after) == (10, "9:16", None)
    assert not any("ngoài khoảng" in (r["message"] or "") for r in db.system_logs())
