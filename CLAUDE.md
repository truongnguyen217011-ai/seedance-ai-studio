# Hướng dẫn bắt buộc cho mọi phiên Claude và mọi agent làm việc trong repo này

1. Đọc `docs/BAI_HOC.md` (sổ bài học) TRƯỚC khi sửa bất kỳ file nào. Không được tái phạm lỗi đã ghi trong đó.
2. Đọc `docs/KIEN_TRUC.md` và tuân thủ mục 1 (quy tắc bất biến).
3. Sau khi sửa xong một lỗi hoặc phát hiện một lỗi mới, THÊM một mục vào cuối `docs/BAI_HOC.md` theo mẫu trong file, trong cùng commit với bản sửa.
4. Trước khi đẩy mã: `python -m pytest tests -q` phải xanh; chạy các lệnh grep ghi ở cột "Kiểm" trong sổ bài học.
5. Thước đo đúng/sai là hợp đồng kiểm nghiệm (các mã C, Q, D, A, K, T, P, G). Không báo "đã sửa" khi chưa tự chạy qua.
6. Chữ hiển thị cho người dùng: tiếng Việt có dấu, nói rõ việc gì, nick nào, vì sao.
