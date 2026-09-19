"""vchat_core._compat · 旧版 import 兼容 shim。

让 vchat 主文件保持「老的 import 写法」就能切到 vchat_core 实现，
避免一次性改 58 处调用。未来主文件重构后这一层可以直接删掉，
改成 `from vchat_core import ...`。
"""

import os
from . import cache as _cache_module
from . import contacts as _contacts
from . import messages as _messages
from . import voice as _voice
from . import content as _content_module


class _PathCache:
    """老接口里 `_cache.get(rel_path)` 返回字符串路径，vchat 旧代码会
    `sqlite3.connect(_cache.get(...))`，所以这层维持 path 语义。
    新代码直接用 `vchat_core.cache.default_cache().get()` 拿连接。
    """

    def __init__(self, real_cache):
        self._real = real_cache

    def get(self, rel_path):
        # 接受 'message/media_0.db' 或 'message\\media_0.db'
        norm = rel_path.replace("\\", "/")
        full = self._real._root / norm
        if not full.exists():
            return None
        return str(full)


_cache = _PathCache(_cache_module.default_cache())


def get_contact_names():
    return _contacts.get_contact_names()


def get_recent_sessions(limit: int = 20) -> str:
    return _messages.get_recent_sessions(limit=limit)


def get_contacts(query: str = "", limit: int = 50) -> str:
    rows = _contacts.search_contacts(query, limit=limit)
    if not rows:
        return f"未找到联系人（搜索: {query or '所有'}）"
    out = [f"找到 {len(rows)} 个联系人（搜索: {query or '所有'}）:", ""]
    for r in rows:
        display = r["remark"] or r["nick_name"] or r["username"]
        line = f"{r['username']}  昵称: {display}"
        alias = r.get("alias") if hasattr(r, "get") else r["alias"]
        if alias:
            line += f"  alias: {alias}"
        desc = r.get("description") if hasattr(r, "get") else r["description"]
        if desc:
            line += f"\n  签名: {desc[:80]}"
        out.append(line)
    return "\n".join(out)


def get_chat_history(chat_name: str, limit: int = 50, offset: int = 0,
                    start_time: str = "", end_time: str = "",
                    oldest_first: bool = False) -> str:
    return _messages.get_chat_history(
        chat_name=chat_name, limit=limit, offset=offset,
        start_time=start_time, end_time=end_time,
        oldest_first=oldest_first,
    )


def search_messages(keyword: str, chat_name=None,
                    start_time: str = "", end_time: str = "",
                    limit: int = 30, offset: int = 0) -> str:
    name = chat_name if isinstance(chat_name, str) else ""
    return _messages.search_messages(
        keyword=keyword, chat_name=name, limit=limit,
    )


def transcribe_voice(chat_name: str, local_id: int) -> str:
    return _voice.transcribe_voice(chat_name, local_id)


def decode_voice(chat_name: str, local_id: int) -> str:
    return _voice.decode_voice(chat_name, local_id)


def _get_self_username():
    return _contacts.get_self_username()


def _decompress_content(content, ct=None):
    return _content_module.decompress_content(content, ct)


def _resolve_chat_context(chat_name: str):
    """老接口返回字段是 `is_group`，新版本叫 `is_chatroom`，这里加别名。"""
    ctx = _contacts.resolve_chat_context(chat_name)
    if ctx is None:
        return None
    ctx["is_group"] = ctx["is_chatroom"]
    return ctx
