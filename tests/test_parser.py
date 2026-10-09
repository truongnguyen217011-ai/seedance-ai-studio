"""Giữ hành vi parser dòng tài khoản (chuyển từ self-test cuối parser.py + các ca bổ sung)."""
import pytest

from parser import clean_line_text, parse_multiple_account_lines, parse_single_account_line

UID = "100089274921029"
TWOFA = "JBSWY3DPEHPK3PXP"
COOKIE = f"c_user={UID}; xs=abcd123;"
PROXY = "103.151.246.12:8080"


def test_legacy_selftest_samples():
    samples = f"""
    # File shop Facebook test
    {UID}|Pass123456|{TWOFA}|{COOKIE}|{PROXY}
    61592837492819|Password@2024|ABCD2345EFGH6789|user@gmail.com
    c_user=10007788990011; xs=secretxs; datr=secret_datr;
    shopclone@gmail.com|GooglePass99|160.250.166.25:10060
    """
    oks, errs = parse_multiple_account_lines(samples)
    assert errs == []
    assert len(oks) == 4
    assert [o["account_type"] for o in oks] == ["facebook", "facebook", "facebook", "google"]
    # "ABCD2345EFGH6789" chứa 8/9 (không phải Base32) nên không được nhận là 2FA
    assert oks[1]["email"] == "user@gmail.com" and oks[1]["twofa"] is None


def test_uid_pass_2fa():
    r = parse_single_account_line(f"{UID}|Pass123456|{TWOFA}")
    assert r["uid"] == UID and r["pass"] == "Pass123456" and r["twofa"] == TWOFA
    assert r["proxy"] is None and r["cookie"] is None and r["email"] is None
    assert r["account_type"] == "facebook" and r["name"] == f"FB {UID[-6:]}"


def test_uid_pass_2fa_proxy():
    r = parse_single_account_line(f"{UID}|Pass123456|{TWOFA}|{PROXY}")
    assert (r["uid"], r["pass"], r["twofa"], r["proxy"]) == (UID, "Pass123456", TWOFA, PROXY)
    assert r["cookie"] is None


def test_uid_pass_cookie():
    r = parse_single_account_line(f"{UID}|Pass123456|{COOKIE}")
    assert r["uid"] == UID and r["pass"] == "Pass123456"
    assert r["cookie"] == COOKIE and r["twofa"] is None and r["proxy"] is None


def test_uid_pass_2fa_cookie_proxy():
    r = parse_single_account_line(f"{UID}|Pass123456|{TWOFA}|{COOKIE}|{PROXY}")
    assert r == {
        "uid": UID, "pass": "Pass123456", "twofa": TWOFA, "proxy": PROXY, "cookie": COOKIE,
        "email": None, "account_type": "facebook", "name": f"FB {UID[-6:]}",
    }


def test_tab_separated_from_excel():
    r = parse_single_account_line(f"{UID}\tPass123456\t{TWOFA}\t{PROXY}")
    assert (r["uid"], r["pass"], r["twofa"], r["proxy"]) == (UID, "Pass123456", TWOFA, PROXY)


def test_raw_cookie_only():
    raw = "c_user=10007788990011; xs=secretxs; datr=secret_datr;"
    r = parse_single_account_line(raw)
    assert r["uid"] == "10007788990011" and r["pass"] == "cookie_login"
    assert r["cookie"] == raw and r["name"] == "FB 990011"


def test_raw_dola_cookie_without_c_user_gets_synthetic_uid():
    r = parse_single_account_line("sessionid=abc123def; sessionid_ss=xyz")
    assert r["uid"].startswith("Dola_") and r["pass"] == "cookie_login"
    assert r["cookie"].startswith("sessionid=")


def test_raw_facebook_cookie_without_c_user_rejected():
    with pytest.raises(ValueError, match="c_user"):
        parse_single_account_line("xs=secretxs; datr=secret_datr;")


def test_email_pass_proxy_google():
    r = parse_single_account_line("shopclone@gmail.com|GooglePass99|160.250.166.25:10060")
    assert r["account_type"] == "google"
    assert r["uid"] == "shopclone@gmail.com" and r["email"] == "shopclone@gmail.com"
    assert r["pass"] == "GooglePass99" and r["proxy"] == "160.250.166.25:10060"
    assert r["name"] == "shopclone"


@pytest.mark.parametrize("proxy", [
    "103.151.246.12:8080:user1:pw1",
    "http://u:p@1.2.3.4:8080",
    "socks5://u:p@1.2.3.4:1080",
])
def test_proxy_formats(proxy):
    r = parse_single_account_line(f"{UID}|Pass123456|{proxy}")
    assert r["proxy"] == proxy and r["twofa"] is None


def test_2fa_with_spaces_is_normalised():
    r = parse_single_account_line(f"{UID}|Pass123456|jbsw y3dp ehpk 3pxp")
    assert r["twofa"] == TWOFA


def test_duplicate_uid_reported():
    oks, errs = parse_multiple_account_lines(f"{UID}|Pass1\n{UID}|Pass2\n")
    assert len(oks) == 1 and oks[0]["pass"] == "Pass1" and oks[0]["line"] == 1
    assert len(errs) == 1 and errs[0]["line"] == 2
    assert "trùng" in errs[0]["reason"] and UID in errs[0]["reason"]


def test_blank_comment_and_header_lines_skipped():
    text = "\n# ghi chú\n\nuid\tpass\t2fa\n" + f"{UID}|Pass1\n"
    oks, errs = parse_multiple_account_lines(text)
    assert errs == []
    assert [o["uid"] for o in oks] == [UID]
    assert oks[0]["line"] == 5


def test_invalid_line_reported_with_reason():
    oks, errs = parse_multiple_account_lines("chi-co-mot-cot\n")
    assert oks == [] and len(errs) == 1
    assert errs[0]["line"] == 1 and errs[0]["reason"]


def test_empty_line_raises():
    with pytest.raises(ValueError):
        parse_single_account_line("   ")


def test_clean_line_text_strips_bom_bullets_quotes():
    assert clean_line_text('﻿- "100089274921029|x" ') == "100089274921029|x"
    assert clean_line_text("1) abc") == "abc"
