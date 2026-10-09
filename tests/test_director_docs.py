"""P7: docs/DAO_DIEN_MAU.md phải khớp bộ quy tắc director.py hiện tại (sinh lại bằng tests/gen_dao_dien_mau.py)."""
from __future__ import annotations

import pathlib

import gen_dao_dien_mau

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_dao_dien_mau_doc_is_up_to_date():
    doc = ROOT / "docs" / "DAO_DIEN_MAU.md"
    assert doc.exists(), "chưa có docs/DAO_DIEN_MAU.md: chạy `python tests/gen_dao_dien_mau.py`"
    current = doc.read_text(encoding="utf-8")
    expected = gen_dao_dien_mau.build_markdown()
    assert current == expected, "docs/DAO_DIEN_MAU.md lệch với director.py: chạy `python tests/gen_dao_dien_mau.py` rồi commit cùng"


def test_dao_dien_mau_doc_has_no_fixed_action_sentence():
    doc = (ROOT / "docs" / "DAO_DIEN_MAU.md").read_text(encoding="utf-8")
    assert "Hollywood blockbuster action masterpiece" not in doc
    assert doc.count("### ") == 30
