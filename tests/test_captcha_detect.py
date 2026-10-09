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
    # BH-39: lớp phủ thật của Dola: div có id, KHÔNG có class, fixed phủ cả trang, iframe bên trong
    ("<div id='captcha_container' style='display: block; z-index: 111111; position: fixed; width: 100%; height: 100%;"
     " background-color: rgba(0,0,0,0.514); inset: 0px;'><iframe src='about:blank'></iframe></div>",
     True, "#captcha_container display:block"),
    ("<div id='captcha_container' style='display: none; position: fixed; width: 100%; height: 100%; inset: 0px;'>"
     "<iframe src='about:blank'></iframe></div>", False, "#captcha_container display:none"),
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


def test_bh38_evidence_names_the_trigger():
    with sync_playwright() as p:
        kw = {"headless": True, "args": ["--no-sandbox"]}
        if CHROME:
            kw["executable_path"] = CHROME
        browser = p.chromium.launch(**kw)
        page = browser.new_page()
        page.set_content("<div id='cap' class='captcha_verify_container' style='width:300px;height:200px'>x</div>")
        ev = dola_service._captcha_evidence(page)
        assert "captcha_verify_container" in ev and "300x200" in ev
        page.set_content("<p>Verify to continue</p>")
        assert 'chữ "verify to continue"' == dola_service._captcha_evidence(page)
        page.set_content("<p>ok</p>")
        assert dola_service._captcha_evidence(page) == ""
        browser.close()


def test_bh39_captcha_container_evidence_and_gone():
    with sync_playwright() as p:
        kw = {"headless": True, "args": ["--no-sandbox"]}
        if CHROME:
            kw["executable_path"] = CHROME
        browser = p.chromium.launch(**kw)
        page = browser.new_page()
        page.set_content("<div id='captcha_container' style='display:block;position:fixed;inset:0;width:100%;height:100%'>"
                         "<iframe src='about:blank'></iframe></div>")
        ev = dola_service._captcha_evidence(page)
        assert "#captcha_container" in ev, ev
        assert dola_service._captcha_gone(page) is False
        page.evaluate("document.getElementById('captcha_container').remove()")
        assert dola_service._captcha_gone(page) is True
        page.close()
        assert dola_service._captcha_gone(page) is False, "trang đã đóng không được coi là 'hết captcha'"
        browser.close()
