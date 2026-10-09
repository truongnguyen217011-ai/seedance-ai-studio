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
- **Python:** 3.10 trở lên
- **Google Chrome** đã được cài đặt trên máy.

### 2. Cài đặt thư viện
```bash
pip install -r requirements.txt
```

### 3. Khởi động ứng dụng
Nhấp đúp chuột vào file:
👉 **`KHOI_DONG.bat`** (hoặc `start.bat`)

Hoặc chạy lệnh thủ công:
```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```
Truy cập giao diện tại: **http://localhost:8000**

---

## 🔒 Bảo Mật
- Toàn bộ cookies và thông tin đăng nhập được lưu trữ cục bộ trong cơ sở dữ liệu SQLite và thư mục profile cá nhân của bạn, không gửi ra ngoài bất kỳ máy chủ bên thứ ba nào.
