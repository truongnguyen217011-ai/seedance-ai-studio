"""Giữ hành vi TOTP (RFC 6238) của twofa.py."""
import pytest

from twofa import clean_base32_key, generate_totp_code, get_totp_candidates

# Vector chuẩn RFC 6238 (SHA1), secret ASCII "12345678901234567890" = Base32 bên dưới
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
RFC_VECTORS_8 = {59: "94287082", 1111111109: "07081804", 1111111111: "14050471", 1234567890: "89005924", 2000000000: "69279037"}


@pytest.mark.parametrize("ts,code8", sorted(RFC_VECTORS_8.items()))
def test_rfc6238_sha1_vectors(ts, code8):
    assert generate_totp_code(RFC_SECRET, ts, digits=8) == code8
    assert generate_totp_code(RFC_SECRET, ts) == code8[-6:]


def test_rfc_vector_59_is_287082():
    assert generate_totp_code(RFC_SECRET, 59) == "287082"


def test_same_time_step_same_code():
    assert generate_totp_code(RFC_SECRET, 30) == generate_totp_code(RFC_SECRET, 59)
    assert generate_totp_code(RFC_SECRET, 59) != generate_totp_code(RFC_SECRET, 60)


def test_legacy_selftest_candidates():
    codes = get_totp_candidates("JBSWY3DPEHPK3PXP")
    assert len(codes) >= 1
    assert all(len(c) == 6 and c.isdigit() for c in codes)


def test_candidates_cover_clock_drift():
    ts = 1111111111
    codes = get_totp_candidates(RFC_SECRET, ts)
    expected = [generate_totp_code(RFC_SECRET, ts + d) for d in (0, -30, 30)]
    assert codes[0] == expected[0]
    assert set(codes) == set(expected)
    assert len(codes) == len(set(codes))


def test_clean_base32_key_normalises_and_pads():
    assert clean_base32_key("jbsw y3dp-ehpk_3pxp") == "JBSWY3DPEHPK3PXP"
    assert clean_base32_key("ABCDEFGHIJKLMNOPQR") == "ABCDEFGHIJKLMNOPQR" + "=" * 6
    assert generate_totp_code("jbsw y3dp ehpk 3pxp", 59) == generate_totp_code("JBSWY3DPEHPK3PXP", 59)


@pytest.mark.parametrize("bad", ["ABC", "ABCDEFGHIJKLMNOP1", "ABCD2345EFGH6789", "A" * 33])
def test_invalid_secret_rejected(bad):
    with pytest.raises(ValueError):
        clean_base32_key(bad)
    with pytest.raises(ValueError):
        generate_totp_code(bad, 59)


def test_empty_secret_cleans_to_empty_string():
    assert clean_base32_key("") == ""
    assert clean_base32_key(None) == ""


def test_candidates_of_invalid_secret_is_empty():
    assert get_totp_candidates("khong-hop-le") == []
