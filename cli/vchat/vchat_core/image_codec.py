"""vchat_core.image_codec · 微信图片 .dat 文件解码（纯自写）

支持两种格式：
  · 旧格式：单字节 XOR 加密。key 通过比对文件头与已知图片 magic 自动检测。
  · V1/V2  ：`\\x07\\x08V1\\x08\\x07` 或 `\\x07\\x08V2\\x08\\x07` 头 + AES-128-ECB + raw + 尾部 XOR
            - V1 用固定 key (md5("0")[:16])
            - V2 用动态 key（从微信进程内存提的 image_aes_key）

V2 文件结构：
  [6B magic] [4B aes_size LE] [4B xor_size LE] [1B padding]
  [aligned_aes_size bytes AES-ECB] [raw_data] [xor_size bytes XOR]

文件路径：
  ~/Library/Containers/.../msg/attach/<md5(username)>/<YYYY-MM>/Img/<file_md5>[_t|_h].dat

参考公开算法规范（不抄第三方源码实现）：
  · WCDB README / Tencent 公开博客
  · 多个开源图片解密项目对该格式的 README 描述
"""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# Magic bytes
V2_MAGIC_4   = b"\x07\x08V2"          # 前 4 字节用于快速检测
V2_MAGIC_6   = b"\x07\x08V2\x08\x07"
V1_MAGIC_6   = b"\x07\x08V1\x08\x07"

# 各种图片格式的 magic（按可靠度降序，越长越靠前）
IMAGE_MAGICS = [
    (b"\x89PNG",          "png"),
    (b"GIF8",             "gif"),
    (b"II*\x00",          "tif"),
    (b"RIFF",             "webp"),   # 还需后续 8..12 字节是 "WEBP"
    (b"\xff\xd8\xff",     "jpg"),
]
# BMP 单独处理（只 2 字节 magic 不可靠）


def detect_format(head: bytes) -> str:
    """根据前 16 字节判断图片格式。返回 'jpg'/'png'/'gif'/'bmp'/'webp'/'tif'/'bin'。"""
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:4] == b"\x89PNG":
        return "png"
    if head[:3] == b"GIF":
        return "gif"
    if head[:4] == b"RIFF" and len(head) >= 12 and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] == b"II*\x00":
        return "tif"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] == b"wxgf":
        return "hevc"  # 微信视频号短视频
    return "bin"


def detect_xor_key(path: Path) -> Optional[int]:
    """旧格式：通过 XOR(header[0], known_magic[0]) 反推单字节 key。"""
    with open(path, "rb") as f:
        head = f.read(16)
    if len(head) < 4:
        return None
    if head[:4] == V2_MAGIC_4:
        return None  # V2 不是 XOR

    # 优先匹配 3+ 字节 magic（可靠）
    for magic, _fmt in IMAGE_MAGICS:
        if len(magic) < 3 or len(head) < len(magic):
            continue
        key = head[0] ^ magic[0]
        ok = True
        for i in range(1, len(magic)):
            if (head[i] ^ key) != magic[i]:
                ok = False
                break
        if ok:
            return key

    # 兜底 BMP（2 字节 magic + 额外 sanity check）
    key = head[0] ^ ord("B")
    if len(head) >= 2 and (head[1] ^ key) == ord("M") and len(head) >= 14:
        dec = bytes(b ^ key for b in head[:14])
        size = struct.unpack_from("<I", dec, 2)[0]
        offset = struct.unpack_from("<I", dec, 10)[0]
        file_size = path.stat().st_size
        if abs(size - file_size) < 1024 and 14 <= offset <= 1078:
            return key
    return None


def xor_decrypt(path: Path, out_path: Optional[Path] = None,
                xor_key: Optional[int] = None) -> Tuple[Optional[Path], Optional[str]]:
    """旧格式：纯单字节 XOR 解密。"""
    if xor_key is None:
        xor_key = detect_xor_key(path)
    if xor_key is None:
        return None, None
    with open(path, "rb") as f:
        data = f.read()
    plain = bytes(b ^ xor_key for b in data)
    fmt = detect_format(plain[:16])
    if out_path is None:
        out_path = path.with_suffix(f".{fmt}")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(plain)
    return Path(out_path), fmt


def _aes_ecb_decrypt(key: bytes, ct: bytes) -> bytes:
    """AES-128-ECB 解密 + 去 PKCS7 填充。key 必须 16 字节。"""
    if len(key) != 16:
        raise ValueError(f"AES-128 key must be 16 bytes, got {len(key)}")
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    pt = cipher.decryptor().update(ct) + cipher.decryptor().finalize()
    # PKCS7 unpad
    if not pt:
        return pt
    pad = pt[-1]
    if 0 < pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
        pt = pt[:-pad]
    return pt


def v2_decrypt(path: Path, out_path: Optional[Path] = None,
               aes_key: Optional[bytes | str] = None,
               xor_key: int = 0x88) -> Tuple[Optional[Path], Optional[str]]:
    """V1/V2 格式解密。

    Args:
        path:    .dat 文件
        out_path: 输出（None 时自动按 magic 推扩展名）
        aes_key:  V2 需要的 16 字节 key（bytes 或 hex/ascii 字符串）
                  V1 文件忽略此参数，自动用固定 key
        xor_key:  尾部 XOR 段的 key（默认 0x88）

    Returns:
        (output_path, format) 或 (None, None) 失败
    """
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 15:
        return None, None
    sig = data[:6]
    if sig not in (V1_MAGIC_6, V2_MAGIC_6):
        return None, None

    # V1 固定 key = md5("0")[:16]
    if sig == V1_MAGIC_6:
        aes_key_b = hashlib.md5(b"0").hexdigest()[:16].encode("ascii")
    else:
        if aes_key is None:
            return None, None
        if isinstance(aes_key, str):
            aes_key_b = aes_key.encode("ascii")[:16]
        else:
            aes_key_b = aes_key[:16]
        if len(aes_key_b) < 16:
            return None, None

    if isinstance(xor_key, str):
        xor_key = int(xor_key, 0)

    aes_size, xor_size = struct.unpack_from("<LL", data, 6)

    # AES 填充对齐：实际密文 >= aes_size 且向上对齐到 16
    # 若 aes_size 已是 16 倍数，还需再加 16（完整填充块）。
    aligned = aes_size + (16 - aes_size % 16)

    offset = 15
    if offset + aligned > len(data):
        return None, None

    aes_data = data[offset:offset + aligned]
    try:
        dec_aes = _aes_ecb_decrypt(aes_key_b, aes_data)
    except Exception:
        return None, None
    offset += aligned

    raw_end = len(data) - xor_size
    raw_data = data[offset:raw_end] if offset < raw_end else b""

    xor_data = data[raw_end:]
    dec_xor = bytes(b ^ xor_key for b in xor_data)

    plain = dec_aes + raw_data + dec_xor
    fmt = detect_format(plain[:16])

    if out_path is None:
        # 去掉 _t / _h 后缀
        base = str(path)
        for suf in (".dat", "_t.dat", "_h.dat"):
            if base.endswith(suf):
                base = base[:-len(suf)]
                break
        out_path = Path(f"{base}.{fmt}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(plain)
    return out_path, fmt


def decrypt_dat(path: Path, out_path: Optional[Path] = None,
                aes_key: Optional[bytes | str] = None,
                xor_key: int = 0x88) -> Tuple[Optional[Path], Optional[str]]:
    """自适应入口：先看 magic 是 V1/V2 还是旧 XOR，自动派发。"""
    path = Path(path)
    with open(path, "rb") as f:
        head = f.read(6)
    if head[:4] == V2_MAGIC_4 or head == V1_MAGIC_6:
        return v2_decrypt(path, out_path, aes_key=aes_key, xor_key=xor_key)
    return xor_decrypt(path, out_path)


__all__ = [
    "decrypt_dat",
    "v2_decrypt",
    "xor_decrypt",
    "detect_format",
    "detect_xor_key",
]
