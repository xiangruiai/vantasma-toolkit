"""vchat_core.contacts · 联系人、群成员、聊天上下文解析。"""

import re
from typing import Optional

from . import cache as _cache


# 微信 contact 表的 local_type 含义（实测推断）
# 1 = 单聊好友, 2 = 群聊, 3 = 系统/陌生联系人, 5/6/7 = 公众号/小程序/其他
LOCAL_TYPE_FRIEND = 1
LOCAL_TYPE_CHATROOM = 2


def get_contact_names() -> dict[str, str]:
    """返回 {wxid: 显示名}，优先级 remark > nick_name > username。

    包含所有 local_type，含群、好友、陌生人。
    """
    conn = _cache.get("contact/contact.db")
    rows = conn.execute(
        "SELECT username, nick_name, remark FROM contact"
    ).fetchall()
    result = {}
    for row in rows:
        u = row["username"]
        n = row["nick_name"] or ""
        r = row["remark"] or ""
        result[u] = r or n or u
    return result


def _resolve_username(name_or_id: str) -> Optional[dict]:
    """模糊解析「显示名/wxid/chatroom」到唯一 contact 行。

    匹配策略（优先级递减）:
        1. username 完全匹配
        2. remark 完全匹配
        3. nick_name 完全匹配
        4. username LIKE '%name%'
        5. remark LIKE '%name%'
        6. nick_name LIKE '%name%'
    """
    conn = _cache.get("contact/contact.db")

    for col in ("username", "remark", "nick_name"):
        row = conn.execute(
            f"SELECT id, username, nick_name, remark, local_type "
            f"FROM contact WHERE {col}=? LIMIT 1",
            (name_or_id,),
        ).fetchone()
        if row:
            return dict(row)

    pat = f"%{name_or_id}%"
    for col in ("remark", "nick_name", "username"):
        row = conn.execute(
            f"SELECT id, username, nick_name, remark, local_type "
            f"FROM contact WHERE {col} LIKE ? LIMIT 1",
            (pat,),
        ).fetchone()
        if row:
            return dict(row)

    return None


def resolve_chat_context(chat_name: str) -> Optional[dict]:
    """把「群名/好友显示名/wxid」解析成完整上下文。

    返回 dict:
        {
            "username": "<wxid 或 chatroom>",
            "display_name": "<最优显示名>",
            "is_chatroom": bool,
            "contact_id": <int contact.id>,
        }

    找不到返回 None。
    """
    row = _resolve_username(chat_name)
    if not row:
        return None
    uname = row["username"] or ""
    return {
        "username": uname,
        "display_name": (row["remark"] or row["nick_name"] or uname),
        # 微信 4.x 的 local_type 有时把群标成 1（实测 6 个群、9 个 type=0 群），
        # 所以 username 后缀 @chatroom 作为权威兜底。
        "is_chatroom": (row["local_type"] == LOCAL_TYPE_CHATROOM
                        or uname.endswith("@chatroom")),
        "contact_id": row["id"],
    }


def get_self_username() -> Optional[str]:
    """推断当前登录用户 wxid。

    优先 `VCHAT_SELF_WXID` / `WECHAT_SELF_WXID` 环境变量；
    否则尝试从数据目录的父目录名解析（多数解密工具会把产物落在
    `<wxid>_<random>/decrypted/...` 这种结构里）；
    都不行就返回 None。
    """
    import os
    # 优先环境变量（新名 + 旧名兼容）
    env = (os.environ.get("VCHAT_SELF_WXID")
           or os.environ.get("WECHAT_SELF_WXID"))
    if env:
        return env

    # 看父目录命名
    root = _cache.default_cache()._root.parent
    parent = root.parent
    name = parent.name
    if name.startswith("wxid_"):
        return name.split("_b")[0] if "_" in name else name

    # 尝试从 session.db 推断（自发消息）
    try:
        conn = _cache.get("session/session.db")
        row = conn.execute(
            "SELECT last_msg_sender FROM SessionTable "
            "WHERE last_msg_sender IS NOT NULL AND last_msg_sender LIKE 'wxid_%' "
            "GROUP BY last_msg_sender ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        if row:
            return row[0]
    except Exception:
        pass

    return None


def search_contacts(query: str = "", limit: int = 50) -> list[dict]:
    """按关键词搜联系人。空 query 返回前 limit 个好友。"""
    conn = _cache.get("contact/contact.db")
    fields = "username, nick_name, remark, local_type, description, alias"
    if query:
        pat = f"%{query}%"
        rows = conn.execute(
            f"SELECT {fields} FROM contact "
            "WHERE nick_name LIKE ? OR remark LIKE ? OR username LIKE ? "
            "OR alias LIKE ? OR description LIKE ? "
            "LIMIT ?",
            (pat, pat, pat, pat, pat, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {fields} FROM contact WHERE local_type=? LIMIT ?",
            (LOCAL_TYPE_FRIEND, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_chatroom_members(room_username: str) -> list[dict]:
    """返回群成员列表 [{username, nick_name, remark}, ...]。"""
    conn = _cache.get("contact/contact.db")
    # 4.x 的 local_type 偶尔把群标成 1，所以放宽：username 后缀
    # @chatroom 时不再校验 local_type。
    if room_username.endswith("@chatroom"):
        row = conn.execute(
            "SELECT id FROM contact WHERE username=? LIMIT 1",
            (room_username,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM contact WHERE username=? AND local_type=? LIMIT 1",
            (room_username, LOCAL_TYPE_CHATROOM),
        ).fetchone()
    if not row:
        return []
    room_id = row["id"]
    rows = conn.execute(
        "SELECT c.username, c.nick_name, c.remark "
        "FROM chatroom_member cm JOIN contact c ON cm.member_id = c.id "
        "WHERE cm.room_id = ?",
        (room_id,),
    ).fetchall()
    return [dict(r) for r in rows]
