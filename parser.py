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
import re
from typing import Dict, List, Tuple, Optional

# Các biểu thức chính quy nhận diện thành phần
RE_COOKIE = re.compile(r'(?:^|;|\b)(?:c_user|xs|datr|fr|sb)=', re.IGNORECASE)
RE_DOLA_COOKIE = re.compile(r'(?:^|;|\b)(?:sessionid|sessionid_ss)=', re.IGNORECASE)
RE_TOKEN = re.compile(r'^EAA[A-Za-z0-9]{20,}$')
RE_EMAIL = re.compile(r'^[^\s@|:]+@[^\s@|:]+\.[^\s@|:]+$')
RE_2FA = re.compile(r'^[A-Z2-7]{16,32}$', re.IGNORECASE)
RE_PROXY = re.compile(r'^(?:https?:\/\/|socks[45]:\/\/)?(?:[a-zA-Z0-9_.-]+(?::[^@]+)?@)?[0-9a-zA-Z.-]+:\d+(?::[a-zA-Z0-9_.-]+:[^|\s]+)?$')
RE_DATE = re.compile(r'^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}(\s|$)|^\d{4}-\d{2}-\d{2}')
RE_TITLE_IGNORE = re.compile(r'^(uid|id|stt|tài khoản|tai khoan|account|user)\b', re.IGNORECASE)

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

    # 1. Trường hợp là JSON (Cookie-Editor, J2TEAM, Playwright storage_state)
    if (text.startswith('[') and text.endswith(']')) or (text.startswith('{') and text.endswith('}')):
        try:
            import json
            jdata = json.loads(text)
            c_list = jdata if isinstance(jdata, list) else (jdata.get("cookies", []) if isinstance(jdata, dict) else [])
            if c_list and isinstance(c_list, list):
                # Tìm c_user hoặc sessionid
                c_user_val = None
                session_val = None
                for c in c_list:
                    if not isinstance(c, dict):
                        continue
                    cname = c.get("name", "")
                    if cname == "c_user" and c.get("value"):
                        c_user_val = str(c["value"]).strip()
                    elif cname in ("sessionid", "sessionid_ss") and c.get("value"):
                        session_val = str(c["value"]).strip()

                if c_user_val:
                    return {
                        "uid": c_user_val,
                        "pass": "cookie_login",
                        "twofa": None,
                        "proxy": None,
                        "cookie": text,
                        "email": None,
                        "account_type": "facebook",
                        "name": f"FB {c_user_val[-6:]}" if len(c_user_val) >= 6 else f"FB {c_user_val}"
                    }
                if session_val:
                    uid = f"Dola_{abs(hash(session_val)) % 1000000}"
                    return {
                        "uid": uid,
                        "pass": "cookie_login",
                        "twofa": None,
                        "proxy": None,
                        "cookie": text,
                        "email": None,
                        "account_type": "facebook",
                        "name": f"Dola {uid[-6:]}"
                    }
                raise ValueError("Cookie JSON không chứa c_user (Facebook) hoặc sessionid (Dola)")
        except json.JSONDecodeError:
            pass

    # 2. Trường hợp chỉ có 1 chuỗi Cookie nguyên bản (không có phân cách | hoặc tab)
    if '|' not in text and '\t' not in text and (RE_COOKIE.search(text) or RE_DOLA_COOKIE.search(text)):
        # Thử trích xuất c_user làm UID
        c_match = re.search(r'(?:^|;\s*)c_user=(\d+)', text)
        uid = c_match.group(1) if c_match else None
        
        # Nếu là Dola cookie mà không có c_user
        if not uid and RE_DOLA_COOKIE.search(text):
            uid = f"Dola_{abs(hash(text)) % 1000000}"
            
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
            "name": f"FB {uid[-6:]}"
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
        "name": name
    }

def parse_multiple_account_lines(text: str) -> Tuple[List[Dict], List[Dict]]:
    """
    Phân tích toàn bộ khối văn bản nhiều dòng (từ file hoặc copy-paste).
    Trả về: (danh_sach_hop_le, danh_sach_loi)
    """
    ok_list = []
    errors = []
    seen_uids = set()

    clean_text = str(text or '').replace('\ufeff', '')
    stripped = clean_text.strip()
    if (stripped.startswith('[') and stripped.endswith(']')) or (stripped.startswith('{') and stripped.endswith('}')):
        try:
            parsed = parse_single_account_line(stripped)
            parsed["line"] = 1
            return [parsed], []
        except Exception:
            # Nếu không phải một khối cookie đơn lẻ, fallback về duyệt từng dòng
            pass

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
            uid = parsed["uid"]
            if uid in seen_uids:
                errors.append({
                    "line": idx,
                    "text": line,
                    "reason": f"UID {uid} bị trùng với dòng trước đó (đã bỏ qua)"
                })
                continue

            seen_uids.add(uid)
            parsed["line"] = idx
            ok_list.append(parsed)
        except Exception as e:
            errors.append({
                "line": idx,
                "text": line,
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
