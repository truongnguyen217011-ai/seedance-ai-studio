"""Đạo diễn AI: ghép bộ mẫu đạo diễn (cỡ cảnh, góc máy, ống kính, ánh sáng, bảng màu, trường phái thị giác)
và mô tả nhân vật đã lưu vào prompt của người dùng TRƯỚC khi gửi sang Dola (docs/KIEN_TRUC.md mục 8).

Toàn bộ là hàm thuần, không gọi API ngoài, không đọc CSDL: assets và options được truyền vào qua tham số.
Bộ quy tắc ARCHETYPES chuyển 1:1 từ nhánh if/else của `analyzePromptWithChatGPTAndBructa` (static/js/app.js,
giữ nguyên câu chữ tiếng Anh của mẫu), bổ sung nhánh T1 "Đối thoại" mà bản JS thiếu (xem docs/DAO_DIEN_MAU.md).

Giao diện chỉ gọi POST /api/director/preview để xem trước, không tự ghép lại bằng JS (BH-41).
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set

from constants import DEFAULT_DURATION, DEFAULT_RATIO, RATIO_ORIENTATION, normalize_duration, normalize_ratio

# ---------------------------------------------------------------- bộ mẫu trường phái
# Thứ tự trong danh sách = thứ tự ưu tiên nhận diện (nhánh đầu tiên khớp từ khóa thắng), giống if/else trong JS;
# nhánh T1 (Đối thoại) đặt đầu vì ngữ pháp máy quay của cảnh nói chuyện quan trọng hơn bối cảnh.
# Từ khóa so khớp trên prompt viết thường (NFC). BH-44: từ khóa NGẮN (tiếng Anh ≤ 5 ký tự, tiếng Việt một âm tiết)
# so theo TỪ NGUYÊN (ranh giới từ Unicode) vì so chuỗi con như JS cũ làm "ring" khớp "bringing", "elf" khớp "shelf",
# "lửa" khớp "tên lửa"; từ khóa dài / nhiều âm tiết vẫn so chuỗi con (chịu được số nhiều: forests, castles).
# Từ Việt một âm tiết quá chung (cây, mặt, lửa, tháp, kiếm, đao) được thay bằng cụm có nghĩa (xem _keyword_pattern).
ARCHETYPES: List[Dict] = [
    {
        "code": "T1",
        "name": "Đối Thoại & Trò Chuyện (Over-the-shoulder, 85mm, ánh sáng mềm)",
        "keywords": ["nói", "đối thoại", "trò chuyện", "hỏi", "trả lời", "dialogue", "talk", "talking", "conversation"],
        "shot": "Medium Shot (MS) over-the-shoulder two-shot, shot/reverse-shot coverage",
        "angle": "Eye Level, 180-degree rule respected, subtle slow push-in",
        "lens": "85mm Portrait Lens f/2, shallow depth of field, natural focus pull between speakers",
        "lighting": "Soft key light with gentle wrap, warm practical fill, no harsh contrast",
        "visual_group": "visual style T1 Đối thoại điện ảnh (natural conversational rhythm, expressive faces, calm steady camera)",
        "palette": "Warm neutral skin-tone palette, soft cinematic color grading",
        "six_elements": "balanced two-person framing, clean breathing space, lip-sync friendly steady composition",
    },
    {
        "code": "P1-Macro",
        "name": "Chân Dung Chi Tiết Biểu Cảm (Micro Detail)",
        "keywords": ["mắt", "nước mắt", "nhẫn", "vết sẹo", "ngón tay", "chi tiết", "vũ khí cận", "eye", "eyes",
                     "macro", "detail", "tear", "tears", "ring", "iris"],
        "shot": "Extreme Close-Up (ECU)",
        "angle": "Eye Level micro view",
        "lens": "Macro Lens 100mm, razor sharp focus, paper-thin depth of field",
        "lighting": "Volumetric Lighting, intentional catchlight in iris, high textural clarity",
        "visual_group": "visual style P1 Chân dung chi tiết có chủ ý (Steve McCurry & Helmut Newton)",
        "palette": "cinematic high-contrast grading, deep black shadows",
        "six_elements": "focused micro composition, clean negative breathing space, hyper-realistic skin & fabric pore textures",
    },
    {
        "code": "F1",
        "name": "Fantasy Cổ Tích & Thiên Nhiên (Alan Lee & John Howe)",
        "keywords": ["rừng", "cổ tích", "tiên", "lâu đài", "tòa tháp", "ngọn tháp", "tháp cổ", "cây cổ thụ", "rừng cây",
                     "tán cây", "gốc cây", "suối", "rêu", "yêu tinh", "thung lũng", "thần thoại", "hoa cỏ", "forest",
                     "castle", "fantasy", "ancient", "fairytale", "elf", "woods", "mossy"],
        "shot": "Full Shot (FS) 3-layer depth landscape",
        "angle": "Eye Level with leading stone path into the depth",
        "lens": "24mm Wide Angle Lens, Deep Focus",
        "lighting": "Soft morning sunlight diffusing through atmospheric mist, volumetric god rays",
        "visual_group": "visual style F1 Fantasy thiên nhiên & cổ tích Alan Lee & John Howe (overgrown mossy roots, weathered stones, clean negative space)",
        "palette": "antique organic palette of Moss Green, Earth Brown and Pale Cream",
        "six_elements": "3-layer depth composition, natural curved linework, gentle mist atmosphere",
    },
    {
        "code": "F2",
        "name": "Fantasy Kịch Tính & Hắc Ám (Frank Frazetta & Aleksi Briclot)",
        "keywords": ["chiến binh", "quái vật", "ngọn lửa", "phun lửa", "lửa cháy", "bốc cháy", "dung nham", "hắc ám",
                     "đánh nhau", "chiến đấu", "thanh kiếm", "đấu kiếm", "đao kiếm", "vung kiếm", "cầm kiếm", "kiếm sĩ",
                     "vung đao", "đại đao", "thanh đao", "rồng", "ma vương", "sát thủ", "chém", "huyết", "warrior",
                     "monster", "fire", "dragon", "dark", "battle", "sword", "swords", "frazetta"],
        "shot": "Cowboy Shot (CS) action pose",
        "angle": "Low Angle, dramatic heroic view, Dutch tilt",
        "lens": "24mm High Dynamic Motion Cine Lens",
        "lighting": "Fiery orange directional rim light cutting through smoke, deep black shadow contrast",
        "visual_group": "visual style F2 Fantasy kịch tính Frank Frazetta & Aleksi Briclot (bold heroic silhouette, muscular tension, rough rock and molten metal textures)",
        "palette": "Dramatic Crimson Red, Fire Amber and Deep Shadow Black palette",
        "six_elements": "diagonal dynamic composition, sharp aggressive silhouettes, heavy textural grime",
    },
    {
        "code": "C1",
        "name": "Không Gian Lớn & Ánh Màu (Alena Aenami & John Harris)",
        "keywords": ["vũ trụ", "hành tinh", "ngân hà", "phi thuyền", "không gian", "mênh mông", "hoàng hôn", "chân trời",
                     "bầu trời", "thiên hà", "vô tận", "cô độc", "space", "galaxy", "planet", "cosmic", "horizon",
                     "nebula", "twilight", "colossal"],
        "shot": "Extreme Wide Establishing Shot (EWS)",
        "angle": "Wide Horizon panoramic view",
        "lens": "16mm Ultra-Wide Angle Lens, infinite depth of field",
        "lighting": "Luminous starlight, cosmic twilight glow, atmospheric scattering",
        "visual_group": "visual style C1 Không gian lớn & Ánh màu Alena Aenami & John Harris (tiny human scale vs colossal cosmic architecture, wide negative space)",
        "palette": "Sunset Golden Hour and Violet Twilight cosmic palette, warm and cool atmospheric contrast",
        "six_elements": "monumental scale balance, ultra-wide negative space, glowing volumetric celestial light",
    },
    {
        "code": "C2",
        "name": "Khoa Học Viễn Tưởng Mô-đun & Cơ Khí (Syd Mead & Chris Foss)",
        "keywords": ["robot", "máy móc", "cơ khí", "công nghệ", "tương lai", "mô-đun", "sci-fi", "cyborg", "cyberpunk",
                     "neon", "giáp sắt", "người máy", "mecha", "android", "future", "high-tech"],
        "shot": "Medium Wide Shot (MWS)",
        "angle": "Low Angle high-tech perspective",
        "lens": "Anamorphic Lens, elliptical horizontal flares, razor sharp geometry",
        "lighting": "Industrial spotlights, hazard light strobes, tungsten blue key light, neon wet puddle reflections",
        "visual_group": "visual style C2 Sci-Fi mô-đun Syd Mead & Chris Foss (modular panel seams, weathered chrome, painted metal functionalism)",
        "palette": "Teal and Orange neon cyber palette, cold cyan key and warm tungsten accents",
        "six_elements": "hard-surface geometric lines, layered metallic seams, high-contrast industrial lighting",
    },
    {
        "code": "E1",
        "name": "Bi Kịch & Lịch Sử Hùng Tráng (Ilya Repin & Gustave Doré)",
        "keywords": ["lịch sử", "bi kịch", "chiến tranh", "vua", "hoàng gia", "đau khổ", "tang thương", "thánh đường",
                     "giáo đường", "triều đình", "quân đội", "thập tự", "historical", "history", "tragedy", "royal",
                     "sorrow", "baroque", "repin", "dore"],
        "shot": "Medium Full Shot (MFS) tableau composition",
        "angle": "Slightly low dramatic theatrical stage perspective",
        "lens": "35mm Cine Lens, high optical resolution",
        "lighting": "Baroque dramatic chiaroscuro lighting, warm golden candle highlights, deep expressive shadows",
        "visual_group": "visual style E1 Bi kịch & Lịch sử Ilya Repin & Gustave Doré (intense emotional climax, rich heavy fabric textures, majestic crowd dynamics)",
        "palette": "Rich Umber, Royal Burgundy Crimson and Warm Candle Gold antique palette",
        "six_elements": "theatrical dynamic composition, dense expressive gestures, layered historical costumes",
    },
    {
        "code": "W1",
        "name": "Miền Tây & Phiêu Lưu Thám Hiểm (Frederic Remington & Frank Schoonover)",
        "keywords": ["miền tây", "cao bồi", "sa mạc", "ngựa", "cát bụi", "hẻm núi", "hoang dã", "súng", "thảo nguyên",
                     "thám hiểm", "khám phá", "western", "cowboy", "desert", "dust", "canyon", "horse", "frontier",
                     "remington"],
        "shot": "Cowboy Shot (CS) tracking across vista",
        "angle": "Eye Level tracking view across rugged landscape",
        "lens": "50mm Prime Lens with raking dust haze",
        "lighting": "Harsh blazing desert sunlight casting long raking shadows, golden sand bounce fill",
        "visual_group": "visual style W1 Miền Tây & Phiêu lưu thám hiểm Frederic Remington & Frank Schoonover (sunburnt dust trails, worn leather, rugged sandstone canyons)",
        "palette": "Sunburnt Ochre, Terracotta Earth and Faded Turquoise sky palette",
        "six_elements": "expansive horizontal horizon, granular atmospheric dust texture, dynamic motion trails",
    },
    {
        "code": "G1",
        "name": "Đồ Họa Đường Nét & Mảng Phẳng (Moebius & Kilian Eng)",
        "keywords": ["anime", "manga", "hoạt hình", "đồ họa", "truyện tranh", "vector", "mảng phẳng", "vẽ nét", "moebius",
                     "comic", "graphic", "lineart", "cartoon", "illustration"],
        "shot": "Medium Shot (MS)",
        "angle": "Cinematic Geometric Eye Level",
        "lens": "50mm Prime Lens, razor sharp line definition",
        "lighting": "Clean graphic lighting, soft ambient fill, crisp rim line highlights",
        "visual_group": "visual style G1 Đồ họa đường nét mảng phẳng Moebius (Jean Giraud) & Kilian Eng (intricate precise ink linework, bold graphic silhouette, flat aesthetic planes)",
        "palette": "Harmonic limited graphic palette of Mustard Yellow, Mint Green and Coral Pink",
        "six_elements": "clean contour linework, zero visual clutter, elegant flat colored negative space",
    },
    {
        "code": "D1",
        "name": "Gothic U Tối & Sinh Cơ Khí (H.R. Giger & Zdzisław Beksiński)",
        "keywords": ["ma quái", "gothic", "kinh dị", "u tối", "xương", "sinh học", "quái dị", "chết chóc", "ác mộng",
                     "địa ngục", "giger", "beksinski", "alien", "horror", "eerie", "skeleton", "dystopian",
                     "biomechanical", "nightmare"],
        "shot": "Medium Close-Up (MCU)",
        "angle": "Slightly low claustrophobic unsettling angle",
        "lens": "35mm Cine Lens, high contrast",
        "lighting": "Icy cold rim light, narrow sliver of light cutting through heavy impenetrable darkness",
        "visual_group": "visual style D1 Biomechanical Gothic H.R. Giger & Zdzisław Beksiński (ribbed spine structures, organic tubes, ominous desolate architecture)",
        "palette": "Monochromatic Deep Charcoal Black, Bone White with subtle sickly viridian sheen",
        "six_elements": "claustrophobic repeating bone textures, deep void negative space, cold organic-metallic fusion",
    },
    {
        "code": "S1",
        "name": "Nội Thất & Tĩnh Vật Ánh Sáng Cửa Sổ (Johannes Vermeer & Chardin)",
        "keywords": ["trong phòng", "nội thất", "tĩnh vật", "cửa sổ", "đọc sách", "tách trà", "bàn làm việc", "ấm cúng",
                     "tĩnh lặng", "bình yên", "hoa trên bàn", "phòng khách", "quán cà phê", "room", "interior",
                     "still life", "window light", "cozy", "quiet", "tea", "vermeer", "reading"],
        "shot": "Medium Shot (MS) intimate interior",
        "angle": "Eye Level contemplative natural framing",
        "lens": "50mm Prime Lens (Nifty Fifty), gentle organic falloff",
        "lighting": "Soft north window side light (Vermeer natural light), gentle delicate wall bounce falloff",
        "visual_group": "visual style S1 Nội thất & Tĩnh vật Johannes Vermeer & Jean-Baptiste Chardin (poetic stillness, tactile linen, glazed ceramic and aged wood)",
        "palette": "Harmonic palette of Ultramarine Blue, Warm Ochre Yellow, Pearl White and Aged Timber Brown",
        "six_elements": "golden ratio interior framing, soft tactile textures, spacious peaceful negative space",
    },
    {
        "code": "A1",
        "name": "Trừu Tượng & Biển Giông Thăng Hoa (J.M.W. Turner & Kandinsky)",
        "keywords": ["bão biển", "sóng thần", "biển động", "giông bão", "trừu tượng", "xoáy màu", "mơ màng", "cuồng nộ",
                     "sóng vỗ", "bão tuyết", "tempest", "stormy sea", "tidal wave", "storm", "swirling colors", "turner",
                     "sublime", "abstract", "ocean gale"],
        "shot": "Wide Atmospheric Vista (WAV)",
        "angle": "Dynamic sweeping angle caught in the tempest",
        "lens": "24mm Cine Lens with water droplet reflections",
        "lighting": "Atmospheric swirling light breaking through storm clouds, radiant elemental glow",
        "visual_group": "visual style A1 Trừu tượng & Biểu hiện cảm xúc J.M.W. Turner (elemental vortex, dissolving sky-sea boundaries, sublime force)",
        "palette": "Storm Sulfur Yellow, Deep Ocean Prussian Blue and Whipped Seafoam White palette",
        "six_elements": "vortical spiral composition, dissolved boundaries, fluid atmospheric motion textures",
    },
    {
        "code": "P1",
        "name": "Chân Dung Điện Ảnh & Biểu Cảm (Steve McCurry & Helmut Newton)",
        "keywords": ["chân dung", "khuôn mặt", "gương mặt", "cô gái", "chàng trai", "người đẹp", "nữ sinh", "doanh nhân",
                     "nụ cười", "mỹ nhân", "nữ hiệp", "thần thái", "portrait", "girl", "girls", "woman", "women", "man",
                     "face", "model", "expressive gaze"],
        "shot": "Close-Up (CU) portrait",
        "angle": "Slightly low eye-level cinematic framing",
        "lens": "85mm Portrait Lens f/1.4, creamy optical bokeh",
        "lighting": "Rembrandt Lighting with chiaroscuro triangle on cheek, catchlight in eyes, subsurface scattering on skin, warm rim light",
        "visual_group": "visual style P1 Chân dung điện ảnh Steve McCurry & Helmut Newton (expressive emotive gaze, natural breathing space)",
        "palette": "Teal and Orange cinema color palette, Blue Key Light, Warm Amber Fill Light",
        "six_elements": "rule of thirds composition, rich skin subsurface texture, controlled shadow gradient",
    },
    {
        # Nhánh mặc định: không có từ khóa, dùng khi không nhánh nào khớp
        "code": "Cine-Master",
        "name": "Điện Ảnh Hollywood Bom Tấn (Blockbuster)",
        "keywords": [],
        "shot": "Medium Shot (MS)",
        "angle": "Cinematic Eye Level framing",
        "lens": "50mm Prime Lens (Nifty Fifty)",
        "lighting": "Three-point lighting, Blue Key Light, Warm Orange Fill Light, subtle catchlight",
        "visual_group": "chuẩn điện ảnh Hollywood Masterpiece (balanced 3-layer composition, controlled negative breathing space)",
        "palette": "Cinematic Color Grading, 35mm Tungsten Film Stock, subtle natural film grain",
        "six_elements": "blockbuster cinematic framing, balanced rule-of-thirds, rich tactile textures",
    },
]

DEFAULT_ARCHETYPE_CODE = "Cine-Master"
ARCHETYPE_BY_CODE: Dict[str, Dict] = {a["code"]: a for a in ARCHETYPES}

# Tên lớp (layer) và khóa setting bật/tắt từng lớp
LAYER_SHOT = "shot"
LAYER_ANGLE = "angle"
LAYER_LENS = "lens"
LAYER_LIGHTING = "lighting"
LAYER_PALETTE = "palette"
LAYER_STYLE = "style"  # visual_group + six_elements (trường phái thị giác)
LAYER_CHARACTER = "character"

SETTING_KEYS = (
    "director_enabled",
    "director_layer_camera",     # shot + angle + lens
    "director_layer_lighting",
    "director_layer_palette",
    "director_layer_character",
    "director_default_style",    # "" = tự nhận diện, hoặc một mã trong ARCHETYPE_BY_CODE
)
SETTING_DEFAULTS = {
    "director_enabled": "1",
    "director_layer_camera": "1",
    "director_layer_lighting": "1",
    "director_layer_palette": "1",
    "director_layer_character": "1",
    "director_default_style": "",
}

# ---------------------------------------------------------------- nhận diện lớp đã có sẵn trong prompt (P3)
# Mỗi lớp: danh sách regex (không phân biệt hoa thường). (?<!\w) ... (?!\w) = khớp từ nguyên, kể cả chữ có dấu.
def _word(p: str) -> str:
    return r"(?<!\w)" + p + r"(?!\w)"


_LAYER_PATTERNS: Dict[str, List[re.Pattern]] = {
    LAYER_SHOT: [re.compile(p, re.IGNORECASE) for p in (
        _word(r"shot"), _word(r"close[\s-]?up"), _word(r"wide"), _word(r"cận cảnh"), _word(r"toàn cảnh"),
        _word(r"cỡ cảnh"), _word(r"trung cảnh"), _word(r"đại cảnh"), _word(r"two-shot"), _word(r"over-the-shoulder"),
    )],
    LAYER_ANGLE: [re.compile(p, re.IGNORECASE) for p in (
        _word(r"angle"), _word(r"fpv"), _word(r"góc quay"), _word(r"góc máy"), _word(r"eye[\s-]level"),
        _word(r"top[\s-]down"), _word(r"bird'?s[\s-]eye"), _word(r"dutch tilt"), _word(r"góc thấp"), _word(r"góc cao"),
    )],
    LAYER_LENS: [re.compile(p, re.IGNORECASE) for p in (
        _word(r"lens"), _word(r"\d{2,3}\s?mm"), _word(r"ống kính"), _word(r"anamorphic"), _word(r"tiêu cự"),
        _word(r"macro"), _word(r"bokeh"), _word(r"depth of field"),
    )],
    LAYER_LIGHTING: [re.compile(p, re.IGNORECASE) for p in (
        _word(r"lighting"), _word(r"light"), _word(r"ánh sáng"), _word(r"god rays"), _word(r"chiaroscuro"),
        _word(r"rembrandt"), _word(r"rim light"), _word(r"key light"), _word(r"backlit"), _word(r"đèn"),
    )],
    LAYER_PALETTE: [re.compile(p, re.IGNORECASE) for p in (
        _word(r"palette"), _word(r"color grading"), _word(r"colour grading"), _word(r"color grade"), _word(r"bảng màu"),
        _word(r"tông màu"), _word(r"film stock"), _word(r"teal and orange"), _word(r"film grain"),
    )],
    LAYER_STYLE: [re.compile(p, re.IGNORECASE) for p in (
        _word(r"cinematic"), _word(r"[48]k"), _word(r"visual style"), _word(r"masterpiece"), _word(r"điện ảnh"),
        _word(r"trường phái"), _word(r"style"),
        # Mã trường phái người dùng chèn từ nút "11 Trường Phái" trên giao diện
        _word(r"(?:F1|F2|C1|C2|E1|W1|G1|P1|D1|S1|A1|T1)"),
    )],
}


def detect_existing_layers(prompt: str) -> Set[str]:
    """Trả về tập lớp mà prompt đã tự mô tả (shot/angle/lens/lighting/palette/style). Lớp nào đã có thì compose không chèn."""
    text = _nfc(prompt or "")
    found: Set[str] = set()
    for layer, patterns in _LAYER_PATTERNS.items():
        if any(p.search(text) for p in patterns):
            found.add(layer)
    return found


# ---------------------------------------------------------------- nhận diện trường phái
# BH-43: chỉ bỏ số thứ tự có DẤU PHÂN CÁCH thật ("01. ", "3: ", "12 - ", "7) "); số lượng đầu prompt
# ("2 cô gái nhảy múa", "3 chiếc xe đua") không có dấu phân cách nên phải giữ nguyên văn.
_LEADING_NUMBER = re.compile(r"^\d+\s*[\.\:\-\)]\s+")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def strip_leading_number(prompt: str) -> str:
    """Bỏ số thứ tự đầu dòng ("01. ", "3: ", "12 - "), giữ nguyên phần còn lại; "2 cô gái ..." giữ số (BH-43)."""
    return _LEADING_NUMBER.sub("", _nfc(prompt).strip(), count=1).strip()


def _keyword_pattern(keyword: str) -> re.Pattern:
    r"""Regex cho một từ khóa trường phái (BH-44).

    - Tiếng Anh (thuần ASCII) dài ≤ 5 ký tự ("ring", "elf", "tea", "man", "dark"...) và tiếng Việt MỘT âm tiết
      ("lửa", "mắt", "rừng", "nói"...): so theo từ nguyên `(?<!\w)...(?!\w)` (ranh giới từ Unicode), vì so chuỗi
      con làm "ring" khớp "bringing", "elf" khớp "shelf", "tea" khớp "steam", "lửa" khớp "tên lửa".
    - Còn lại (từ dài, cụm nhiều âm tiết): so chuỗi con như JS cũ, chịu được số nhiều/biến thể (forests, castles).
    """
    k = _nfc(keyword).strip().lower()
    single_token = " " not in k and "-" not in k
    if (k.isascii() and len(k) <= 5) or (not k.isascii() and single_token):
        return re.compile(_word(re.escape(k)))
    return re.compile(re.escape(k))


_ARCHETYPE_PATTERNS: List[tuple] = [(a, [_keyword_pattern(k) for k in a["keywords"]]) for a in ARCHETYPES]


def keyword_matches(keyword: str, text: str) -> bool:
    """Từ khóa có khớp prompt (đã viết thường, NFC) theo quy tắc _keyword_pattern không."""
    return _keyword_pattern(keyword).search(_nfc(text).lower()) is not None


def detect_archetype(prompt: str) -> Dict:
    """Nhánh đầu tiên (theo thứ tự ARCHETYPES) có từ khóa khớp prompt viết thường (xem _keyword_pattern);
    không có → mặc định."""
    lower = strip_leading_number(prompt).lower()
    for arch, patterns in _ARCHETYPE_PATTERNS:
        if any(p.search(lower) for p in patterns):
            return arch
    return ARCHETYPE_BY_CODE[DEFAULT_ARCHETYPE_CODE]


def analyze(prompt: str) -> Dict:
    """Trả về {code, name, shot, angle, lens, lighting, visual_group, palette, six_elements, existing_layers}."""
    arch = detect_archetype(prompt)
    out = {k: v for k, v in arch.items() if k != "keywords"}
    out["existing_layers"] = sorted(detect_existing_layers(prompt))
    return out


def resolve_style(style_code: Optional[str]) -> Optional[Dict]:
    """Mã trường phái người dùng ép → archetype; "" / None → None (tự nhận diện). Mã lạ → ValueError tiếng Việt."""
    code = (style_code or "").strip()
    if not code:
        return None
    for c, arch in ARCHETYPE_BY_CODE.items():
        if c.lower() == code.lower():
            return arch
    raise ValueError(f"Mã trường phái '{code}' không có trong bộ mẫu (các mã hợp lệ: {', '.join(ARCHETYPE_BY_CODE)})")


# ---------------------------------------------------------------- nhân vật (P4)
def find_characters(prompt: str, assets: Iterable[Dict]) -> List[Dict]:
    """Asset có `name` hoặc `character_code` xuất hiện trong prompt dưới dạng từ nguyên (không phân biệt hoa thường,
    tên có dấu so sau khi chuẩn hóa NFC). Tên dài được ưu tiên: "Tiểu Vũ" đã khớp thì asset "Vũ" không khớp vào
    đoạn đó nữa. Trả về danh sách asset theo thứ tự xuất hiện trong prompt, không trùng."""
    text = _nfc(prompt).lower()
    candidates = []
    for asset in assets or ():
        if not isinstance(asset, dict):
            asset = dict(asset)
        needles = []
        for key in ("name", "character_code"):
            needle = _nfc(str(asset.get(key) or "")).strip().lower()
            if len(needle) >= 2:
                needles.append(needle)
        if needles:
            candidates.append((max(len(n) for n in needles), needles, asset))
    candidates.sort(key=lambda t: -t[0])  # tên dài khớp trước
    hits = []
    masked = text
    for _, needles, asset in candidates:
        best = None
        for needle in sorted(needles, key=len, reverse=True):
            m = re.search(_word(re.escape(needle)), masked)
            if m and (best is None or m.start() < best.start()):
                best = m
        if best is not None:
            masked = masked[:best.start()] + " " * (best.end() - best.start()) + masked[best.end():]
            hits.append((best.start(), asset))
    hits.sort(key=lambda t: t[0])
    out, seen = [], set()
    for _, asset in hits:
        ident = asset.get("id") or (asset.get("name"), asset.get("character_code"))
        if ident in seen:
            continue
        seen.add(ident)
        out.append(asset)
    return out


# ---------------------------------------------------------------- options
def _flag(options: Optional[Dict], key: str, default: str = "1") -> bool:
    raw = (options or {}).get(key, SETTING_DEFAULTS.get(key, default))
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "on", "yes")


def is_enabled(options: Optional[Dict]) -> bool:
    """Đạo diễn AI có bật không (setting director_enabled, mặc định bật)."""
    return _flag(options, "director_enabled")


def options_from_settings(settings: Optional[Dict]) -> Dict:
    """Lọc dict settings (key → value chuỗi) ra các khóa director_*, điền mặc định cho khóa thiếu."""
    settings = settings or {}
    return {k: settings.get(k, v) for k, v in SETTING_DEFAULTS.items()}


# ---------------------------------------------------------------- ghép prompt (P1..P6)
def _duration_seconds(duration_label) -> int:
    """'15 giây' → 15; 10 → 10; "30 giây" → 15 (ép vào khoảng Dola hỗ trợ, BH-46); rỗng → mặc định."""
    return normalize_duration(duration_label)[0]


DEFAULT_MODEL = "Seedance 2.5"
# Câu mở đầu do tool tự chèn (không phải prompt của người dùng). Khớp cả bản cũ "Tạo video X dài N giây." để
# build_full_prompt sửa lại header của job tạo trước khi có tỷ lệ/ép thời lượng (xem fix_header).
HEADER_RE = re.compile(r"^Tạo video (?P<model>.+?) dài (?P<seconds>\d+) giây(?P<ratio>, tỷ lệ khung hình [^.]*)?\."
                       r"(?: Không hỏi lại, tạo video ngay\.)?", re.S)


def build_header(model=DEFAULT_MODEL, duration_label=DEFAULT_DURATION, ratio=DEFAULT_RATIO) -> str:
    """Câu mở đầu gửi Dola, nêu rõ ba tham số Dola cần (BH-46): model, số giây (4-15), tỷ lệ khung hình.

    "Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay."
    """
    model = str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    seconds = _duration_seconds(duration_label)
    ratio_value = normalize_ratio(ratio)[0]
    orientation = RATIO_ORIENTATION.get(ratio_value, "")
    return (f"Tạo video {model} dài {seconds} giây, tỷ lệ khung hình {ratio_value} ({orientation}). "
            f"Không hỏi lại, tạo video ngay.")


def fix_header(prompt_final: str, duration_label, ratio, model=None) -> str:
    """Thay câu mở đầu của prompt_final đã lưu bằng câu mở đầu hiện tại (thời lượng đã ép, có tỷ lệ).

    Job tạo trước bản này có header "Tạo video Seedance 2.5 dài 30 giây." → "... dài 15 giây, tỷ lệ ... ".
    Không có header nhận ra được (người dùng đã sửa tay toàn bộ) → giữ nguyên văn, không chèn gì.
    """
    text = (prompt_final or "").strip()
    m = HEADER_RE.match(text)
    if not m:
        return text
    header = build_header(model or m.group("model"), duration_label, ratio)
    rest = text[m.end():].lstrip()
    return f"{header} {rest}".strip()


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def compose(prompt: str, *, duration_label=DEFAULT_DURATION, ratio=DEFAULT_RATIO, model=DEFAULT_MODEL,
            options: Optional[Dict] = None, assets: Optional[Sequence[Dict]] = None,
            style_override: Optional[str] = None, path_exists: Callable[[str], bool] = os.path.isfile) -> Dict:
    """Ghép prompt cuối cùng gửi Dola.

    Cấu trúc: "Tạo video {model} dài {N} giây, tỷ lệ khung hình {ratio} ({dọc|ngang}). Không hỏi lại, tạo video ngay.
    {prompt gốc nguyên văn, chỉ bỏ số thứ tự đầu dòng}.
    Nhân vật: {mô tả đã lưu của từng nhân vật khớp}. Hình ảnh: {visual_group}; {shot}; {angle}; {lens}; {lighting};
    {palette}; {six_elements}." — chỉ gồm lớp được bật trong options và chưa có sẵn trong prompt (P3, P6).
    style_override (mã F1..A1/P1/T1) ép trường phái; "" → options['director_default_style']; "" nữa → tự nhận diện.
    Trả về dict(prompt_final, archetype{code,name}, archetype_code, archetype_name, layers_added, characters,
    reference_image, existing_layers, enabled).
    """
    options = options_from_settings(options)
    clean = strip_leading_number(prompt)
    model = str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    header = build_header(model, duration_label, ratio)
    enabled = _flag(options, "director_enabled")

    result = {
        "prompt": prompt,
        "prompt_clean": clean,
        "enabled": enabled,
        "archetype": None,
        "archetype_code": "",
        "archetype_name": "",
        "layers_added": [],
        "existing_layers": sorted(detect_existing_layers(clean)),
        "characters": [],
        "reference_image": None,
    }
    if not enabled:
        result["prompt_final"] = f"{header} {_sentence(clean)}" if clean else header
        return result

    arch = resolve_style(style_override) or resolve_style(options.get("director_default_style")) or detect_archetype(clean)
    existing = set(result["existing_layers"])
    parts: List[str] = [header]
    if clean:
        parts.append(_sentence(clean))

    # Nhân vật đã lưu (P4)
    matched: List[Dict] = []
    if _flag(options, "director_layer_character"):
        matched = find_characters(clean, assets or [])
        descs = []
        for a in matched:
            desc = _nfc(str(a.get("description") or "")).strip()
            name = _nfc(str(a.get("name") or a.get("character_code") or "")).strip()
            if desc:
                descs.append(f"{name}: {desc}" if name else desc)
        if descs:
            parts.append(_sentence("Nhân vật: " + "; ".join(d.rstrip(".") for d in descs)))
            result["layers_added"].append(LAYER_CHARACTER)
        for a in matched:
            img = str(a.get("image_url") or "").strip()
            if img and not img.lower().startswith(("http://", "https://", "data:")) and path_exists(img):
                result["reference_image"] = img
                break

    # Các lớp hình ảnh: (tên lớp, có bật không, chuỗi mẫu)
    camera_on = _flag(options, "director_layer_camera")
    layer_specs = [
        (LAYER_STYLE, True, arch["visual_group"]),
        (LAYER_SHOT, camera_on, arch["shot"]),
        (LAYER_ANGLE, camera_on, arch["angle"]),
        (LAYER_LENS, camera_on, arch["lens"]),
        (LAYER_LIGHTING, _flag(options, "director_layer_lighting"), arch["lighting"]),
        (LAYER_PALETTE, _flag(options, "director_layer_palette"), arch["palette"]),
        (LAYER_STYLE, True, arch["six_elements"]),
    ]
    visual: List[str] = []
    for layer, on, text in layer_specs:
        if not on or layer in existing or not text:
            continue
        visual.append(text)
        if layer not in result["layers_added"]:
            result["layers_added"].append(layer)
    if visual:
        parts.append(_sentence("Hình ảnh: " + "; ".join(v.rstrip(".") for v in visual)))

    result["prompt_final"] = " ".join(parts)
    result["archetype"] = {"code": arch["code"], "name": arch["name"]}
    result["archetype_code"] = arch["code"]
    result["archetype_name"] = arch["name"]
    result["characters"] = [str(a.get("name") or a.get("character_code") or "") for a in matched]
    return result


def style_choices() -> List[Dict]:
    """Danh sách {code, name} cho select "Trường phái" trên giao diện (thứ tự như ARCHETYPES)."""
    return [{"code": a["code"], "name": a["name"]} for a in ARCHETYPES]
