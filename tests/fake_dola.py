"""
Fake Dola: server HTTP cục bộ mô phỏng vừa đủ www.dola.com để dola_service chạy hết một job
(docs/KIEN_TRUC.md mục 6).

Chạy độc lập để xem thử:   python tests/fake_dola.py   (in ra base_url, Ctrl+C để dừng)

Thiết kế:
- Mỗi "phiên" được nhận diện bằng cookie ``sessionid`` (giống Dola thật, mỗi nick có cookie riêng).
  Conversation, credit và nhật ký request được gắn theo phiên, nên hai nick chạy song song không
  nhìn thấy conversation của nhau (điều kiện bắt buộc để test T5/Q1 có nghĩa).
- Conversation id là chuỗi số (dola_service tìm bằng regex ``/chat/(\\d+)``).
- Trạng thái toàn cục (mode, render_seconds, credits mặc định...) đổi qua ``POST /__control``,
  đọc toàn bộ qua ``GET /__state``.
- mode=captcha giống Dola thật (BH-39): trang tải lên bình thường; ``POST /__send`` đầu tiên trong phiên trả
  ``{captcha: true}`` (KHÔNG tạo conversation) và trang chèn ``#captcha_container`` (div có id, không class,
  fixed phủ cả trang, bên trong iframe ``/__captcha_frame``). ``{"solve_captcha_after": N}``: N giây sau lần hiện
  đầu tiên server tự đổi mode về normal, trang poll ``/__captcha_state`` mỗi 1 s và gỡ lớp phủ; ``/__send`` kế
  tiếp tạo conversation bình thường. Không đặt → captcha vĩnh viễn (test Q4).
- ``{"auto_resend_after_solve": true}`` (chỉ có nghĩa cùng solve_captcha_after): mô phỏng Dola TỰ gửi prompt đã
  gõ ngay khi captcha được giải (như Dola thật đôi khi làm): lúc chuyển mode về normal, server tạo conversation
  cho mọi phiên đã bị captcha chặn với đúng prompt họ đã gửi và trừ 1 credit. Ô nhập trên trang vẫn còn chữ
  (giống thật: trang không biết server đã gửi). Dùng để kiểm dola_service KHÔNG gửi lại (tốn thêm credit, BH-45).
- mode=ask_ratio (BH-46/BH-47, bằng chứng: HTML trang Dola lúc job #23 hết 8 phút chờ): tin nhắn ĐẦU của một
  conversation không tạo video; chain/single trả về văn bản trợ lý đúng nguyên văn câu Dola hỏi lại
  (ASK_RATIO_TEXT, không có URL video), không trừ credit. Tin nhắn KẾ TIẾP trong CÙNG conversation (trang gửi
  ``conversation_id`` lấy từ URL /chat/{id}) có chứa "9:16" hoặc "16:9" → bắt đầu render như normal (trừ 1 credit).
  Cấu trúc chain: ``content`` là CHUỖI JSON ``{"text": ...}`` lồng trong JSON (dạng tin nhắn Doubao/Dola) để kiểm
  dola_service._assistant_texts parse được JSON trong chuỗi. Như Dola thật, chain trả CẢ LỊCH SỬ conversation
  (BH-48): tin người dùng (prompt, rồi câu trả lời tỷ lệ của tool) ``role: user`` + tin trợ lý; trong lúc render có
  thêm ``{"role": "assistant", "text": "Generating video..."}`` và ``status: generating``.
- mode=reply_text: mọi conversation chỉ trả văn bản REPLY_TEXT ("I cannot create that video"), không bao giờ có video.
"""
from __future__ import annotations

import asyncio
import json
import random
import socket
import threading
import time
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

MODES = ("normal", "captcha", "daily_limit", "slow", "crash", "ask_ratio", "reply_text")
# Nguyên văn câu Dola hỏi lại (HTML trang Dola của người dùng, job #23) khi prompt nói "dài 30 giây" và không nêu tỷ lệ
ASK_RATIO_TEXT = ("Video generation currently supports durations from 4 to 15 seconds. I can generate it at the nearest "
                  "supported duration of 15 seconds. I also need to confirm the aspect ratio you want: "
                  "A. 16:9 cinematic wide screen B. 9:16 vertical short video C. 2.39:1 anamorphic film look. "
                  "Which option would you like?")
REPLY_TEXT = "I cannot create that video, please try a different description."
FAKE_MP4_SIZE = 120 * 1024  # > 50 000 byte theo điều kiện của dola_service
DAILY_LIMIT_TEXT = "You have reached the daily limit for video generation"
CAPTCHA_TEXT = "Verify to continue"
# Lớp phủ captcha giống Dola thật (BH-39): div có id, không có class, position:fixed phủ cả trang, bên trong là
# iframe captcha của ByteDance. Chỉ xuất hiện SAU khi gửi prompt lần đầu trong phiên; không nằm sẵn trong trang.
CAPTCHA_CONTAINER_HTML = (
    '<div id="captcha_container" style="display:block;position:fixed;inset:0;width:100%;height:100%;'
    'z-index:111111;background:rgba(0,0,0,.5)">'
    '<iframe src="/__captcha_frame?from=iframe&fp=verify_x" style="width:400px;height:300px"></iframe></div>'
)
SESSION_COOKIE = "sessionid"
ANON_SESSION = "__anonymous__"


class FakeDolaState:
    """Toàn bộ trạng thái của fake, có thể đọc trực tiếp trong tiến trình hoặc qua /__state."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.mode: str = "normal"
        self.render_seconds: float = 2.0
        self.credits: int = 4            # credit khởi điểm cho mỗi phiên mới
        self.slow_delay: float = 3.0     # mode=slow: trễ mỗi phản hồi (giây)
        # mode=captcha: None = captcha vĩnh viễn (người dùng không giải); N = tự "giải" N giây sau lần hiện đầu tiên
        self.solve_captcha_after: Optional[float] = None
        self.auto_resend_after_solve: bool = False
        self.captcha_shown_at: Optional[float] = None
        self.captcha_solved_at: Optional[float] = None
        self.sent_prompts: List[str] = []
        self.conversations: Dict[str, Dict[str, Any]] = {}
        self.request_log: List[str] = []
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.downloads: List[Dict[str, Any]] = []
        self._next_conv = 7100000000000000000 + random.randint(0, 999)

    # ----- tiện ích -----
    def reset(self) -> None:
        with self.lock:
            self.mode = "normal"
            self.render_seconds = 2.0
            self.credits = 4
            self.slow_delay = 3.0
            self.solve_captcha_after = None
            self.auto_resend_after_solve = False
            self.captcha_shown_at = None
            self.captcha_solved_at = None
            self.sent_prompts = []
            self.conversations = {}
            self.request_log = []
            self.sessions = {}
            self.downloads = []

    def session(self, sid: str) -> Dict[str, Any]:
        with self.lock:
            s = self.sessions.get(sid)
            if s is None:
                s = {"credits": self.credits, "requests": 0, "first_seen": time.time(), "last_seen": time.time()}
                self.sessions[sid] = s
            s["last_seen"] = time.time()
            s["requests"] += 1
            return s

    def new_conversation(self, sid: str, prompt: str, **extra) -> str:
        with self.lock:
            self._next_conv += 1
            cid = str(self._next_conv)
            self.conversations[cid] = {
                "prompt": prompt,
                "created_at": time.time(),
                "session": sid,
                # ask_ratio: True = đang chờ người dùng trả lời tỷ lệ; answered_at = lúc trả lời (bắt đầu render)
                "asked": False,
                "answered_at": None,
                "reply_text": False,
                "messages": [prompt],
            }
            self.conversations[cid].update(extra)
            self.sent_prompts.append(prompt)
            return cid

    def conversations_of(self, sid: str) -> List[str]:
        with self.lock:
            items = [(cid, c) for cid, c in self.conversations.items() if c["session"] == sid]
        items.sort(key=lambda kv: kv[1]["created_at"], reverse=True)  # mới nhất trước
        return [cid for cid, _ in items]

    def captcha_blocking(self) -> bool:
        """mode=captcha còn hiệu lực không; tự chuyển về normal khi đã quá solve_captcha_after giây kể từ lần hiện đầu."""
        with self.lock:
            if self.mode != "captcha":
                return False
            if (self.solve_captcha_after is not None and self.captcha_shown_at is not None
                    and time.time() - self.captcha_shown_at >= self.solve_captcha_after):
                self.mode = "normal"
                self.captcha_solved_at = time.time()
                if self.auto_resend_after_solve:
                    self._auto_resend_pending()
                return False
            return True

    def mark_captcha_shown(self, sid: str, text: str = "") -> None:
        with self.lock:
            if self.captcha_shown_at is None:
                self.captcha_shown_at = time.time()
            sess = self.session(sid)
            sess["captcha_shown"] = True
            if text:
                sess["pending_prompt"] = text  # prompt đã gõ lúc captcha chặn (auto_resend_after_solve)

    def _auto_resend_pending(self) -> None:
        """auto_resend_after_solve: tạo conversation cho prompt đã gửi lúc captcha chặn, trừ 1 credit (giữ lock)."""
        for sid, sess in self.sessions.items():
            text = sess.pop("pending_prompt", "")
            if not text or sess["credits"] <= 0:
                continue
            sess["credits"] = max(0, sess["credits"] - 1)
            self.new_conversation(sid, text)

    def daily_limited(self, sid: str) -> bool:
        with self.lock:
            if self.mode == "daily_limit":
                return True
            s = self.sessions.get(sid)
            return bool(s is not None and s["credits"] <= 0)

    def count_requests(self, method: str, path_prefix: str, exact: bool = False) -> int:
        key = f"{method} {path_prefix}"
        with self.lock:
            if exact:
                return sum(1 for r in self.request_log if r == key)
            return sum(1 for r in self.request_log if r.startswith(key))

    @property
    def chat_get_count(self) -> int:
        """Số lần GET /chat/ (trang gốc) = số lần dola_service mở Chrome và goto DOLA_CHAT_URL."""
        return self.count_requests("GET", "/chat/", exact=True) + self.count_requests("GET", "/chat", exact=True)

    def active_sessions(self, window_seconds: float = 6.0) -> int:
        now = time.time()
        with self.lock:
            return sum(1 for sid, s in self.sessions.items() if sid != ANON_SESSION and now - s["last_seen"] <= window_seconds)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "mode": self.mode,
                "render_seconds": self.render_seconds,
                "credits": self.credits,
                "slow_delay": self.slow_delay,
                "solve_captcha_after": self.solve_captcha_after,
                "auto_resend_after_solve": self.auto_resend_after_solve,
                "captcha_shown_at": self.captcha_shown_at,
                "captcha_solved_at": self.captcha_solved_at,
                "sent_prompts": list(self.sent_prompts),
                "conversations": {k: dict(v) for k, v in self.conversations.items()},
                "request_log": list(self.request_log),
                "chat_get_count": self.chat_get_count,
                "chat_page_loads": self.count_requests("GET", "/chat"),
                "recent_conv_calls": self.count_requests("POST", "/im/chain/recent_conv"),
                "single_calls": self.count_requests("POST", "/im/chain/single"),
                "sessions": {k: dict(v) for k, v in self.sessions.items()},
                "active_sessions": self.active_sessions(),
                "downloads": list(self.downloads),
                "total_requests": len(self.request_log),
            }


STATE = FakeDolaState()


def fake_mp4_bytes(conv_id: str) -> bytes:
    """mp4 giả: header chứa conv_id (để test T5 đối chiếu) + đệm cho đủ 120 KB."""
    head = f"FAKEMP4;conv={conv_id};".encode("ascii")
    return head + b"\x00" * (FAKE_MP4_SIZE - len(head))


def _session_id(request: Request) -> str:
    return request.cookies.get(SESSION_COOKIE) or ANON_SESSION


def _log(request: Request) -> str:
    """Ghi request_log (bỏ qua /__* của test điều khiển: request_log chỉ phản ánh lưu lượng "Dola")."""
    sid = _session_id(request)
    if request.url.path.startswith("/__"):
        return sid
    with STATE.lock:
        STATE.request_log.append(f"{request.method} {request.url.path}")
    STATE.session(sid)
    return sid


def _ensure_cookie(request: Request, response: Response) -> None:
    if not request.cookies.get(SESSION_COOKIE):
        response.set_cookie(SESSION_COOKIE, f"fake-{random.randint(100000, 999999)}", path="/")


# ---------------------------------------------------------------- trang chat
PAGE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Fake Dola</title>
<style>
 body { font-family: sans-serif; margin: 24px; }
 .ProseMirror { border: 1px solid #999; min-height: 48px; padding: 8px; }
 .captcha-box { border: 2px solid red; padding: 12px; margin: 12px 0; }
 .msg { margin: 6px 0; padding: 6px; background: #f3f3f3; }
</style></head>
<body>
<header><span id="credits">You have __CREDITS__ video credits left</span></header>
__DAILY_LIMIT__
__CAPTCHA__
<main id="messages">__HISTORY__</main>
<div class="ProseMirror" contenteditable="true"></div>
<script>
(function () {
  const box = document.querySelector('.ProseMirror');
  const msgs = document.getElementById('messages');
  function addMsg(text, cls) {
    const d = document.createElement('div'); d.className = 'msg ' + (cls || ''); d.textContent = text; msgs.appendChild(d);
  }
  async function sendPrompt() {
    const text = box.innerText;
    if (!text.trim()) return;
    // Giống thật: tin nhắn gửi trong /chat/{id} thuộc conversation đó (ask_ratio: câu trả lời tỷ lệ)
    const m = location.pathname.match(new RegExp('/chat/([0-9]+)'));
    const resp = await fetch('/__send', {
      method: 'POST', credentials: 'include',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({text: text, conversation_id: m ? m[1] : null})
    });
    const data = await resp.json();
    if (data.captcha) {
      if (!document.getElementById('captcha_container')) {
        document.body.insertAdjacentHTML('beforeend', __CAPTCHA_CONTAINER_JSON__);
        pollCaptcha();
      }
      return;
    }
    if (data.daily_limit) { addMsg('__DAILY_LIMIT_TEXT__', 'limit'); document.getElementById('credits').textContent = 'You have 0 video credits left'; return; }
    if (data.conversation_id) {
      addMsg(text, 'user');
      addMsg(data.assistant_text || 'Generating video...', 'bot');
      box.innerText = '';
      if (typeof data.credits_left === 'number') {
        document.getElementById('credits').textContent = 'You have ' + data.credits_left + ' video credits left';
      }
      history.pushState({conv: data.conversation_id}, '', '/chat/' + data.conversation_id);
    }
  }
  // Giống thật: lớp phủ tự biến mất khi "đã kéo xong" (server đổi mode qua solve_captcha_after)
  function pollCaptcha() {
    const timer = setInterval(async function () {
      try {
        const r = await fetch('/__captcha_state', {credentials: 'include'});
        const st = await r.json();
        if (!st.captcha) {
          const c = document.getElementById('captcha_container');
          if (c) c.remove();
          clearInterval(timer);
        }
      } catch (e) { /* server tắt: thôi poll */ clearInterval(timer); }
    }, 1000);
  }
  box.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); sendPrompt(); }
  });
})();
</script>
</body></html>
"""


def render_page(sid: str, conv_id: Optional[str]) -> str:
    sess = STATE.session(sid)
    limited = STATE.daily_limited(sid)
    credits = 0 if limited else sess["credits"]
    daily_block = f'<div class="limit-banner">{DAILY_LIMIT_TEXT}</div>' if limited else ""
    captcha_block = ""  # captcha chỉ hiện sau khi gửi prompt (xem /__send), giống Dola thật
    history = ""
    if conv_id:
        conv = STATE.conversations.get(conv_id)
        if conv and conv["session"] == sid:
            history = f'<div class="msg user">{_escape(conv["prompt"])}</div>'
    return (PAGE_HTML
            .replace("__CREDITS__", str(credits))
            .replace("__DAILY_LIMIT__", daily_block)
            .replace("__CAPTCHA__", captcha_block)
            .replace("__HISTORY__", history)
            .replace("__CAPTCHA_CONTAINER_JSON__", json.dumps(CAPTCHA_CONTAINER_HTML))
            .replace("__DAILY_LIMIT_TEXT__", DAILY_LIMIT_TEXT))


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- ứng dụng
app = FastAPI(title="Fake Dola")


@app.get("/chat/", response_class=HTMLResponse)
@app.get("/chat", response_class=HTMLResponse)
async def chat_root(request: Request):
    sid = _log(request)
    resp = HTMLResponse(render_page(sid, None))
    _ensure_cookie(request, resp)
    return resp


@app.get("/chat/{conv_id}", response_class=HTMLResponse)
async def chat_conv(conv_id: str, request: Request):
    sid = _log(request)
    resp = HTMLResponse(render_page(sid, conv_id))
    _ensure_cookie(request, resp)
    return resp


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    _log(request)
    return HTMLResponse('<a href="/chat/">chat</a>')


@app.post("/__send")
async def send_prompt(request: Request):
    sid = _log(request)
    body = await request.json()
    text = str(body.get("text") or "")
    if STATE.captcha_blocking():
        STATE.mark_captcha_shown(sid, text)
        return {"captcha": True}  # không tạo conversation khi captcha đang hiện
    if STATE.daily_limited(sid):
        return {"daily_limit": True, "credits_left": 0}
    sess = STATE.session(sid)
    conv_id = str(body.get("conversation_id") or "")
    conv = STATE.conversations.get(conv_id)
    if conv is not None and conv["session"] == sid and conv.get("asked") and not conv.get("answered_at"):
        # ask_ratio: tin nhắn kế tiếp trong cùng conversation
        with STATE.lock:
            conv["messages"].append(text)
            STATE.sent_prompts.append(text)
            if "9:16" in text or "16:9" in text:
                conv["answered_at"] = time.time()
                conv["created_at"] = time.time()  # render tính từ lúc có đủ tham số
                sess["credits"] = max(0, sess["credits"] - 1)
                return {"conversation_id": conv_id, "credits_left": sess["credits"], "answered": True}
            return {"conversation_id": conv_id, "credits_left": sess["credits"], "assistant_text": ASK_RATIO_TEXT}
    if STATE.mode == "ask_ratio":
        cid = STATE.new_conversation(sid, text, asked=True)
        return {"conversation_id": cid, "credits_left": sess["credits"], "assistant_text": ASK_RATIO_TEXT}
    if STATE.mode == "reply_text":
        cid = STATE.new_conversation(sid, text, reply_text=True)
        return {"conversation_id": cid, "credits_left": sess["credits"], "assistant_text": REPLY_TEXT}
    with STATE.lock:
        sess["credits"] = max(0, sess["credits"] - 1)
        credits_left = sess["credits"]
    cid = STATE.new_conversation(sid, text)
    return {"conversation_id": cid, "credits_left": credits_left}


@app.get("/__captcha_state")
async def captcha_state(request: Request):
    return {"captcha": STATE.captcha_blocking(), "mode": STATE.mode, "captcha_shown_at": STATE.captcha_shown_at,
            "captcha_solved_at": STATE.captcha_solved_at}


@app.get("/__captcha_frame", response_class=HTMLResponse)
async def captcha_frame(request: Request):
    """Nội dung iframe captcha (giả lập bdcaptcha.html của ByteDance)."""
    return HTMLResponse(f"<!doctype html><html><body><p>{CAPTCHA_TEXT}</p><p>Drag the puzzle piece into place</p>"
                        "<div class='slider' style='width:300px;height:40px;background:#ddd'></div></body></html>")


@app.post("/im/chain/recent_conv")
async def recent_conv(request: Request):
    sid = _log(request)
    cells = [{"conversation": {"conversation_id": cid, "name": STATE.conversations[cid]["prompt"][:30]}, "id": cid}
             for cid in STATE.conversations_of(sid)]
    return {"downlink_body": {"pull_recent_conv_chain_downlink_body": {"cells": cells}}}


@app.post("/im/chain/single")
async def single_chain(request: Request):
    sid = _log(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    conv_id = str(((body.get("uplink_body") or {}).get("pull_singe_chain_uplink_body") or {}).get("conversation_id") or "")
    if STATE.mode == "daily_limit":
        return {"data": {"messages": [{"content": DAILY_LIMIT_TEXT}]}}
    conv = STATE.conversations.get(conv_id)
    if not conv:
        return JSONResponse({"data": {"status": "error", "message": "conversation not found"}}, status_code=404)
    # Giống Dola thật (BH-48): chain trả CẢ lịch sử — mọi tin người dùng đã gửi (prompt, câu trả lời tỷ lệ) lẫn tin
    # trợ lý — chứ không chỉ tin mới nhất; dola_service phải tự loại tin của chính mình.
    def _text_msg(role: str, text: str) -> Dict[str, Any]:
        return {"content_type": "text", "role": role, "content": json.dumps({"text": text}, ensure_ascii=False)}

    history: List[Dict[str, Any]] = [_text_msg("user", conv["prompt"])]
    if conv.get("reply_text"):
        return {"data": {"messages": history + [_text_msg("assistant", REPLY_TEXT)]}}
    if conv.get("asked"):
        history.append(_text_msg("assistant", ASK_RATIO_TEXT))
        for extra in conv["messages"][1:]:   # câu trả lời tỷ lệ/thời lượng của người dùng (tool) trong cùng conversation
            history.append(_text_msg("user", extra))
        if not conv.get("answered_at"):
            return {"data": {"messages": history}}
    if time.time() - conv["created_at"] < STATE.render_seconds:
        return {"data": {"status": "generating",
                         "messages": history + [{"content_type": "text", "role": "assistant", "text": "Generating video..."}]}}
    base = str(request.base_url).rstrip("/")  # http://127.0.0.1:PORT (server không có TLS)
    return {"data": {"messages": history + [{"content_type": "video", "content": f"{base}/video/tos/{conv_id}.mp4"}]}}


@app.get("/video/tos/{name}")
async def video(name: str, request: Request):
    _log(request)
    conv_id = name.rsplit(".", 1)[0]
    with STATE.lock:
        STATE.downloads.append({"conv_id": conv_id, "referer": request.headers.get("referer"),
                                "user_agent": request.headers.get("user-agent")})
    return Response(content=fake_mp4_bytes(conv_id), media_type="video/mp4")


@app.post("/__control")
async def control(request: Request):
    _log(request)
    body = await request.json()
    with STATE.lock:
        if body.get("reset"):
            STATE.reset()
        if "mode" in body:
            if body["mode"] not in MODES:
                return JSONResponse({"error": f"mode phải thuộc {MODES}"}, status_code=400)
            STATE.mode = body["mode"]
        if "render_seconds" in body:
            STATE.render_seconds = float(body["render_seconds"])
        if "slow_delay" in body:
            STATE.slow_delay = float(body["slow_delay"])
        if "solve_captcha_after" in body:
            v = body["solve_captcha_after"]
            STATE.solve_captcha_after = None if v is None else float(v)
            STATE.captcha_shown_at = None
            STATE.captcha_solved_at = None
        if "auto_resend_after_solve" in body:
            STATE.auto_resend_after_solve = bool(body["auto_resend_after_solve"])
        if "credits" in body:
            STATE.credits = int(body["credits"])
            for s in STATE.sessions.values():
                s["credits"] = STATE.credits
    return STATE.snapshot()


@app.get("/__state")
async def state(request: Request):
    _log(request)
    return STATE.snapshot()


@app.post("/__reset")
async def reset(request: Request):
    STATE.reset()
    return STATE.snapshot()


class _ChaosMiddleware:
    """mode=slow: trễ mỗi phản hồi; mode=crash: đóng socket TCP TRƯỚC khi gửi header (client thấy
    net::ERR_EMPTY_RESPONSE ngay lập tức, như Dola sập). Đường /__* không bị ảnh hưởng.

    BH-25: cách cũ (gửi header với Content-Length lớn rồi cắt thân) làm Chromium treo đủ 60 s của
    page.goto thay vì lỗi ngay, vì trang đã commit mà domcontentloaded không bao giờ bắn.
    uvicorn không cho ASGI đóng socket, nên lấy transport qua `send.__self__` (RequestResponseCycle của
    uvicorn h11); nếu không lấy được thì ném lỗi để uvicorn tự đóng kết nối sau khi đã gửi header."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith("/__"):
            return await self.inner(scope, receive, send)
        if STATE.mode == "crash":
            with STATE.lock:
                STATE.request_log.append(f"{scope['method']} {scope['path']}")
            cycle = getattr(send, "__self__", None)
            transport = getattr(cycle, "transport", None)
            if transport is not None:
                cycle.disconnected = True  # uvicorn không gửi 500 vào socket đã đóng
                transport.close()
                return
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/html")]})
            await send({"type": "http.response.body", "body": b"<html>crash", "more_body": True})
            raise ConnectionResetError("fake Dola mode=crash: cắt kết nối giữa chừng")
        if STATE.mode == "slow":
            await asyncio.sleep(STATE.slow_delay)
        return await self.inner(scope, receive, send)


asgi_app = _ChaosMiddleware(app)


# ---------------------------------------------------------------- chạy server trong thread
def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class FakeDola:
    """Bọc uvicorn.Server chạy ở thread daemon + vài hàm tiện cho test. Hỗ trợ unpack (server, port, base_url)."""

    def __init__(self, server: uvicorn.Server, thread: threading.Thread, host: str, port: int):
        self.server = server
        self.thread = thread
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.state = STATE

    def __iter__(self):
        return iter((self.server, self.port, self.base_url))

    # --- HTTP tiện ích (dùng urllib để không phụ thuộc thư viện ngoài) ---
    def _request(self, method: str, path: str, payload: Optional[dict] = None, cookies: Optional[dict] = None) -> Any:
        import urllib.request
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("content-type", "application/json")
        if cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            ctype = resp.headers.get("content-type", "")
            return json.loads(raw) if "json" in ctype else raw

    def control(self, **kwargs) -> Dict[str, Any]:
        return self._request("POST", "/__control", kwargs)

    def reset(self) -> Dict[str, Any]:
        return self._request("POST", "/__reset", {})

    def get_state(self) -> Dict[str, Any]:
        return self._request("GET", "/__state")

    def send(self, text: str, sessionid: str) -> Dict[str, Any]:
        """Tạo conversation thay cho trình duyệt (vd. tạo conversation cũ cho test T5)."""
        return self._request("POST", "/__send", {"text": text}, cookies={SESSION_COOKIE: sessionid})

    def stop(self, timeout: float = 10.0) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=timeout)


def start_fake_dola(port: Optional[int] = None, host: str = "127.0.0.1", startup_timeout: float = 15.0) -> FakeDola:
    """Khởi động fake Dola trong thread daemon. Trả về FakeDola (unpack được thành (server, port, base_url))."""
    port = port or find_free_port(host)
    config = uvicorn.Config(asgi_app, host=host, port=port, log_level="warning", access_log=False, lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name=f"fake-dola-{port}", daemon=True)
    thread.start()
    deadline = time.time() + startup_timeout
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError(f"fake Dola không khởi động được trên cổng {port}")
        if time.time() > deadline:
            raise RuntimeError(f"fake Dola không sẵn sàng sau {startup_timeout}s (cổng {port})")
        time.sleep(0.05)
    return FakeDola(server, thread, host, port)


def stop_fake_dola(fake: FakeDola) -> None:
    fake.stop()


if __name__ == "__main__":
    fd = start_fake_dola()
    print(f"Fake Dola đang chạy tại {fd.base_url}/chat/  (Ctrl+C để dừng)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        fd.stop()
