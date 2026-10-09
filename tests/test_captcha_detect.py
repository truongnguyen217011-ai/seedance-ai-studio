"""BH-36: bộ phát hiện captcha không được báo nhầm trên trang Dola bình thường."""
import os
import pytest
from playwright.sync_api import sync_playwright

import dola_service

CHROME = os.environ.get("SEEDANCE_CHROME_PATH")

CASES = [
    # (html, kỳ vọng, mô tả)
    ("<h1>How can I assist you today?</h1><svg class='icon-error' style='display:none'></svg>"
     "<div class='secsdk-sdk-loader' style='width:0;height:0'></div>", False, "icon lỗi ẩn + loader secsdk 0px"),
    ("<p>Your account is verified. Scheduled Tasks</p>", False, "chữ verified không phải captcha"),
    ("<div class='captcha_verify_container' style='width:300px;height:200px'>Drag the slider</div>", True, "khung captcha hiện"),
    ("<p>Verify to continue</p>", True, "câu chữ captcha"),
    ("<div class='captcha-box' style='display:none'>Verify</div>", False, "khung captcha ẩn"),
]


@pytest.mark.parametrize("html,expected,desc", CASES, ids=[c[2] for c in CASES])
def test_bh36_detect_captcha(html, expected, desc):
    with sync_playwright() as p:
        kw = {"headless": True, "args": ["--no-sandbox"]}
        if CHROME:
            kw["executable_path"] = CHROME
        browser = p.chromium.launch(**kw)
        page = browser.new_page()
        page.set_content(f"<html><body>{html}</body></html>")
        assert dola_service._detect_captcha(page) is expected, desc
        browser.close()


def test_bh36_no_loose_verify_keyword_in_source():
    src = open(dola_service.__file__, encoding="utf-8").read()
    assert '["verify", "xác minh", "puzzle", "kéo mảnh"]' not in src
    assert "ERROR_ICON_SELECTOR" not in src
