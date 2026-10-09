# HƯỚNG DẪN SỬ DỤNG HỆ THỐNG SEEDANCE AI STUDIO (DOLA 2.5)

Thư mục cài đặt: `C:\AI SEEDANE`  
Giao diện quản lý: `http://localhost:8000`

---

## 1. Hướng Dẫn Khởi Động 1-Click
Để chạy hệ thống, bạn chỉ cần thực hiện 1 trong 2 cách:
* **Cách 1 (Nhanh nhất):** Nhấp đúp chuột vào file **`KHOI_DONG.bat`** (hoặc `start.bat`) trong thư mục `C:\AI SEEDANE`. Trình duyệt web sẽ tự động mở trang Studio tại `http://localhost:8000`.
* **Cách 2 (Bằng Terminal/Command Prompt):**
  ```bash
  cd "C:\AI SEEDANE"
  python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
  ```

---

## 2. Quản Lý Tài Khoản (Muse AI & Dola AI)
Hệ thống hỗ trợ quản lý không giới hạn tài khoản Muse AI (Mail Dongvanfb 1 tỷ token) và Facebook/Dola.

### Đối với tài khoản MUSE AI:
1. **Thêm tài khoản:**
   * Bấm **`[Thêm Tài Khoản]`** -> Chọn tab **`[Muse AI (Mail)]`**.
   * Nhập Email (từ mail Dongvanfb) và Proxy (khuyên dùng Proxy US/Canada).
2. **Tự động đăng nhập 1-Click (Auto Login Muse):**
   * Bấm nút **`[⚡ Auto Login]`** trên dòng tài khoản Muse.
   * Hệ thống tự động mở trình duyệt ngầm -> Điền email -> Yêu cầu gửi mã OTP -> Tự động cào hòm thư `http://dongvanfb.net/read_mail_box/` -> Lấy mã xác nhận 6 số và điền vào Muse AI -> Lưu phiên vĩnh viễn!
3. **Kiểm tra Token:**
   * Bấm nút **`[Check Token]`** để xem số dư (ví dụ: `1,000,000,000 tokens`).

---

## 2.1. Nạp 180 Clip Đối Thoại Từ TOOL AI (B3 Pipeline)
* Khi bạn sản xuất xong kịch bản bài đối thoại 30 phút trong `TOOL_AI` (đã xuất ra file `_ALL_CLIP_PROMPTS.txt` và thư mục `images/` chứa ảnh nhân vật):
1. Tại Tab **Tạo Video**, bấm nút màu tím **`[⚡ Nạp 180 Clip B3 (TOOL AI)]`**.
2. Dán đường dẫn đến file `_ALL_CLIP_PROMPTS.txt` (Ví dụ: `D:\TOOL_AI\Ten_Bai\_ALL_CLIP_PROMPTS.txt`).
3. Hệ thống sẽ tự động:
   * Tách đủ 180 clip kèm prompt cảnh và gắn đúng ảnh nhân vật tương ứng.
   * **Tự động chia đều 180 clip cho toàn bộ tài khoản Muse AI đang sẵn sàng** theo cụm phân đoạn (Scene Batch).
   * Kích hoạt các luồng render song song qua từng proxy riêng biệt.
   * Thu hoạch 180 video clip MP4 về thư mục `outputs/BATCH_.../clip_001.mp4` đến `clip_180.mp4`!

---

## 3. Tạo Video Seedance 2.5 & Nhận Diện 11 Trường Phái Thị Giác
Hệ thống tích hợp bộ phân tích thông minh chuẩn Notebook ChatGPT & Bructa:
* **F1 (Alan Lee):** Cổ tích rêu phong 3 lớp cảnh, chiều sâu đại ngàn.
* **F2 (Frank Frazetta):** Chiến binh cơ bắp, độ tương phản ánh sáng gắt.
* **C1 (Alena Aenami):** Không gian cô độc, tương phản ấm - lạnh, bầu trời hoàng hôn tím.
* **C2 (Syd Mead):** Siêu đô thị Sci-Fi cơ khí, mô-đun công nghiệp.
* **E1 (Ilya Repin):** Hiện thực sử thi, kịch tính biểu cảm con người.
* **W1 (Frederic Remington):** Viễn Tây bụi bặm, chuyển động động lực học.
* **G1 (Moebius & Kilian Eng):** Nghệ thuật đồ họa nét sắc & mảng màu phẳng.
* **P1 (Steve McCurry):** Chân dung điện ảnh ánh sáng Rembrandt, lens 85mm.
* **D1 (H.R. Giger):** Sinh cơ học Biomechanical Gothic đen huyền bí.
* **S1 (Johannes Vermeer):** Ánh sáng cửa sổ bên, tĩnh vật cổ điển.
* **A1 (J.M.W. Turner):** Bão táp thiên nhiên, ánh sáng hòa tan khí quyển.

---

## 4. Hàng Đợi & Tự Động Xoay Tài Khoản
* Hỗ trợ tạo đơn lẻ hoặc tạo hàng loạt hàng chục video cùng lúc.
* Tự động gán tài khoản rảnh và xoay vòng IP proxy.
* Nếu 1 tài khoản hết token hoặc bị rate limit, hệ thống tự động xoay sang nick khác để tiếp tục render.
* Thời gian render chuẩn cho video Seedance 2.5 (30s) là **3 - 5 phút**.

---

## 5. Xem Trực Tiếp & Tải Video MP4
* Bấm **`[Xem Video Siêu Mượt]`** để mở trình phát video chất lượng cao tích hợp.
* Bấm **`[Tải MP4]`** (ngay trên hàng đợi hoặc trong trình phát) để lưu video về máy tính.

---

## 6. Cấu Trúc Thư Mục Hệ Thống
```
C:\AI SEEDANE\
├── app.py                  # Máy chủ FastAPI Backend & API REST
├── database.py             # Hệ quản trị CSDL SQLite (studio.db)
├── dola_service.py         # Module điều khiển Playwright & Google Chrome
├── worker.py               # Tiến trình quét hàng đợi đa luồng
├── studio.db               # Database lưu tài khoản, job, media
├── KHOI_DONG.bat           # File khởi chạy 1-click
├── start.bat               # File khởi chạy phụ
├── requirements.txt        # Danh sách thư viện Python
├── HUONG_DAN_SU_DUNG.md    # Tài liệu hướng dẫn sử dụng chi tiết
├── static/                 # Giao diện Dark Cyberpunk (HTML/CSS/JS)
│   ├── index.html
│   └── js/app.js
├── outputs/                # Thư mục lưu video thành phẩm xuất ra
└── profiles/               # Thư mục lưu profile Chrome biệt lập của từng nick
```
