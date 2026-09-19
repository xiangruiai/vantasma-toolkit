"""vchat_core.content · 消息 content 解码。

微信消息的 message_content / compress_content 字段，
如果 WCDB_CT_message_content 标记是压缩态，需要先解压（zstd/lz4）。
正常文本消息直接是 UTF-8。富媒体消息通常是 XML。

简化策略:
    - 文本消息直接 UTF-8 解码
    - XML 消息保留原文（让上层正则匹配）
    - 压缩消息尝试 zstd / lz4 解压，失败就返回原文
"""

from typing import Optional


def decompress_content(content: Optional[str], ct_flag: Optional[int] = None) -> str:
    """解压消息内容。

    content: message_content 字段原始值（通常已是 TEXT）
    ct_flag: WCDB_CT_message_content 字段（压缩类型标记，可能不可靠）
    """
    if content is None:
        return ""
    if isinstance(content, bytes):
        # 尝试 UTF-8
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            # 尝试 zstd
            decoded = _try_zstd(content)
            if decoded is not None:
                return decoded
            # 兜底
            return content.decode("utf-8", errors="replace")

    # 已经是 str
    return content


def _try_zstd(data: bytes) -> Optional[str]:
    """尝试 zstd 解压。"""
    try:
        import zstandard as zstd
    except ImportError:
        return None
    try:
        decompressor = zstd.ZstdDecompressor()
        out = decompressor.decompress(data)
        return out.decode("utf-8", errors="replace")
    except Exception:
        return None


def _try_lz4(data: bytes) -> Optional[str]:
    """尝试 lz4 解压。"""
    try:
        import lz4.frame as lz4f
    except ImportError:
        return None
    try:
        out = lz4f.decompress(data)
        return out.decode("utf-8", errors="replace")
    except Exception:
        return None


def parse_money_msg(content: str) -> dict:
    """解析转账消息（local_type=49 + subtype=2000/2001/2003）。

    微信转账消息内容是 XML，含 transferid / paymsgid / pay_memo 等字段。
    红包消息类似但字段不同。

    返回:
        {
            "type": "transfer" | "redpack" | "unknown",
            "memo": "<付款留言>",
            "feedesc": "<金额，如 ¥10.00>",
            "raw": "<完整 XML 原文>",
        }
    """
    if not content or "<msg>" not in content:
        return {"type": "unknown", "memo": "", "feedesc": "", "raw": content}

    import re
    result = {"type": "unknown", "memo": "", "feedesc": "", "raw": content}

    # 转账
    if "<wcpayinfo>" in content:
        result["type"] = "transfer"
        m = re.search(r"<feedesc>(?:<!\[CDATA\[)?([^<\]]+)", content)
        if m:
            result["feedesc"] = m.group(1).strip()
        m = re.search(r"<pay_memo>(?:<!\[CDATA\[)?([^<\]]*)", content)
        if m:
            result["memo"] = m.group(1).strip()

    # 红包
    if "<sendid>" in content or "wxpay/luckymoney" in content:
        result["type"] = "redpack"
        m = re.search(r"<sendertitle>(?:<!\[CDATA\[)?([^<\]]*)", content)
        if m:
            result["memo"] = m.group(1).strip()

    return result


def parse_link_card(content: str) -> dict:
    """解析公众号/链接卡片消息（local_type=49 + subtype=5/6/8）。

    内容是 XML，常见字段 title / des / url / sourcedisplayname。
    """
    if not content or "<msg>" not in content:
        return {"title": "", "des": "", "url": "", "source": "", "raw": content}

    import re
    result = {"title": "", "des": "", "url": "", "source": "", "raw": content}

    for key, field in [
        ("title", "title"),
        ("des", "des"),
        ("url", "url"),
        ("source", "sourcedisplayname"),
    ]:
        m = re.search(
            rf"<{field}>(?:<!\[CDATA\[)?([^<\]]+)(?:\]\]>)?</{field}>",
            content,
        )
        if m:
            result[key] = m.group(1).strip()

    return result
