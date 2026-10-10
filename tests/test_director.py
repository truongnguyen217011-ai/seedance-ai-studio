"""
Đạo diễn AI (director.py) — hợp đồng P1..P7 (docs/KIEN_TRUC.md mục 8, BH-41).

Hàm thuần, không CSDL, không Chrome: chạy nhanh.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import director

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Câu mở đầu do tool tự chèn (BH-46: nêu rõ số giây 4-15 và tỷ lệ khung hình, bảo Dola không hỏi lại)
H15 = director.build_header("Seedance 2.5", "15 giây", "16:9")

ASSETS = [
    {"id": 1, "name": "Tiểu Vũ", "character_code": "TV01", "image_url": "",
     "description": "cô gái 20 tuổi, tóc đen dài ngang lưng, áo dài trắng, ánh mắt kiên định"},
    {"id": 2, "name": "Lão Trần", "character_code": "LT02", "image_url": "",
     "description": "ông lão 70 tuổi râu bạc, áo nâu sờn, chống gậy trúc"},
    {"id": 3, "name": "Vũ", "character_code": "", "image_url": "", "description": "KHÔNG ĐƯỢC KHỚP (chuỗi con của Tiểu Vũ)"},
]

# Mỗi trường phái ít nhất một prompt nhận diện đúng (thứ tự ưu tiên như JS cũ, T1 đứng đầu)
ARCHETYPE_SAMPLES = {
    "T1": "Hai người ngồi đối thoại trong quán cà phê, người đàn ông hỏi, cô gái trả lời",
    "P1-Macro": "Cận cảnh đôi mắt ngấn nước mắt của cô gái",
    "F1": "Khu rừng cổ tích rêu phong, suối chảy qua lâu đài cổ",
    "F2": "Chiến binh cầm kiếm chiến đấu với rồng phun lửa",
    "C1": "Phi thuyền cô độc trôi giữa ngân hà, bầu trời hoàng hôn tím",
    "C2": "Thành phố sci-fi neon, người máy khổng lồ bước đi",
    "E1": "Nhà vua đau khổ trước triều đình, bi kịch lịch sử",
    "W1": "Cao bồi cưỡi ngựa băng qua sa mạc cát bụi",
    "G1": "Phong cách anime, truyện tranh vẽ nét mảng phẳng",
    "D1": "Hành lang gothic ma quái, xương sống sinh học, ác mộng",
    "S1": "Trong phòng ấm cúng, ánh nắng cửa sổ chiếu lên tách trà và sách",
    "A1": "Bão biển cuồng nộ, sóng thần vỗ vào vách đá",
    "P1": "Chân dung cô gái mỉm cười, thần thái tự tin",
    "Cine-Master": "Chiếc xe chạy qua cầu lúc nửa đêm",
}


def test_archetypes_match_js_codes_and_every_code_has_sample():
    codes = [a["code"] for a in director.ARCHETYPES]
    assert codes == ["T1", "P1-Macro", "F1", "F2", "C1", "C2", "E1", "W1", "G1", "D1", "S1", "A1", "P1", "Cine-Master"]
    assert set(ARCHETYPE_SAMPLES) == set(codes)
    for a in director.ARCHETYPES:
        for key in ("shot", "angle", "lens", "lighting", "visual_group", "palette", "six_elements"):
            assert a[key].strip(), (a["code"], key)
        if a["code"] != director.DEFAULT_ARCHETYPE_CODE:
            assert a["keywords"], a["code"]


@pytest.mark.parametrize("code,prompt", sorted(ARCHETYPE_SAMPLES.items()))
def test_detect_archetype(code, prompt):
    assert director.detect_archetype(prompt)["code"] == code
    r = director.compose(prompt)
    assert r["archetype_code"] == code
    assert r["archetype_name"] == director.ARCHETYPE_BY_CODE[code]["name"]


# ---------------------------------------------------------------- BH-44: từ khóa ngắn không được khớp chuỗi con
@pytest.mark.parametrize("prompt,not_code", [
    ("Spring festival parade", "P1-Macro"),        # "ring" trong "spring"
    ("A boy bringing flowers", "P1-Macro"),        # "ring" trong "bringing"
    ("Books on the shelf", "F1"),                  # "elf" trong "shelf"
    ("Tên lửa bay lên", "F2"),                     # "lửa" trong "tên lửa"
    ("Mặt trời mọc", "P1"),                        # "mặt" (trời) không phải khuôn mặt
    ("Cây cầu bắc qua sông", "F1"),                # "cây" (cầu) không phải rừng cây
    ("Steam rises from the kettle", "S1"),         # "tea" trong "steam"
    ("Human figure walking on the road", "P1"),    # "man" trong "human"
    ("Thợ kiếm tiền bằng nghề mộc", "F2"),         # "kiếm" (tiền) không phải thanh kiếm
])
def test_bh44_short_keywords_match_whole_words_only(prompt, not_code):
    code = director.detect_archetype(prompt)["code"]
    assert code != not_code, (prompt, code)
    assert code == "Cine-Master", (prompt, code)


@pytest.mark.parametrize("prompt,code", [
    ("Ngọn lửa bùng lên trong đêm", "F2"),
    ("Chiến binh vung đao chém quái vật", "F2"),
    ("Rừng cây cổ thụ phủ rêu", "F1"),
    ("Ngọn tháp cổ giữa thung lũng", "F1"),
    ("Khuôn mặt người đàn ông dưới mưa", "P1"),
    ("The girl with the ring", "P1-Macro"),        # "ring" đứng một mình vẫn khớp
    ("An elf in the woods", "F1"),
    ("Hai người nói chuyện", "T1"),
])
def test_bh44_whole_word_keywords_still_match(prompt, code):
    assert director.detect_archetype(prompt)["code"] == code


def test_bh44_keyword_pattern_rules():
    assert director.keyword_matches("ring", "the ring glows") and not director.keyword_matches("ring", "bringing")
    # "lửa" đứng riêng vẫn là một từ trong "tên lửa" → từ nguyên không đủ, nên bộ mẫu thay bằng cụm (kiểm bên dưới)
    assert director.keyword_matches("lửa", "ngọn lửa") and director.keyword_matches("lửa", "tên lửa")
    assert director.keyword_matches("nói", "hai người nói") and not director.keyword_matches("nói", "nóichuyện")
    assert director.keyword_matches("cô gái", "các cô gái")           # cụm nhiều âm tiết: chuỗi con
    assert director.keyword_matches("forest", "forests at dawn")      # tiếng Anh dài: chuỗi con (số nhiều)
    assert director.keyword_matches("Ngọn lửa", "NGỌN LỬA")           # không phân biệt hoa thường
    import unicodedata
    assert director.keyword_matches("mắt", unicodedata.normalize("NFD", "đôi mắt"))  # NFD vẫn khớp NFC
    # Không còn từ Việt một âm tiết quá chung trong bộ mẫu
    for arch in director.ARCHETYPES:
        for bad in ("cây", "mặt", "lửa", "tháp", "kiếm", "đao"):
            assert bad not in arch["keywords"], (arch["code"], bad)


def test_default_branch_keeps_cine_master_wording():
    """Nhánh mặc định giữ nguyên câu chữ của JS (không bịa mẫu mới) và KHÔNG còn câu FPV bom tấn cố định."""
    d = director.ARCHETYPE_BY_CODE["Cine-Master"]
    assert d["shot"] == "Medium Shot (MS)"
    assert d["lens"] == "50mm Prime Lens (Nifty Fifty)"
    src = (ROOT / "director.py").read_text(encoding="utf-8")
    assert "Hollywood blockbuster action masterpiece" not in src
    assert "FPV" not in src.replace("fpv", "")  # chỉ còn 'fpv' trong regex nhận diện lớp góc máy đã có


# ---------------------------------------------------------------- P1: đối thoại
def test_p1_dialogue_gets_portrait_soft_light_not_action():
    r = director.compose("Tiểu Vũ nói với Lão Trần: con sẽ đi, ông trả lời bằng một cái gật đầu", assets=ASSETS)
    assert r["archetype_code"] == "T1"
    pf = r["prompt_final"].lower()
    assert "over-the-shoulder" in pf and "85mm" in pf and "soft key light" in pf
    for bad in ("fpv", "acrobatic", "blockbuster action", "nhào lộn", "bom tấn"):
        assert bad not in pf, bad
    assert r["characters"] == ["Tiểu Vũ", "Lão Trần"]


def test_dialogue_beats_setting_keywords_but_style_override_wins():
    p = "Hai cao bồi trò chuyện trước quán rượu giữa sa mạc"
    assert director.compose(p)["archetype_code"] == "T1"
    assert director.compose(p, style_override="W1")["archetype_code"] == "W1"
    assert director.compose(p, options={"director_default_style": "W1"})["archetype_code"] == "W1"
    # style_override thắng cả setting mặc định
    assert director.compose(p, style_override="F1", options={"director_default_style": "W1"})["archetype_code"] == "F1"
    with pytest.raises(ValueError) as ei:
        director.compose(p, style_override="XYZ")
    assert "không có trong bộ mẫu" in str(ei.value)


# ---------------------------------------------------------------- P2: cấu trúc, prompt gốc nguyên văn
@pytest.mark.parametrize("prompt", list(ARCHETYPE_SAMPLES.values()) + [
    "Tiểu Vũ chạy xe máy qua phố, camera bám theo",
    "Prompt có dấu chấm cuối.",
    "Prompt tiếng Anh: a cat jumps over the moon, 8k",
])
def test_original_prompt_verbatim_inside_final(prompt):
    r = director.compose(prompt, duration_label="15 giây", model="Seedance 2.0", assets=ASSETS)
    assert r["prompt_final"].startswith("Tạo video Seedance 2.0 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. ")
    assert prompt in r["prompt_final"]
    assert ".." not in r["prompt_final"]


def test_leading_number_stripped_only():
    r = director.compose("03. Cô gái đứng bên cửa sổ")
    assert "03." not in r["prompt_final"]
    assert "Cô gái đứng bên cửa sổ" in r["prompt_final"]
    assert r["prompt_clean"] == "Cô gái đứng bên cửa sổ"
    assert director.strip_leading_number("12 - Cảnh 12 có số 12 ở giữa") == "Cảnh 12 có số 12 ở giữa"


# ---------------------------------------------------------------- BH-43: số lượng đầu prompt không phải số thứ tự
@pytest.mark.parametrize("prompt", [
    "2 cô gái nhảy múa trên sân khấu",
    "3 chiếc xe đua qua cầu",
    "10 con ngựa phi qua thảo nguyên",
    "2cô gái",            # không có khoảng trắng sau số: không phải số thứ tự
])
def test_bh43_leading_quantity_is_kept_verbatim(prompt):
    assert director.strip_leading_number(prompt) == prompt
    r = director.compose(prompt)
    assert r["prompt_clean"] == prompt
    assert prompt in r["prompt_final"]


@pytest.mark.parametrize("prompt,expected", [
    ("03. Cảnh mở đầu", "Cảnh mở đầu"),
    ("12 - Cảnh 12 có số 12 ở giữa", "Cảnh 12 có số 12 ở giữa"),
    ("3: Cảnh ba", "Cảnh ba"),
    ("7) Cảnh bảy", "Cảnh bảy"),
    ("  01.  Cảnh có khoảng trắng thừa  ", "Cảnh có khoảng trắng thừa"),
])
def test_bh43_ordinal_with_separator_is_stripped(prompt, expected):
    assert director.strip_leading_number(prompt) == expected


def test_duration_and_model_header():
    """BH-46: câu mở đầu nêu đủ model, số giây (ép vào 4-15, "30 giây" → 15) và tỷ lệ khung hình (mặc định 16:9 ngang)."""
    assert director.compose("x", duration_label="30 giây")["prompt_final"].startswith(
        "Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay.")
    assert director.compose("x", duration_label=10)["prompt_final"].startswith("Tạo video Seedance 2.5 dài 10 giây, tỷ lệ khung hình 16:9 (ngang).")
    assert director.compose("x", duration_label="", model="")["prompt_final"].startswith("Tạo video Seedance 2.5 dài 15 giây,")
    assert director.compose("x", ratio="9:16")["prompt_final"].startswith("Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 9:16 (dọc). Không hỏi lại, tạo video ngay.")
    assert director.compose("x", ratio="Dọc")["prompt_final"].startswith("Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 9:16 (dọc).")
    assert director.compose("x", duration_label="3 giây", ratio="4:3")["prompt_final"].startswith("Tạo video Seedance 2.5 dài 4 giây, tỷ lệ khung hình 16:9 (ngang).")
    assert director.build_header() == H15
    assert "?" not in H15


def test_bh46_fix_header_rewrites_old_header_only():
    """Job cũ trong hàng đợi có prompt_final "dài 30 giây." (không tỷ lệ) → header mới, phần sau nguyên văn;
    header đã có giây 4-15 VÀ tỷ lệ hợp lệ → giữ nguyên dù tham số truyền vào khác (BH-49, người dùng đã sửa tay);
    prompt_final người dùng tự viết (không có header nhận ra được) → giữ nguyên."""
    old = "Tạo video Seedance 2.5 dài 30 giây. Cô gái cười. Hình ảnh: abc; def."
    assert director.fix_header(old, "30 giây", "16:9") == f"{H15} Cô gái cười. Hình ảnh: abc; def."
    new = f"{director.build_header('Seedance 2.0', '10 giây', '9:16')} Cô gái cười."
    assert director.fix_header(new, "10 giây", "9:16") == new
    assert director.fix_header(new, "15 giây", "16:9") == new, "header hợp lệ không bị ghi đè bởi cột job/setting"
    # thiếu tỷ lệ hoặc giây ngoài khoảng → viết lại
    assert director.fix_header("Tạo video Seedance 2.5 dài 10 giây. Cô gái cười.", "10 giây", "9:16") == \
        f"{director.build_header('Seedance 2.5', '10 giây', '9:16')} Cô gái cười."
    assert director.fix_header("Tạo video Seedance 2.5 dài 30 giây, tỷ lệ khung hình 16:9 (ngang). Cô gái cười.", "15 giây", "16:9") == \
        f"{H15} Cô gái cười."
    assert director.fix_header("Prompt tay không có câu mở đầu, 30 giây.", "30 giây", "16:9") == "Prompt tay không có câu mở đầu, 30 giây."
    assert director.fix_header("", "15 giây", "16:9") == ""


def test_bh49_parse_header_reads_back_user_edited_values():
    """BH-49: người dùng sửa header thành 8 giây 9:16 → đọc ngược đúng, valid=True; thiếu tỷ lệ/giây lạ → valid=False."""
    edited = f"{director.build_header('Seedance 2.5', '8 giây', '9:16')} Cô gái cười."
    info = director.parse_header(edited)
    assert (info["model"], info["seconds"], info["ratio"], info["valid"]) == ("Seedance 2.5", 8, "9:16", True)
    assert edited[info["end"]:].strip() == "Cô gái cười."
    assert director.fix_header(edited, "15 giây", "16:9") == edited
    info = director.parse_header("Tạo video Seedance 2.5 dài 30 giây. Cô gái cười.")
    assert (info["seconds"], info["ratio"], info["valid"]) == (30, None, False)
    info = director.parse_header("Tạo video Seedance 2.5 dài 10 giây. Cô gái cười.")
    assert (info["seconds"], info["ratio"], info["valid"]) == (10, None, False)
    info = director.parse_header("Tạo video Seedance 2.5 dài 20 giây, tỷ lệ khung hình 16:9 (ngang). Cô gái cười.")
    assert (info["seconds"], info["ratio"], info["valid"]) == (20, "16:9", False)
    assert director.parse_header("Prompt tay không có câu mở đầu.") is None
    assert director.parse_header("") is None


def test_visual_section_order_and_layers_added():
    r = director.compose("Chiếc xe chạy qua cầu lúc nửa đêm")
    d = director.ARCHETYPE_BY_CODE["Cine-Master"]
    expected = "Hình ảnh: " + "; ".join([d["visual_group"], d["shot"], d["angle"], d["lens"], d["lighting"], d["palette"], d["six_elements"]]) + "."
    assert r["prompt_final"].endswith(expected)
    assert r["layers_added"] == ["style", "shot", "angle", "lens", "lighting", "palette"]


# ---------------------------------------------------------------- P3: lớp đã có thì không chèn
def test_p3_existing_lens_not_inserted_twice():
    r = director.compose("Chân dung cô gái, ống kính 85mm", options={"director_layer_character": "0"})
    assert "lens" in r["existing_layers"]
    assert "lens" not in r["layers_added"]
    pf = r["prompt_final"]
    assert pf.count("85mm") == 1, pf
    assert "Portrait Lens f/1.4" not in pf
    # lớp khác vẫn được chèn
    assert "Rembrandt Lighting" in pf and "Close-Up (CU) portrait" in pf


@pytest.mark.parametrize("prompt,layers", [
    ("cận cảnh gương mặt", {"shot"}),
    ("Close-up on the hands", {"shot"}),
    ("góc quay từ trên cao", {"angle"}),
    ("FPV drone bay qua thung lũng", {"angle"}),
    ("ống kính 24mm", {"lens"}),
    ("ánh sáng hoàng hôn", {"lighting"}),
    ("rim light on hair", {"lighting"}),
    ("bảng màu cam xanh", {"palette"}),
    ("teal and orange color grading", {"palette"}),
    ("cinematic 4k", {"style"}),
    ("F1 Fantasy thiên nhiên và cổ tích (Alan Lee style, leading stone path)", {"style"}),
    ("Lightning storm over the lighthouse, slightly tilted", set()),   # không nhầm light trong lightning/lighthouse/slightly
    ("Hai người nói chuyện", set()),
])
def test_detect_existing_layers(prompt, layers):
    assert director.detect_existing_layers(prompt) == layers


def test_fully_described_prompt_only_gets_header_and_characters():
    """Prompt đã được bản JS cũ 'nâng cấp' (đủ shot/lens/lighting/palette/visual style) → chỉ thêm câu mở đầu."""
    old_js = ("Cô gái, Close-Up (CU) portrait, Slightly low eye-level cinematic framing, 85mm Portrait Lens f/1.4, "
              "Rembrandt Lighting, visual style P1, Teal and Orange cinema color palette, 8k resolution, cinematic masterpiece")
    r = director.compose(old_js)
    assert r["layers_added"] == []
    assert r["prompt_final"] == f"{H15} {old_js}."


# ---------------------------------------------------------------- P4: nhân vật
def test_p4_character_description_inserted_verbatim():
    r = director.compose("Tiểu Vũ bước vào sân đình", assets=ASSETS)
    assert r["characters"] == ["Tiểu Vũ"]
    assert "character" in r["layers_added"]
    assert "Nhân vật: Tiểu Vũ: cô gái 20 tuổi, tóc đen dài ngang lưng, áo dài trắng, ánh mắt kiên định." in r["prompt_final"]
    assert "KHÔNG ĐƯỢC KHỚP" not in r["prompt_final"]   # "Vũ" là chuỗi con của "Tiểu Vũ", không khớp từ nguyên


def test_p4_character_matching_rules():
    assert [a["name"] for a in director.find_characters("tiểu vũ và LT02 gặp nhau", ASSETS)] == ["Tiểu Vũ", "Lão Trần"]
    assert director.find_characters("Tiểu Vũng Tàu buổi sáng", ASSETS) == []        # không khớp một phần từ
    assert director.find_characters("TiểuVũ", ASSETS) == []
    # NFD (dấu tổ hợp) trong prompt vẫn khớp tên NFC trong CSDL
    import unicodedata
    nfd = unicodedata.normalize("NFD", "Tiểu Vũ đi chợ")
    assert [a["name"] for a in director.find_characters(nfd, ASSETS)] == ["Tiểu Vũ"]
    # thứ tự theo vị trí xuất hiện
    assert [a["name"] for a in director.find_characters("Lão Trần gọi Tiểu Vũ", ASSETS)] == ["Lão Trần", "Tiểu Vũ"]


def test_p4_reference_image_only_when_file_exists(tmp_path):
    img = tmp_path / "tieu_vu.png"
    img.write_bytes(b"\x89PNG")
    assets = [dict(ASSETS[0], image_url=str(img)), dict(ASSETS[1], image_url=str(tmp_path / "missing.png"))]
    r = director.compose("Lão Trần và Tiểu Vũ", assets=assets)
    assert r["reference_image"] == str(img)          # Lão Trần đứng trước nhưng ảnh không tồn tại → lấy Tiểu Vũ
    assets_url = [dict(ASSETS[0], image_url="https://example.com/a.png")]
    assert director.compose("Tiểu Vũ", assets=assets_url)["reference_image"] is None
    assert director.compose("Tiểu Vũ", assets=assets, path_exists=lambda p: False)["reference_image"] is None


def test_character_without_description_counts_but_adds_no_text():
    assets = [{"id": 9, "name": "Bé Na", "character_code": "", "image_url": "", "description": ""}]
    r = director.compose("Bé Na cười", assets=assets)
    assert r["characters"] == ["Bé Na"]
    assert "Nhân vật:" not in r["prompt_final"]
    assert "character" not in r["layers_added"]


# ---------------------------------------------------------------- P6: tắt lớp
def test_p6_disabled_layers_are_not_inserted():
    opts = {"director_layer_camera": "0", "director_layer_lighting": "0", "director_layer_palette": "0",
            "director_layer_character": "0"}
    r = director.compose("Tiểu Vũ chân dung", options=opts, assets=ASSETS)
    d = director.ARCHETYPE_BY_CODE["P1"]
    pf = r["prompt_final"]
    for text in (d["shot"], d["angle"], d["lens"], d["lighting"], d["palette"], "Nhân vật:"):
        assert text not in pf, text
    assert d["visual_group"] in pf and d["six_elements"] in pf
    assert r["layers_added"] == ["style"]


def test_p6_director_disabled_sends_header_plus_raw_prompt():
    r = director.compose("Tiểu Vũ chân dung", options={"director_enabled": "0"}, assets=ASSETS)
    assert r["enabled"] is False
    assert r["prompt_final"] == f"{H15} Tiểu Vũ chân dung."
    assert r["archetype_code"] == "" and r["layers_added"] == [] and r["characters"] == []


def test_options_from_settings_fills_defaults():
    o = director.options_from_settings({"director_enabled": "0", "max_concurrent_jobs": "6"})
    assert o["director_enabled"] == "0"
    assert o["director_layer_camera"] == "1" and o["director_default_style"] == ""
    assert "max_concurrent_jobs" not in o
    assert set(director.SETTING_DEFAULTS) == set(director.SETTING_KEYS)


# ---------------------------------------------------------------- giao diện và CSDL dùng cùng bộ mã
def test_index_html_style_selects_match_archetypes():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    codes = [a["code"] for a in director.ARCHETYPES]
    for select_id in ("batchStyleSelect", "settingDirectorStyle"):
        m = re.search(rf'<select id="{select_id}".*?</select>', html, re.S)
        assert m, select_id
        values = re.findall(r'<option value="([^"]*)"', m.group(0))
        assert values[0] == "", select_id
        assert values[1:] == codes, (select_id, values[1:])


def test_init_db_seeds_director_settings(db):
    rows = {r["key"]: r["value"] for r in db.rows("SELECT key, value FROM settings")}
    for k, v in director.SETTING_DEFAULTS.items():
        assert rows.get(k) == v, k
    assert "archetype_code" in db.columns("jobs")
