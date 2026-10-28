# Kịch bản test tay giai đoạn 2 — quản lý nick (khoảng 30 phút)

Trả lời theo mã: **đạt / không đạt / chưa thử**. Xong thì bấm "Tải gói chẩn đoán" (modal Chẩn đoán) và gửi file zip cùng kết quả.

## Chuẩn bị
1. Chạy `CAP_NHAT.bat claude/giai-doan-2-nick` rồi `KHOI_DONG.bat`.
2. Có sẵn: một file shop 10 dòng (`UID|Pass|2FA|Proxy`), một cookie Dola thô (`sessionid=...; sessionid_ss=...`), một proxy còn sống, một proxy chết (vd. `127.0.0.1:9`).

## A: thêm / quản lý nick
| Mã | Làm | Đạt khi |
| --- | --- | --- |
| A1 | Tab Tài khoản → Thêm tài khoản → "Nhiều nick" → dán 10 dòng shop → bấm **Lưu** | Modal "Kết quả nhập tài khoản" hiện 10 dòng "Đã thêm" kèm số nick mới (#id), cột 2FA ✓, cột Proxy đúng từng dòng; bảng nick có thêm 10 nick |
| A2 | Dán lại đúng 10 dòng đó → Lưu | 10 dòng nhãn "Đã có" với lý do "Nick đã có: trùng UID ... với nick #…"; tổng số nick không tăng |
| A3 | Trong "Nhiều nick" dán lẫn 6 kiểu: `UID\|Pass\|2FA`, `UID\|Pass\|2FA\|Proxy`, `UID\|Pass\|Cookie`, `UID\|Pass\|2FA\|Cookie\|Proxy`, một dòng copy từ Excel (tab), một cookie Dola thô, cộng một dòng chỉ có UID và một dòng 2FA sai (`ABCD2345EFGH6789`) → bấm **Xem trước** | Bảng xác nhận hiện từng dòng: UID, Pass ✓, 2FA ✓, Cookie nhãn **Dola**/**Facebook**, Proxy; dòng chỉ UID → "Thiếu mật khẩu"; dòng 2FA sai → "Mã 2FA ... sai định dạng"; cookie Dola thô → UID `Dola_...`. Nút đổi thành "Lưu N nick"; bấm Lưu → đúng N nick được thêm, nick từ cookie Dola thô hiện "Đã kết nối Dola" ngay |
| A4 | Gán proxy sống cho 1 nick → Chẩn đoán nick đó; rồi thêm 1 prompt để job chạy trên nick đó | Bước "Proxy" hiện "IP ra ngoài: x.x.x.x" (IP của proxy, không phải IP máy), cột Proxy trong bảng hiện "IP: x.x.x.x"; job chạy xong bình thường; trên trang quản lý proxy (nếu có) thấy lưu lượng tăng trong lúc job chạy |
| A5 | Đổi proxy của 1 nick sang `127.0.0.1:9` (proxy chết) → thêm 1 prompt | Trong ~1 phút nick có nhãn đỏ "Proxy lỗi" + lỗi "Proxy '...' không phản hồi (ERR_PROXY_CONNECTION_FAILED) khi chạy job" (mật khẩu proxy bị che `***`); job về **Chờ** với lý do "Proxy của nick '...' không phản hồi..." hoặc "Chưa có nick phù hợp: 1 nick proxy lỗi"; nếu còn nick khác thì job chạy bằng nick khác. Nhật ký **không** có dòng "thử kết nối trực tiếp". Gán proxy mới (nút Gán proxy) → nhãn "Proxy lỗi" biến mất |
| A6 | Thêm 1 prompt gán sẵn nick X (hoặc để job Tạm dừng trên nick X) → Xóa nick X | Nick biến mất, thư mục `profiles/acc_<id>` không còn; job đó về Chờ với lý do "Nick 'X' đã bị xóa, job chờ nick khác". Xóa nick đang chạy job → toast "đang bận với job #…, không xóa được", nick vẫn còn |
| A7 | Nhập đủ 200 nick (có thể dán file lớn) | Bảng tải trong < 1 giây, phân trang 50/trang ("Trang 1/4 · hiện 1–50 trong 200 nick", nút Trước/Sau), ô "Tìm tên / UID / email" lọc đúng, select trạng thái (Sẵn sàng / Cần can thiệp / Đang nghỉ / Đang bận / Chưa kết nối Dola / Chưa có proxy) lọc đúng, nhãn "Tổng: N nick" đổi theo bộ lọc; giao diện không giật mỗi 3 giây |

## K: kết nối Dola
| Mã | Làm | Đạt khi |
| --- | --- | --- |
| K1 | Nick có UID/Pass/2FA → bấm ⚡ Auto Login → tab Nhật ký lọc theo nick | Có đủ các dòng: "Mở trang Dola", "Bấm nút 'Tiếp tục với Facebook'", "Tự động điền UID", "Tự sinh mã 2FA TOTP lần n", "Bấm nút xác nhận cấp quyền", "Đăng nhập Dola thành công"; cột Credit/Trạng thái có "Kiểm tra lúc <giờ vừa rồi>" (last_check) kể cả khi thất bại |
| K2 | Nick sai mật khẩu (hoặc nick bị checkpoint) → Auto Login | Nick nhãn "Cần đăng nhập lại" + lỗi "Sai mật khẩu Facebook [ảnh: ...]" (hoặc "Facebook checkpoint (xác minh danh tính) [ảnh: ...]"), ảnh mở được từ `logs/screenshots`; thêm prompt → job Chờ với "Chưa có nick phù hợp: 1 nick cần đăng nhập lại" (nick không được chọn) |
| K3 | Dán cookie Dola thô vào **ô Cookie của form thêm 1 nick** (loại Facebook); rồi dán cookie Facebook (`c_user=...; xs=...`) vào modal **Dán Cookie** của một nick khác | Nick 1 hiện "Đã kết nối Dola" ngay sau khi thêm; nick 2 báo "Đã nạp N cookie Facebook. Chưa thấy sessionid Dola..." và vẫn "Chưa kết nối Dola" (không gắn sai domain) |
| K4 | Chạy 1 job trên nick biết trước số credit | Sau khi job xong, cột Credit giảm đúng 1 (đọc từ trang hoặc từ câu "will use 1 video credits ... only have N left today" của Dola); không đọc được thì hiện "Chưa rõ", không bịa số |
| K5 | Nick còn 1 credit → thêm 2 prompt, có nick khác còn credit | Job 1 xong; nick 1 chuyển "Nghỉ (hết lượt)" đến 00:05; job 2 chuyển sang nick khác trong vòng ~10 giây |
| K6 | Để qua 00:05 (hoặc sửa tay `rest_until` trong CSDL về quá khứ) | Trong 1 vòng quét (2 giây) nick hết nhãn "Nghỉ", được chọn lại cho job |
| K7 | Đang có job chạy, trên Dola thật đăng xuất nick (hoặc xóa cookie sessionid trong `profiles/acc_<id>/storage_state.json` rồi chạy job) | Job về Chờ "Nick '...' mất phiên Dola, cần đăng nhập lại; job chờ nick khác [ảnh]"; nick nhãn "Cần đăng nhập lại"; nhật ký có "mất phiên Dola → tự đăng nhập lại một lần bằng mật khẩu Facebook" rồi "tự đăng nhập lại thành công" (cờ mất, job tự chạy lại) hoặc "...thất bại ..., không thử tiếp" (cờ còn, Chrome KHÔNG mở đi mở lại) |
| K8 | Bấm **Chrome** của nick → trong cửa sổ mở thêm 1 tab, đóng tab đầu tiên (giữ tab 2) → đăng nhập Dola ở tab 2 → đóng cả cửa sổ | Nhật ký chỉ ghi "đã lưu phiên ... sau khi đóng Chrome" **sau khi đóng cả cửa sổ**, không ghi lúc đóng tab đầu; nick "Đã kết nối Dola" |
| K9 | Cài đặt Số Chrome = 2 → bấm **Quét tất cả** với ≥ 8 nick | Thanh tiến độ "Đang quét tất cả nick… (đang kiểm nick #a, #b)" tăng dần, Task Manager không quá 2 chrome.exe của tool; xong hiện "Quét xong N nick lúc ..." + tổng kết Sẵn sàng / Hết credit / Cần đăng nhập / Proxy chết / Cần kéo captcha / Lỗi khác / Chưa rõ; mỗi nick có Credit và "Kiểm tra lúc" mới; bấm Quét tất cả lần nữa khi đang quét → toast "Đang quét dở x/N nick" |

## Ghi chú
- A4/A5 cần proxy thật; nếu không có, ghi "chưa thử" và chỉ làm phần proxy chết (`127.0.0.1:9`).
- K2 cần một nick sai mật khẩu thật; không có thì ghi "chưa thử".
- Mọi lỗi lạ: chụp màn hình + gói chẩn đoán là đủ.
