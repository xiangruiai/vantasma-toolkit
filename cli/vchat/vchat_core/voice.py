"""vchat_core.voice · 微信语音解码 + 转写。

链路:
    media_0.db.VoiceInfo (chat_name_id INTEGER, local_id, voice_data BLOB)
        → 用 chatroom username 反查 chat_name_id (Name2Id 表)
        → 取 voice_data BLOB
        → pysilk 解码为 PCM
        → 保存 wav
        → openai-whisper 转写
        → 缓存到 voice_transcriptions.json
"""

import hashlib
import json
import os
import struct
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import cache as _cache
from . import contacts as _contacts


# 缓存文件位置（项目目录下）
_CACHE_FILE = (Path(__file__).resolve().parent.parent
               / "voice_transcriptions.json")


def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict):
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _voice_dir() -> Path:
    """解码后的 wav 文件目录（`<data_dir>/decoded_voices/`）。"""
    from . import get_data_dir
    p = get_data_dir() / "decoded_voices"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_chat_name_id(chat_username: str) -> Optional[int]:
    """根据 chatroom username 找 media_0.db.Name2Id 里的 rowid。"""
    try:
        conn = _cache.get("message/media_0.db")
    except FileNotFoundError:
        return None
    row = conn.execute(
        "SELECT rowid FROM Name2Id WHERE user_name=?", (chat_username,)
    ).fetchone()
    return row[0] if row else None


def list_voices(chat_name: str, limit: int = 20) -> str:
    """列某个聊天里的语音消息。"""
    ctx = _contacts.resolve_chat_context(chat_name)
    if not ctx:
        return f"❌ 找不到聊天对象: {chat_name}"
    chat_name_id = _resolve_chat_name_id(ctx["username"])
    if chat_name_id is None:
        return f"{ctx['display_name']} 无语音消息"

    conn = _cache.get("message/media_0.db")
    rows = conn.execute(
        "SELECT local_id, create_time, length(voice_data) AS sz "
        "FROM VoiceInfo WHERE chat_name_id=? "
        "ORDER BY create_time DESC LIMIT ?",
        (chat_name_id, limit),
    ).fetchall()
    if not rows:
        return f"{ctx['display_name']} 无语音消息"

    out = [f"{ctx['display_name']} 的语音（{len(rows)} 条）:"]
    out.append("")
    for r in rows:
        when = datetime.fromtimestamp(r["create_time"]).strftime(
            "%Y-%m-%d %H:%M"
        )
        kb = r["sz"] / 1024
        out.append(f"  local_id={r['local_id']}  [{when}]  {kb:.1f}KB")
    return "\n".join(out)


def voice_stats(top_n: int = 10) -> str:
    """全局语音密度统计：哪些聊天对象语音最多。"""
    try:
        conn = _cache.get("message/media_0.db")
    except FileNotFoundError:
        return "❌ media_0.db 不存在"

    total = conn.execute("SELECT COUNT(*) FROM VoiceInfo").fetchone()[0]
    # 按 chat_name_id 聚合
    rows = conn.execute(
        "SELECT chat_name_id, COUNT(*) AS n FROM VoiceInfo "
        "GROUP BY chat_name_id ORDER BY n DESC LIMIT ?",
        (top_n,),
    ).fetchall()
    # 反查 Name2Id
    n2i_rows = conn.execute(
        "SELECT rowid, user_name FROM Name2Id"
    ).fetchall()
    rowid_to_user = {r["rowid"]: r["user_name"] for r in n2i_rows}
    names = _contacts.get_contact_names()

    out = [f"本机缓存语音消息：{total} 条", "", f"各聊天对象的语音数 top {top_n}:"]
    for r in rows:
        u = rowid_to_user.get(r["chat_name_id"], "?")
        display = names.get(u, u)
        out.append(f"  {r['n']:4d}  {display}")
    return "\n".join(out)


def _decode_silk(silk_bytes: bytes, wav_path: Path) -> float:
    """SILK → WAV。返回时长（秒）。

    需要 pysilk 包。SILK 是微信语音格式，标准 PCM 16-bit mono 24000Hz。
    """
    import io
    try:
        import pysilk
    except ImportError:
        raise RuntimeError(
            "缺少 pysilk。装：pip3 install silk-python"
        )

    # 微信封装格式：第 1 字节 = 0x02，剩下是 SILK_V3 数据
    if silk_bytes[:10] == b"\x02#!SILK_V3":
        payload = silk_bytes
    elif silk_bytes[:1] == b"\x02":
        payload = silk_bytes[1:]
    else:
        payload = silk_bytes

    src = io.BytesIO(payload)
    dst = io.BytesIO()
    pysilk.decode(src, dst, 24000)
    pcm = dst.getvalue()

    # 写 wav（16-bit PCM，单声道，24000Hz）
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)

    # 时长 = pcm 字节数 / (2 * 24000)
    return len(pcm) / (2 * 24000)


def _whisper_transcribe(wav_path: Path, language: str = "zh") -> str:
    """跑 openai-whisper base 模型。"""
    try:
        import whisper
    except ImportError:
        raise RuntimeError(
            "缺少 openai-whisper。"
            "装：pip3 install openai-whisper --break-system-packages"
        )
    model = whisper.load_model("base")
    result = model.transcribe(str(wav_path), language=language)
    return result["text"].strip()


def transcribe_voice(chat_name: str, local_id: int) -> str:
    """转写单条语音。带缓存。

    返回格式：
        [YYYY-MM-DD HH:MM] (zh)
        转写文字
    """
    ctx = _contacts.resolve_chat_context(chat_name)
    if not ctx:
        return f"❌ 找不到聊天对象: {chat_name}"

    chat_name_id = _resolve_chat_name_id(ctx["username"])
    if chat_name_id is None:
        return f"❌ {ctx['display_name']} 无语音"

    conn = _cache.get("message/media_0.db")
    row = conn.execute(
        "SELECT create_time, voice_data FROM VoiceInfo "
        "WHERE chat_name_id=? AND local_id=? LIMIT 1",
        (chat_name_id, local_id),
    ).fetchone()
    if not row:
        return f"❌ 找不到 local_id={local_id} 的语音"

    create_time = row["create_time"]
    voice_data = row["voice_data"]
    cache_key = f"{ctx['username']}|{local_id}|{create_time}"

    cache = _load_cache()
    if cache_key in cache:
        entry = cache[cache_key]
        ts = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M")
        return f"[{ts}] (zh)\n{entry['text']}"

    # 解码 + 转写
    safe_chatroom = ctx["username"].replace("@", "_at_")
    fname = (
        f"{safe_chatroom}_"
        f"{datetime.fromtimestamp(create_time).strftime('%Y%m%d_%H%M%S')}"
        f"_{local_id}.wav"
    )
    wav_path = _voice_dir() / fname
    if not wav_path.exists():
        _decode_silk(voice_data, wav_path)

    text = _whisper_transcribe(wav_path)
    cache[cache_key] = {
        "create_time": create_time,
        "text": text,
        "wav_path": str(wav_path),
    }
    _save_cache(cache)

    ts = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M")
    return f"[{ts}] (zh)\n{text}"


def decode_voice(chat_name: str, local_id: int) -> str:
    """只解码不转写：把 SILK 转成 wav 落到 decoded_voices/。"""
    ctx = _contacts.resolve_chat_context(chat_name)
    if not ctx:
        return f"❌ 找不到聊天对象: {chat_name}"

    chat_name_id = _resolve_chat_name_id(ctx["username"])
    if chat_name_id is None:
        return f"❌ {ctx['display_name']} 无语音"

    conn = _cache.get("message/media_0.db")
    row = conn.execute(
        "SELECT create_time, voice_data FROM VoiceInfo "
        "WHERE chat_name_id=? AND local_id=? LIMIT 1",
        (chat_name_id, local_id),
    ).fetchone()
    if not row:
        return f"❌ 找不到 local_id={local_id} 的语音"

    safe_chatroom = ctx["username"].replace("@", "_at_")
    fname = (
        f"{safe_chatroom}_"
        f"{datetime.fromtimestamp(row['create_time']).strftime('%Y%m%d_%H%M%S')}"
        f"_{local_id}.wav"
    )
    wav_path = _voice_dir() / fname
    duration = _decode_silk(row["voice_data"], wav_path)
    size = wav_path.stat().st_size
    return (
        f"解码成功!\n"
        f"  文件: {wav_path}\n"
        f"  时长: {duration:.1f}秒\n"
        f"  大小: {size:,} bytes"
    )
