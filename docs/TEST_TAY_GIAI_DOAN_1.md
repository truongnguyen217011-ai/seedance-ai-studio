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
| Q4 | Nếu Dola bắt kéo captcha (thường ngay sau khi gửi prompt) | Cửa sổ Chrome của nick **tự hiện ra màn hình**, job vẫn Đang chạy với lý do "Dola yêu cầu kéo mảnh ghép: cửa sổ Chrome của nick 'X' đã được đưa ra màn hình, hãy kéo mảnh ghép trong 3 phút". Kéo xong trong 3 phút → cửa sổ tự ẩn, job chạy tiếp và Hoàn thành (nhật ký có dòng "đã kéo xong mảnh ghép"; nếu phải gửi lại thì có dòng nói rõ bằng chứng: "ô nhập còn nguyên prompt ... gửi lại bằng Enter" hoặc "credit ... đã giảm ... KHÔNG gửi lại"; credit của nick chỉ giảm đúng 1). Không kéo → sau 3 phút cửa sổ ẩn, job Tạm dừng, nick có nhãn "Cần kéo captcha", Chrome KHÔNG mở lại liên tục; bấm Chrome kéo xong → bấm Tiếp tục |
| Q4b | Nhìn Task Manager khi job chạy bình thường | Có chrome.exe của tool nhưng không thấy cửa sổ nào (cửa sổ đặt ngoài màn hình, không phải headless); trang Dola không đòi captcha mỗi lần gửi prompt |
| Q10 | Thêm 1 prompt (modal Thêm hàng loạt: thời lượng chỉ còn 5/10/15 giây, có ô Tỷ lệ 16:9/9:16). Bấm Prompt trên job: câu mở đầu phải là "Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay." | Video ra bình thường. Nếu Dola vẫn hỏi lại (xem nhật ký): có dòng "Dola hỏi lại: '...' → đã tự trả lời", tool gửi "15 giây, tỷ lệ 16:9. Hãy tạo video ngay, không cần hỏi thêm." rồi video vẫn ra, Hoàn thành; modal Prompt của job hiện "Dola trả lời:" với nguyên văn câu hỏi. Nếu Dola từ chối bằng chữ ("cannot", "sorry", "không thể"...) mà không tạo video → job Thất bại trong ~1 phút (văn bản khác không rõ là từ chối: ~2 phút) với lý do "Dola trả lời bằng chữ thay vì tạo video: '...'", không tự chạy lại, nick vẫn sẵn sàng; câu tool tự trả lời ("15 giây, tỷ lệ 16:9...") KHÔNG được hiện ở "Dola trả lời:" hay trong lý do thất bại |

## D: chẩn đoán
| Mã | Làm | Đạt khi |
| --- | --- | --- |
| D1 | Mở thư mục logs | Có file studio_<ngày>.log, dòng có giờ, mức, module, job, nick |
| D3 | Bấm Chẩn đoán trên 1 nick | Trong 60 giây có 5 dòng proxy / chrome / cookie FB / phiên Dola / credit, xanh đỏ xám kèm lý do |
| D4 | Bấm Tải gói chẩn đoán | Có file zip, mở ra không thấy mật khẩu thật |
| D6 | Tab Nhật ký, lọc theo số job | Chỉ còn dòng của job đó |

## Ghi chú
- **Khi một job xong (Hoàn thành hay Thất bại), gửi kèm file HTML/ảnh của trang Dola lúc đó**: gói chẩn đoán (nút "Tải gói chẩn đoán") đã chứa ảnh chụp và HTML trong `logs/screenshots/`; nếu bạn còn mở Chrome của nick, bấm Ctrl+S lưu trang Dola (HTML) hoặc chụp màn hình cuộc trò chuyện. Cấu trúc JSON chain của Dola thật (tin của người dùng/trợ lý, trường `role`/`user_type`) chỉ đối chiếu được từ các file này (BH-48); không có thì tool chỉ được test với Dola giả.
- Nếu một bước không làm được vì thiếu dữ liệu (ví dụ chưa có nick bị captcha), ghi "chưa thử".
- Mọi lỗi lạ: chụp màn hình + gói chẩn đoán là đủ, không cần mô tả dài.
