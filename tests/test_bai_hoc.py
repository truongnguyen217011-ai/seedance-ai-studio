"""
Tự động hóa cột "Kiểm" của docs/BAI_HOC.md (quét mã nguồn bằng Python, không gọi grep ngoài).
Mục tiêu: `python -m pytest tests/test_bai_hoc.py -q` xanh hoàn toàn (trừ xfail có lý do).
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys
from collections import Counter
from typing import Dict, List

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
BAI_HOC = ROOT / "docs" / "BAI_HOC.md"

def root_py_files() -> List[pathlib.Path]:
    """*.py ở thư mục gốc dự án (không gồm tests/)."""
    return sorted(p for p in ROOT.glob("*.py") if p.is_file())


def phase1_py_files() -> List[pathlib.Path]:
    """*.py ở gốc dự án sau khi đã gỡ hoàn toàn các file legacy ở giai đoạn 5."""
    return root_py_files()


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _lines_matching(p: pathlib.Path, pattern: re.Pattern) -> List[str]:
    return [f"{p.name}:{i}: {line.strip()}" for i, line in enumerate(read(p).splitlines(), 1) if pattern.search(line)]


# ---------------------------------------------------------------- BH-01
IMPORT_TO_DIST = {  # tên import → tên gói trong requirements.txt (chữ thường)
    "yaml": "pyyaml", "PIL": "pillow", "cv2": "opencv-python", "dotenv": "python-dotenv",
    "multipart": "python-multipart", "bs4": "beautifulsoup4", "dateutil": "python-dateutil",
}
LOCAL_MODULES = {p.stem for p in root_py_files()} | {"static", "tests"}


def _imports_of(p: pathlib.Path) -> set:
    tree = ast.parse(read(p), filename=str(p))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _requirements() -> set:
    out = set()
    for line in read(ROOT / "requirements.txt").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].strip().lower().replace("_", "-")
        out.add(name)
    return out


def test_bh01_external_imports_listed_in_requirements():
    reqs = _requirements()
    stdlib = set(sys.stdlib_module_names) | set(sys.builtin_module_names)
    missing: Dict[str, List[str]] = {}
    for p in root_py_files():
        for mod in _imports_of(p):
            if mod in stdlib or mod in LOCAL_MODULES or mod == "__future__":
                continue
            dist = IMPORT_TO_DIST.get(mod, mod).lower().replace("_", "-")
            if dist not in reqs:
                missing.setdefault(mod, []).append(p.name)
    assert not missing, f"BH-01: import thư viện ngoài chuẩn chưa có trong requirements.txt: {missing}"


# ---------------------------------------------------------------- BH-02
LEGACY_STATUS = ["Đang chờ", "Đang xử lý", "Lỗi", "Chờ đăng nhập Dola"]
RE_LEGACY_STATUS = re.compile("|".join(re.escape(f"'{s}'") + "|" + re.escape(f'"{s}"') for s in LEGACY_STATUS))


def test_bh02_no_handwritten_legacy_job_status_strings():
    files = [p for p in phase1_py_files() if p.name != "constants.py"]
    js = ROOT / "static" / "js" / "app.js"
    if js.exists():
        files.append(js)
    hits = [h for p in files for h in _lines_matching(p, RE_LEGACY_STATUS)]
    assert not hits, "BH-02: chuỗi trạng thái job viết tay (chỉ constants.py được chứa):\n" + "\n".join(hits)


# ---------------------------------------------------------------- BH-03
def test_bh03_kill_orphan_chrome_only_in_allowed_modules():
    allowed = {"browser.py", "diagnostics.py", "database.py"}
    hits = [h for p in phase1_py_files() if p.name not in allowed
            for h in _lines_matching(p, re.compile(r"kill_orphan_chrome"))]
    assert not hits, "BH-03: kill_orphan_chrome chỉ được ở browser.py/diagnostics.py/database.py/tests:\n" + "\n".join(hits)


# ---------------------------------------------------------------- BH-06
def test_bh06_no_reload_flag_in_bat_files():
    hits = [h for p in sorted(ROOT.glob("*.bat")) for h in _lines_matching(p, re.compile(r"--reload"))]
    assert not hits, "BH-06: file .bat cho người dùng không được có --reload:\n" + "\n".join(hits)


# ---------------------------------------------------------------- BH-07
def test_bh07_sqlite3_connect_only_in_database_py():
    hits = [h for p in phase1_py_files() if p.name != "database.py"
            for h in _lines_matching(p, re.compile(r"sqlite3\.connect"))]
    assert not hits, "BH-07: sqlite3.connect chỉ được có trong database.py (dùng database.get_connection):\n" + "\n".join(hits)


# ---------------------------------------------------------------- BH-08
# Khớp cả `except Exception:` lẫn `except Exception as e:` theo sau bởi `pass` (cùng regex với cột Kiểm nhưng rộng hơn)
RE_EXCEPT_PASS = re.compile(r"except\s+Exception(?:\s+as\s+\w+)?\s*:[^\n]*\n\s*pass\b")


def test_bh08_no_swallowed_exceptions():
    hits = []
    for p in phase1_py_files():
        text = read(p)
        for m in RE_EXCEPT_PASS.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append(f"{p.name}:{line_no}")
    assert not hits, f"BH-08: còn `except Exception: pass` ({len(hits)} chỗ): " + ", ".join(hits)


# ---------------------------------------------------------------- BH-09
RE_FAKE_DEFAULT = re.compile(r"else 4\b|1000000000")


def test_bh09_no_fake_default_values():
    hits = [h for p in phase1_py_files() for h in _lines_matching(p, RE_FAKE_DEFAULT)]
    assert not hits, "BH-09: không ghi giá trị mặc định giả (else 4 / 1000000000):\n" + "\n".join(hits)


# ---------------------------------------------------------------- BH-10
# check_env.py chạy TRƯỚC khi cài thư viện (bootstrap trong KHOI_DONG.bat) nên không thể import browser.py;
# nó chỉ DÒ đường dẫn chrome.exe để báo cho người dùng, không mở Chrome → được phép nhắc tên chrome.exe.
BH10_ALLOWED = {"browser.py", "check_env.py"}


def test_bh10_chrome_exe_and_startfile_only_in_browser_py():
    pat = re.compile(r"os\.startfile|startfile\(|chrome\.exe", re.IGNORECASE)
    hits = [h for p in phase1_py_files() if p.name not in BH10_ALLOWED for h in _lines_matching(p, pat)]
    assert not hits, "BH-10: os.startfile / chrome.exe chỉ được có trong browser.py (find_chrome) và check_env.py:\n" + "\n".join(hits)
    # check_env.py tuyệt đối không được mở Chrome (chỉ dò đường dẫn)
    bad = _lines_matching(ROOT / "check_env.py", re.compile(r"os\.startfile|startfile\(|subprocess\.Popen\(.*chrome", re.IGNORECASE))
    assert not bad, "BH-10: check_env.py chỉ được dò đường dẫn, không được mở Chrome:\n" + "\n".join(bad)


# ---------------------------------------------------------------- BH-23
RE_BH_HEADING = re.compile(r"^## BH-(\d+)\s*·", re.MULTILINE)


def _lesson_numbers() -> List[int]:
    return [int(n) for n in RE_BH_HEADING.findall(read(BAI_HOC))]


def test_bh23_lesson_numbers_unique_and_consecutive():
    nums = _lesson_numbers()
    assert nums, "docs/BAI_HOC.md không có mục `## BH-xx ·` nào"
    dup = sorted(n for n, c in Counter(nums).items() if c > 1)
    assert not dup, f"BH-23: số bài học bị trùng (hai agent cùng đánh số): BH-{dup}. Số mới = số lớn nhất + 1"
    assert nums == sorted(nums), f"BH-23: số bài học không tăng dần theo thứ tự trong file: {nums}"
    expected = list(range(1, max(nums) + 1))
    assert nums == expected, f"BH-23: số bài học phải liên tục 1..{max(nums)}, thiếu {sorted(set(expected) - set(nums))}"
