"""Chạy trong tiến trình con dưới xvfb-run (tests/test_browser_hidden_xvfb.py): mở Chrome ở chế độ cửa sổ ẩn
thật (SEEDANCE_HEADLESS=0), gọi show_window/hide_window và in vị trí cửa sổ đọc lại qua CDP.

In ra từng dòng `KEY=VALUE` để test đối chiếu; thoát mã 0 khi mọi bước chạy không ném."""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
import browser  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def _bounds(context, page) -> dict:
    session = context.new_cdp_session(page)
    try:
        return session.send("Browser.getWindowForTarget")["bounds"]
    finally:
        session.detach()


def main() -> int:
    print(f"HEADLESS={config.HEADLESS}")
    profile = tempfile.mkdtemp(prefix="hidden-probe-")
    with sync_playwright() as p:
        with browser.browser_session(p, profile, headless=True) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_content("<h1>probe</h1>")
            b0 = _bounds(context, page)
            print(f"INITIAL={b0.get('left')},{b0.get('top')}")
            shown = browser.show_window(context, page)
            b1 = _bounds(context, page)
            print(f"SHOWN={shown}")
            print(f"AFTER_SHOW={b1.get('left')},{b1.get('top')}")
            hidden = browser.hide_window(context, page)
            b2 = _bounds(context, page)
            print(f"HIDDEN={hidden}")
            print(f"AFTER_HIDE={b2.get('left')},{b2.get('top')}")
    print("DONE=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
