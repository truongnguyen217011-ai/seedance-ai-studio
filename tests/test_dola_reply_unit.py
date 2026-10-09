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


# N-6: các cách viết tỷ lệ người dùng/Dola hay dùng đều về 16:9 hoặc 9:16
@pytest.mark.parametrize("value,expected", [
    ("16/9", "16:9"), ("9/16", "9:16"), ("16x9", "16:9"), ("9x16", "9:16"), ("16×9", "16:9"), ("16 : 9", "16:9"),
    ("tỷ lệ khung hình 16:9 (ngang)", "16:9"), ("B. 9:16 vertical short video", "9:16"),
    ("ngang", "16:9"), ("dọc", "9:16"), ("Dọc", "9:16"), ("landscape", "16:9"), ("portrait", "9:16"),
    ("video dọc cho TikTok", "9:16"), ("horizontal", "16:9"), ("vertical", "9:16"),
])
def test_normalize_ratio_accepts_common_spellings(value, expected):
    assert constants.normalize_ratio(value) == (expected, None)


@pytest.mark.parametrize("value", ["4:3", "19:16", "document", "2.39:1", "abc"])
def test_normalize_ratio_rejects_unknown_with_warning(value):
    ratio, warning = constants.normalize_ratio(value)
    assert ratio == constants.DEFAULT_RATIO and warning and value in warning


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


def test_bh48_assistant_texts_drops_own_auto_answer_even_without_role():
    """BH-48: chain của Dola chứa cả câu tool tự trả lời; không có trường role thì vẫn phải loại nhờ own_texts."""
    answer = dola_service._auto_answer_text(15, "16:9")
    chain = _chain({"content": json.dumps({"text": answer}, ensure_ascii=False)})
    assert dola_service._assistant_texts(chain, PROMPT, [answer]) == []
    # không truyền own_texts thì câu đó bị đọc như Dola nói (đây chính là lỗi BH-48)
    assert dola_service._assistant_texts(chain, PROMPT) == [answer]
    # bản gửi lại sau captcha (cùng prompt) và bản bị cắt ngắn cũng bị loại
    chain = _chain({"content": PROMPT}, {"content": answer[:30]}, _msg("assistant", ASK))
    assert dola_service._assistant_texts(chain, PROMPT, [answer, PROMPT]) == [ASK]


@pytest.mark.parametrize("node", [
    {"role": "user"}, {"role": "User"}, {"user_type": 1}, {"user_type": "1"}, {"sender": "user"}, {"from": "human"},
    {"sender": {"role": "user"}},
])
def test_bh48_assistant_texts_skips_nodes_marked_as_user(node):
    """BH-48: tin nhắn có role/user_type/sender/from = user bị bỏ cả nhánh, kể cả khi chữ không trùng gì đã gửi."""
    user = dict(node, content=json.dumps({"text": "Một câu dài hơn hai mươi ký tự do người dùng gõ tay"}, ensure_ascii=False))
    chain = _chain(user, _msg("assistant", ASK))
    assert dola_service._assistant_texts(chain) == [ASK]
    # role trợ lý/khác → vẫn đọc
    other = {"role": "assistant", "user_type": 2, "content": json.dumps({"text": ASK})}
    assert dola_service._assistant_texts(_chain(other)) == [ASK]


def test_n2_own_prompt_head_is_taken_after_fixed_header():
    """N-2: dấu hiệu "prompt của mình" là 40 ký tự SAU câu mở đầu cố định, nên câu Dola trích lại header
    ("You asked: 'Tạo video ...' but I cannot ...") vẫn được trả về."""
    quoted = ("You asked: 'Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang).' but I cannot create "
              "that video for policy reasons.")
    chain = _chain(_msg("user", PROMPT), _msg("assistant", quoted))
    assert dola_service._assistant_texts(chain, PROMPT) == [quoted]
    assert dola_service._own_text_head(PROMPT) == "người nhện đánh nhau với robot. Hình ảnh"
    plain = "không có header, chỉ là câu trả lời ngắn gọn thôi, dài hơn bốn mươi ký tự"
    assert dola_service._own_text_head(plain) == plain[:dola_service.PROMPT_PREFIX_CHECK_CHARS]
    # prompt của mình bị Dola hiện dạng cắt ngắn SAU header vẫn bị loại nhờ phần đầu sau header
    truncated = f"{director.build_header()} người nhện đánh nhau với robot. Hình ảnh: chuẩn điện ảnh Hollywood …"
    assert dola_service._assistant_texts(_chain({"content": truncated}), PROMPT) == []


# ---------------------------------------------------------------- N-1: từ chối → 60 s, văn bản khác → 120 s
@pytest.mark.parametrize("text", [
    "I cannot create that video, please try a different description.", "I can't do that", "Sorry, this is unavailable",
    "I'm unable to help", "I am not able to render it", "This model does not support that length",
    "Tôi không thể tạo video này", "Dola không hỗ trợ nội dung này", "Xin lỗi, nội dung vi phạm", "Bạn không được phép",
])
def test_looks_like_refusal_positive(text):
    assert dola_service._looks_like_refusal(text)


@pytest.mark.parametrize("text", ["Generating video...", "Here is a summary of your scene", "Đang tạo video", "", None])
def test_looks_like_refusal_negative(text):
    assert not dola_service._looks_like_refusal(text)


def test_reply_should_fail_rules():
    refusal = "I cannot create that video."
    other = "Here is a description of the scene I will render for you."
    assert not dola_service._reply_should_fail(refusal, 59, False)
    assert dola_service._reply_should_fail(refusal, 60, False)
    assert not dola_service._reply_should_fail(refusal, 600, True), "đang generating thì chờ"
    assert not dola_service._reply_should_fail(other, 60, False)
    assert not dola_service._reply_should_fail(other, 119, False)
    assert dola_service._reply_should_fail(other, 120, False)
    assert not dola_service._reply_should_fail(other, 120, True)
    assert dola_service.REPLY_NO_VIDEO_SECONDS == 60 and dola_service.REPLY_NO_VIDEO_HARD_SECONDS == 120


# ---------------------------------------------------------------- N-3: tự trả lời chỉ tính khi gửi được, thử tối đa 3 lần
def test_auto_answer_step_retries_until_sent_or_three_failures():
    calls = []
    fail = lambda a: calls.append(a) or False
    ok = lambda a: calls.append(a) or True
    assert dola_service._auto_answer_step(fail, "x", 0) == (False, 1, False)
    assert dola_service._auto_answer_step(fail, "x", 1) == (False, 2, False)
    assert dola_service._auto_answer_step(fail, "x", 2) == (False, 3, True), "lần 3 hỏng → coi là đã trả lời, không thử nữa"
    assert dola_service._auto_answer_step(ok, "x", 1) == (True, 2, True)
    assert dola_service._auto_answer_step(ok, "x", 0) == (True, 1, True)
    assert calls == ["x"] * 5 and dola_service.AUTO_ANSWER_MAX_TRIES == 3


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


def test_bh49_build_full_prompt_keeps_user_edited_valid_header_and_updates_job(db):
    """BH-49/N-4: người dùng sửa tay câu mở đầu thành "8 giây"/"9:16" (hợp lệ) → giữ nguyên prompt, không ghi đè bằng
    cột duration/ratio cũ; ngược lại jobs.duration/ratio được ghi theo header (thứ thật sự gửi Dola)."""
    edited = f"{director.build_header('Seedance 2.5', '8 giây', '9:16')} Cô gái cười. Hình ảnh: abc."
    job_id = db.add_job("Cô gái cười", duration="15 giây", ratio="16:9", prompt_final=edited)
    full = dola_service.build_full_prompt(db.job(job_id))
    assert full == edited
    after = db.job(job_id)
    assert after["duration"] == "8 giây" and after["ratio"] == "9:16"
    assert dola_service.job_video_params(after) == (8, "9:16", None)
    assert not any("ngoài khoảng" in (r["message"] or "") for r in db.system_logs())
    # header hợp lệ nhưng thiếu tỷ lệ → vẫn viết lại (cột job thắng)
    partial = "Tạo video Seedance 2.5 dài 10 giây. Cô gái cười."
    job2 = db.add_job("Cô gái cười", duration="10 giây", ratio="16:9", prompt_final=partial)
    assert dola_service.build_full_prompt(db.job(job2)) == f"{director.build_header('Seedance 2.5', '10 giây', '16:9')} Cô gái cười."
