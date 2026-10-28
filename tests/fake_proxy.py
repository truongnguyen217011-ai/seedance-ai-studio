"""
Fake proxy HTTP cục bộ cho test A4/A5: chuyển tiếp request HTTP thường (absolute-URI) và CONNECT, ghi nhận từng
request đi qua (method, host, path) để test đếm. Không có xác thực, không cache.

Dùng: ``fp = start_fake_proxy(); nick.proxy = f"127.0.0.1:{fp.port}"``; ``fp.requests`` là danh sách request đã qua.
Mỗi request chuyển tiếp được gắn thêm header ``X-Fake-Proxy: 1`` để server đích (fake Dola /__ip) nhận ra.
Chromium mặc định bỏ qua proxy với 127.0.0.1, nên conftest đặt SEEDANCE_PROXY_BYPASS="<-loopback>".
"""
from __future__ import annotations

import http.server
import socket
import socketserver
import threading
import time
from typing import List, Optional, Tuple
from urllib.parse import urlsplit


class _ProxyState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: List[Tuple[str, str, str]] = []   # (method, host, path)

    def record(self, method: str, host: str, path: str) -> None:
        with self.lock:
            self.requests.append((method, host, path))


def _make_handler(state: _ProxyState):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # im lặng
            return

        def _forward(self) -> None:
            parts = urlsplit(self.path)
            if not parts.netloc:
                self.send_error(400, "fake proxy chỉ nhận absolute-URI")
                return
            host, _, port = parts.netloc.partition(":")
            port_n = int(port) if port else 80
            state.record(self.command, parts.netloc, parts.path or "/")
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            target_path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            headers = []
            for k, v in self.headers.items():
                if k.lower() in ("proxy-connection", "connection", "keep-alive"):
                    continue
                headers.append(f"{k}: {v}")
            headers.append("X-Fake-Proxy: 1")
            headers.append("Connection: close")
            req = f"{self.command} {target_path} HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n"
            try:
                with socket.create_connection((host, port_n), timeout=30) as up:
                    up.sendall(req.encode("latin-1") + body)
                    up.shutdown(socket.SHUT_WR)
                    chunks = []
                    while True:
                        data = up.recv(65536)
                        if not data:
                            break
                        chunks.append(data)
            except OSError as e:
                self.send_error(502, f"fake proxy: không nối được {parts.netloc}: {e}")
                return
            raw = b"".join(chunks)
            # Chuyển tiếp nguyên văn (server đích trả Connection: close nên thân kết thúc khi đóng socket)
            self.wfile.write(raw)
            self.close_connection = True

        def do_GET(self):
            self._forward()

        def do_POST(self):
            self._forward()

        def do_HEAD(self):
            self._forward()

        def do_PUT(self):
            self._forward()

        def do_OPTIONS(self):
            self._forward()

        def do_CONNECT(self):
            host, _, port = self.path.partition(":")
            state.record("CONNECT", self.path, "")
            try:
                up = socket.create_connection((host, int(port or 443)), timeout=30)
            except OSError as e:
                self.send_error(502, f"fake proxy: CONNECT {self.path} thất bại: {e}")
                return
            self.send_response(200, "Connection established")
            self.end_headers()
            self.close_connection = True
            client = self.connection

            def pump(src, dst):
                try:
                    while True:
                        data = src.recv(65536)
                        if not data:
                            break
                        dst.sendall(data)
                except OSError:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass

            t = threading.Thread(target=pump, args=(up, client), daemon=True)
            t.start()
            pump(client, up)
            t.join(timeout=5)
            up.close()

    return Handler


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class FakeProxy:
    def __init__(self, server: _Server, thread: threading.Thread, state: _ProxyState, host: str, port: int):
        self.server = server
        self.thread = thread
        self.state = state
        self.host = host
        self.port = port

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def requests(self) -> List[Tuple[str, str, str]]:
        with self.state.lock:
            return list(self.state.requests)

    def count(self, path_prefix: str = "", method: Optional[str] = None) -> int:
        return sum(1 for m, _h, p in self.requests if p.startswith(path_prefix) and (method is None or m == method))

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_fake_proxy(host: str = "127.0.0.1", port: int = 0) -> FakeProxy:
    state = _ProxyState()
    server = _Server((host, port), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, name="fake-proxy", daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection((host, server.server_address[1]), timeout=1):
                break
        except OSError:
            time.sleep(0.05)
    return FakeProxy(server, thread, state, host, server.server_address[1])


def closed_port(host: str = "127.0.0.1") -> int:
    """Một cổng vừa đóng (không có gì lắng nghe) để mô phỏng proxy chết (A5)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    fp = start_fake_proxy()
    print(f"Fake proxy đang chạy tại {fp.address} (Ctrl+C để dừng)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        fp.stop()
