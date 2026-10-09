"""
Module tạo mã xác thực 2FA (TOTP - RFC 6238)
Hỗ trợ tạo mã xác thực 6 số cho Facebook từ Secret Key Base32
Bao gồm cả bù trừ thời gian (Clock Drift) [-30s, Hiện tại, +30s]
"""
import base64
import hashlib
import hmac
import logging
import struct
import time
import re

log = logging.getLogger("twofa")

def clean_base32_key(secret: str) -> str:
    """
    Làm sạch chuỗi secret Base32: xoá khoảng trắng, dấu gạch nối, chuyển in hoa,
    thêm padding '=' nếu cần.
    """
    if not secret:
        return ""
    # Loại bỏ khoảng cách, dấu gạch ngang
    cleaned = re.sub(r'[\s\-_]', '', secret).upper()
    # Base32 hợp lệ chỉ gồm A-Z và 2-7
    if not re.match(r'^[A-Z2-7]{16,32}$', cleaned):
        raise ValueError("Mã bí mật 2FA không hợp lệ. Cần 16-32 ký tự Base32 (A-Z, 2-7).")
    
    # Bù padding '=' cho đủ bội số của 8
    missing_padding = len(cleaned) % 8
    if missing_padding != 0:
        cleaned += '=' * (8 - missing_padding)
    return cleaned

def generate_totp_code(secret: str, timestamp: int = None, digits: int = 6) -> str:
    """
    Tạo mã TOTP 6 số từ mã bí mật Base32 tại 1 thời điểm timestamp (giây).
    """
    cleaned = clean_base32_key(secret)
    key = base64.b32decode(cleaned)
    
    if timestamp is None:
        timestamp = int(time.time())
        
    time_step = timestamp // 30
    time_bytes = struct.pack(">Q", time_step)
    
    # Tính HMAC-SHA1
    mac = hmac.new(key, time_bytes, hashlib.sha1).digest()
    
    # Dynamic Truncation
    offset = mac[-1] & 0x0F
    code_int = struct.unpack(">I", mac[offset:offset+4])[0] & 0x7FFFFFFF
    code = code_int % (10 ** digits)
    return str(code).zfill(digits)

def get_totp_candidates(secret: str, timestamp: int = None) -> list[str]:
    """
    Tạo danh sách các mã ứng viên chống lệch giờ [Hiện tại, -30s, +30s]
    như cơ chế của HaLi AI (hàm si)
    """
    if timestamp is None:
        timestamp = int(time.time())
        
    candidates = []
    # Thử hiện tại trước, sau đó lệch -30s và +30s
    for delta in [0, -30, 30]:
        t = timestamp + delta
        try:
            code = generate_totp_code(secret, t)
            if code not in candidates:
                candidates.append(code)
        except Exception as e:  # noqa: BLE001 - secret hỏng ở một mốc giờ: bỏ ứng viên đó, không chặn mốc khác (BH-08)
            log.debug("Không tạo được mã TOTP tại mốc %s: %s", t, e)
            continue
    return candidates

if __name__ == "__main__":
    # Test mã mẫu chuẩn
    test_secret = "JBSWY3DPEHPK3PXP" # Base32 secret chuẩn RFC
    codes = get_totp_candidates(test_secret)
    print(f"Test TOTP with {test_secret}: current candidate codes = {codes}")
    assert len(codes) >= 1
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    print("TOTP module test passed successfully!")
