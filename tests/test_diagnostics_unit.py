"""
BH-33: không lộ mật khẩu proxy trong detail chẩn đoán, last_error và gói chẩn đoán.
"""
from __future__ import annotations

import json
import os
import zipfile

import pytest

diagnostics = pytest.importorskip("diagnostics", reason="diagnostics.py chưa có")


@pytest.mark.parametrize("raw, expected", [
    ("1.2.3.4:8080:user:secretpw", "1.2.3.4:8080:user:***"),
    ("http://user:secretpw@1.2.3.4:8080", "http://user:***@1.2.3.4:8080"),
    ("socks5://user:se:cr:et@host:1080", "socks5://user:***@host:1080"),
    ("1.2.3.4:8080", "1.2.3.4:8080"),
    ("http://1.2.3.4:8080", "http://1.2.3.4:8080"),
    ("http://user@host:1", "http://user@host:1"),
    ("  1.2.3.4:8080:user:secretpw  ", "1.2.3.4:8080:user:***"),
    ("", ""),
    (None, ""),
])
def test_bh33_mask_proxy(raw, expected):
    out = diagnostics.mask_proxy(raw)
    assert out == expected
    assert "secretpw" not in out


def test_bh33_proxy_step_detail_hides_password(db, monkeypatch):
    def failing(proxy_url):
        raise ConnectionError(f"cannot connect via {proxy_url}")

    monkeypatch.setattr(diagnostics, "_fetch_ip", failing)
    acc = {"id": 1, "name": "n", "proxy": "1.2.3.4:8080:user:secretpw"}
    step = diagnostics._check_proxy(acc)
    assert step["ok"] is False
    assert "secretpw" not in step["detail"], step["detail"]
    assert "1.2.3.4:8080:user:***" in step["detail"], step["detail"]

    acc = {"id": 2, "name": "n", "proxy": "http://user:secretpw@1.2.3.4:8080"}
    step = diagnostics._check_proxy(acc)
    assert "secretpw" not in step["detail"], step["detail"]


def test_bh33_bundle_masks_proxy_and_last_error(db):
    db.add_account("nick proxy", proxy="1.2.3.4:8080:user:secretpw",
                   last_error="Proxy '1.2.3.4:8080:user:secretpw' không phản hồi: http://user:secretpw@1.2.3.4:8080 timeout")
    db.add_account("nick url", proxy="http://u2:secretpw2@5.6.7.8:3128", last_error="x")
    path = diagnostics.build_bundle()
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            assert "accounts.json" in names and "jobs.json" in names and "thong_tin.json" in names
            raw = zf.read("accounts.json").decode("utf-8")
        assert "secretpw" not in raw, raw
        accounts = json.loads(raw)
        by_name = {a["name"]: a for a in accounts}
        assert by_name["nick proxy"]["proxy"] == "1.2.3.4:8080:user:***"
        assert "1.2.3.4:8080:user:***" in by_name["nick proxy"]["last_error"]
        assert by_name["nick url"]["proxy"] == "http://u2:***@5.6.7.8:3128"
        for a in accounts:
            assert a["fb_pass"] in ("", "***") and a["cookies"] in ("", "***")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_bh33_no_raw_proxy_in_user_strings():
    import pathlib
    root = pathlib.Path(diagnostics.__file__).resolve().parent
    for name in ("diagnostics.py", "dola_service.py"):
        for i, line in enumerate((root / name).read_text(encoding="utf-8").splitlines(), 1):
            if "acc.get('proxy')" in line or 'acc.get("proxy")' in line or 'acc["proxy"]' in line:
                assert "mask_proxy(" in line or "parse_proxy(" in line, f"{name}:{i}: proxy nối thẳng vào chuỗi: {line.strip()}"
