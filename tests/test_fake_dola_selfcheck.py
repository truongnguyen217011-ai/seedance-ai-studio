"""
Kiểm chứng độc lập fake Dola bằng Playwright thật (không phụ thuộc backend mới).
Mô phỏng đúng các bước dola_service làm: mở /chat/, đọc credit, gõ prompt + Enter, URL đổi sang
/chat/{id}, recent_conv trả id, single trả generating rồi URL mp4, tải mp4 > 50 KB bằng urllib + Referer.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

import pytest

RECENT_CONV_JS = """async () => {
  const resp = await fetch('/im/chain/recent_conv', {method: 'POST', credentials: 'include',
    headers: {'content-type': 'application/json; encoding=utf-8'},
    body: JSON.stringify({cmd: 3200, uplink_body: {pull_recent_conv_chain_uplink_body: {limit: 10}}})});
  const data = await resp.json();
  const cells = data?.downlink_body?.pull_recent_conv_chain_downlink_body?.cells || [];
  return cells.map(c => c?.conversation?.conversation_id || c?.id).filter(Boolean);
}"""

SINGLE_JS = """async (convId) => {
  const resp = await fetch('/im/chain/single', {method: 'POST', credentials: 'include',
    headers: {'content-type': 'application/json; encoding=utf-8'},
    body: JSON.stringify({cmd: 3100, uplink_body: {pull_singe_chain_uplink_body: {conversation_id: convId}}})});
  if (!resp.ok) return null;
  return await resp.json();
}"""


@pytest.fixture(scope="module")
def browser_ctx():
    from playwright.sync_api import sync_playwright
    exe = os.environ.get("SEEDANCE_CHROME_PATH")
    if not exe or not os.path.exists(exe):
        pytest.skip(f"Không có Chromium tại SEEDANCE_CHROME_PATH={exe!r}")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe, headless=True,
                                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        yield browser
        browser.close()


@pytest.fixture
def page(browser_ctx, fake_dola):
    ctx = browser_ctx.new_context()
    pg = ctx.new_page()
    yield pg
    ctx.close()


def _download(url: str, referer: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    with urllib.request.urlopen(req, timeout=30) as resp:
        assert resp.headers.get("content-type", "").startswith("video/mp4")
        return resp.read()


def test_full_job_flow_with_real_chromium(fake_dola, page):
    fake_dola.control(render_seconds=2, credits=4)
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")

    body = page.inner_text("body")
    assert re.search(r"have\s+4\s+video\s+credits?\s+left", body, re.I)
    assert "daily limit" not in body.lower()
    assert "verify to continue" not in body.lower()

    # Set-Cookie sessionid cho host 127.0.0.1
    cookies = page.context.cookies()
    sess = [c for c in cookies if c["name"] == "sessionid"]
    assert sess and sess[0]["domain"] == "127.0.0.1" and sess[0]["value"].startswith("fake-")

    # chưa có conversation nào
    assert page.evaluate(RECENT_CONV_JS) == []

    box = page.locator("div.ProseMirror, textarea, [contenteditable='true']").first
    assert box.is_visible()
    box.click()
    prompt = "Tạo video Seedance 2.5 dài 30 giây: con mèo bay"
    box.fill(prompt)
    page.keyboard.press("Enter")

    page.wait_for_url(re.compile(r"/chat/\d+$"), timeout=10000)
    conv_id = re.search(r"/chat/(\d+)", page.url).group(1)

    ids = page.evaluate(RECENT_CONV_JS)
    assert ids == [conv_id]

    res = page.evaluate(SINGLE_JS, conv_id)
    assert res["data"]["status"] == "generating"
    assert ".mp4" not in json.dumps(res)

    time.sleep(2.3)
    res = page.evaluate(SINGLE_JS, conv_id)
    s = json.dumps(res.get("data") or res, ensure_ascii=False)
    urls = [u for u in re.findall(r'https?://[^\s"\'<>]+', s) if ".mp4" in u or "/video/tos/" in u]
    assert urls, s
    assert urls[0] == f"{fake_dola.base_url}/video/tos/{conv_id}.mp4"

    data = _download(urls[0], referer=fake_dola.base_url + "/")
    assert len(data) > 50000
    assert data.startswith(f"FAKEMP4;conv={conv_id};".encode())

    # credit sau khi gửi giảm 1 (DOM được JS cập nhật)
    assert re.search(r"have\s+3\s+video\s+credits?\s+left", page.inner_text("body"), re.I)

    st = fake_dola.get_state()
    assert st["sent_prompts"] == [prompt]
    assert conv_id in st["conversations"]
    assert st["conversations"][conv_id]["prompt"] == prompt
    assert st["chat_get_count"] == 1
    assert "GET /chat/" in st["request_log"]
    assert st["downloads"][-1]["conv_id"] == conv_id
    assert st["downloads"][-1]["referer"] == fake_dola.base_url + "/"


def test_captcha_mode(fake_dola, page):
    """BH-39: giống Dola thật, captcha KHÔNG nằm sẵn trong trang; chỉ chèn #captcha_container sau khi gửi prompt,
    và lần gửi đó không tạo conversation. Không đặt solve_captcha_after → lớp phủ còn mãi."""
    fake_dola.control(mode="captcha")
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")
    assert page.locator("#captcha_container").count() == 0, "captcha không được hiện trước khi gửi prompt"
    box = page.locator("div.ProseMirror").first
    box.click()
    box.fill("prompt bị chặn")
    page.keyboard.press("Enter")
    time.sleep(1)
    cont = page.locator("#captcha_container")
    assert cont.count() == 1 and cont.is_visible()
    assert cont.get_attribute("class") in (None, ""), "div thật không có class"
    assert "bdcaptcha" in page.locator("#captcha_container iframe").get_attribute("src") or \
        "captcha_frame" in page.locator("#captcha_container iframe").get_attribute("src")
    assert re.search(r"/chat/\d+", page.url) is None
    st = fake_dola.get_state()
    assert st["conversations"] == {} and st["sent_prompts"] == []
    assert st["captcha_shown_at"] is not None and st["solve_captcha_after"] is None
    # gửi lần nữa khi captcha đang hiện: vẫn không tạo conversation
    page.keyboard.press("Enter")
    time.sleep(1)
    assert fake_dola.get_state()["conversations"] == {}
    time.sleep(3)
    assert page.locator("#captcha_container").is_visible(), "không đặt solve_captcha_after thì captcha phải còn mãi"


def test_captcha_mode_solved_after_delay(fake_dola, page):
    """solve_captcha_after=3: lớp phủ tự biến mất ~3 s sau lần hiện đầu; /__send kế tiếp tạo conversation."""
    fake_dola.control(mode="captcha", solve_captcha_after=3, render_seconds=1)
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")
    box = page.locator("div.ProseMirror").first
    box.click()
    box.fill("prompt sau captcha")
    page.keyboard.press("Enter")
    time.sleep(1)
    assert page.locator("#captcha_container").is_visible()
    deadline = time.time() + 10
    while time.time() < deadline and page.locator("#captcha_container").count() > 0:
        time.sleep(0.5)
    assert page.locator("#captcha_container").count() == 0, "lớp phủ phải tự gỡ sau solve_captcha_after"
    st = fake_dola.get_state()
    assert st["mode"] == "normal" and st["captcha_solved_at"] is not None
    assert st["conversations"] == {}, "prompt gửi lúc captcha đang hiện không được tạo conversation"
    box.click()
    page.keyboard.press("Enter")
    # BH-41: Sync API chỉ cập nhật page.url khi có lệnh Playwright đang chạy; không đọc page.url sau time.sleep
    page.wait_for_url(re.compile(r"/chat/\d+"), timeout=10000)
    st = fake_dola.get_state()
    assert len(st["conversations"]) == 1 and st["sent_prompts"] == ["prompt sau captcha"]


def test_captcha_mode_auto_resend_after_solve(fake_dola, page):
    """auto_resend_after_solve: khi captcha được giải, server TỰ tạo conversation cho prompt đã gõ và trừ 1 credit;
    ô nhập trên trang vẫn còn chữ (trang không biết). Enter lần nữa sẽ tạo conversation THỨ HAI (tốn thêm credit) →
    đó là thứ dola_service phải tránh (BH-45)."""
    fake_dola.control(mode="captcha", solve_captcha_after=2, auto_resend_after_solve=True, render_seconds=1, credits=4)
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")
    box = page.locator("div.ProseMirror").first
    box.click()
    box.fill("prompt dola tự gửi")
    page.keyboard.press("Enter")
    time.sleep(1)
    assert page.locator("#captcha_container").is_visible()
    deadline = time.time() + 10
    while time.time() < deadline and page.locator("#captcha_container").count() > 0:
        time.sleep(0.5)
    assert page.locator("#captcha_container").count() == 0
    st = fake_dola.get_state()
    assert st["auto_resend_after_solve"] is True and st["mode"] == "normal"
    assert len(st["conversations"]) == 1 and st["sent_prompts"] == ["prompt dola tự gửi"]
    sess = next(s for s in st["sessions"].values() if s.get("captcha_shown"))
    assert sess["credits"] == 3 and "pending_prompt" not in sess
    assert box.inner_text().strip() == "prompt dola tự gửi", "ô nhập vẫn còn chữ như Dola thật"
    # Gửi lại mù quáng → conversation thứ hai, mất thêm credit
    box.click()
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"/chat/\d+"), timeout=10000)
    st = fake_dola.get_state()
    assert len(st["conversations"]) == 2 and len(st["sent_prompts"]) == 2
    assert next(s for s in st["sessions"].values() if s.get("captcha_shown"))["credits"] == 2


def test_daily_limit_mode(fake_dola, page):
    fake_dola.control(mode="daily_limit")
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")
    body = page.inner_text("body")
    assert "reached the daily limit for video generation" in body
    assert re.search(r"have\s+0\s+video\s+credits?\s+left", body, re.I)
    res = page.evaluate(SINGLE_JS, "123")
    assert "reached the daily limit for video generation" in json.dumps(res)


def test_credits_exhaust_to_daily_limit(fake_dola, page):
    fake_dola.control(credits=1)
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")
    box = page.locator("div.ProseMirror").first
    box.click()
    box.fill("job 1")
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"/chat/\d+$"), timeout=10000)
    first = page.url
    box.click()
    box.fill("job 2")
    page.keyboard.press("Enter")
    time.sleep(1)
    assert page.url == first
    assert "reached the daily limit for video generation" in page.inner_text("body")
    assert len(fake_dola.get_state()["conversations"]) == 1
    # tải lại trang: vẫn daily limit vì phiên này hết credit
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")
    assert "reached the daily limit for video generation" in page.inner_text("body")


def test_sessions_are_isolated(fake_dola):
    a = fake_dola.send("prompt của A", sessionid="sess-A")
    b = fake_dola.send("prompt của B", sessionid="sess-B")
    a2 = fake_dola.send("prompt 2 của A", sessionid="sess-A")

    def recent(sid):
        req = urllib.request.Request(fake_dola.base_url + "/im/chain/recent_conv", data=b"{}", method="POST",
                                     headers={"content-type": "application/json", "Cookie": f"sessionid={sid}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        return [c["conversation"]["conversation_id"] for c in d["downlink_body"]["pull_recent_conv_chain_downlink_body"]["cells"]]

    assert recent("sess-A") == [a2["conversation_id"], a["conversation_id"]]  # mới nhất trước
    assert recent("sess-B") == [b["conversation_id"]]
    assert recent("sess-C") == []
    assert all(cid.isdigit() for cid in (a["conversation_id"], b["conversation_id"]))


def test_control_and_state_roundtrip(fake_dola):
    st = fake_dola.control(mode="slow", render_seconds=7, credits=9, slow_delay=0.5)
    assert st["mode"] == "slow" and st["render_seconds"] == 7 and st["credits"] == 9
    t0 = time.time()
    urllib.request.urlopen(fake_dola.base_url + "/chat/", timeout=10).read()
    assert time.time() - t0 >= 0.45, "Độ trễ slow_delay phải >= 0.45s (cho phép sai số clock tick ~15ms trên Windows)"
    with pytest.raises(urllib.error.HTTPError):
        fake_dola.control(mode="khong-co")
    st = fake_dola.reset()
    assert st["mode"] == "normal" and st["render_seconds"] == 2 and st["credits"] == 4
    assert st["request_log"] == [] and st["conversations"] == {}


def test_crash_mode_drops_connection(fake_dola):
    fake_dola.control(mode="crash")
    with pytest.raises(Exception):
        urllib.request.urlopen(fake_dola.base_url + "/chat/", timeout=10).read()
    # đường /__* vẫn sống để test điều khiển được
    assert fake_dola.get_state()["mode"] == "crash"


def test_ask_ratio_mode(fake_dola, page):
    """BH-46/BH-47: tin nhắn đầu tạo conversation nhưng chain chỉ có câu hỏi của Dola (content là chuỗi JSON lồng,
    không URL video, không trừ credit); tin nhắn kế tiếp trong cùng /chat/{id} có "16:9" → render như normal."""
    from fake_dola import ASK_RATIO_TEXT
    fake_dola.control(mode="ask_ratio", render_seconds=1, credits=4)
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")
    box = page.locator("div.ProseMirror").first
    box.click()
    box.fill("Tạo video dài 30 giây. người nhện đánh nhau với robot")
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"/chat/\d+"), timeout=10000)
    conv_id = re.search(r"/chat/(\d+)", page.url).group(1)
    chain = page.evaluate(SINGLE_JS, conv_id)
    dumped = json.dumps(chain, ensure_ascii=False)
    assert ASK_RATIO_TEXT.replace('"', '\\"') in dumped or ASK_RATIO_TEXT in dumped
    assert "/video/tos/" not in dumped and "generating" not in dumped.lower()
    inner = json.loads(chain["data"]["messages"][1]["content"])
    assert inner["text"] == ASK_RATIO_TEXT, "content phải là chuỗi JSON lồng chứa text"
    st = fake_dola.get_state()
    assert st["sent_prompts"] == ["Tạo video dài 30 giây. người nhện đánh nhau với robot"]
    def real_session(state):
        return next(v for k, v in state["sessions"].items() if k != "__anonymous__")
    assert real_session(st)["credits"] == 4, "hỏi lại thì chưa trừ credit"
    # trả lời trong cùng conversation
    box.click()
    box.fill("15 giây, tỷ lệ 16:9. Hãy tạo video ngay, không cần hỏi thêm.")
    page.keyboard.press("Enter")
    time.sleep(1)
    page.evaluate("1")  # BH-41: bơm sự kiện trước khi đọc URL
    assert re.search(r"/chat/(\d+)", page.url).group(1) == conv_id, "trả lời không được tạo conversation mới"
    deadline = time.time() + 10
    url = None
    while time.time() < deadline:
        chain = page.evaluate(SINGLE_JS, conv_id)
        m = re.search(r'https?://[^"\s]+/video/tos/\d+\.mp4', json.dumps(chain))
        if m:
            url = m.group(0)
            break
        time.sleep(0.5)
    assert url and url.endswith(f"/video/tos/{conv_id}.mp4"), chain
    st = fake_dola.get_state()
    assert len(st["sent_prompts"]) == 2 and len(st["conversations"]) == 1
    assert real_session(st)["credits"] == 3


def test_reply_text_mode(fake_dola, page):
    """mode=reply_text: chain luôn là văn bản từ chối, không bao giờ có video."""
    from fake_dola import REPLY_TEXT
    fake_dola.control(mode="reply_text", render_seconds=0)
    page.goto(fake_dola.base_url + "/chat/", wait_until="domcontentloaded")
    box = page.locator("div.ProseMirror").first
    box.click()
    box.fill("prompt bị từ chối")
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"/chat/\d+"), timeout=10000)
    conv_id = re.search(r"/chat/(\d+)", page.url).group(1)
    time.sleep(1.5)
    chain = page.evaluate(SINGLE_JS, conv_id)
    dumped = json.dumps(chain, ensure_ascii=False)
    assert "/video/tos/" not in dumped
    assert json.loads(chain["data"]["messages"][1]["content"])["text"] == REPLY_TEXT
