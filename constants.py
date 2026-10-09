"""Hằng số dùng chung cho backend và frontend (xem docs/KIEN_TRUC.md mục 3-4)."""

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
    POLICY_REFUSED = "Dola từ chối tạo video do chính sách nội dung"
    DOWNLOAD_FAILED = "Tải video về máy thất bại: {error}"
    BROWSER_ERROR = "Lỗi trình duyệt: {error}"
    MAX_ATTEMPTS = "Đã thử {n} lần vẫn lỗi, dừng tự chạy lại. Bấm Chạy lại nếu muốn thử tiếp"
    USER_PAUSED = "Người dùng tạm dừng"
    USER_RETRY = "Người dùng yêu cầu chạy lại"
