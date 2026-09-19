"""vchat_core.crypto · SQLCipher v4 解密器（纯自写）

参考的公开规范：
  · Zetetic SQLCipher Design Doc (https://www.zetetic.net/sqlcipher/design/)
  · SQLite File Format (https://www.sqlite.org/fileformat.html)

参数（SQLCipher v4 默认 + 微信实测一致）：
  · Cipher:       AES-256-CBC
  · KDF:          PBKDF2-HMAC-SHA512
  · KDF iter:     256000（passphrase 模式；raw key 模式跳过 KDF）
  · Fast iter:    2（mac_key 派生）
  · HMAC:         HMAC-SHA512
  · Page size:    4096
  · Reserve:      80（= 16 IV + 64 HMAC）
  · Salt:         前 16 字节

页面布局：
  Page 1: salt(16) || ciphertext(4000) || iv(16) || hmac(64)
  Page N: ciphertext(4016) || iv(16) || hmac(64)

raw key 模式（微信使用）：
  · key 直接是 32 字节，跳过 PBKDF2(passphrase)
  · mac_key = PBKDF2-HMAC-SHA512(enc_key, salt XOR 0x3a, iter=2, dklen=64)
"""

import hmac
import hashlib
import struct
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


PAGE_SIZE = 4096
RESERVE_SIZE = 80
IV_SIZE = 16
HMAC_SIZE = 64
SALT_SIZE = 16
FAST_KDF_ITER = 2


SQLITE_HEADER = b"SQLite format 3\x00"


def derive_mac_key(enc_key: bytes, salt: bytes) -> bytes:
    """从加密 key + salt 派生 HMAC key。

    PBKDF2-HMAC-SHA512(enc_key, salt XOR 0x3a, iter=2, dklen=32)
    输出 32 字节 mac_key（HMAC-SHA512 接受任意长度 key）。
    """
    if len(enc_key) != 32:
        raise ValueError(f"enc_key 必须 32 字节，实际 {len(enc_key)}")
    if len(salt) != SALT_SIZE:
        raise ValueError(f"salt 必须 16 字节，实际 {len(salt)}")
    mac_salt = bytes(b ^ 0x3a for b in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, FAST_KDF_ITER, dklen=32)


def decrypt_page(page_data: bytes, page_num: int, enc_key: bytes, mac_key: bytes,
                 is_first_page: bool, verify_hmac: bool = True) -> bytes:
    """解一页。返回 4096 字节明文页（首页含 SQLite header）。

    Args:
        page_data: 4096 字节加密页
        page_num: 页号（1-indexed）
        enc_key: 32 字节 AES 密钥
        mac_key: 64 字节 HMAC 密钥
        is_first_page: 是否第一页（前 16 字节是 salt）
        verify_hmac: 是否校验 HMAC（默认开；调参数时可关）
    """
    if len(page_data) != PAGE_SIZE:
        raise ValueError(f"page 必须 {PAGE_SIZE} 字节，实际 {len(page_data)}")

    # 微信消息分片可能包含未分配的稀疏页。该页在磁盘上保持全零，
    # 没有 IV/HMAC；将其视为空白页，不能因为它没有认证尾部而中断整库解密。
    if not any(page_data):
        return bytes(PAGE_SIZE)

    if is_first_page:
        # 跳过前 16 字节 salt
        ct_start = SALT_SIZE
        ct_len = PAGE_SIZE - SALT_SIZE - RESERVE_SIZE  # 4000
    else:
        ct_start = 0
        ct_len = PAGE_SIZE - RESERVE_SIZE  # 4016

    ciphertext = page_data[ct_start:ct_start + ct_len]
    iv = page_data[ct_start + ct_len:ct_start + ct_len + IV_SIZE]
    tag = page_data[ct_start + ct_len + IV_SIZE:ct_start + ct_len + IV_SIZE + HMAC_SIZE]

    if verify_hmac:
        h = hmac.new(mac_key, digestmod=hashlib.sha512)
        h.update(ciphertext)
        h.update(iv)
        h.update(struct.pack("<I", page_num))
        if not hmac.compare_digest(h.digest(), tag):
            raise ValueError(f"HMAC 校验失败 page={page_num}")

    cipher = Cipher(algorithms.AES(enc_key), modes.CBC(iv))
    plaintext = cipher.decryptor().update(ciphertext) + cipher.decryptor().finalize()

    if is_first_page:
        # SQLite header(16) + decrypted(4000) + reserve_zeros(80) = 4096
        return SQLITE_HEADER + plaintext + bytes(RESERVE_SIZE)
    else:
        # decrypted(4016) + reserve_zeros(80) = 4096
        return plaintext + bytes(RESERVE_SIZE)


def decrypt_db(encrypted_path: Path, output_path: Path, raw_key_hex: str,
               max_pages: Optional[int] = None) -> dict:
    """解密整个 db 文件，写到 output_path。

    Args:
        encrypted_path: 加密 db 路径
        output_path: 明文 db 输出路径
        raw_key_hex: 64 字符 hex（32 字节）的 raw key
        max_pages: 最多解多少页（None = 全部）

    Returns:
        {"pages": N, "salt_hex": "...", "verified": True}
    """
    raw_key = bytes.fromhex(raw_key_hex.replace(" ", ""))
    if len(raw_key) != 32:
        raise ValueError(f"raw key 必须 32 字节 (64 hex chars)，实际 {len(raw_key)} 字节")

    encrypted_path = Path(encrypted_path)
    output_path = Path(output_path)

    size = encrypted_path.stat().st_size
    if size % PAGE_SIZE != 0:
        raise ValueError(f"db 大小 {size} 不是 {PAGE_SIZE} 的整数倍 — 可能不是 SQLCipher db 或被截断")
    n_pages = size // PAGE_SIZE
    if max_pages is not None:
        n_pages = min(n_pages, max_pages)

    # 读 first page 拿 salt + 派生 mac_key
    with open(encrypted_path, "rb") as f:
        first_page = f.read(PAGE_SIZE)
    salt = first_page[:SALT_SIZE]
    mac_key = derive_mac_key(raw_key, salt)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as out, open(encrypted_path, "rb") as inp:
        for pg in range(1, n_pages + 1):
            page = inp.read(PAGE_SIZE)
            if len(page) != PAGE_SIZE:
                break  # 文件末尾对不齐
            plain = decrypt_page(page, pg, raw_key, mac_key, is_first_page=(pg == 1))
            out.write(plain)

    return {
        "pages": n_pages,
        "salt_hex": salt.hex(),
        "verified": True,
    }


def quick_verify_key(encrypted_path: Path, raw_key_hex: str) -> bool:
    """快速校验：只解第一页 + HMAC 检查。用于 key 候选筛选。"""
    try:
        raw_key = bytes.fromhex(raw_key_hex.replace(" ", ""))
        if len(raw_key) != 32:
            return False
        with open(encrypted_path, "rb") as f:
            page = f.read(PAGE_SIZE)
        if len(page) != PAGE_SIZE:
            return False
        salt = page[:SALT_SIZE]
        mac_key = derive_mac_key(raw_key, salt)
        decrypt_page(page, 1, raw_key, mac_key, is_first_page=True, verify_hmac=True)
        return True
    except Exception:
        return False


__all__ = [
    "decrypt_db",
    "decrypt_page",
    "derive_mac_key",
    "quick_verify_key",
    "PAGE_SIZE",
    "RESERVE_SIZE",
]
