"""
Sinh docs/DAO_DIEN_MAU.md (P7): chạy director.compose trên 30 prompt mẫu tiếng Việt đa dạng và ghi bảng
gốc → kết quả → mã trường phái để người dùng duyệt bộ mẫu. Tái tạo được: `python tests/gen_dao_dien_mau.py`.
tests/test_director_docs.py kiểm file đã sinh khớp với bộ quy tắc hiện tại (sửa director.py → chạy lại script).
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import director  # noqa: E402

OUT = ROOT / "docs" / "DAO_DIEN_MAU.md"

# Kho nhân vật giả định (giống dữ liệu người dùng lưu ở tab Kho nhân vật)
SAMPLE_ASSETS = [
    {"id": 1, "name": "Tiểu Vũ", "character_code": "TV01", "image_url": "",
     "description": "cô gái 20 tuổi, tóc đen dài ngang lưng, áo dài trắng, ánh mắt kiên định"},
    {"id": 2, "name": "Lão Trần", "character_code": "LT02", "image_url": "",
     "description": "ông lão 70 tuổi râu bạc, áo nâu sờn, chống gậy trúc"},
]

SAMPLE_PROMPTS = [
    # Đối thoại (T1)
    "Tiểu Vũ và Lão Trần ngồi đối thoại bên bếp lửa, ông hỏi về chuyến đi, cô trả lời khẽ",
    "Hai người bạn trò chuyện trên ghế đá công viên lúc chiều tà",
    "Cô giáo nói với học sinh trước cổng trường, học sinh cúi đầu nghe",
    # Chi tiết / macro
    "Cận cảnh đôi mắt ngấn nước mắt của Tiểu Vũ",
    "Chiếc nhẫn bạc xoay chậm trên bàn gỗ, chi tiết hoa văn",
    # Cổ tích / thiên nhiên
    "Khu rừng cổ tích rêu phong, suối nhỏ chảy qua gốc cây cổ thụ",
    "Lâu đài trên đỉnh núi trong sương sớm, đàn chim bay qua tháp",
    # Hành động / hắc ám
    "Chiến binh rượt đuổi quái vật qua cánh đồng dung nham",
    "Sát thủ vung đao trong hẻm tối, lửa cháy phía sau",
    # Không gian lớn
    "Phi thuyền cô độc trôi giữa ngân hà, bầu trời hoàng hôn tím",
    "Người đứng một mình trước chân trời mênh mông sau cơn mưa",
    # Sci-fi
    "Thành phố sci-fi neon về đêm, người máy khổng lồ bước qua đại lộ",
    "Xưởng cơ khí tương lai, cánh tay robot lắp ráp mô-đun",
    # Lịch sử / bi kịch
    "Nhà vua đau khổ trước triều đình sau tin bại trận",
    "Đoàn quân đội trở về thánh đường trong tang thương",
    # Viễn tây
    "Cao bồi cưỡi ngựa băng qua sa mạc cát bụi lúc hoàng hôn",
    "Nhóm thám hiểm vượt hẻm núi đỏ, bụi mù phía sau",
    # Đồ họa
    "Phong cách anime, cô gái tóc xanh đứng trên mái nhà",
    "Minh họa truyện tranh vẽ nét, thành phố mảng phẳng",
    # Gothic
    "Hành lang gothic ma quái với xương sống sinh học trên tường",
    "Ác mộng dưới địa ngục, bóng người quái dị bước ra",
    # Nội thất
    "Trong phòng ấm cúng, ánh nắng cửa sổ chiếu lên tách trà và quyển sách",
    "Quán cà phê tĩnh lặng buổi sáng, hơi nước bốc lên",
    # Bão biển / trừu tượng
    "Bão biển cuồng nộ, sóng thần vỗ vào vách đá",
    "Xoáy màu trừu tượng mơ màng chuyển động chậm",
    # Chân dung
    "Chân dung cô gái mỉm cười dưới mưa, thần thái tự tin",
    "Doanh nhân đứng trước cửa kính tòa nhà, nụ cười nhẹ",
    # Mặc định / đã có lớp sẵn / có nhân vật
    "Chiếc xe chạy qua cầu lúc nửa đêm, camera bám theo",
    "Tiểu Vũ chạy xe máy qua phố cổ, ống kính 85mm, ánh sáng hoàng hôn",
    "02. Lão Trần chống gậy đi qua cánh đồng lúa chín",
]


def build_markdown() -> str:
    assert len(SAMPLE_PROMPTS) == 30, len(SAMPLE_PROMPTS)
    options = director.options_from_settings({})
    lines = [
        "# Bộ mẫu Đạo diễn AI: 30 prompt mẫu và kết quả ghép (P7)",
        "",
        "File này do `python tests/gen_dao_dien_mau.py` sinh ra từ `director.py` (không sửa tay; sửa bộ mẫu thì chạy lại script).",
        "Mục đích: người dùng duyệt xem tool ghép mẫu đạo diễn vào prompt của mình **trước khi gửi Dola** có đúng ý không.",
        "",
        "## Cách ghép",
        "",
        "```",
        "Tạo video {model} dài {N} giây, tỷ lệ khung hình {tỷ lệ} (dọc|ngang). Không hỏi lại, tạo video ngay.",
        "{prompt gốc nguyên văn, chỉ bỏ số thứ tự đầu dòng}.",
        "Nhân vật: {tên}: {mô tả đã lưu trong Kho nhân vật}; ...",
        "Hình ảnh: {trường phái}; {cỡ cảnh}; {góc máy}; {ống kính}; {ánh sáng}; {bảng màu}; {6 thành tố}.",
        "```",
        "",
        "- N là số giây đã ép vào khoảng Dola hỗ trợ 4-15 (\"30 giây\" cũ → 15); tỷ lệ 16:9 (ngang, mặc định) hoặc 9:16 (dọc). "
        "Câu mở đầu nêu rõ cả ba tham số để Dola không hỏi lại (BH-46).",
        "- Lớp nào prompt đã tự mô tả (có `ống kính 85mm`, `cận cảnh`, `ánh sáng ...`, `FPV`, `bảng màu`...) thì **không chèn lại** (P3).",
        "- Lớp tắt trong Cài đặt → Đạo diễn AI thì không chèn (P6). Tắt hẳn Đạo diễn AI → chỉ còn câu mở đầu + prompt gốc.",
        "- Trường phái: tự nhận diện theo từ khóa (bảng dưới), hoặc ép bằng ô \"Trường phái\" khi nạp lô / Cài đặt.",
        "- **Không còn** câu cố định \"FPV ... Hollywood bom tấn\" của bản cũ; cảnh đối thoại được nhánh T1 (over-the-shoulder, 85mm, ánh sáng mềm).",
        "",
        "## Bộ trường phái (thứ tự ưu tiên nhận diện từ trên xuống)",
        "",
        "Bản JS cũ thiếu nhánh **đối thoại** (cảnh hai người nói chuyện bị gán mặc định Cine-Master, rồi backend nối thêm câu FPV hành động). "
        "Nhánh **T1** được thêm với từ khóa `nói`, `đối thoại`, `trò chuyện`, `hỏi`, `trả lời`, `dialogue`, `talk`, `conversation` và đặt **đầu** danh sách: "
        "cảnh có người nói chuyện thì ngữ pháp máy quay (over-the-shoulder, 85mm, ánh sáng mềm) quan trọng hơn bối cảnh. Muốn giữ bối cảnh (ví dụ W1 viễn tây) thì chọn trường phái tay.",
        "",
        "| Mã | Tên | Từ khóa nhận diện |",
        "| --- | --- | --- |",
    ]
    for a in director.ARCHETYPES:
        kw = ", ".join(f"`{k}`" for k in a["keywords"]) or "(mặc định khi không nhánh nào khớp)"
        lines.append(f"| {a['code']} | {a['name']} | {kw} |")
    lines += [
        "",
        "## 30 prompt mẫu (Kho nhân vật giả định: Tiểu Vũ/TV01, Lão Trần/LT02; mọi lớp bật; Seedance 2.5, 15 giây, 16:9)",
        "",
    ]
    for i, p in enumerate(SAMPLE_PROMPTS, 1):
        r = director.compose(p, duration_label="15 giây", ratio="16:9", model="Seedance 2.5", options=options,
                             assets=SAMPLE_ASSETS, path_exists=lambda _p: False)
        lines += [
            f"### {i:02d}. [{r['archetype_code']}] {r['archetype_name']}",
            "",
            f"- Gốc: `{p}`",
            f"- Lớp đã có sẵn (không chèn): {', '.join(r['existing_layers']) or 'không'} · Lớp đã chèn: {', '.join(r['layers_added']) or 'không'}"
            + (f" · Nhân vật: {', '.join(r['characters'])}" if r["characters"] else ""),
            f"- Kết quả gửi Dola: {r['prompt_final']}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    OUT.write_text(build_markdown(), encoding="utf-8")
    print(f"Đã ghi {OUT} ({len(SAMPLE_PROMPTS)} prompt mẫu)")


if __name__ == "__main__":
    main()
