# Kịch bản test tay giai đoạn 1 (khoảng 15 phút)

Trả lời theo mã: **đạt / không đạt / chưa thử**. Xong thì bấm "Tải gói chẩn đoán" ở tab Tài khoản và gửi file zip cùng kết quả.

## Chuẩn bị
1. Tắt tool nếu đang chạy. Chạy `CAP_NHAT.bat claude/giai-doan-1-hang-doi` (lần đầu chưa có `.git` thì làm theo hướng dẫn file in ra).
2. Chạy `KHOI_DONG.bat`. Góc trên giao diện phải hiện **v1.1.0**.

## C: cài đặt
| Mã | Làm | Đạt khi |
| --- | --- | --- |
| C2 | Nhấp đúp KHOI_DONG.bat | Trong 10 giây trình duyệt mở Studio, cửa sổ đen vẫn mở, không báo lỗi |
| C3 | Nhìn góc trên giao diện | "Chrome: OK". Nếu "Thiếu" → chạy CAI_TRINH_DUYET.bat rồi mở lại, phải thành OK |
| C5 | Tab Nhật ký ngay sau khởi động | Có dòng ghi phiên bản, đường dẫn Chrome, số nick |
| C6 | Ctrl+C tắt, mở lại | Task Manager không còn chrome.exe của tool trước khi mở lại |

## Q: hàng đợi (cần ít nhất 2 nick đã kết nối Dola)
| Mã | Làm | Đạt khi |
| --- | --- | --- |
| Q1 | Cài đặt: Số Chrome = 2. Thêm 4 prompt | Task Manager không bao giờ quá 2 Chrome của tool |
| Q3 | Như trên với 2 nick | Mỗi nick cùng lúc chỉ chạy 1 job (cột Tài khoản trong bảng) |
| Q5 | Đang có job Đang chạy → Ctrl+C → mở lại | Job đó về Chờ với lý do "App khởi động lại" rồi tự chạy lại |
| Q6 | Chờ 1 job thất bại (hoặc đặt proxy sai cho nick) | Hiện đỏ "Thất bại" + lý do + link "Xem ảnh lỗi" mở được + nút Chạy lại |
| Q7 | Xóa/cho nghỉ hết nick rồi thêm 1 prompt | Job Chờ, lý do dạng "Chưa có nick phù hợp: ...", không mở Chrome |
| Q4 | Nếu Dola bắt kéo captcha | Job Tạm dừng, nick có nhãn "Cần kéo captcha", Chrome KHÔNG mở lại liên tục; bấm Chrome kéo xong → bấm Tiếp tục |

## D: chẩn đoán
| Mã | Làm | Đạt khi |
| --- | --- | --- |
| D1 | Mở thư mục logs | Có file studio_<ngày>.log, dòng có giờ, mức, module, job, nick |
| D3 | Bấm Chẩn đoán trên 1 nick | Trong 60 giây có 5 dòng proxy / chrome / cookie FB / phiên Dola / credit, xanh đỏ xám kèm lý do |
| D4 | Bấm Tải gói chẩn đoán | Có file zip, mở ra không thấy mật khẩu thật |
| D6 | Tab Nhật ký, lọc theo số job | Chỉ còn dòng của job đó |

## Ghi chú
- Nếu một bước không làm được vì thiếu dữ liệu (ví dụ chưa có nick bị captcha), ghi "chưa thử".
- Mọi lỗi lạ: chụp màn hình + gói chẩn đoán là đủ, không cần mô tả dài.
