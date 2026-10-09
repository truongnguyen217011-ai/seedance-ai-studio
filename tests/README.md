# Kiểm thử Seedance AI Studio

## Cài đặt

```bash
pip install -r requirements.txt        # thư viện chạy app
pip install -r requirements-dev.txt    # pytest>=8, pytest-timeout>=2.3, httpx (chỉ để chạy test)
python -m playwright install chromium  # hoặc đặt SEEDANCE_CHROME_PATH trỏ tới Chromium/Chrome có sẵn
```

`pytest.ini` ở thư mục gốc khai báo marker `integration`, `timeout` và đặt timeout mặc định 180 s/test
(có hiệu lực khi đã cài `pytest-timeout`).

## Chạy

```bash
# toàn bộ (gồm test tích hợp chạy Chromium thật + fake Dola, vài phút)
python -m pytest tests -q

# nhanh: bỏ test tích hợp
python -m pytest tests -q -m "not integration"

# chỉ test tích hợp
python -m pytest tests -q -m integration
```

Chạy từ thư mục gốc dự án. Thiếu `pytest-timeout` vẫn chạy được (các helper tự có deadline) nhưng
test treo sẽ không bị cưỡng bức dừng.

## Các file

| File | Nội dung |
| --- | --- |
| `conftest.py` | Đặt env (`SEEDANCE_DATA_DIR`, `SEEDANCE_DB_PATH`, `SEEDANCE_CHROME_PATH`, `SEEDANCE_DOLA_URL`) **trước** khi import module dự án; fixture `env_tmp`, `fake_dola`, `db`, `worker_runner` |
| `fake_dola.py` | Server giả lập Dola (FastAPI/uvicorn trong thread). Chạy tay: `python tests/fake_dola.py` |
| `_helpers.py` | Mọi phụ thuộc vào tên API backend (pool, slots, worker) gom ở đây |
| `test_fake_dola_selfcheck.py` | Kiểm chứng fake Dola bằng Playwright thật |
| `test_parser.py`, `test_twofa.py` | Hành vi parser dòng tài khoản và TOTP |
| `test_database.py` | Migration CSDL cũ (`fixtures/old_database.py`) → mới, reset job mồ côi |
| `test_account_pool.py` | Chọn nick, khóa nick, tóm tắt lý do |
| `test_worker_fake_dola.py` | Q1, Q2/Q3, Q4, Q5, Q7, Q8, T5, K4 và tự chạy lại lỗi kỹ thuật (mode=crash) với worker thật (`-m integration`) |
| `test_bai_hoc.py` | Tự động hóa cột "Kiểm" của `docs/BAI_HOC.md` (quét mã nguồn) |

Biến môi trường tùy chọn: `SEEDANCE_CHROME_PATH` (mặc định `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`),
`SEEDANCE_TEST_KEEP=1` (giữ thư mục dữ liệu tạm để xem log/ảnh), `SEEDANCE_TEST_Q8_JOBS` (số job test Q8, mặc định 20).
