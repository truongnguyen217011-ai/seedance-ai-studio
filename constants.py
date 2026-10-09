"""Hằng số dùng chung cho backend và frontend (xem docs/KIEN_TRUC.md mục 3-4)."""
import re
from typing import Optional, Tuple

# ---- Tham số video gửi sang Dola (BH-46): chỉ những giá trị Dola THẬT chấp nhận ----
# Bằng chứng (HTML trang Dola, job #23): "Video generation currently supports durations from 4 to 15 seconds";
# Dola hỏi lại tỷ lệ khung hình nếu prompt không nói. Người dùng chốt mặc định 15 giây, 16:9 (ngang).
DURATION_MIN_SECONDS = 4
DURATION_MAX_SECONDS = 15
DURATION_CHOICES = ("5 giây", "10 giây", "15 giây")
RATIO_CHOICES = ("16:9", "9:16")
DEFAULT_DURATION = "15 giây"
DEFAULT_RATIO = "16:9"
RATIO_ORIENTATION = {"16:9": "ngang", "9:16": "dọc"}

_RE_FIRST_INT = re.compile(r"\d+")


def normalize_duration(label) -> Tuple[int, Optional[str]]:
    """Nhãn/giá trị thời lượng → (số giây đã ép vào 4..15, cảnh báo tiếng Việt hoặc None).

    "30 giây" → (15, "Thời lượng 30 giây ngoài khoảng Dola hỗ trợ (4-15 giây), đã ép về 15 giây");
    "15 giây" / 15 / "15" → (15, None); rỗng hoặc không có số → (15, cảnh báo dùng mặc định).
    """
    raw = str(label if label is not None else "").strip()
    m = _RE_FIRST_INT.search(raw)
    default_seconds = int(_RE_FIRST_INT.search(DEFAULT_DURATION).group(0))
    if not m:
        if not raw:
            return default_seconds, None
        return default_seconds, f"Thời lượng '{raw}' không hợp lệ, dùng mặc định {DEFAULT_DURATION}"
    seconds = int(m.group(0))
    if seconds < DURATION_MIN_SECONDS or seconds > DURATION_MAX_SECONDS:
        clamped = max(DURATION_MIN_SECONDS, min(DURATION_MAX_SECONDS, seconds))
        return clamped, (f"Thời lượng {seconds} giây ngoài khoảng Dola hỗ trợ "
                         f"({DURATION_MIN_SECONDS}-{DURATION_MAX_SECONDS} giây), đã ép về {clamped} giây")
    return seconds, None


def duration_label(seconds: int) -> str:
    return f"{int(seconds)} giây"


def normalize_ratio(value) -> Tuple[str, Optional[str]]:
    """Tỷ lệ khung hình → (một trong RATIO_CHOICES, cảnh báo hoặc None). Chấp nhận "Dọc"/"Ngang" của giao diện cũ."""
    raw = str(value if value is not None else "").strip()
    if not raw:
        return DEFAULT_RATIO, None
    low = raw.lower()
    if low in ("dọc", "doc", "vertical", "portrait"):
        return "9:16", None
    if low in ("ngang", "horizontal", "landscape"):
        return "16:9", None
    compact = low.replace(" ", "")
    for r in RATIO_CHOICES:
        if compact == r:
            return r, None
    return DEFAULT_RATIO, f"Tỷ lệ khung hình '{raw}' không hợp lệ, dùng mặc định {DEFAULT_RATIO}"


class JobStatus:
    CHO = "Chờ"
    DANG_CHAY = "Đang chạy"
    HOAN_THANH = "Hoàn thành"
    THAT_BAI = "Thất bại"
    TAM_DUNG = "Tạm dừng"

    ALL = (CHO, DANG_CHAY, HOAN_THANH, THAT_BAI, TAM_DUNG)
    FINISHED = (HOAN_THANH, THAT_BAI)


# Trạng thái cũ còn trong CSDL của người dùng → trạng thái mới
LEGACY_JOB_STATUS_MAP = {
    "Đang chờ": JobStatus.CHO,
    "Chờ đăng nhập Dola": JobStatus.CHO,
    "Đang xử lý": JobStatus.DANG_CHAY,
    "Lỗi": JobStatus.THAT_BAI,
}


class AccountStatus:
    READY = "ready"
    RATE_LIMITED = "rate_limited"
    RESTING = "resting"
    DISABLED = "disabled"


class NeedsManual:
    """Cột accounts.needs_manual: nick cần người dùng can thiệp tay."""
    CAPTCHA = "captcha"
    LOGIN = "login"
    PROXY = "proxy"


class Reason:
    """Chuỗi lý do chuẩn hiển thị cho người dùng."""
    APP_RESTARTED = "App khởi động lại, job sẽ chạy lại từ đầu"
    WAITING_ACCOUNT = "Chưa có nick phù hợp: {summary}"
    ACCOUNT_BUSY = "Chờ nick '{name}' rảnh (đang chạy job #{job_id})"
    CAPTCHA = "Nick '{name}' bị Dola yêu cầu kéo mảnh ghép (captcha). Mở Chrome của nick, kéo mảnh ghép, rồi bấm Tiếp tục"
    NO_CREDIT_ROTATE = "Nick '{name}' hết credit hôm nay, đã chuyển sang nick '{next_name}'"
    NO_CREDIT_WAIT = "Nick '{name}' hết credit hôm nay, chưa có nick khác, chờ hồi phục lúc 00:05"
    NO_NEW_CONV = "Dola không tạo cuộc trò chuyện mới cho prompt này (không lấy lại video cũ)"
    RENDER_TIMEOUT = "Quá {seconds}s chưa nhận được video từ Dola"
    RENDER_TIMEOUT_WITH_REPLY = "Quá {seconds}s chưa nhận được video từ Dola; Dola trả lời: '{text}'"
    # Dola trả lời bằng chữ (hỏi lại lần hai, từ chối, giải thích) thay vì tạo video: lỗi nội dung, không tự chạy lại
    DOLA_REPLIED_TEXT = "Dola trả lời bằng chữ thay vì tạo video: '{text}'"
    POLICY_REFUSED = "Dola từ chối tạo video do chính sách nội dung"
    DOWNLOAD_FAILED = "Tải video về máy thất bại: {error}"
    BROWSER_ERROR = "Lỗi trình duyệt: {error}"
    MAX_ATTEMPTS = "Đã thử {n} lần vẫn lỗi, dừng tự chạy lại. Bấm Chạy lại nếu muốn thử tiếp"
    USER_PAUSED = "Người dùng tạm dừng"
    USER_RETRY = "Người dùng yêu cầu chạy lại"
