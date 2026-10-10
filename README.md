# Seedance AI Studio (Dola 2.5 & Muse AI Automation)

Hệ thống tự động hóa tạo video và hình ảnh điện ảnh bằng trí tuệ nhân tạo, hỗ trợ đa nền tảng **ByteDance Seedance 2.5 (Dola AI)** và **Muse AI**.

---

## 🌟 Tính Năng Nổi Bật

- **Tự động hóa Dola AI (ByteDance Seedance 2.5):**
  - Tự động đăng nhập qua Facebook OAuth / Cookies / Google.
  - Tự động giải 2FA bằng TOTP thuật toán chuẩn.
  - Tự động điều phối (Auto-rotation) tài khoản khi hết lượt/credit trong ngày.
  - Tự động nhận diện và chống ghi đè/lấy lại video cũ từ cuộc trò chuyện trước.
  - Tăng cường Prompt chuẩn Hollywood điện ảnh (FPV Drone, 4K Cinematic, Blockbuster action choreography).
- **Tự động hóa Muse AI:**
  - Hỗ trợ đăng nhập tự động qua Mail Dongvanfb bốc mã OTP ngầm.
  - Quản lý số dư token và render video hàng loạt.
- **Quản lý Tài Khoản & Proxy:**
  - Nhập hàng loạt tài khoản định dạng linh hoạt: `UID|Pass|2FA|Cookie` hoặc `Email|Pass|2FA|Proxy`.
  - Hỗ trợ Proxy HTTP / SOCKS5 cách ly cho từng tài khoản.
- **Giao diện Web Hiện Đại (Studio UI):**
  - Quản lý hàng đợi render video, tạo ảnh, kho nhân vật/assets.
  - Xem trước và tải video thành phẩm trực tiếp từ trình duyệt.

---

## 🚀 Cài Đặt & Khởi Động

### 1. Yêu cầu hệ thống
- **Hệ điều hành:** Windows 10/11
- **Python:** 3.10 trở lên (khi cài nhớ tích *Add python.exe to PATH*)
- **Trình duyệt:** Google Chrome, hoặc Chromium do `CAI_TRINH_DUYET.bat` tải về
- **RAM:** 8 GB chạy được 2 Chrome cùng lúc; 32 GB nên để 6 (chỉnh trong *Cài đặt*)

### 2. Khởi động (lần đầu và mọi lần sau)
Nhấp đúp **`KHOI_DONG.bat`** (`start.bat` chỉ gọi lại file này). Script sẽ:
1. Kiểm tra Python.
2. Chạy `check_env.py`: kiểm tra thư viện (thiếu thì tự `pip install -r requirements.txt`) và tìm Chrome. Thiếu Chrome thì dừng và nhắc chạy `CAI_TRINH_DUYET.bat`.
3. Mở trình duyệt tại **http://localhost:8000** và chạy server (không dùng `--reload`, sửa file mã không làm server khởi động lại).

Giữ cửa sổ đen mở trong suốt quá trình làm việc; nhấn `Ctrl+C` để dừng.

### 3. Thiếu Chrome
Nhấp đúp **`CAI_TRINH_DUYET.bat`** một lần (tải Chromium ~150 MB qua `python -m playwright install chromium`). Có thể chỉ tay đường dẫn `chrome.exe` ở tab *Cài đặt → Đường dẫn Chrome*.

### 4. Cập nhật phiên bản mới
Nhấp đúp **`CAP_NHAT.bat`** (hoặc `CAP_NHAT.bat ten_nhanh` để lấy nhánh khác `main`). Script cần Git; nếu máy chưa có Git hoặc thư mục không phải bản clone, script in hướng dẫn tải ZIP / clone một lần. Cập nhật **không** xóa `studio.db`, `profiles/`, `outputs/`, `logs/`. Phiên bản hiện tại nằm trong file `VERSION` và hiện ở góc trên giao diện.

### 5. Chạy tay (không dùng .bat)
```bash
python check_env.py
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

## 🔒 Bảo Mật
- Toàn bộ cookies và thông tin đăng nhập được lưu trữ cục bộ trong cơ sở dữ liệu SQLite và thư mục profile cá nhân của bạn, không gửi ra ngoài bất kỳ máy chủ bên thứ ba nào.
