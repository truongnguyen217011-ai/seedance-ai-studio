"""BH-35: cổng 8000 bị bản cũ chiếm phải được phát hiện trước khi khởi động server."""
import socket
import check_env


def test_bh35_port_free_then_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert check_env.port_in_use(port=port) is False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        assert check_env.port_in_use(port=port) is True
        assert check_env.check_port(port) is False
    assert check_env.check_port(port) is True


def test_bh35_main_returns_3_when_port_busy(monkeypatch):
    monkeypatch.setattr(check_env, "check_python", lambda: True)
    monkeypatch.setattr(check_env, "check_libraries", lambda: True)
    monkeypatch.setattr(check_env, "check_chrome", lambda: True)
    monkeypatch.setattr(check_env, "port_in_use", lambda host="127.0.0.1", port=8000: True)
    monkeypatch.setattr(check_env, "find_pid_on_port", lambda port=8000: "4242")
    assert check_env.main() == 3
