"""
Module phân tích & bóc tách dòng tài khoản nguyên tử (Smart Account Line Parser)
Tương thích 100% với logic parser của HaLi AI (hàm us & oi)
Hỗ trợ mọi định dạng shop Facebook & Google:
- uid|pass|2fa|cookie|proxy
- uid|pass|2fa
- uid|pass|proxy
- uid|pass|cookie
- Chuỗi cookie c_user=...; xs=...
- Email|Pass|2FA|Proxy (Google/Dola)
- Định dạng copy từ Excel (tab-separated)
"""
import hashlib
import json
import re
from typing import Dict, List, Optional, Tuple

# Các biểu thức chính quy nhận diện thành phần
RE_COOKIE = re.compile(r'(?:^|;|\b)(?:c_user|xs|datr|fr|sb)=', re.IGNORECASE)
RE_DOLA_COOKIE = re.compile(r'(?:^|;|\b)(?:sessionid|sessionid_ss)=', re.IGNORECASE)
RE_TOKEN = re.compile(r'^EAA[A-Za-z0-9]{20,}$')
RE_EMAIL = re.compile(r'^[^\s@|:]+@[^\s@|:]+\.[^\s@|:]+$')
RE_2FA = re.compile(r'^[A-Z2-7]{16,32}$', re.IGNORECASE)
RE_PROXY = re.compile(r'^(?:https?:\/\/|socks[45]:\/\/)?(?:[a-zA-Z0-9_.-]+(?::[^@]+)?@)?[0-9a-zA-Z.-]+:\d+(?::[a-zA-Z0-9_.-]+:[^|\s]+)?$')
RE_DATE = re.compile(r'^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}(\s|$)|^\d{4}-\d{2}-\d{2}')
RE_TITLE_IGNORE = re.compile(r'^(uid|id|stt|tài khoản|tai khoan|account|user)\b', re.IGNORECASE)
# Chuỗi trông như người dùng ĐỊNH đưa mã 2FA nhưng không phải Base32 (A-Z, 2-7): chữ+số 10-40 ký tự, không phải
# toàn số (UID), không có ':' (proxy) hay '.' (email/IP). Dùng để báo "2FA sai định dạng" thay vì lặng lẽ bỏ qua.
# G-1: chỉ coi là "2FA sai định dạng" khi chuỗi dài ≥ 16 (độ dài mã 2FA thật) HOẶC gần Base32 (≥ 14 ký tự, không
# lẫn hoa/thường, tối đa 2 ký tự ngoài A-Z2-7 như 0/1/8/9); cột thừa ngắn kiểu "Nguyenvan2024" là ghi chú → `note`.
RE_2FA_LOOKALIKE = re.compile(r'^[A-Za-z0-9]{10,40}$')
TWOFA_LOOKALIKE_MIN_LEN = 16
TWOFA_NEAR_BASE32_MIN_LEN = 14
TWOFA_NEAR_BASE32_MAX_ODD = 2
RE_NOT_BASE32_CHAR = re.compile(r'[^A-Z2-7]')

# Tên cookie đặc trưng của từng dịch vụ (K3, BH-11): quyết định domain theo NỘI DUNG, không theo loại nick
DOLA_COOKIE_NAMES = frozenset({"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt", "uid_tt_ss", "ttwid",
                               "sid_ucp_v1", "ssid_ucp_v1", "passport_csrf_token", "msToken"})
FACEBOOK_COOKIE_NAMES = frozenset({"c_user", "xs", "datr", "fr", "sb", "wd", "presence", "dpr", "locale"})
COOKIE_KIND_DOLA = "dola"
COOKIE_KIND_FACEBOOK = "facebook"
COOKIE_KIND_JSON = "json"


def detect_cookie_kind(raw) -> Optional[str]:
    """Nhận diện cookie dán vào thuộc dịch vụ nào, chỉ dựa vào NỘI DUNG (K3, BH-11).

    Trả về "dola" (có sessionid/sessionid_ss), "facebook" (có c_user/xs...), "json" (JSON đã có trường domain
    riêng từng cookie, giữ nguyên) hoặc None (không nhận ra cookie nào).
    """
    text = str(raw or "").strip()
    if not text:
        return None
    if text[:1] in "[{":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            data = data.get("cookies", [])
        if isinstance(data, list):
            names = {str(c.get("name", "")) for c in data if isinstance(c, dict)}
            if names & DOLA_COOKIE_NAMES:
                return COOKIE_KIND_DOLA
            if names & FACEBOOK_COOKIE_NAMES:
                return COOKIE_KIND_FACEBOOK
            if any(isinstance(c, dict) and c.get("domain") for c in data):
                return COOKIE_KIND_JSON
            return None
    if RE_DOLA_COOKIE.search(text):
        return COOKIE_KIND_DOLA
    if RE_COOKIE.search(text):
        return COOKIE_KIND_FACEBOOK
    return None


def stable_dola_uid(cookie_text: str) -> str:
    """UID thay thế cho dòng chỉ có cookie Dola (không c_user): băm ỔN ĐỊNH theo giá trị sessionid để dán lại
    cùng cookie ở phiên sau vẫn nhận ra là trùng (BH-51: `hash()` của Python đổi mỗi lần chạy)."""
    m = re.search(r'(?:^|;\s*)sessionid(?:_ss)?=([^;\s]+)', cookie_text)
    key = m.group(1) if m else cookie_text.strip()
    return "Dola_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]

def looks_like_bad_twofa(item: str) -> bool:
    """G-1: chuỗi thừa có phải là mã 2FA sai định dạng (đáng báo lỗi) hay chỉ là ghi chú ngắn (bỏ qua, ghi `note`).

    Báo lỗi khi: chữ+số 10-40 ký tự, không toàn số, VÀ (dài ≥ 16, hoặc gần Base32: ≥ 14 ký tự, chữ cái không lẫn
    hoa/thường, ≤ 2 ký tự ngoài A-Z2-7). "ABCD2345EFGH6789" → True; "Nguyenvan2024" → False.
    """
    item = str(item or "")
    if not RE_2FA_LOOKALIKE.match(item) or item.isdigit():
        return False
    if len(item) >= TWOFA_LOOKALIKE_MIN_LEN:
        return True
    if len(item) < TWOFA_NEAR_BASE32_MIN_LEN:
        return False
    letters = [c for c in item if c.isalpha()]
    mixed_case = any(c.islower() for c in letters) and any(c.isupper() for c in letters)
    if mixed_case:
        return False
    odd = len(RE_NOT_BASE32_CHAR.findall(item.upper()))
    return odd <= TWOFA_NEAR_BASE32_MAX_ODD


def mask_line(line: str) -> str:
    """Che dòng tài khoản để đưa vào phản hồi API / nhật ký (C-2, BH-57): chỉ giữ cột đầu (UID/email), mọi cột còn
    lại (mật khẩu, 2FA, cookie, proxy) thành "***". Dòng chỉ có cookie thô → "c_user=<uid>;***" hoặc "***".
    Không bao giờ trả nguyên dòng người dùng dán cho client hay ghi vào system_logs."""
    text = clean_line_text(line)
    if not text:
        return ""
    sep = '|' if '|' in text else ('\t' if '\t' in text else None)
    parts = [p.strip() for p in text.split(sep)] if sep else [text]
    first = parts[0]
    if RE_COOKIE.search(first) or RE_DOLA_COOKIE.search(first) or '=' in first and ';' in first:
        c_match = re.search(r'(?:^|;\s*)c_user=(\d+)', first)
        first = f"c_user={c_match.group(1)};***" if c_match else "***"
    rest = ["***" for p in parts[1:] if p]
    return "|".join([first] + rest)


def clean_line_text(line: str) -> str:
    """Loại bỏ ký tự BOM, khoảng trắng, gạch đầu dòng, dấu ngoặc kép"""
    t = str(line or '').replace('\ufeff', '').strip()
    t = re.sub(r'^(?:[-*•]\s*|\d+[.)]\s*)', '', t)
    t = t.strip('\'" \t\r\n')
    return t

def parse_single_account_line(raw_line: str) -> Dict[str, Optional[str]]:
    """
    Bóc tách 1 dòng tài khoản đơn lẻ theo cơ chế nguyên tử của HaLi AI.
    """
    text = clean_line_text(raw_line)
    if not text:
        raise ValueError("Dòng trống")

    # 1. Trường hợp chỉ có 1 chuỗi Cookie nguyên bản (không có phân cách | hoặc tab)
    if '|' not in text and '\t' not in text and (RE_COOKIE.search(text) or RE_DOLA_COOKIE.search(text)):
        # Thử trích xuất c_user làm UID
        c_match = re.search(r'(?:^|;\s*)c_user=(\d+)', text)
        uid = c_match.group(1) if c_match else None
        
        # Nếu là Dola cookie mà không có c_user
        if not uid and RE_DOLA_COOKIE.search(text):
            uid = stable_dola_uid(text)
            
        if not uid:
            raise ValueError("Cookie Facebook thiếu c_user")
            
        return {
            "uid": uid,
            "pass": "cookie_login",
            "twofa": None,
            "proxy": None,
            "cookie": text,
            "email": None,
            "account_type": "facebook",
            "name": f"FB {uid[-6:]}",
            "cookie_kind": detect_cookie_kind(text),
            "twofa_invalid": None,
            "unassigned": [],
            "note": "",
        }

    # 2. Trường hợp chuỗi có phân cách (| hoặc Tab)
    sep = '|' if '|' in text else '\t'
    parts = [p.strip() for p in text.split(sep) if p.strip()]
    if not parts:
        raise ValueError("Dòng trống")

    uid = None
    pwd = None
    twofa = None
    proxy = None
    cookie = None
    email = None
    account_type = "facebook"

    # Nếu cột 0 là số nguyên 6-25 chữ số và cột 1 không phải cookie -> Ưu tiên UID | PASS
    remaining = []
    if len(parts) >= 2 and re.match(r'^\d{6,25}$', parts[0]) and not RE_COOKIE.search(parts[0]) and not RE_COOKIE.search(parts[1]):
        uid = parts[0]
        pwd = parts[1]
        remaining = parts[2:]
    elif len(parts) >= 2 and RE_EMAIL.match(parts[0]) and not RE_COOKIE.search(parts[1]):
        email = parts[0]
        uid = email
        pwd = parts[1]
        account_type = "google"
        remaining = parts[2:]
    else:
        remaining = list(parts)

    unassigned = []
    for item in remaining:
        if not item:
            continue
        # Bắt Cookie
        if RE_COOKIE.search(item) or RE_DOLA_COOKIE.search(item):
            cookie = item
            c_match = re.search(r'(?:^|;\s*)c_user=(\d+)', item)
            if c_match and not uid:
                uid = c_match.group(1)
            continue

        # Bỏ qua Token và Ngày tháng
        if RE_TOKEN.match(item) or RE_DATE.match(item):
            continue

        # Bắt Email
        if RE_EMAIL.match(item):
            if not email:
                email = item
            continue

        # Bắt 2FA Base32 Authenticator
        clean_2fa = re.sub(r'[\s\-_]', '', item).upper()
        if (RE_2FA.match(clean_2fa) and 16 <= len(clean_2fa) <= 32 
                and ':' not in item and '.' not in item and not item.isdigit()):
            if not twofa:
                twofa = clean_2fa
            continue

        # Bắt Proxy
        if (':' in item) and (RE_PROXY.match(item) or re.search(r':\d{2,5}', item)):
            if not proxy:
                proxy = item
            continue

        unassigned.append(item)

    # Gán dự phòng từ unassigned
    if not uid and unassigned:
        # Tìm phần tử là dãy số UID trước
        found_idx = next((i for i, v in enumerate(unassigned) if re.match(r'^\d{6,25}$', v)), -1)
        if found_idx != -1:
            uid = unassigned.pop(found_idx)
        elif email:
            uid = email
            account_type = "google"
        else:
            uid = unassigned.pop(0)

    if not pwd and unassigned:
        pwd = unassigned.pop(0)
    elif not pwd and cookie:
        pwd = "cookie_login"

    if not uid and email:
        uid = email
        account_type = "google"

    if not uid:
        raise ValueError("Không tìm thấy UID Facebook hoặc Email trong dòng này")
    if not pwd:
        raise ValueError("Thiếu mật khẩu hoặc Cookie đăng nhập")

    uid = str(uid).replace(" ", "")

    # Chuỗi thừa trông như mã 2FA nhưng không phải Base32 → báo cho người dùng (không lặng lẽ bỏ); cột thừa ngắn
    # (tên, ghi chú) không bị coi là 2FA (G-1) mà gom vào `note`
    twofa_invalid = None
    if not twofa:
        for item in unassigned:
            if looks_like_bad_twofa(item):
                twofa_invalid = item
                break
    note = ", ".join(item for item in unassigned if item != twofa_invalid)

    # Đặt tên gợi nhớ
    if account_type == "google" and email:
        name = email.split('@')[0]
    else:
        name = f"FB {uid[-6:]}" if len(uid) >= 6 else f"FB {uid}"

    return {
        "uid": uid,
        "pass": pwd,
        "twofa": twofa,
        "proxy": proxy,
        "cookie": cookie,
        "email": email,
        "account_type": account_type,
        "name": name,
        "cookie_kind": detect_cookie_kind(cookie) if cookie else None,
        "twofa_invalid": twofa_invalid,
        "unassigned": unassigned,
        "note": note,
    }


def twofa_invalid_reason(token: str) -> str:
    return (f"Mã 2FA '{token}' sai định dạng: phải là Base32 (chữ A-Z và số 2-7, 16-32 ký tự, có thể có khoảng trắng); "
            f"bỏ qua dòng này để không tạo nick thiếu 2FA")


def parse_multiple_account_lines(text: str, strict_2fa: bool = False) -> Tuple[List[Dict], List[Dict]]:
    """
    Phân tích toàn bộ khối văn bản nhiều dòng (từ file hoặc copy-paste).
    Trả về: (danh_sach_hop_le, danh_sach_loi). `errors[].text` là dòng ĐÃ CHE (mask_line: chỉ cột đầu, còn lại "***",
    BH-57) vì danh sách này đi thẳng ra API và nhật ký.

    strict_2fa=True (A1): dòng có chuỗi trông như mã 2FA nhưng không phải Base32 bị đưa vào danh sách lỗi với lý do
    rõ, thay vì tạo nick không có 2FA rồi Auto Login thất bại về sau.
    """
    ok_list = []
    errors = []
    seen_uids = set()

    clean_text = str(text or '').replace('\ufeff', '')
    lines = clean_text.splitlines()

    for idx, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        # Bỏ qua dòng tiêu đề nếu người dùng copy cả header từ bảng Excel
        if not ('|' in line) and RE_TITLE_IGNORE.match(line):
            continue

        try:
            parsed = parse_single_account_line(line)
            if strict_2fa and parsed.get("twofa_invalid"):
                errors.append({"line": idx, "text": mask_line(line), "reason": twofa_invalid_reason(parsed["twofa_invalid"])})
                continue
            uid = parsed["uid"]
            if uid in seen_uids:
                errors.append({
                    "line": idx,
                    "text": mask_line(line),
                    "reason": f"UID {uid} bị trùng với dòng trước đó (đã bỏ qua)"
                })
                continue

            seen_uids.add(uid)
            parsed["line"] = idx
            ok_list.append(parsed)
        except Exception as e:
            errors.append({
                "line": idx,
                "text": mask_line(line),
                "reason": str(e)
            })

    return ok_list, errors

if __name__ == "__main__":
    # Test thử các định dạng shop phổ biến
    samples = """
    # File shop Facebook test
    100089274921029|Pass123456|JBSWY3DPEHPK3PXP|c_user=100089274921029; xs=abcd123;|103.151.246.12:8080
    61592837492819|Password@2024|ABCD2345EFGH6789|user@gmail.com
    c_user=10007788990011; xs=secretxs; datr=secret_datr;
    shopclone@gmail.com|GooglePass99|160.250.166.25:10060
    """
    oks, errs = parse_multiple_account_lines(samples)
    print(f"Parse result: OK={len(oks)}, Errors={len(errs)}")
    for item in oks:
        print(f" -> [{item['account_type'].upper()}] {item['name']} | UID: {item['uid']} | 2FA: {item['twofa']} | Proxy: {item['proxy']} | Cookie: {bool(item['cookie'])}")
    assert len(oks) == 4
    print("Smart Parser module test passed successfully!")
