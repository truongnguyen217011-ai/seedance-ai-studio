# Kiến trúc Seedance AI Studio (chuẩn từ giai đoạn 1)

Tài liệu này là luật chung cho mọi thay đổi. Agent nào sửa mã đều phải đọc trước và không được phá các quy tắc ở mục 1. Hợp đồng kiểm nghiệm (các mã C1..C6, Q1..Q9, D1..D6, A1.., K1.., T1.., P1.., G1..) là thước đo đầu ra.

## 1. Quy tắc bất biến

0. **Đọc `docs/BAI_HOC.md` trước khi sửa, ghi bài học sau khi sửa.** Lỗi đã ghi trong sổ mà tái phạm là lỗi nặng nhất.
1. **Một tiến trình, một worker, nhiều luồng job.** Toàn bộ Chrome/Chromium đều được mở qua `browser.py` và phải giữ một *slot* trong `BrowserSlots`. Không module nào tự gọi `launch_persistent_context` trực tiếp.
2. **Mỗi tài khoản tại một thời điểm chỉ có một Chrome.** Mọi thao tác cần profile của nick (job, auto login, check credit, chẩn đoán, mở Chrome tay) phải `AccountPool.acquire(account_id)` trước và `release` sau. Không acquire được thì chờ hoặc báo "nick đang bận", tuyệt đối không giết Chrome của người khác.
3. **Trạng thái job chỉ có 5 giá trị** trong `constants.JobStatus`. Không viết chuỗi trạng thái tay ở bất kỳ đâu (backend lẫn frontend dùng cùng tên).
4. **Không nuốt lỗi.** Không còn `except Exception: pass`. Tối thiểu là `log.debug(...)` qua `logger.py`; lỗi làm job thất bại phải ghi `WARNING`/`ERROR` kèm `job_id`/`account_id` và gọi `save_failure_artifacts` nếu có `page`.
5. **Không ghi giá trị mặc định giả.** Không đọc được credit thì `credits = NULL` + `last_error`, không ghi 4. Không đọc được token thì không đánh dấu sẵn sàng.
6. **Cấu hình qua `config.py`.** Không hard-code đường dẫn Chrome, URL Dola, thư mục dữ liệu ở nơi khác.
7. **CSDL mở qua `database.get_connection()`** (timeout 30s, WAL). Không `sqlite3.connect` ở nơi khác.
8. **Thay đổi schema chỉ bằng migration trong `database.init_db()`**, có kiểm tra cột tồn tại, chạy được trên CSDL cũ.
9. **Chuỗi hiển thị cho người dùng là tiếng Việt có dấu, nói rõ việc gì, nick nào, vì sao.**

## 2. Module

| Module | Vai trò | Ghi chú |
| --- | --- | --- |
| `config.py` | BASE_DIR, DATA_DIR, PROFILES_DIR, OUTPUTS_DIR, LOGS_DIR, DOLA_BASE_URL, DOLA_DOMAIN, CHROME_PATH (env), VERSION | Đã viết sẵn |
| `constants.py` | `JobStatus`, `AccountFlag`, chuỗi lý do chuẩn, bảng map trạng thái cũ → mới | Đã viết sẵn |
| `logger.py` | `get_logger(module)`; `log_event(message, level, module, job_id=None, account_id=None)` ghi file `logs/studio_YYYY-MM-DD.log` **và** bảng `system_logs`; `save_failure_artifacts(page, tag, job_id=None, account_id=None)` lưu `logs/screenshots/{tag}_{id}_{YYYYmmdd_HHMMSS}.png` + `.html`, trả về đường dẫn | Dùng `logging` chuẩn, handler theo ngày, không bao giờ raise |
| `database.py` | `get_connection()`, `init_db()` + migration, `reset_orphans_on_startup()` | Cột mới xem mục 3 |
| `browser.py` | `find_chrome()`; `BrowserSlots` (semaphore có thể đổi kích thước theo setting `max_concurrent_jobs`); `launch_context(pw, profile_dir, proxy=None, headless=True)` trả về context, tự giữ/trả slot qua context manager `browser_session(...)`; `active_count()`; `kill_orphan_chrome(profile_dir)` chỉ được gọi khi profile không có job nào đang giữ; so khớp tiến trình bằng `_cmdline_uses_profile` (token `--user-data-dir`, so bằng sau normcase/normpath, BH-28) | Chrome tìm theo: env `SEEDANCE_CHROME_PATH` → setting `chrome_path` → Program Files, Program Files (x86), LOCALAPPDATA → Chromium của Playwright nếu tồn tại → None |
| `account_pool.py` | `AccountPool.acquire(account_id, job_id)` / `release(account_id)` / `is_busy`; `select_account_for_job(job, excluded=None)` trả `(account_dict | None, summary_str)`; summary dạng `"3 nick hết credit, 2 nick chưa đăng nhập Dola, 1 nick đang bận, 1 nick cần kéo captcha"` | Bộ nhớ trong + cột `busy_job_id` để UI nhìn thấy |
| `worker.py` | Vòng lặp 2 giây: tính slot trống từ `BrowserSlots`, lấy job `CHO` theo `(batch_id, seq, id)`, chọn nick qua pool, chạy job trên `JOB_EXECUTOR` (ThreadPoolExecutor 32 thread riêng, BH-32), `finally` trả nick và slot. Job không có nick: cập nhật `status_message` **chỉ khi nội dung đổi**, không mở Chrome; kết quả "không có nick" và `has_dola_session` được dùng lại trong một vòng quét (`TickCache`). Không có Chrome (`find_chrome()` None): không điều phối, ghi lý do lên job Chờ, WARNING 1 lần/60 s. Mọi job đã điều phối trong vòng quét đều được khởi chạy hoặc rollback về Chờ (`_rollback_dispatched`, BH-27) | Lúc khởi động gọi `reset_orphans_on_startup()` |
| `dola_service.py` | Toàn bộ thao tác trên Dola: auto login, check credit, chạy job, chẩn đoán | Dùng `browser.py`, `constants`, `logger`; không giết Chrome |
| `diagnostics.py` | `diagnose_account(account_id)` trả danh sách bước; `build_bundle()` trả đường dẫn zip | Zip gồm log 24h, screenshots, settings, danh sách nick đã che mật |
| `app.py` | REST API, mount static | Không chứa logic nghiệp vụ |

## 3. Cơ sở dữ liệu (cột thêm ở giai đoạn 1)

`accounts`: `busy_job_id INTEGER NULL`, `needs_manual TEXT NULL` (`captcha` | `login` | `proxy`), `last_error TEXT`, `last_ip TEXT`, `chrome_ok INTEGER NULL`, `consecutive_errors INTEGER DEFAULT 0` (số lần lỗi kết nối Dola liên tiếp, xem mục 4).

`jobs`: `batch_name TEXT`, `seq INTEGER`, `prompt_final TEXT`, `attempts INTEGER DEFAULT 0`, `started_at TIMESTAMP`, `finished_at TIMESTAMP`. `status_message` giữ vai trò "lý do hiện tại". `batch_id` đã có, giữ.

`system_logs`: thêm `job_id INTEGER`, `account_id INTEGER`.

`settings`: `max_concurrent_jobs` (số Chrome tối đa, mặc định 6), `chrome_path`, `dola_base_url`.

Migration trạng thái cũ chạy một lần trong `init_db()`: `Đang chờ`→`Chờ`, `Đang xử lý`→`Đang chạy`, `Lỗi`→`Thất bại`, `Chờ đăng nhập Dola`→`Chờ`, `Chờ xử lý`/`Chờ render` chỉ là status_message.

## 4. Máy trạng thái job

```
Chờ ──(worker có nick + slot)──► Đang chạy ──► Hoàn thành
                                      │──► Thất bại   ──(Chạy lại)──► Chờ
                                      │──► Tạm dừng   ──(Tiếp tục)──► Chờ
Khởi động lại app: Đang chạy ──► Chờ ("App khởi động lại, chạy lại từ đầu")
```

- Captcha → `Tạm dừng`, nick `needs_manual='captcha'`, nick không được chọn cho job khác cho đến khi người dùng bấm *Tiếp tục* (xóa cờ) hoặc *Chẩn đoán* thấy hết captcha.
- Hết credit → nick nghỉ đến 00:05, job về `Chờ` với lý do, worker chọn nick khác (không mở lại Chrome trên nick đã nghỉ).
- **Lỗi kỹ thuật tự chạy lại** (BH-04, BH-24; mã: `dola_service._fail_technical`, `_apply_technical_failure`). Lỗi kỹ thuật gồm `BROWSER_ERROR` (Chrome không mở được, goto thất bại, proxy chết, ngoại lệ Playwright), `RENDER_TIMEOUT`, `DOWNLOAD_FAILED`. **Không** gồm `NO_NEW_CONV`, `POLICY_REFUSED`, "không thấy ô nhập prompt" (lỗi nội dung/trang → `Thất bại` ngay).
  - `attempts` tăng **mỗi lần worker nhặt job** (trong `_dispatch_one`), nên khi job lỗi thì `attempts` = số lần đã thử.
  - `attempts <= config.MAX_AUTO_RETRIES` (mặc định 2) → job về `Chờ`, `status_message = "<lý do> · tự chạy lại lần {attempts}/{MAX_AUTO_RETRIES} [ảnh: ...]"`. Worker nhặt lại ở vòng sau và chọn nick **theo pool** (ưu tiên nick đã gán nếu còn đủ điều kiện, không thì nick khác).
  - `attempts > MAX_AUTO_RETRIES` → `Thất bại`, `status_message = Reason.MAX_ATTEMPTS ("Đã thử {n} lần vẫn lỗi...") + ". " + lý do gốc + [ảnh: ...]`. Không có lần thử thứ 4; người dùng bấm *Chạy lại* nếu muốn.
  - Nick (cột `consecutive_errors`): lỗi xảy ra **sau khi đã vào được trang Dola** (`page_reached`) → lỗi thuộc phiên/proxy của nick → `status = rate_limited` ngay (worker mở lại sau 30 phút, `_recover_accounts`), job về Chờ sẽ được gán nick khác nếu có. Lỗi **trước khi vào được trang** (không mở được Chrome, `goto` thất bại) → chỉ `consecutive_errors += 1`, nick vẫn `ready`; quá `MAX_AUTO_RETRIES` lần liên tiếp (lần thứ 3) mới `rate_limited`. `consecutive_errors` về 0 khi nick vào được trang có phiên (`_mark_account_connected`). Ngưỡng cố ý bằng `MAX_AUTO_RETRIES + 1` (không phải 2) để với **một nick duy nhất** job vẫn dùng hết 3 lượt rồi `Thất bại` với lý do rõ, thay vì kẹt ở `Chờ` 30 phút vì nick bị nghỉ sau lần lỗi thứ 2.
  - Hết credit, mất phiên Dola (`needs_manual=login`): job về `Chờ` và `attempts -= 1` (lỗi thuộc nick, không tính lượt của job).

## 5. API (hợp đồng với frontend)

| Method | Đường dẫn | Trả về |
| --- | --- | --- |
| GET | `/api/version` | `{version, chrome_path, active_browsers, max_browsers}` |
| GET | `/api/health` | `{ok, db_ok, chrome_found, chrome_path, active_browsers, max_browsers, worker_alive, version}` |
| GET | `/api/jobs?limit=500` | `{jobs:[{id, batch_id, batch_name, seq, status, status_message, progress, attempts, account_id, account_name, account_proxy, prompt, prompt_final, local_video_path, created_at, updated_at}]}` |
| POST | `/api/jobs/{id}/retry` | job `Thất bại`/`Tạm dừng` → `Chờ`; `{success, status}` |
| POST | `/api/jobs/{id}/resume` | job `Tạm dừng` → `Chờ`, xóa `needs_manual` của nick gán; `{success}` |
| POST | `/api/jobs/{id}/pause` | job `Chờ` → `Tạm dừng` (lý do: người dùng); `{success}` |
| GET | `/api/logs?limit=500&job_id=&account_id=&level=` | `{logs:[{id, level, module, message, job_id, account_id, created_at}]}` |
| POST | `/api/accounts/{id}/diagnose` | `{success, steps:[{key, name, ok (true/false/null), detail}], summary}` với key ∈ `proxy, chrome, fb_cookie, dola_session, credits` |
| GET | `/api/diagnostics/bundle` | file zip tải về |
| GET | `/api/accounts` | như cũ **cộng** `busy_job_id, needs_manual, last_error, last_ip, last_check`; **bỏ** `fb_pass`, `fb_2fa`, `cookies` dạng rõ (chỉ `has_pass`, `has_2fa`, `has_cookies`) |
| DELETE | `/api/jobs/{id}` | từ chối (`{success:false, message}`) khi job `Đang chạy` hoặc nằm trong `worker.running_job_ids()`; giao diện hiện toast từ `message` |
| POST | `/api/accounts/login_muse`, `/api/accounts/check_muse_token` | luôn `{success:false, message:"Muse AI không còn được hỗ trợ"}` (không mở Chrome ngoài slot/pool; `muse_service.py` gỡ ở giai đoạn 5) |

Thao tác mở Chrome theo yêu cầu tay (auto login, mở Chrome đăng nhập, check credit, chẩn đoán) chạy trên `worker.JOB_EXECUTOR` (BH-32), không dùng executor mặc định của asyncio.

**Đường dẫn tĩnh** (mount trong `app.py`). Chỉ ba đường dẫn này; **không** mount cả `/logs` vì file `studio_*.log` chứa tên nick, lỗi, proxy (BH-31):

| Đường dẫn web | Thư mục | Dùng cho |
| --- | --- | --- |
| `/static` | `config.STATIC_DIR` | `index.html`, `js/app.js` |
| `/outputs` | `config.OUTPUTS_DIR` | video đã tải về |
| `/logs/screenshots` | `config.SCREENSHOTS_DIR` | ảnh/HTML chụp lúc lỗi; app.js dựng link từ `[ảnh: <tên>]` trong `status_message` |

## 6. Fake Dola cho kiểm thử (`tests/fake_dola.py`)

Server HTTP cục bộ (FastAPI, cổng ngẫu nhiên) mô phỏng đủ để `dola_service` chạy hết một job:

- `GET /chat/` và `GET /chat/{conv_id}`: trang có `div.ProseMirror[contenteditable=true]`; JS bắt phím Enter → `POST /__send {text}` → server tạo `conv_id` mới, trang `history.pushState` sang `/chat/{conv_id}`. Thân trang có dòng `You have {credits} video credits left`.
- `POST /im/chain/recent_conv` → `{downlink_body:{pull_recent_conv_chain_downlink_body:{cells:[{conversation:{conversation_id}}]}}}`.
- `POST /im/chain/single` → trước `render_seconds`: `{data:{status:"generating"}}`; sau đó JSON chứa `http://127.0.0.1:PORT/video/tos/{conv_id}.mp4`. File mp4 giả lớn hơn 50 KB.
- Chế độ qua `POST /__control {mode, render_seconds, credits}`: `normal`, `captcha` (trang có "Verify to continue" + `div.captcha`), `daily_limit` (trang có "reached the daily limit for video generation"), `slow`, `crash` (đóng kết nối).
- Cookie phiên: `Set-Cookie: sessionid=...` cho host `127.0.0.1`. `has_dola_session` so khớp `config.DOLA_DOMAIN`.
- **Dola giả tách phiên theo cookie `sessionid`, credit theo phiên**: mỗi `sessionid` có bộ đếm credit, danh sách conversation và nhật ký request riêng (`STATE.sessions[sid]`), nên hai nick chạy song song không nhìn thấy conversation của nhau (điều kiện để T5/Q1 có nghĩa). `POST /__control {credits}` đặt lại credit cho mọi phiên đang có và phiên mới.
- `mode=crash` đóng socket TCP **trước khi gửi header** (Chromium thấy `net::ERR_EMPTY_RESPONSE` ngay, `page.goto` ném lỗi tức thì). Không dùng cách "gửi header rồi cắt thân": Chromium commit trang dở và treo đủ 60 s timeout của `goto` (BH-25).
- Test chạy với `SEEDANCE_DOLA_URL=http://127.0.0.1:PORT`, `SEEDANCE_CHROME_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, `SEEDANCE_DATA_DIR=<tmp>`.

## 7. Kiểm thử bắt buộc trước mỗi lần đẩy mã

```
python -m pytest tests -q
```

- `tests/test_parser.py`, `tests/test_twofa.py`: giữ hành vi parser và TOTP.
- `tests/test_database.py`: migration trên CSDL cũ, reset mồ côi.
- `tests/test_account_pool.py`: chọn nick, khóa nick, tóm tắt lý do.
- `tests/test_worker_fake_dola.py`: Q1 (không quá N Chrome), Q2/Q3 (một nick một job), Q4 (captcha → Tạm dừng, không lặp), Q5 (reset mồ côi), Q6/Q7 (lý do rõ), Q8 (nhiều job không "database is locked": **tự động chạy 20 job** để vừa 180 s/test; **50 job là test tay**: `SEEDANCE_TEST_Q8_JOBS=50 python -m pytest tests -q -k q8`), T5 (lấy đúng conv mới), K4 (hết credit → nick nghỉ, job về Chờ), tự chạy lại lỗi kỹ thuật (`mode=crash`: 3 lần rồi Thất bại, không có lần 4).
- `tests/test_bai_hoc.py`: tự động hóa cột "Kiểm" của sổ bài học; file sẽ gỡ ở giai đoạn 5 nằm trong một danh sách `LEGACY_PHASE5` duy nhất, kèm test xfail(strict) nhắc xóa danh sách khi gỡ xong.
- Thư viện test: `pip install -r requirements-dev.txt` (pytest, pytest-timeout, httpx). `pytest.ini` đặt timeout mặc định 180 s.
- Trình duyệt cho test: Chromium **1194** (bản Playwright tải sẵn tại `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`) chạy qua `executable_path` với **Playwright 1.63** (bản Playwright này mặc định đòi Chromium khác số, nên `browser.find_chrome` phải nhận đường dẫn từ `SEEDANCE_CHROME_PATH`, không dựa vào `p.chromium.launch()` mặc định). Đổi bằng env `SEEDANCE_CHROME_PATH`.
