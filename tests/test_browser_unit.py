"""
Test đơn vị cho browser.py: BH-28 (so khớp profile đúng token) và BH-29 (find_chrome gọi được từ luồng
event loop, không cache kết quả dò lỗi, app.py/worker.py không dùng sync_playwright).
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import re
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

browser = pytest.importorskip("browser", reason="browser.py chưa có")


# ---------------------------------------------------------------- BH-28
@pytest.mark.parametrize("cmdline, profile, expected", [
    (["chrome", "--user-data-dir=/p/profiles/acc_10"], "/p/profiles/acc_1", False),
    (["chrome", "--user-data-dir=/p/profiles/acc_1"], "/p/profiles/acc_1", True),
    (["chrome", "--user-data-dir=/p/profiles/acc_1"], "/p/profiles/acc_10", False),
    (["chrome", "--user-data-dir=/p/profiles/acc_19", "--headless"], "/p/profiles/acc_1", False),
    (["chrome", '--user-data-dir="/p/profiles/acc_1"'], "/p/profiles/acc_1", True),
    (["chrome", '--user-data-dir="/p/profiles/acc_10"'], "/p/profiles/acc_1", False),
    (["chrome", "--user-data-dir", "/p/profiles/acc_1/"], "/p/profiles/acc_1", True),
    (["chrome", "--user-data-dir=/p/profiles/acc_1/Default"], "/p/profiles/acc_1", False),
    (["chrome", "--no-first-run"], "/p/profiles/acc_1", False),
    ([], "/p/profiles/acc_1", False),
    (["chrome", "--user-data-dir=/p/profiles/acc_1"], "", False),
    # psutil trả cả dòng lệnh trong một phần tử (Windows), có dấu nháy và khoảng trắng
    (['chrome.exe --x --user-data-dir="C:\\Studio\\profiles\\acc_1" --y'], "C:\\Studio\\profiles\\acc_1", True),
    (['chrome.exe --x --user-data-dir="C:\\Studio\\profiles\\acc_10" --y'], "C:\\Studio\\profiles\\acc_1", False),
])
def test_bh28_cmdline_uses_profile_exact_match(cmdline, profile, expected):
    assert browser._cmdline_uses_profile(cmdline, profile) is expected


def test_bh28_no_substring_match_in_kill_orphan_chrome():
    src = (ROOT / "browser.py").read_text(encoding="utf-8")
    assert "norm_p in" not in src, "BH-28: kill_orphan_chrome không được so chuỗi con đường dẫn profile"
    assert "_cmdline_uses_profile(cmdline" in src


# ---------------------------------------------------------------- BH-29
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def no_chrome_hint(db, monkeypatch):
    """Xóa mọi gợi ý Chrome (env + setting) để find_chrome phải đi tới bước dò Chromium của Playwright.
    Sau test, khôi phục env và dò lại để các test tích hợp vẫn thấy Chromium."""
    import config
    original = config.CHROME_PATH_ENV
    monkeypatch.setattr(config, "CHROME_PATH_ENV", "")
    db.exec("DELETE FROM settings WHERE key = 'chrome_path'")
    cap = _Capture()
    logging.getLogger("studio").addHandler(cap)
    try:
        yield cap
    finally:
        logging.getLogger("studio").removeHandler(cap)
        config.CHROME_PATH_ENV = original
        browser.find_chrome(refresh=True)


def test_bh29_find_chrome_inside_event_loop_same_as_thread(no_chrome_hint):
    cap = no_chrome_hint
    results = {}

    def in_thread():
        results["thread"] = browser.find_chrome(refresh=True)

    t = threading.Thread(target=in_thread)
    t.start()
    t.join(30)
    assert not t.is_alive()

    async def main():
        # Gọi thẳng trên luồng event loop (như startup_event cũ): không được văng/nuốt lỗi Sync API
        return browser.find_chrome(refresh=True)

    results["loop"] = asyncio.run(main())

    assert results["loop"] == results["thread"], results
    bad = [m for m in cap.messages if "Sync API inside" in m or "asyncio loop" in m]
    assert not bad, f"BH-29: Playwright Sync API bị gọi trên luồng event loop: {bad}"
    assert not any("Không hỏi được Playwright" in m for m in cap.messages), cap.messages
    # Bước dò chạy sạch (playwright import được) → kết quả được cache, kể cả khi là None
    assert browser._chrome_cache["checked"] is True


def test_bh29_probe_error_is_not_cached(no_chrome_hint, monkeypatch):
    calls = {"n": 0}

    def failing_probe():
        calls["n"] += 1
        return None, False  # dò lỗi vì môi trường

    monkeypatch.setattr(browser, "_probe_playwright_chromium", failing_probe)
    assert browser.find_chrome(refresh=True) is None
    assert browser._chrome_cache["checked"] is False, "BH-29: kết quả dò lỗi không được cache"
    assert browser.find_chrome() is None  # dò lại
    assert calls["n"] == 2

    monkeypatch.setattr(browser, "_probe_playwright_chromium", lambda: ("/fake/chromium", True))
    assert browser.find_chrome() == "/fake/chromium"  # không refresh vẫn dò lại vì lần trước chưa cache
    assert browser._chrome_cache["checked"] is True
    assert browser.find_chrome() == "/fake/chromium"


def test_bh29_no_sync_playwright_in_app_or_worker():
    hits = []
    for name in ("app.py", "worker.py"):
        for i, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"sync_playwright", line):
                hits.append(f"{name}:{i}: {line.strip()}")
    assert not hits, "BH-29: app.py/worker.py không được dùng Playwright Sync API trên luồng event loop:\n" + "\n".join(hits)


def test_bh29_startup_calls_find_chrome_off_loop():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "await asyncio.to_thread(browser.find_chrome)" in src
    assert re.search(r"^\s*chrome = browser\.find_chrome\(\)", src, re.MULTILINE) is None, \
        "coroutine trong app.py không được gọi browser.find_chrome() trực tiếp"


# ---------------------------------------------------------------- G-2
def test_g2_browser_session_reports_slot_wait(monkeypatch):
    """Hết slot: on_wait được gọi đúng 1 lần với 'Đang chờ chỗ mở Chrome (x/N đang dùng)'; hết slot_timeout → RuntimeError."""
    slots = browser.SLOTS
    original = slots.capacity()
    slots.resize(1)
    assert slots.acquire(timeout=0)  # chiếm chỗ duy nhất
    messages = []
    monkeypatch.setattr(browser, "launch_context", lambda *a, **k: (_ for _ in ()).throw(AssertionError("không được mở Chrome")))
    try:
        with pytest.raises(RuntimeError, match="Hết chỗ mở Chrome"):
            with browser.browser_session(None, "/tmp/acc_x", slot_timeout=0.3, on_wait=messages.append):
                pass
        assert messages == ["Đang chờ chỗ mở Chrome (1/1 đang dùng)"], messages
        assert slots.active_count() == 1, "slot bị trả nhầm khi chưa acquire được"
    finally:
        slots.release()
        slots.resize(original)
    src = open(ROOT / "dola_service.py", encoding="utf-8").read()
    assert "slot_timeout=JOB_SLOT_TIMEOUT_SECONDS" in src and "on_wait=_on_wait_slot" in src
    assert "JOB_SLOT_TIMEOUT_SECONDS = 120" in src
