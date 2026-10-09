"""BH-39: chế độ cửa sổ ẩn THẬT (Chrome headless=False đặt ngoài màn hình) + show_window/hide_window.

Máy test Linux không có DISPLAY nên conftest đặt SEEDANCE_HEADLESS=1 cho mọi test khác; test này chạy
tests/_hidden_window_probe.py trong tiến trình con dưới `xvfb-run` với SEEDANCE_HEADLESS=0 và đối chiếu
vị trí cửa sổ đọc lại qua CDP. Bỏ qua nếu máy không có xvfb-run.
"""
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROBE = ROOT / "tests" / "_hidden_window_probe.py"

pytestmark = pytest.mark.timeout(150)


@pytest.mark.skipif(shutil.which("xvfb-run") is None, reason="không có xvfb-run (cần X ảo để mở Chrome headless=False)")
def test_bh39_hidden_window_show_and_hide_under_xvfb(env_tmp, tmp_path):
    env = dict(os.environ)
    env["SEEDANCE_HEADLESS"] = "0"
    env["SEEDANCE_DATA_DIR"] = str(tmp_path / "data")
    env["SEEDANCE_DB_PATH"] = str(tmp_path / "data" / "studio.db")
    env.pop("DISPLAY", None)  # xvfb-run cấp DISPLAY riêng
    proc = subprocess.run(["xvfb-run", "-a", sys.executable, str(PROBE)], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=120)
    out = proc.stdout + "\n" + proc.stderr
    assert proc.returncode == 0, out
    lines = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line and not line.startswith(" "))
    assert lines.get("HEADLESS") == "False", out
    assert lines.get("INITIAL") == "-32000,-32000", f"cửa sổ ẩn phải mở ở ngoài màn hình: {out}"
    assert lines.get("SHOWN") == "True" and lines.get("AFTER_SHOW") == "80,80", out
    assert lines.get("HIDDEN") == "True" and lines.get("AFTER_HIDE") == "-32000,-32000", out
    assert lines.get("DONE") == "1"
    assert "Không đưa ra màn hình được" not in out and "Không ẩn được" not in out


def test_bh39_show_hide_are_noop_when_headless():
    """Với config.HEADLESS (chế độ của mọi test khác) hai hàm trả False và không đụng CDP."""
    import config
    import browser
    assert config.HEADLESS is True
    assert browser.playwright_headless(True) is True
    assert browser.playwright_headless(False) is False

    class _Boom:
        def new_cdp_session(self, page):
            raise AssertionError("không được gọi CDP khi HEADLESS")

    assert browser.show_window(_Boom(), None) is False
    assert browser.hide_window(_Boom(), None) is False
    args = browser._build_args(True, False)
    assert f"--window-position={config.HIDDEN_WINDOW_POSITION}" in args and "--start-maximized" not in args
    assert "--start-maximized" in browser._build_args(False, False)
