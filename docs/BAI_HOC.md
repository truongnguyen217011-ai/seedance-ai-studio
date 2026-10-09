# Sổ bài học (Lessons Learned)

**Luật:** Trước khi sửa bất kỳ dòng mã nào, đọc hết file này. Sau khi sửa xong một lỗi, thêm một mục mới ở cuối theo đúng mẫu. Một lỗi đã có trong sổ mà tái phạm được coi là lỗi nặng nhất.

Mẫu một mục:

```
## BH-xx · <tên ngắn của lỗi>
- Ngày: YYYY-MM-DD · Giai đoạn: N · Mã hợp đồng liên quan: Q1, D2...
- Triệu chứng: người dùng thấy gì
- Nguyên nhân gốc: vì sao mã sai (không phải "quên", mà là giả định sai nào)
- Quy tắc rút ra: câu lệnh ngắn, có thể kiểm bằng mắt hoặc bằng grep/test
- Cách kiểm để không tái phạm: test nào, lệnh grep nào
```

---

## BH-01 · Thiếu thư viện trong requirements
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C1
- Triệu chứng: cài theo README xong app không khởi động, báo thiếu psutil.
- Nguyên nhân gốc: thêm `import` mới nhưng không cập nhật requirements.txt; không có bước kiểm tra "máy sạch".
- Quy tắc: mỗi `import` thư viện ngoài chuẩn phải có dòng tương ứng trong requirements.txt trong cùng một commit.
- Kiểm: `check_env.py` chạy lúc khởi động; `tests/test_bai_hoc.py::test_bh01_external_imports_listed_in_requirements` so sánh import với requirements.

## BH-02 · Đếm job đang chạy bằng chuỗi trạng thái trong CSDL
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q1
- Triệu chứng: nạp nhiều job thì Chrome mở không giới hạn, máy treo.
- Nguyên nhân gốc: worker đếm `status = 'Đang chạy'` nhưng một nhánh mã khác đổi sang `'Đang xử lý'`; chuỗi trạng thái viết tay ở nhiều nơi nên lệch nhau.
- Quy tắc: giới hạn tài nguyên (Chrome) phải đếm bằng semaphore trong bộ nhớ (`browser.BrowserSlots`), không bằng chuỗi trong CSDL. Chuỗi trạng thái chỉ lấy từ `constants.JobStatus`.
- Kiểm: `grep -rn "'Đang " *.py` không được có chuỗi trạng thái tay; test Q1.

## BH-03 · Không có khóa "nick đang bận"
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q2, Q3
- Triệu chứng: nhiều job dồn vào cùng một nick; job sau giết Chrome của job trước; job thất bại vô cớ.
- Nguyên nhân gốc: hàm chọn nick xếp theo `last_used`, mà `last_used` chỉ cập nhật khi job xong, nên 5 job lấy cùng lúc chọn cùng một nick. Thêm vào đó mỗi job gọi `kill_orphan_chrome` trên profile dùng chung.
- Quy tắc: mọi thao tác cần profile nick phải `AccountPool.acquire` trước; không bao giờ giết tiến trình Chrome trong luồng job.
- Kiểm: test Q2/Q3; `grep -n kill_orphan_chrome` chỉ được xuất hiện trong reset lúc khởi động và diagnostics.

## BH-04 · Đặt job về "Chờ" khi gặp lỗi cần người can thiệp
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q4
- Triệu chứng: gặp captcha, Chrome mở đi mở lại mỗi vài giây.
- Nguyên nhân gốc: "Chờ" nghĩa là worker sẽ nhặt lại ngay; lỗi cần tay người phải là trạng thái riêng (Tạm dừng) kèm cờ trên nick.
- Quy tắc: lỗi cần người → `Tạm dừng` + `needs_manual`; lỗi tạm thời → `Thất bại` + `attempts`, tối đa 2 lần tự chạy lại.
- Kiểm: test Q4 đếm số lần mở trang sau khi tạm dừng.

## BH-05 · Không reset job mồ côi khi khởi động
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q5
- Triệu chứng: sau khi tắt/mở lại app, hàng đợi đứng im vì job "Đang chạy" ma chiếm chỗ.
- Nguyên nhân gốc: trạng thái "Đang chạy" sống trong CSDL nhưng tiến trình chạy nó đã chết.
- Quy tắc: mọi trạng thái "đang làm" phải được reset lúc khởi động (`reset_orphans_on_startup`).
- Kiểm: test Q5.

## BH-06 · Dùng --reload cho bản chạy thật
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C4
- Triệu chứng: sửa một file là server khởi động lại, job đang render chết.
- Nguyên nhân gốc: cờ dành cho lập trình viên bị để trong file khởi động của người dùng.
- Quy tắc: file .bat người dùng không bao giờ có `--reload`.
- Kiểm: `grep -- --reload *.bat` phải rỗng.

## BH-07 · SQLite mở không timeout, không WAL
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q8
- Triệu chứng: nhiều luồng ghi cùng lúc → "database is locked", lỗi bị nuốt, tiến độ đứng.
- Nguyên nhân gốc: `sqlite3.connect` mặc định timeout 5s và journal rollback.
- Quy tắc: chỉ mở CSDL qua `database.get_connection()` (timeout 30s, WAL, busy_timeout).
- Kiểm: `grep -rn "sqlite3.connect" *.py` chỉ được có trong database.py; test Q8 quét log.

## BH-08 · Nuốt lỗi bằng except: pass
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: D5
- Triệu chứng: "cứ bị kẹt mà không biết lỗi gì".
- Nguyên nhân gốc: hơn 40 chỗ `except Exception: pass`; lỗi thật biến mất.
- Quy tắc: mọi `except` phải ghi log có nội dung; lỗi làm job thất bại phải kèm ảnh chụp.
- Kiểm: `grep -Pzo "except Exception:\s*\n\s*pass" *.py` phải rỗng.

## BH-09 · Ghi giá trị mặc định thay cho giá trị không đọc được
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: K4
- Triệu chứng: nick hiện "4 credits" xanh dù chưa đọc được gì; Muse hiện "1 tỷ token" dù chưa đăng nhập.
- Nguyên nhân gốc: coi "không đọc được" là "có vẻ ổn".
- Quy tắc: không đọc được thì ghi NULL + `last_error`, giao diện hiện "Chưa rõ". Không bao giờ bịa số.
- Kiểm: `grep -n "else 4\|1000000000" *.py` phải rỗng.

## BH-10 · Hai cơ chế cùng mở Chrome trên một profile
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: K8
- Triệu chứng: bấm "Chrome" thì hai cửa sổ tranh nhau, cửa sổ sau giết cửa sổ trước.
- Nguyên nhân gốc: vừa ghi và chạy file .bat mở chrome.exe, vừa mở Playwright trên cùng profile.
- Quy tắc: mọi Chrome đều qua `browser.browser_session`; không sinh file .bat động.
- Kiểm: `grep -rn "startfile\|chrome.exe" *.py` chỉ được có trong browser.find_chrome.

## BH-11 · Gắn sai domain cho cookie dán vào
- Ngày: 2026-10-09 · Giai đoạn: 2 · Mã: K3
- Triệu chứng: dán cookie Dola ở form thêm nick thì báo "Chưa kết nối Dola".
- Nguyên nhân gốc: form gắn domain `.facebook.com` theo loại nick, không nhìn nội dung cookie.
- Quy tắc: nhận diện domain từ nội dung cookie (`sessionid` → Dola, `c_user` → Facebook), không từ loại nick.
- Trạng thái: chưa áp dụng, làm ở giai đoạn 2 (K3).
- Kiểm: test parser cookie; K3.

## BH-12 · Tính năng giả trả dữ liệu mẫu như thật
- Ngày: 2026-10-09 · Giai đoạn: 5 · Mã: G2
- Triệu chứng: "tạo ảnh" ra ảnh Unsplash, "giọng đọc" ra nhạc mẫu, "đổi IP" chỉ alert; log mẫu "5/5 proxy tốt".
- Nguyên nhân gốc: mã khung để demo bị để lại trong bản chạy thật.
- Quy tắc: không có nút nào trên giao diện trả dữ liệu giả; chưa làm thì không hiện.
- Kiểm: `grep -rn "unsplash\|soundhelix" .` phải rỗng sau giai đoạn 5.

## BH-13 · Đường dẫn file video không nhất quán giữa các luồng
- Ngày: 2026-10-09 · Giai đoạn: 3 · Mã: T6
- Triệu chứng: nút Xem/Tải trả 404 với video nằm trong thư mục con.
- Nguyên nhân gốc: một luồng lưu đường dẫn web `/outputs/x.mp4`, luồng khác lưu đường dẫn tuyệt đối; endpoint chỉ nhìn thư mục gốc.
- Quy tắc: `local_video_path` luôn là đường dẫn tương đối so với `OUTPUTS_DIR`; endpoint stream/download dựng từ đó.
- Kiểm: test T6.

## BH-14 · Giao diện chỉ biết một phần trạng thái backend
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q6
- Triệu chứng: job thất bại hiện "Đang chạy" nhấp nháy mãi.
- Nguyên nhân gốc: frontend viết tay 4 chuỗi, backend có 7 chuỗi.
- Quy tắc: frontend hiển thị theo đúng 5 trạng thái của `constants.JobStatus`; trạng thái lạ hiện nguyên chữ, không đoán.
- Kiểm: chưa có test tự động, kiểm tay bằng Playwright với dữ liệu giả (đủ 5 trạng thái + 1 trạng thái lạ).

## BH-15 · Giao diện bịa số khi API không trả giá trị
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: K4, G2
- Triệu chứng: nick hiện "4 credits" xanh dù chưa check; alert kết nối Dola hiện "10 cookies" khi API không trả `cookies_count`; proxy nào cũng hiện "IP mới - lượt 1/1".
- Nguyên nhân gốc: trong template JS dùng `x || 4`, `x || 10` hoặc chuỗi cứng để "cho đẹp"; `||` biến `null`/`0` thành số mặc định.
- Quy tắc: trong app.js, giá trị lấy từ API chỉ hiện khi `!== null && !== undefined`; không có thì hiện "Chưa rõ" màu xám. Không dùng `|| <số>` cho dữ liệu nghiệp vụ.
- Kiểm: `grep -nE "\|\| ?[0-9]+\b" static/js/app.js` chỉ được ra các giá trị đếm (total_images || 0); test UI dữ liệu giả có `credits: null`.

## BH-16 · Frontend tự suy diễn trạng thái mặc định là "Đang chạy"
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q6
- Triệu chứng: job trạng thái lạ (CSDL cũ "Chờ render", "Đang xử lý") đều hiện badge "Đang chạy" nhấp nháy.
- Nguyên nhân gốc: `fetchJobs` khởi tạo badge mặc định là "Đang chạy" rồi chỉ ghi đè cho 3 trạng thái biết; nhánh `default` đồng nghĩa "đang chạy".
- Quy tắc: badge trạng thái viết bằng `switch` trên `JOB_STATUS` (bản sao của `constants.JobStatus`), nhánh `default` in nguyên chữ màu xám; thanh tiến độ chỉ hiện khi đúng `JOB_STATUS.DANG_CHAY`.
- Kiểm: `grep -n "'Đang chờ'\|'Đang xử lý'\|=== 'Lỗi'" static/js/app.js` phải rỗng; test UI với 5 trạng thái + 1 trạng thái lạ.

## BH-17 · Lỗi mạng chỉ ghi console.error, người dùng không biết
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: D5 (phía giao diện)
- Triệu chứng: server chết hoặc API trả 500 nhưng giao diện đứng im với dữ liệu cũ; người dùng tưởng "đang chạy".
- Nguyên nhân gốc: mọi `fetch` chỉ `console.error` trong `catch`, không có kênh báo lỗi trên màn hình; `res.json()` trên HTTP 500 cũng không được coi là lỗi.
- Quy tắc: gọi API qua `apiJson()` (ném lỗi khi `!res.ok`), bắt lỗi bằng `reportFetchError()` → toast góc màn hình (chống spam 15 giây/lỗi). Header hiện "Mất kết nối máy chủ" khi `/api/health` không trả lời.
- Kiểm: `grep -n "console.error" static/js/app.js` chỉ còn trong `reportFetchError` và lỗi trình phát video; tắt server rồi mở UI phải thấy toast đỏ.

## BH-18 · .gitignore quét nhầm file mã thật
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C1
- Triệu chứng: `check_env.py` tạo xong nhưng `git status` không thấy, bản cập nhật của người dùng thiếu file này nên KHOI_DONG.bat báo lỗi. Tương tự, mẫu `test_*.py` (dành cho script thử tay) từng ignore **cả thư mục `tests/`**: toàn bộ test tích hợp không vào repo, máy khác chạy `pytest` thấy "0 tests".
- Nguyên nhân gốc: `.gitignore` có mẫu `check_*.py`, `test_*.py` (dành cho script tạm của tác giả) khớp luôn file mã/test chính thức. Mẫu không có `/` đầu nên khớp ở mọi thư mục con.
- Quy tắc: tên file mã/test chính thức không được khớp mẫu tạm trong `.gitignore`; script tạm để trong `scratch/` (đã ignore cả thư mục) thay vì dùng mẫu theo tên; nếu buộc phải trùng, thêm dòng `!tên_file` ngay dưới và ghi chú. Đã gỡ cả `check_*.py` lẫn `test_*.py` khỏi `.gitignore`.
- Kiểm: `git check-ignore -v check_env.py tests/test_bai_hoc.py` phải không ra gì; `git ls-files tests | wc -l` > 0 sau khi commit.

## BH-19 · Giao diện chết hẳn khi CDN (Tailwind, lucide) không tải được
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C4
- Triệu chứng: máy không có mạng (hoặc mạng chặn unpkg.com/cdn.tailwindcss.com) thì trang trắng, không bảng, không nút; app.js dừng ngay tại `lucide.createIcons()` trong `DOMContentLoaded` nên không gọi API nào.
- Nguyên nhân gốc: index.html lấy Tailwind và lucide từ CDN, app.js coi `lucide` là luôn tồn tại; không có bản dự phòng cục bộ.
- Quy tắc: app.js phải chạy được khi thư viện ngoài vắng mặt (đã thêm guard `window.lucide = { createIcons() {} }`). Về lâu dài, chép Tailwind build và lucide vào `static/vendor/` để tool chạy offline (chưa làm được trong môi trường này vì CDN bị chặn).
- Kiểm: chưa có test tự động, kiểm tay bằng Playwright với dữ liệu giả (chặn `**/unpkg.com/**`, `**/cdn.tailwindcss.com/**` vẫn phải render đủ bảng job); `grep -n "cdn\." static/index.html` nhắc việc còn phải vendor.

## BH-20 · Migration ALTER TABLE chạy trước CREATE TABLE
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: D2
- Triệu chứng: CSDL mới tạo thiếu cột `batch_id`, `clip_index` của bảng jobs; chỉ sau lần khởi động thứ hai mới có.
- Nguyên nhân gốc: `init_db()` cũ gọi `ALTER TABLE jobs ADD COLUMN` trước `CREATE TABLE jobs`; lỗi "no such table" bị `except: pass` nuốt nên không ai thấy.
- Quy tắc: trong `init_db()` tạo đủ bảng trước, rồi mới chạy migration cột bằng `_add_column_if_missing` (kiểm `PRAGMA table_info`), không dùng try/except để dò cột.
- Kiểm: `tests/test_database.py` tạo CSDL trống, gọi `init_db()` một lần và so cột; `grep -n "except Exception" database.py` phải rỗng.

## BH-21 · So khớp domain cookie bằng chuỗi cứng "dola"
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: T5, Q6
- Triệu chứng: chạy với fake Dola (`SEEDANCE_DOLA_URL=http://127.0.0.1:PORT`) mọi nick đều "chưa đăng nhập Dola" dù cookie sessionid có sẵn; đổi URL Dola thật cũng không đổi được.
- Nguyên nhân gốc: `has_dola_session` kiểm `"dola" in cookie["domain"]` và URL `https://www.dola.com/chat/` viết cứng ở nhiều chỗ, nên cấu hình `config.DOLA_BASE_URL` không có tác dụng.
- Quy tắc: domain cookie so với `config.DOLA_DOMAIN` qua `_cookie_domain_matches` (chấp nhận `.dola.com`, `www.dola.com`, IP); URL chỉ lấy từ `config.DOLA_CHAT_URL`.
- Kiểm: `grep -n "dola.com" dola_service.py app.py worker.py` chỉ được ra trong chú thích/regex; test T5 với fake Dola trên 127.0.0.1.

## BH-22 · Tạo asyncio task từ trong thread
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q1
- Triệu chứng: worker báo "no running event loop" ngay vòng quét đầu tiên, không job nào chạy.
- Nguyên nhân gốc: vòng quét CSDL được đẩy sang `asyncio.to_thread` (để không chặn event loop khi SQLite bận), nhưng bên trong vẫn gọi `asyncio.create_task`, hàm này chỉ hợp lệ trên luồng chạy event loop.
- Quy tắc: hàm chạy trong `to_thread` chỉ trả về dữ liệu (danh sách job cần chạy); việc `create_task` làm ở coroutine `worker_loop` sau khi `await`.
- Kiểm: `grep -n "create_task" worker.py` chỉ được xuất hiện trong coroutine `worker_loop`/`start_worker`; test Q1 khởi chạy worker thật.

## BH-23 · Hai agent đánh trùng số bài học
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: (quy trình)
- Triệu chứng: hai agent sửa song song cùng thêm "BH-22" với nội dung khác nhau; sổ có hai mục cùng số, lệnh "xem BH-22" không biết trỏ vào đâu, `tests/test_bai_hoc.py` không biết mục nào là thật.
- Nguyên nhân gốc: số bài học được chọn bằng cách "nhớ số cuối lúc bắt đầu đọc", không kiểm lại ngay trước khi ghi; mỗi agent đều thấy số cuối là 21.
- Quy tắc: **số BH mới = số lớn nhất hiện có trong `docs/BAI_HOC.md` + 1**, đọc lại file ngay trước khi ghi (không dùng số nhớ từ đầu phiên). Agent thứ hai gặp trùng thì đổi số của mình, không đổi số của người khác. Số phải liên tục 1..N, tăng dần theo thứ tự trong file.
- Kiểm: `tests/test_bai_hoc.py::test_bh23_lesson_numbers_unique_and_consecutive` (đếm trùng và kiểm liên tục); tay: `grep -o "^## BH-[0-9]*" docs/BAI_HOC.md | sort | uniq -d` phải rỗng.

## BH-24 · Nick bị rate_limited ngay lỗi kết nối đầu tiên nên "tự chạy lại" không bao giờ chạy
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q4, Q7
- Triệu chứng: Dola sập hoặc mạng chập chờn một lần, nick duy nhất chuyển `rate_limited`; job về Chờ với chữ "tự chạy lại lần 1/2" nhưng nằm im 30 phút ("1 nick bị giới hạn tạm thời"), không có lần thử thứ 2. Trước đó nữa, lỗi kỹ thuật bị đặt thẳng `Thất bại` nên "tối đa 2 lần tự chạy lại" (BH-04) chỉ là lời hứa trong tài liệu.
- Nguyên nhân gốc: `_apply_technical_failure` coi "Chrome đã mở" (`launched`) là "lỗi do nick" và cho nick nghỉ ngay; nhưng `goto` thất bại là lỗi kết nối tới Dola, không nói gì về nick. Đồng thời job luôn bị đặt `Thất bại` (worker chỉ nhặt `Chờ`), nên `attempts` không bao giờ vượt 1.
- Quy tắc: lỗi kỹ thuật đi qua `_fail_technical`: `attempts <= MAX_AUTO_RETRIES` → `Chờ` + "tự chạy lại lần n/N", ngược lại `Thất bại` + `MAX_ATTEMPTS`. Nick chỉ `rate_limited` ngay khi lỗi **sau khi đã vào được trang** (`page_reached`); lỗi trước đó chỉ tăng `consecutive_errors`, quá `MAX_AUTO_RETRIES` lần liên tiếp mới nghỉ (về 0 khi vào được trang). Chi tiết: `docs/KIEN_TRUC.md` mục 4.
- Kiểm: `tests/test_worker_fake_dola.py::test_technical_error_auto_retries_then_fails_with_max_attempts` (mode=crash, 1 nick: attempts == 3, "Đã thử 3 lần", không có lần 4 trong 10 s); `grep -n "JobStatus.THAT_BAI" dola_service.py` không được đi kèm `RENDER_TIMEOUT`/`DOWNLOAD_FAILED`/`BROWSER_ERROR` ngoài `_fail_technical`.

## BH-25 · Fake Dola "crash" bằng Content-Length sai làm Chromium treo 60 s thay vì lỗi ngay
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: T5 (hạ tầng test)
- Triệu chứng: test mode=crash mỗi lần thử mất đúng 60 s (`page.goto: Timeout 60000ms exceeded`), 3 lần thử vượt 180 s/test; `curl` thì thấy kết nối bị cắt ngay nên tưởng fake đúng.
- Nguyên nhân gốc: fake gửi header `Content-Length: 1000000` rồi cắt thân; Chromium đã nhận header + vài byte HTML nên **commit** trang dở, `domcontentloaded` không bao giờ bắn, Playwright chờ hết timeout. Hành vi của curl và của trình duyệt khác nhau với cùng một socket.
- Quy tắc: mô phỏng "server sập" phải đóng socket **trước khi gửi header** (Chromium báo `net::ERR_EMPTY_RESPONSE` tức thì). Trong uvicorn, ASGI không có API đóng socket → lấy `transport` qua `send.__self__` (RequestResponseCycle), đặt `disconnected = True` rồi `transport.close()`. Mọi mode lỗi của fake phải được thử bằng Chromium thật, không chỉ bằng curl.
- Kiểm: `tests/test_fake_dola_selfcheck.py` (Chromium thật); test tự chạy lại ở BH-24 phải xong trong < 60 s.

## BH-26 · Test kiểm "nick đã được trả" ngay sau khi job đổi trạng thái
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q2, Q4 (hạ tầng test)
- Triệu chứng: Q4 và Q2/Q3 thỉnh thoảng đỏ với `assert acc["busy_job_id"] is None` → `assert 1 is None`, dù chạy lại thì xanh; máy càng bận càng hay đỏ.
- Nguyên nhân gốc: trạng thái job (`Tạm dừng`/`Hoàn thành`) được ghi **bên trong** phiên Chrome, còn nick được trả (`AccountPool.release` → `busy_job_id = NULL`) ở `finally` của worker **sau khi Chrome đóng** (khoảng 0,5–2 s). Test `wait_until` trạng thái job rồi assert nick ngay lập tức nên rơi đúng vào khoảng hở đó. Đây là thứ tự đúng theo thiết kế (không được trả nick khi Chrome còn mở, mục 1.2), nên lỗi ở test.
- Quy tắc: trong test, mọi kiểm tra "nick đã rảnh" (`busy_job_id`, `is_busy`, `active_count`) sau khi job đổi trạng thái phải qua `wait_until(..., 30)`, không assert tức thì (mẫu đúng: test K4).
- Kiểm: `grep -n 'assert .*busy_job_id.*is None' tests/test_worker_fake_dola.py` chỉ được ra trong test Q5 (gọi `reset_orphans_on_startup()` đồng bộ, không có worker/Chrome); test đơn vị trong `test_account_pool.py` (release tay, không Chrome) được assert ngay.

## BH-27 · Điều phối job trước khi vòng quét kết thúc an toàn
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q1, Q2
- Triệu chứng: job hiện "Đang chạy" mãi mà không có Chrome nào mở; nick gán cho nó "đang bận" vĩnh viễn; mỗi lần như vậy số Chrome tối đa thực tế giảm một, lâu dần worker không nhặt job nào nữa dù máy rảnh.
- Nguyên nhân gốc: `_tick` làm ba việc nối tiếp trong một `try`: điều phối (`_dispatch_one` đã UPDATE job → Đang chạy, `pool.acquire`, `_running_jobs.add`), rồi `_recover_accounts`, rồi `return to_start`. Giả định sai: "các bước sau điều phối không thể ném". Khi `_recover_accounts` ném (CSDL bận), ngoại lệ bay qua `finally` và `to_start` không bao giờ về tới `worker_loop`, nên không thread nào chạy job đã đánh dấu, không ai `release` nick hay dọn `_running_jobs`.
- Quy tắc: mọi job đã được đánh dấu "Đang chạy" trong vòng quét **phải** được khởi chạy hoặc rollback về Chờ trong cùng vòng quét đó. Trong `_tick`: bước sau điều phối (`_recover_accounts`) nằm trong `try/except` riêng; lưới ngoài cùng gọi `_rollback_dispatched(to_start)` (job → Chờ, `attempts -= 1`, trả nick, bỏ khỏi `_running_jobs`) rồi trả `[]`. Không được viết thêm bước nào vào `_tick` sau vòng điều phối mà không nằm trong `try/except` riêng.
- Kiểm: `tests/test_worker_tick.py::test_bh27_tick_returns_dispatched_jobs_when_recover_accounts_raises` (monkeypatch `_recover_accounts` ném → `_tick()` vẫn trả job đã điều phối, job Đang chạy + nick bận chờ khởi chạy) và `::test_bh27_tick_rolls_back_when_connection_close_raises` (lỗi sau điều phối → job về Chờ, nick rảnh, `_running_jobs` rỗng).

## BH-28 · So khớp đường dẫn profile bằng chuỗi con
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q2, Q3 (Windows)
- Triệu chứng: bấm Chẩn đoán nick 1 thì job đang chạy trên nick 10..19 chết giữa chừng ("Target page, context or browser has been closed"); lúc khởi động dọn Chrome mồ côi cũng diệt nhầm.
- Nguyên nhân gốc: `kill_orphan_chrome` kiểm `norm_p in " ".join(cmdline)`; chuỗi `...\profiles\acc_1` là **tiền tố** của `...\profiles\acc_10`, `acc_11`... Giả định sai: "đường dẫn profile là chuỗi đủ đặc trưng để so chuỗi con".
- Quy tắc: so khớp tiến trình với profile phải tách đúng token `--user-data-dir=<path>` (có/không dấu nháy, hoặc hai token) và so **bằng** sau `os.path.normcase(os.path.normpath(...))`, qua hàm thuần `browser._cmdline_uses_profile(cmdline_list, profile_dir)`. Không bao giờ `in` trên chuỗi đường dẫn để quyết định giết tiến trình.
- Kiểm: `tests/test_browser_unit.py::test_bh28_cmdline_uses_profile_exact_match` (acc_10 vs acc_1 → False, acc_1 vs acc_1 → True, dạng có dấu nháy, dạng hai token, thư mục con → False); `grep -n "norm_p in" browser.py` phải rỗng.

## BH-29 · Gọi Playwright Sync API trên luồng event loop và cache kết quả rỗng
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C4, K8
- Triệu chứng: máy không có Chrome cài sẵn nhưng đã chạy `CAI_TRINH_DUYET.bat` (Chromium của Playwright có thật) vẫn bị `/api/health` báo `chrome_found: false`, log "Không tìm thấy Chrome hay Chromium nào trên máy"; bấm Chẩn đoán (gọi `find_chrome(refresh=True)` trong thread) thì lại thấy. Khởi động lại app cũng không hết.
- Nguyên nhân gốc: `find_chrome()` được gọi thẳng trong coroutine `startup_event` (luồng event loop); bước dò Chromium dùng `sync_playwright()` ném "Sync API inside the asyncio loop", bị `except` nuốt thành `log.debug`, rồi kết quả `None` được **cache** (`checked = True`) nên mọi lần gọi sau trả None luôn. Hai giả định sai: "hàm dò chỉ đọc file, gọi ở đâu cũng được" và "dò không thấy và dò lỗi là một".
- Quy tắc: (1) Không gọi `sync_playwright()` trực tiếp trên luồng event loop: trong app.py/worker.py không xuất hiện `sync_playwright`; coroutine gọi `find_chrome` qua `await asyncio.to_thread(...)`. (2) `browser._playwright_chromium_path` tự phát hiện event loop đang chạy (`asyncio.get_running_loop()`) và dò trong thread riêng. (3) Chỉ cache kết quả khi bước dò **chạy sạch**; dò lỗi vì môi trường thì không cache, lần sau dò lại.
- Kiểm: `tests/test_browser_unit.py::test_bh29_find_chrome_inside_event_loop_same_as_thread` (gọi trong `asyncio.run` và trong thread cho cùng kết quả, không có log "Sync API inside"), `::test_bh29_probe_error_is_not_cached`, `::test_bh29_no_sync_playwright_in_app_or_worker` (grep).

## BH-30 · Dấu `)` trong echo bên trong khối if của cmd
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C4
- Triệu chứng: KHOI_DONG.bat in xong "[2/4] Kiem tra moi truong" rồi thoát ngay, không bao giờ chạy uvicorn; CAP_NHAT.bat không bao giờ `git pull`. Chạy tay từng lệnh thì bình thường nên tưởng lỗi Python/Git.
- Nguyên nhân gốc: trong khối `if ... (` ... `)`, cmd đọc **cả khối** một lần và coi dấu `)` đầu tiên không được escape là kết thúc khối, kể cả khi nó nằm trong dòng `echo ... (ma loi %errorlevel%).` Giả định sai: "echo in nguyên văn mọi ký tự sau nó".
- Quy tắc: trong file .bat, dòng `echo` nằm bên trong khối `( ... )` không được chứa `)` (nếu buộc phải có thì viết `^)`); tránh luôn cả `(` để khỏi nhầm. Thông điệp cần ngoặc thì viết lại bằng dấu phẩy/gạch ngang.
- Kiểm: `tests/test_bat_syntax.py::test_bh30_echo_inside_block_has_no_unescaped_paren` (parse mọi *.bat, theo dõi độ sâu khối theo dòng `if/else/for ... (` và `)` đầu dòng, assert echo trong khối không có `)` thiếu `^`), `::test_bat_blocks_balanced`; KHOI_DONG.bat lấy phiên bản từ file VERSION (`::test_khoi_dong_title_reads_version`).

## BH-31 · Giao diện trỏ tới đường dẫn tĩnh backend không mount
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: D5, Q6
- Triệu chứng: link "📷 Xem ảnh lỗi" trong bảng job trả 404 (ảnh có thật trong `logs/screenshots/`). Bản vá đầu tiên mount nguyên `/logs` → ai mở `http://localhost:8000/logs/studio_2026-10-09.log` đọc được toàn bộ nhật ký (tên nick, proxy, lỗi).
- Nguyên nhân gốc: app.js dựng URL `/logs/screenshots/<tên>` từ `[ảnh: <tên>]` nhưng app.py chưa mount thư mục này; hợp đồng "đường dẫn tĩnh" không được ghi ở đâu nên hai bên lệch nhau; vá vội theo hướng "mount cả thư mục cha cho tiện" mở rộng bề mặt lộ dữ liệu.
- Quy tắc: mọi đường dẫn tĩnh mà frontend dùng phải có trong bảng "Đường dẫn tĩnh" ở `docs/KIEN_TRUC.md` mục 5 và được mount **đúng thư mục con cần thiết** (`/logs/screenshots` → `config.SCREENSHOTS_DIR`); không bao giờ mount `config.LOGS_DIR`, `config.DATA_DIR`, `config.PROFILES_DIR`.
- Kiểm: `tests/test_app_api.py::test_bh31_screenshots_served_but_logs_not` (TestClient: png trong SCREENSHOTS_DIR → `/logs/screenshots/x.png` 200; `/logs/studio_x.log` → 404) và `::test_bh31_no_broad_logs_mount` (grep `app.mount("/logs"` không có trong app.py).

## BH-32 · Dùng executor mặc định của asyncio cho job dài hàng phút
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q1, C4
- Triệu chứng: đặt 6–8 Chrome đồng thời trên máy 2–4 nhân thì `/api/health` treo nhiều giây, header hiện "Mất kết nối máy chủ" dù server còn sống; nút Chẩn đoán/Check credit "đang chạy" mãi; worker báo không sống (`worker_alive` False) vì vòng quét `_tick` không được cấp thread.
- Nguyên nhân gốc: `asyncio.to_thread` dùng executor mặc định với `min(32, cpu + 4)` thread; mỗi job chiếm một thread trọn hàng phút (Chrome + render), nên 6 job trên máy 2 nhân (6 thread) đã chiếm hết, `_tick`, `find_chrome`, chẩn đoán xếp hàng sau job. Giả định sai: "executor mặc định đủ rộng cho mọi việc".
- Quy tắc: việc dài (mở Chrome: job, auto login, check credit, chẩn đoán, mở Chrome đăng nhập) chạy trên `worker.JOB_EXECUTOR` (ThreadPoolExecutor 32 thread cố định, prefix `job`; 32 vì executor không đổi được kích thước và 6–20 Chrome + vài thao tác tay vẫn dư; giới hạn Chrome thật vẫn do `BrowserSlots`). Việc ngắn (`_tick`, `find_chrome`, build_bundle) giữ `asyncio.to_thread`. Thêm thao tác mở Chrome mới phải đi qua `run_in_job_executor`.
- Kiểm: `tests/test_worker_executor.py::test_bh32_health_responsive_while_jobs_run` (cpu_count giả = 1, 6 job render 8 s chạy đồng thời; `worker_alive()` True và `/api/health` qua TestClient < 2 s); `grep -n "to_thread(execute_video_job" worker.py` phải rỗng.

## BH-33 · Lộ mật khẩu proxy trong lỗi và gói chẩn đoán
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: A3, D5
- Triệu chứng: bước "Proxy" của Chẩn đoán hiện `Proxy '1.2.3.4:8080:user:matkhau' không phản hồi`; chuỗi đó được ghi vào `accounts.last_error`, hiện trên giao diện và nằm nguyên trong `accounts.json` của gói chẩn đoán gửi hỗ trợ (cột `proxy` cũng để trần dù `fb_pass` đã che).
- Nguyên nhân gốc: coi proxy là "cấu hình mạng" chứ không phải "bí mật" nên không đưa vào danh sách cột cần che; thông điệp lỗi nối thẳng chuỗi proxy gốc của người dùng và thông điệp của thư viện mạng (có thể lặp lại URL proxy kèm mật khẩu).
- Quy tắc: mọi chỗ hiển thị/ghi proxy (detail bước chẩn đoán, `last_error`, log_event, gói chẩn đoán) phải qua `diagnostics.mask_proxy` (`ip:port:user:***`, `scheme://user:***@host:port`); `build_bundle` che cả cột `proxy` và `last_error`. Không nối `acc["proxy"]` trực tiếp vào chuỗi cho người dùng.
- Kiểm: `tests/test_diagnostics_unit.py::test_bh33_mask_proxy` (các dạng proxy), `::test_bh33_proxy_step_detail_hides_password`, `::test_bh33_bundle_masks_proxy_and_last_error`; `grep -n "acc.get('proxy')\|acc\[\"proxy\"\]" diagnostics.py dola_service.py` chỉ được đi kèm `mask_proxy`/`parse_proxy`.

## BH-34 · Test assert thông điệp trạng thái tạm mà worker được phép ghi đè ở vòng quét sau
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: K4, Q7 (hạ tầng test)
- Triệu chứng: test K4 đỏ ngẫu nhiên (~1/3 lần) với `AssertionError: Chưa có nick phù hợp: 1 nick đang nghỉ` dù hành vi hết credit đúng; chạy lại thì xanh. Lộ ra khi máy bận hơn (nhiều Chrome của test BH-32 chạy trước đó) làm Chrome đóng nhanh/chậm khác nhau.
- Nguyên nhân gốc: `dola_service` ghi job về `Chờ` với "Nick X hết credit hôm nay, chưa có nick khác, chờ hồi phục lúc 00:05"; sau khi Chrome đóng và nick được trả, vòng quét 2 giây kế tiếp **đúng thiết kế Q7** ghi đè `status_message` thành tóm tắt "Chưa có nick phù hợp: 1 nick đang nghỉ". Test assert chuỗi tạm ngay sau khi thấy `status = Chờ` nên rơi vào cửa sổ đua giữa hai lần ghi (cùng họ với BH-26).
- Quy tắc: thông điệp mà job mang lúc rời `Đang chạy` là **tạm**; test chỉ được assert nó dưới dạng "một trong các thông điệp hợp lệ", còn lý do gốc (hết credit, captcha, lỗi kỹ thuật) phải kiểm qua kênh bền: `system_logs` (log_event ghi cùng lúc), cột nick (`rest_until`, `needs_manual`), hoặc `attempts`. Không bao giờ assert bằng `==` trên `status_message` của job `Chờ` khi worker đang chạy.
- Kiểm: `tests/test_worker_fake_dola.py::test_k4_partial_daily_limit_rests_account_and_requeues_job` (chấp nhận "hết credit" hoặc "nick đang nghỉ", kiểm "hết credit hôm nay" trong `system_logs`); `grep -n 'assert .*status_message.*== ' tests/test_worker_fake_dola.py` chỉ được ra trong Q5 (gọi `reset_orphans_on_startup()` đồng bộ, không có worker) và Q7 (so hai lần đọc với nhau, không so với chuỗi cứng).

## BH-35 · Cổng 8000 bị bản tool cũ chiếm, server mới tắt im lặng
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C2
- Triệu chứng: người dùng chạy KHOI_DONG.bat, mọi bước kiểm tra OK, rồi một dòng đỏ tiếng Anh "Errno 10048 only one usage of each socket address", server tắt; người dùng tưởng đã xong.
- Nguyên nhân gốc: check_env.py kiểm Python, thư viện, Chrome nhưng không kiểm cổng; lỗi của uvicorn bằng tiếng Anh, không nói cách xử lý.
- Quy tắc: mọi tài nguyên server cần (cổng, thư mục dữ liệu, Chrome) đều phải kiểm trước khi khởi động và báo bằng tiếng Việt kèm cách xử lý (PID, lệnh taskkill).
- Kiểm: `tests/test_check_env_port.py`; thử tay: mở KHOI_DONG.bat hai lần, cửa sổ thứ hai phải báo "Cổng 8000 đang bị chiếm bởi PID ..." và không khởi động server.

## BH-36 · Báo nhầm captcha trên trang Dola bình thường
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q4
- Triệu chứng: job cứ Tạm dừng "Nick bị Dola yêu cầu kéo mảnh ghép" trong khi mở Chrome thật thì trang Dola bình thường, không có captcha.
- Nguyên nhân gốc: bộ phát hiện coi "có bất kỳ icon lỗi nào trong DOM, kể cả ẩn" là captcha; nhánh khác chỉ cần chữ "verify" (khớp cả "verified") là báo captcha. Dấu hiệu quá rộng nên dương tính giả.
- Quy tắc: một dấu hiệu chỉ được dùng để tạm dừng job khi nó là đặc trưng riêng của tình huống đó (khung captcha đang hiển thị và có kích thước, hoặc câu chữ nguyên văn của captcha). Mọi lần tạm dừng phải kèm ảnh chụp để người dùng đối chiếu.
- Kiểm: `tests/test_captcha_detect.py`; thử tay: trang Dola thường không được báo captcha.

## BH-37 · Script cập nhật mặc định về nhánh main làm người dùng quay lại bản cũ
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C2, mục "Cách nhận bản mới"
- Triệu chứng: người dùng đang test bản mới, chạy CAP_NHAT.bat (không gõ tên nhánh) rồi khởi động, giao diện lại hiện chữ của bản cũ ("Đang chờ", "Đang ghép acc"), tưởng lỗi chưa sửa.
- Nguyên nhân gốc: CAP_NHAT.bat không có tham số thì checkout `main`; người dùng không biết khái niệm nhánh.
- Quy tắc: script cập nhật mặc định giữ nguyên nhánh đang dùng và in rõ tên nhánh sẽ cập nhật; chỉ đổi nhánh khi người dùng gõ tên nhánh. Phiên bản ở góc giao diện là cách kiểm nhanh.
- Kiểm: `tests/test_bat_syntax.py::test_bh37_cap_nhat_keeps_current_branch`; thử tay: đang ở nhánh test, chạy CAP_NHAT.bat không tham số, vẫn ở nhánh test.

## BH-38 · Thông báo tạm dừng không nói dấu hiệu nào đã kích hoạt
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q4, D2
- Triệu chứng: job báo "bị yêu cầu kéo captcha" nhưng không ai biết tool dựa vào đâu; phải đoán giữa nhiều quy tắc phát hiện.
- Nguyên nhân gốc: hàm phát hiện chỉ trả True/False, vứt bỏ thông tin phần tử hoặc câu chữ đã khớp.
- Quy tắc: mọi kết luận tự động làm job dừng (captcha, hết credit, từ chối chính sách) phải ghi kèm dấu hiệu cụ thể đã khớp (selector, kích thước, câu chữ) vào lý do và last_error.
- Kiểm: `tests/test_captcha_detect.py::test_bh38_evidence_names_the_trigger`.

## BH-39 · Chạy headless bị Dola chặn bằng captcha ByteDance ngay sau khi gửi prompt
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q4, T5
- Triệu chứng: mọi job đều Tạm dừng "bị Dola yêu cầu kéo mảnh ghép" ngay sau khi gửi prompt (trang có `<div id="captcha_container" style="display:block; position:fixed; inset:0; z-index:111111">` chứa iframe `bdcaptcha.html` của ByteDance); người dùng bấm nút Chrome (cửa sổ thật, cùng profile, cùng nick) thì không hề có captcha. Thêm nữa, khi captcha hiện thì job dừng ngay dù người dùng đang ngồi trước máy và có thể kéo trong vài giây.
- Nguyên nhân gốc: Chrome `headless=True` lộ dấu hiệu tự động hóa (không có cửa sổ/GPU thật, user-agent và API khác bản thường) nên hệ chống bot của Dola bắt kéo captcha; nick không bị gì cả. Giả định sai: "headless chỉ là Chrome không có cửa sổ, site không phân biệt được".
- Quy tắc: thao tác tự động trên site có chống bot (Dola) phải dùng **Chrome thật** với cửa sổ đặt ngoài màn hình (`browser.launch_context`: `headless=True` nghĩa là *ẩn*, Playwright `headless=False` + `--window-position=-32000,-32000`); headless thật chỉ khi `config.HEADLESS` (`SEEDANCE_HEADLESS=1`, máy test không có màn hình). Gặp captcha giữa job: `show_window` đưa cửa sổ ra màn hình, chờ người dùng kéo tại chỗ `CAPTCHA_SOLVE_TIMEOUT_SECONDS` (3 phút), giải xong `hide_window` và chỉ gửi lại prompt một lần **khi có bằng chứng lần gửi trước không đi** (BH-45); hết giờ mới Tạm dừng. Không bao giờ đặt `headless=True` trực tiếp cho Playwright ngoài `browser.py`.
- Kiểm: `tests/test_worker_fake_dola.py::test_captcha_solved_in_place_job_completes` (captcha sau gửi prompt, giải sau 6 s → Hoàn thành, nick không needs_manual), `::test_q4_captcha_pauses_job_and_does_not_reopen_chrome` (không giải → Tạm dừng sau timeout), `tests/test_browser_hidden_xvfb.py` (cửa sổ ẩn thật ở -32000, show → 80,80, hide → -32000); `grep -n '"headless": ' browser.py` chỉ được là `playwright_headless(hidden)`; thử tay Q4/Q4b trong `docs/TEST_TAY_GIAI_DOAN_1.md` (job chạy không đòi captcha; khi có thì cửa sổ tự hiện).

## BH-40 · Fake Dola mô phỏng sai thời điểm captcha nên nhánh "captcha sau khi gửi prompt" chưa từng được test
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q4 (hạ tầng test)
- Triệu chứng: Q4 xanh suốt từ đầu nhưng với Dola thật captcha xuất hiện ở một chỗ khác (sau khi gửi prompt) và có cấu trúc khác (`div#captcha_container` không có class, phủ cả trang) với thứ fake tạo (`div.captcha-box` nằm sẵn trong trang lúc tải). Nhánh mã phát hiện captcha sau khi gửi prompt và việc "prompt gửi lúc captcha hiện không tạo conversation" không có test nào chạm tới.
- Nguyên nhân gốc: fake được viết theo tưởng tượng về captcha ("có khung Verify to continue trong trang") chứ không theo HTML thật thu được từ máy người dùng; test chỉ chứng minh mã khớp với fake, không chứng minh mã khớp với Dola.
- Quy tắc: mỗi mode của fake Dola phải bám **bằng chứng HTML/thời điểm thật** (ghi nguồn trong docstring hoặc KIEN_TRUC mục 6); khi có bằng chứng mới từ máy người dùng (ảnh/HTML trong gói chẩn đoán) thì cập nhật fake trước, rồi mới sửa mã theo test đỏ. Fake captcha: chỉ hiện sau `/__send` đầu tiên, có id không class, `/__send` lúc captcha hiện không tạo conversation.
- Kiểm: `tests/test_fake_dola_selfcheck.py::test_captcha_mode` (không có captcha trước khi gửi; sau gửi có `#captcha_container` không class, conversation rỗng), `::test_captcha_mode_solved_after_delay`; `tests/test_captcha_detect.py` có ca `#captcha_container display:block/none`.

## BH-41 · Đọc `page.url` sau `time.sleep` trong Playwright Sync API cho giá trị cũ
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: T5 (hạ tầng test)
- Triệu chứng: test gõ Enter, `time.sleep(1)`, rồi `assert re.search(r"/chat/\d+", page.url)` đỏ dù server đã tạo conversation và trang đã `pushState`; đo thời gian thì phản hồi `/__send` "mất đúng 1 s / 3 s" bằng đúng khoảng sleep của luồng test.
- Nguyên nhân gốc: Sync API của Playwright chỉ bơm sự kiện (`framenavigated` cập nhật `page.url`, `response`, ...) **khi luồng đang ở trong một lệnh Playwright**; trong `time.sleep` không có gì được xử lý nên `page.url` và các callback `page.on(...)` đứng yên. Giả định sai: "page.url luôn là URL hiện tại của trang".
- Quy tắc: muốn thấy URL/trạng thái mới phải dùng lệnh Playwright có chờ (`page.wait_for_url`, `wait_for_function`, `locator.wait_for`) hoặc gọi một lệnh bất kỳ (`page.evaluate`) trước khi đọc `page.url`; không `time.sleep` rồi đọc thuộc tính cache. Trong `dola_service._wait_new_conversation` mỗi vòng đều gọi `_fetch_recent_conv_ids` (evaluate) nên không mắc lỗi này.
- Kiểm: `tests/test_fake_dola_selfcheck.py::test_captcha_mode_solved_after_delay` dùng `page.wait_for_url`; `grep -n "time.sleep" tests/test_fake_dola_selfcheck.py` không được đi ngay trước `assert ... page.url` dương tính.


## BH-42 · Bộ mẫu đạo diễn chỉ nằm ở giao diện, backend gửi prompt thô kèm câu cố định
- Ngày: 2026-10-09 · Giai đoạn: 4 · Mã: P1, P3, P4, P6, P7
- Triệu chứng: người dùng đã có sẵn bộ đạo diễn trong tool (cỡ cảnh, góc máy, ống kính, ánh sáng, 11 trường phái, kho nhân vật) nhưng video Dola trả về không theo; cảnh đối thoại hai người bị quay kiểu "FPV nhào lộn hành động bom tấn". Xem `jobs.prompt_final` thì thấy prompt thô + một câu tiếng Anh cố định.
- Nguyên nhân gốc: logic ghép mẫu (`analyzePromptWithChatGPTAndBructa`) nằm trong app.js và chỉ chạy khi người dùng bấm tay rồi ghi đè ô nhập; backend (`dola_service.build_full_prompt`) không biết bộ mẫu, chỉ nối một câu "FPV ... Hollywood bom tấn" cho mọi prompt chưa có từ "cinematic/shot/lens". Hai bản logic (JS và Python) lệch nhau và bản chạy thật là bản nghèo hơn. Bộ mẫu cũng thiếu nhánh "đối thoại" nên cảnh nói chuyện rơi vào mặc định.
- Quy tắc: **mọi biến đổi prompt là một hàm thuần ở backend** (`director.compose`, không I/O, assets/options truyền qua tham số), chạy **lúc tạo job** và lưu `jobs.prompt_final` + `archetype_code`; giao diện chỉ gọi `POST /api/director/preview` để xem trước và `PUT /api/jobs/{id}/prompt_final` để sửa tay, không tự ghép bằng JS. Không có câu mẫu cố định nào ngoài bộ `director.ARCHETYPES`; lớp prompt đã tự mô tả thì không chèn lại; lớp tắt trong Cài đặt thì không chèn. Thêm/sửa mẫu → chạy `python tests/gen_dao_dien_mau.py` để cập nhật `docs/DAO_DIEN_MAU.md` cho người dùng duyệt.
- Kiểm: `tests/test_director.py` (mỗi trường phái một prompt; P1 đối thoại → T1 không FPV; P3 "ống kính 85mm" không chèn lens thứ hai; P4 "Tiểu Vũ" được chèn mô tả; P6 tắt lớp; prompt gốc nguyên văn; không còn "Hollywood blockbuster action masterpiece" trong director.py), `tests/test_director_docs.py` (P7 docs khớp mã), `tests/test_app_api.py` (preview không tạo job, batch lưu prompt_final, PUT bị từ chối khi Đang chạy); `grep -n "textarea.value =" static/js/app.js` không được nằm trong `autoDetectAndEnhanceBructa`.

## BH-43 · Regex bỏ số thứ tự đầu prompt ăn cả số lượng
- Ngày: 2026-10-09 · Giai đoạn: 4 · Mã: P2
- Triệu chứng: prompt "2 cô gái nhảy múa trên sân khấu" được gửi Dola thành "cô gái nhảy múa trên sân khấu"; "3 chiếc xe đua qua cầu" mất số 3. Video thiếu nhân vật/xe mà người dùng không biết vì giao diện vẫn hiện prompt gốc.
- Nguyên nhân gốc: `director._LEADING_NUMBER = ^\d+[\.\:\-\s]+` coi **khoảng trắng** là dấu phân cách, nên mọi prompt bắt đầu bằng số đều bị cắt. Giả định sai: "prompt bắt đầu bằng số thì số đó là số thứ tự". Quy tắc "giữ nguyên văn prompt gốc" (P2) chỉ được test với prompt có "03." nên không lộ.
- Quy tắc: chỉ bỏ số thứ tự khi có **dấu phân cách thật** sau số (`^\d+\s*[\.\:\-\)]\s+`: "01. ", "3: ", "12 - ", "7) "); mọi biến đổi "dọn" prompt phải có ca test với giá trị hợp lệ trông giống rác (số lượng, ngày tháng, tỉ lệ 16:9...).
- Kiểm: `tests/test_director.py::test_bh43_leading_quantity_is_kept_verbatim`, `::test_bh43_ordinal_with_separator_is_stripped`; `grep -n "_LEADING_NUMBER = " director.py` phải chứa `[\.\:\-\)]\s+` và không chứa `\s]+`.

## BH-44 · Từ khóa ngắn so chuỗi con gây nhận nhầm trường phái khi tự động hóa
- Ngày: 2026-10-09 · Giai đoạn: 4 · Mã: P1, P7
- Triệu chứng: "Spring festival parade" và "A boy bringing flowers" → P1-Macro (ống kính macro 100mm cho một cuộc diễu hành), "Books on the shelf" → F1 Fantasy, "Tên lửa bay lên" → F2 hắc ám, "Mặt trời mọc" → P1 chân dung, "Cây cầu bắc qua sông" → F1. Video sai hẳn phong cách; bảng duyệt mẫu (DAO_DIEN_MAU) không có các prompt này nên không ai thấy.
- Nguyên nhân gốc: `detect_archetype` so `keyword in lower` (chuỗi con, chuyển 1:1 từ `lower.includes` của JS cũ): "ring" nằm trong "spring"/"bringing", "elf" trong "shelf", "tea" trong "steam", "man" trong "human"; từ Việt một âm tiết quá chung ("cây", "mặt", "lửa", "tháp", "kiếm", "đao") khớp cả "cây cầu", "mặt trời", "tên lửa", "kiếm tiền". Ở bản JS cũ người dùng bấm tay và nhìn kết quả nên lỗi được sửa bằng mắt; khi tự động hóa cho hàng trăm prompt thì không ai nhìn nữa.
- Quy tắc: quy tắc nhận diện chạy tự động trên văn bản tự do phải so **từ nguyên** cho từ khóa ngắn (`director._keyword_pattern`: tiếng Anh ≤ 5 ký tự và tiếng Việt một âm tiết dùng `(?<!\w)...(?!\w)` Unicode); từ Việt một âm tiết quá chung không được làm từ khóa, thay bằng cụm có nghĩa ("cây cổ thụ", "khuôn mặt", "ngọn lửa", "thanh kiếm"). Mỗi trường phái phải có **ca âm** (prompt không được rơi vào nó) bên cạnh ca dương.
- Kiểm: `tests/test_director.py::test_bh44_short_keywords_match_whole_words_only` (9 ca âm), `::test_bh44_whole_word_keywords_still_match`, `::test_bh44_keyword_pattern_rules` (không còn `cây/mặt/lửa/tháp/kiếm/đao` trong `ARCHETYPES`); `grep -n "if any(k in lower" director.py` phải rỗng; `python tests/gen_dao_dien_mau.py` rồi `tests/test_director_docs.py` xanh.

## BH-45 · Gửi lại prompt sau captcha có thể tốn 2 credit
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q4, K4
- Triệu chứng: nick kéo xong captcha, job Hoàn thành nhưng credit của nick giảm 2 thay vì 1; trong lịch sử Dola có hai cuộc trò chuyện cùng prompt (một video thừa không ai tải).
- Nguyên nhân gốc: `_conv_after_captcha_solved` chờ 15 s không thấy conversation mới là **gửi lại ngay** (gõ lại prompt + Enter). Giả định sai: "prompt gửi lúc captcha hiện chắc chắn không được Dola nhận". Thực tế Dola có lúc tự gửi prompt đã gõ ngay sau khi giải, hoặc conversation mới xuất hiện trong recent_conv chậm hơn 15 s; gửi lại mù quáng tạo video thứ hai và trừ thêm credit.
- Quy tắc: **trước khi lặp lại một thao tác tốn tiền (gửi prompt, tạo video, mua gói) phải kiểm bằng chứng thao tác trước đã/không thành công**: credit đọc được và đã giảm → đã thành công, không lặp (chỉ chờ thêm); ô nhập còn nguyên nội dung → chưa gửi, chỉ bấm Enter (không gõ lại để khỏi nhân đôi); không có bằng chứng (ô trống, credit không đọc được) → chờ thêm rồi mới lặp. Luôn truyền trạng thái trước thao tác (`credits_pre`) vào hàm quyết định lặp và ghi rõ nhánh đã chọn vào nhật ký.
- Kiểm: `tests/test_captcha_resend.py` (các nhánh a/b/c1/c2 với trang giả; mọi lời gọi `_conv_after_captcha_solved` truyền `credits_pre`), `tests/test_worker_fake_dola.py::test_captcha_solved_dola_auto_sends_no_resend` (Dola tự gửi → 1 conversation, credit giảm đúng 1), `::test_captcha_solved_in_place_job_completes` (ô còn prompt → gửi lại bằng Enter một lần); `tests/test_fake_dola_selfcheck.py::test_captcha_mode_auto_resend_after_solve`.

## BH-46 · Giả định thời lượng 30 giây và không gửi tỷ lệ, Dola hỏi lại thay vì tạo
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q6, P2, K4
- Triệu chứng: job #23 gửi "Tạo video Seedance 2.5 dài 30 giây. người nhện đánh nhau với robot. Hình ảnh: ..." rồi RENDER_TIMEOUT sau 8 phút. HTML trang Dola lúc đó cho thấy Dola **không tạo video** mà trả lời bằng chữ: "Video generation currently supports durations from 4 to 15 seconds ... I also need to confirm the aspect ratio you want: A. 16:9 ... B. 9:16 ... Which option would you like?". Mặc định "30 giây" nằm ở CSDL, giao diện (nút 20/25/30 giây), request model và câu mở đầu; tỷ lệ "Dọc/Ngang" chỉ là biến JS không bao giờ gửi đi.
- Nguyên nhân gốc: tham số của dịch vụ bên ngoài (thời lượng, tỷ lệ) được **giả định** theo mong muốn của mình thay vì **kiểm từ phản hồi thật** của dịch vụ; và một tham số có ở giao diện (tỷ lệ) nhưng không có đường đi tới prompt nên Dola phải hỏi.
- Quy tắc: mọi tham số gửi sang dịch vụ ngoài phải có **bằng chứng từ chính dịch vụ đó** (ghi nguồn trong `constants.py`: Dola hỗ trợ 4-15 giây, hỏi tỷ lệ nếu thiếu) và phải được **nêu rõ trong prompt** (`director.build_header`: "Tạo video {model} dài {N} giây, tỷ lệ khung hình {ratio} (dọc|ngang). Không hỏi lại, tạo video ngay."). Giá trị người dùng/CSDL cũ nằm ngoài khoảng hỗ trợ phải bị ép về biên **ở backend** (`constants.normalize_duration`, dùng trong app.py, database.init_db, dola_service.build_full_prompt) kèm cảnh báo trả về giao diện/nhật ký; giao diện chỉ hiện các lựa chọn hợp lệ (`DURATION_CHOICES`, `RATIO_CHOICES`), mặc định 15 giây, 16:9 (ngang). Tỷ lệ là cột thật `jobs.ratio` và setting `default_ratio`, không phải biến JS mồ côi.
- Kiểm: `tests/test_dola_reply_unit.py` (`normalize_duration` ép 30→15, 3→4; `build_full_prompt` viết lại header job cũ "30 giây"), `tests/test_director.py::test_duration_and_model_header`, `::test_bh46_fix_header_rewrites_old_header_only`, `tests/test_app_api.py` (preview/batch trả `warnings` khi gửi "30 giây", lưu `jobs.ratio`), `tests/test_database.py` (CSDL cũ `default_duration` "30 giây" → "15 giây" + 1 dòng INFO; cột `ratio`, `dola_reply`); `grep -n "30 giây\|25 giây\|20 giây" static/index.html static/js/app.js` phải rỗng (mã Python chỉ còn nhắc "30 giây" trong chú thích/docstring); `tests/test_worker_fake_dola.py::test_dola_asks_ratio_tool_answers_once_and_completes`.

## BH-47 · Chờ kết quả 8 phút mà không đọc câu trả lời của dịch vụ
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q6, D2
- Triệu chứng: Dola trả lời bằng một câu hỏi ngay sau khi nhận prompt (BH-46), nhưng vòng poll chỉ tìm URL video (và vài chuỗi cố định "daily limit", "cannot provide") nên chờ đủ 480 giây rồi báo "Quá 480s chưa nhận được video từ Dola" trơ trọi; lý do không nói Dola đã nói gì, job còn bị coi là lỗi kỹ thuật và tự chạy lại 2 lần nữa (thêm 16 phút), người dùng không có cách nào biết vì sao.
- Nguyên nhân gốc: khi chờ một kết quả bất đồng bộ, mã chỉ nhận diện **kết quả mong muốn** (video) và vài **lỗi đã biết**, vứt bỏ mọi phản hồi trung gian; giả định sai "nếu chưa có video thì Dola vẫn đang render".
- Quy tắc: khi chờ kết quả bất đồng bộ từ dịch vụ ngoài phải **đọc mọi phản hồi trung gian** (`dola_service._assistant_texts` trích văn bản trợ lý từ JSON chain, kể cả JSON lồng trong chuỗi) và lưu nguyên văn cho người dùng (`jobs.dola_reply`, modal Prompt "Dola trả lời:"). Phản hồi dạng **câu hỏi** (`_looks_like_question`) → trả lời tự động đúng một lần bằng tham số của job rồi chờ tiếp; phản hồi dạng **từ chối/giải thích** không kèm "generating" quá 60 s, hoặc câu hỏi lần hai → **dừng sớm** `Thất bại` với `Reason.DOLA_REPLIED_TEXT` (200 ký tự đầu nguyên văn), là lỗi nội dung (không tự chạy lại, không `rate_limited`). Hết giờ mà có phản hồi thì lý do phải kèm nguyên văn (`RENDER_TIMEOUT_WITH_REPLY`). Không bao giờ báo "quá N giây chưa có kết quả" khi dịch vụ đã nói gì đó.
- Kiểm: `tests/test_dola_reply_unit.py` (`_assistant_texts` JSON lồng/chuỗi JSON trong chuỗi/bỏ URL và prompt; `_looks_like_question` vi/en), `tests/test_worker_fake_dola.py::test_dola_asks_ratio_tool_answers_once_and_completes` (2 tin đã gửi, log "Dola hỏi lại", Hoàn thành), `::test_dola_replies_text_job_fails_fast_with_reply_in_reason` (Thất bại < 120 s, lý do chứa "cannot create", attempts == 1, nick ready), `tests/test_fake_dola_selfcheck.py::test_ask_ratio_mode`; `grep -n "RENDER_TIMEOUT.format" dola_service.py` chỉ được nằm trong nhánh `else` sau khi đã kiểm `seen_replies`.

## BH-48 · Đọc nhầm tin nhắn do chính tool gửi thành câu trả lời của dịch vụ
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: Q6, D2
- Triệu chứng: Dola hỏi lại tỷ lệ, tool tự trả lời "15 giây, tỷ lệ 16:9. Hãy tạo video ngay, không cần hỏi thêm." rồi ở vòng poll kế tiếp chính câu đó (Dola thật và fake đều trả CẢ lịch sử conversation, gồm tin của người dùng) bị `_assistant_texts` coi là "Dola trả lời bằng chữ": `jobs.dola_reply` bị ghi đè bằng câu của tool, và sau 60 s không thấy "generating" job `Thất bại` oan với lý do "Dola trả lời bằng chữ thay vì tạo video: '15 giây, tỷ lệ 16:9...'" trong khi video đang được tạo.
- Nguyên nhân gốc: khi phân tích lịch sử hội thoại, mã chỉ loại **một** tin của mình (prompt đầu) và loại bằng 40 ký tự đầu của prompt (chính là câu mở đầu cố định giống nhau ở mọi job, nên vừa bỏ sót câu tự trả lời vừa bỏ nhầm câu Dola trích lại header); trường `role`/`user_type` của tin nhắn bị bỏ qua. Giả định sai: "chain chỉ chứa tin mới nhất của trợ lý" và "fake chỉ cần trả tin trợ lý là đủ" (fake cũ không trả câu trả lời của người dùng nên test xanh mà bug vẫn còn).
- Quy tắc: khi phân tích lịch sử hội thoại của dịch vụ ngoài, **loại trước mọi nội dung do mình gửi** (prompt, câu tự trả lời, bản gửi lại sau captcha — truyền danh sách `own_texts` vào `_assistant_texts`, so nguyên văn, bản cắt ngắn và 40 ký tự đầu **sau** câu mở đầu cố định `director.HEADER_RE`) **và tôn trọng trường role**: node có `role`/`user_type`/`sender`/`from` là user (`"user"`, `1`, `"human"`) bị bỏ cả nhánh. Fake Dola phải trả **cả tin của mình** như dịch vụ thật (lịch sử đầy đủ, có `role`), không chỉ tin trợ lý. Dừng sớm vì "trả lời bằng chữ" chỉ khi văn bản giống lời từ chối (60 s, `_looks_like_refusal`) hoặc đã quá 120 s không video và không "generating" (`_reply_should_fail`); `auto_answered` chỉ bật khi gửi được, không thấy ô nhập thì thử lại tối đa 3 lần (`_auto_answer_step`).
- Kiểm: `tests/test_dola_reply_unit.py::test_bh48_assistant_texts_drops_own_auto_answer_even_without_role` (chain chứa đúng câu `_auto_answer_text` → `[]`), `::test_bh48_assistant_texts_skips_nodes_marked_as_user`, `::test_n2_own_prompt_head_is_taken_after_fixed_header` ("You asked: 'Tạo video…' but I cannot…" được trả về), `::test_reply_should_fail_rules`, `::test_auto_answer_step_retries_until_sent_or_three_failures`; `tests/test_worker_fake_dola.py::test_dola_asks_ratio_tool_answers_once_and_completes` (fake trả cả câu tool đã gửi; `dola_reply` == câu hỏi của Dola, đúng 1 dòng "Dola hỏi lại", Hoàn thành) — đỏ trước khi sửa `_assistant_texts`, xanh sau; `grep -n "_assistant_texts(chain_res" dola_service.py` phải truyền `own_texts`.

## BH-49 · Ghi đè câu mở đầu người dùng đã sửa tay bằng cột duration/ratio cũ của job
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: P2, Q6
- Triệu chứng: người dùng bấm "Prompt" sửa câu mở đầu thành "dài 8 giây, tỷ lệ khung hình 9:16 (dọc)" rồi Lưu; lúc worker nhặt, `build_full_prompt` gọi `director.fix_header` với `jobs.duration`/`ratio` cũ (15 giây, 16:9) nên header bị viết lại thành 15 giây 16:9, video ra sai thứ người dùng vừa sửa, mà bảng job vẫn hiện "15 giây" nên không ai thấy.
- Nguyên nhân gốc: `fix_header` viết lại header **vô điều kiện** hễ nhận ra được header, coi cột CSDL là nguồn sự thật duy nhất; nhưng header trong `prompt_final` là thứ người dùng được phép sửa (BH-42) và là thứ thật sự gửi Dola. Hai nguồn (cột và header) lệch nhau thì bản gửi đi phải thắng, không phải cột.
- Quy tắc: lớp tự động chỉ được **sửa khi thiếu/sai** (giây ngoài 4-15 hoặc thiếu tỷ lệ), không ghi đè giá trị hợp lệ người dùng đã viết; `director.parse_header` đọc ngược header hợp lệ và `build_full_prompt` ghi `jobs.duration`/`ratio` theo nó để cột khớp với thứ đã gửi. Tổng quát: khi một giá trị vừa có trong CSDL vừa có trong văn bản người dùng sửa được, văn bản thắng và CSDL được đồng bộ ngược.
- Kiểm: `tests/test_director.py::test_bh46_fix_header_rewrites_old_header_only` (header 10 giây 9:16 không đổi khi truyền 15 giây 16:9), `::test_bh49_parse_header_reads_back_user_edited_values`; `tests/test_dola_reply_unit.py::test_bh49_build_full_prompt_keeps_user_edited_valid_header_and_updates_job` (8 giây 9:16 → prompt giữ nguyên, `jobs.duration` thành "8 giây"); `grep -n "parse_header" dola_service.py` phải có trong `build_full_prompt`.

## BH-50 · Đường dẫn Chrome cứng Linux và socket Keep-Alive trên Windows làm đứt chuỗi test
- Ngày: 2026-10-09 · Giai đoạn: 1 · Mã: C3, T5
- Triệu chứng: Chạy test trên Windows thì test tìm Chrome báo thiếu đường dẫn Linux `/opt/pw-browsers/...`; chạy hàng trăm test HTTP liên tiếp với fake Dola cục bộ bị lỗi `WinError 10053 An established connection was aborted by the software in your host machine`.
- Nguyên nhân gốc: `conftest.py` chỉ định cứng `DEFAULT_CHROME` theo Linux; `no_chrome_hint` chỉ xóa env/setting mà không mock `_windows_candidates` khiến test không đi đến bước dò Playwright trên Windows; client urllib trong test dùng keep-alive dễ bị Windows hủy socket khi uvicorn đóng kết nối trước.
- Quy tắc: Cấu hình test trình duyệt phải tự thích ứng nền tảng (`sys.platform == "win32"` dò Chrome Windows chuẩn trước); request HTTP trong fake Dola test dùng `Connection: close` và retry backoff ngắn khi gặp lỗi kết nối hệ thống; fixture dọn gợi ý Chrome phải dọn cả ứng viên Windows.
- Kiểm: `python -m pytest tests/test_browser_unit.py -q`; `tests/test_worker_fake_dola.py`.
