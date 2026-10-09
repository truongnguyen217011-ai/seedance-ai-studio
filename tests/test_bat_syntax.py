"""
BH-30: cmd đọc cả khối `if ... ( ... )` một lần; dấu `)` không escape trong dòng `echo` bên trong khối
đóng khối sớm → phần còn lại của file không bao giờ chạy (KHOI_DONG không chạy uvicorn, CAP_NHAT không pull).

Quy tắc đơn giản để theo dõi độ sâu khối:
- dòng `if`/`else`/`for` (hoặc `) else (`) kết thúc bằng `(` → mở khối;
- dòng bắt đầu bằng `)` → đóng khối.
"""
from __future__ import annotations

import pathlib
import re
from typing import List, Tuple

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BAT_FILES = sorted(ROOT.glob("*.bat"))

RE_OPEN = re.compile(r"^\s*(?:\)\s*)?(?:if|else|for)\b.*\(\s*$", re.IGNORECASE)
RE_CLOSE = re.compile(r"^\s*\)")
RE_ECHO = re.compile(r"^\s*echo(?:\s|\.|$)", re.IGNORECASE)
RE_UNESCAPED_PAREN = re.compile(r"(?<!\^)\)")


def _read(p: pathlib.Path) -> List[str]:
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def _walk(p: pathlib.Path) -> Tuple[List[str], int]:
    """Trả về (danh sách vi phạm, độ sâu cuối file)."""
    depth = 0
    bad = []
    for no, line in enumerate(_read(p), 1):
        stripped = line.strip()
        if RE_CLOSE.match(stripped):
            depth -= 1
        if depth > 0 and RE_ECHO.match(stripped) and RE_UNESCAPED_PAREN.search(stripped):
            bad.append(f"{p.name}:{no}: {stripped}")
        if RE_OPEN.match(stripped):
            depth += 1
    return bad, depth


@pytest.mark.parametrize("bat", BAT_FILES, ids=[p.name for p in BAT_FILES])
def test_bh30_echo_inside_block_has_no_unescaped_paren(bat: pathlib.Path):
    bad, _ = _walk(bat)
    assert not bad, "BH-30: dòng echo bên trong khối ( ... ) chứa ')' không escape (đóng khối sớm):\n" + "\n".join(bad)


@pytest.mark.parametrize("bat", BAT_FILES, ids=[p.name for p in BAT_FILES])
def test_bat_blocks_balanced(bat: pathlib.Path):
    _, depth = _walk(bat)
    assert depth == 0, f"{bat.name}: số khối mở/đóng không cân ({depth})"


def test_bat_files_present():
    names = {p.name for p in BAT_FILES}
    assert {"KHOI_DONG.bat", "CAP_NHAT.bat", "CAI_TRINH_DUYET.bat"} <= names, names


def test_khoi_dong_title_reads_version():
    text = (ROOT / "KHOI_DONG.bat").read_text(encoding="utf-8", errors="replace")
    assert re.search(r"set /p VER=<VERSION", text), "KHOI_DONG.bat phải đọc phiên bản từ file VERSION (set /p VER=<VERSION)"
    title = [ln for ln in text.splitlines() if ln.strip().lower().startswith("title ")]
    assert title and "%VER%" in title[0], f"title phải dùng %VER%: {title}"
    assert not re.search(r"title .*v\d+\.\d+", text), "không ghi cứng số phiên bản trong title"
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip(), "file VERSION trống"


def test_bh30_detector_catches_known_bad_pattern(tmp_path):
    """Tự kiểm bộ dò: mẫu lỗi gốc phải bị bắt, mẫu đã escape thì không."""
    bad = tmp_path / "bad.bat"
    bad.write_text("@echo off\nif %errorlevel% neq 0 (\n    echo [LOI] loi (ma loi 1). Thu lai\n    exit /b 1\n)\n", encoding="utf-8")
    hits, depth = _walk(bad)
    assert hits and depth == 0
    ok = tmp_path / "ok.bat"
    ok.write_text("@echo off\nif %errorlevel% neq 0 (\n    echo [LOI] loi ^(ma loi 1^). Thu lai\n    exit /b 1\n)\necho (ngoai khoi thi duoc)\n", encoding="utf-8")
    hits, depth = _walk(ok)
    assert not hits and depth == 0


def test_bh37_cap_nhat_keeps_current_branch():
    """BH-37: không có tham số thì CAP_NHAT.bat dùng nhánh hiện tại, không ép về main."""
    src = (ROOT / "CAP_NHAT.bat").read_text(encoding="utf-8")
    assert "git rev-parse --abbrev-ref HEAD" in src
    assert 'if "%BRANCH%"=="" set BRANCH=main\r\n' in src or 'if "%BRANCH%"=="" set BRANCH=main\n' in src
    # dòng ép main chỉ còn là dự phòng SAU khi đã thử đọc nhánh hiện tại
    assert src.index("git rev-parse --abbrev-ref HEAD") < src.index('if "%BRANCH%"=="" set BRANCH=main')
