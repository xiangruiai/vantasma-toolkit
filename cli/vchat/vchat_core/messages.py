"""vchat_core.messages · 聊天消息查询。

核心算法:
    table_name = "Msg_" + md5(username).hexdigest()
    real_sender_id 是 contact.id（数字），需要 JOIN contact 表得到 wxid

跨分片:
    解密后可能存在 message_0.db, message_1.db, ...
    要逐个 db 尝试找 table_name。
"""

import hashlib
import re
import sqlite3
from datetime import datetime
from typing import Optional

from . import cache as _cache
from . import contacts as _contacts


_TABLE_NAME_PATTERN = re.compile(r"^Msg_[0-9a-f]{32}$")


def _msg_table_name(username: str) -> str:
    """username → 'Msg_<md5>'"""
    return f"Msg_{hashlib.md5(username.encode()).hexdigest()}"


def _is_safe_table_name(name: str) -> bool:
    return bool(_TABLE_NAME_PATTERN.fullmatch(name))


def _list_message_dbs() -> list[str]:
    """返回所有 message_N.db 的 rel_path，按 N 升序。"""
    root = _cache.default_cache()._root
    msg_dir = root / "message"
    if not msg_dir.exists():
        return []
    names = sorted(
        p.name for p in msg_dir.iterdir()
        if p.name.startswith("message_") and p.name.endswith(".db")
        and "_fts" not in p.name and "resource" not in p.name
    )
    return [f"message/{n}" for n in names]


def find_message_table(username: str) -> Optional[tuple[str, str]]:
    """在所有 message_N.db 中找 username 的消息表。

    返回 (db_rel_path, table_name)，找不到返回 None。
    """
    table = _msg_table_name(username)
    if not _is_safe_table_name(table):
        return None
    for db_rel in _list_message_dbs():
        try:
            conn = _cache.get(db_rel)
        except FileNotFoundError:
            continue
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if exists:
            return db_rel, table
    return None


# ---- 公开 API ----

def get_recent_sessions_dict(limit: int = 20) -> list[dict]:
    """结构化版本：返回 list[{username, display_name, last_timestamp, summary, unread_count}]。"""
    try:
        conn = _cache.get("session/session.db")
    except FileNotFoundError:
        return []
    names = _contacts.get_contact_names()
    rows = conn.execute(
        "SELECT username, last_timestamp, summary, unread_count "
        "FROM SessionTable WHERE last_timestamp > 0 "
        "ORDER BY last_timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        {
            "username": r["username"],
            "display_name": names.get(r["username"], r["username"]),
            "last_timestamp": r["last_timestamp"],
            "summary": (r["summary"] or "").strip(),
            "unread_count": r["unread_count"] or 0,
        }
        for r in rows
    ]


def get_recent_sessions(limit: int = 20) -> str:
    """返回最近活跃的会话列表（文本格式）。"""
    try:
        conn = _cache.get("session/session.db")
    except FileNotFoundError:
        return "❌ session.db 不存在"
    names = _contacts.get_contact_names()
    rows = conn.execute(
        "SELECT username, last_timestamp, summary, unread_count "
        "FROM SessionTable "
        "WHERE last_timestamp > 0 "
        "ORDER BY last_timestamp DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "（无会话）"

    out = [f"最近 {len(rows)} 个会话："]
    for r in rows:
        u = r["username"]
        display = names.get(u, u)
        ts = r["last_timestamp"]
        when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"
        summary = (r["summary"] or "").strip().replace("\n", " ")[:50]
        unread = r["unread_count"] or 0
        unread_tag = f"  📬{unread}" if unread else ""
        out.append(f"  [{when}] {display}{unread_tag}")
        if summary:
            out.append(f"           {summary}")
    return "\n".join(out)


def get_chat_history(chat_name: str, limit: int = 50,
                    offset: int = 0,
                    start_time: str = "",
                    end_time: str = "",
                    oldest_first: bool = False) -> str:
    """看某个聊天对象的历史。

    chat_name: 群名/好友显示名/wxid（模糊匹配）
    """
    ctx = _contacts.resolve_chat_context(chat_name)
    if not ctx:
        return f"❌ 找不到聊天对象: {chat_name}"
    return _format_chat_history(
        ctx, limit=limit, offset=offset,
        start_time=start_time, end_time=end_time,
        oldest_first=oldest_first,
    )


def _parse_ts(s: str) -> Optional[int]:
    """支持 'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD HH:MM:SS' 转 unix。"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    return None


def _build_sender_map(db_rel: str) -> dict[int, str]:
    """从 message db 的 Name2Id 表建立 rowid → user_name 映射。"""
    conn = _cache.get(db_rel)
    rows = conn.execute(
        "SELECT rowid, user_name FROM Name2Id"
    ).fetchall()
    return {r["rowid"]: r["user_name"] for r in rows}


def _format_chat_history(ctx: dict, limit: int, offset: int,
                         start_time: str, end_time: str,
                         oldest_first: bool) -> str:
    location = find_message_table(ctx["username"])
    if not location:
        return f"❌ 没找到 {ctx['display_name']} 的消息表（可能没聊过）"
    db_rel, table = location
    conn = _cache.get(db_rel)
    names = _contacts.get_contact_names()
    sender_map = _build_sender_map(db_rel)
    self_wxid = _contacts.get_self_username()

    where = ["1=1"]
    params: list = []
    start_ts = _parse_ts(start_time)
    end_ts = _parse_ts(end_time)
    if start_ts:
        where.append("create_time >= ?")
        params.append(start_ts)
    if end_ts:
        where.append("create_time <= ?")
        params.append(end_ts)

    order = "ASC" if oldest_first else "DESC"
    sql = (
        f"SELECT local_id, create_time, local_type, real_sender_id, "
        f"message_content FROM [{table}] "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY create_time {order} LIMIT ? OFFSET ?"
    )
    params += [limit, offset]
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return f"（{ctx['display_name']} 范围内无消息）"

    out = [
        f"{ctx['display_name']} 的消息记录"
        f"（返回 {len(rows)} 条，offset={offset}, limit={limit}）"
        f" {'[群聊]' if ctx['is_chatroom'] else '[私聊]'}"
    ]
    if start_time or end_time:
        out.append(f"时间范围: {start_time or '不限'} ~ {end_time or '不限'}")
    out.append("")

    from . import content as _content_module

    for r in rows:
        ts = r["create_time"]
        when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"
        local_type = r["local_type"]
        raw = r["message_content"] or ""
        # 走 decompress_content：bytes 会尝试 utf-8 → zstd
        content = _content_module.decompress_content(raw)

        # 群消息：发送者从 Name2Id 表查
        if ctx["is_chatroom"]:
            sender_id = r["real_sender_id"]
            wxid = sender_map.get(sender_id, "")
            if wxid == self_wxid:
                sender = "me"
            elif wxid:
                sender = names.get(wxid, wxid)
            else:
                sender = "[系统]"
        else:
            sender_id = r["real_sender_id"]
            wxid = sender_map.get(sender_id, "")
            if wxid == self_wxid or wxid == "":
                sender = "me"
            else:
                sender = names.get(wxid, ctx["display_name"])

        # local_type 标签
        if local_type == 1:
            label = ""
        elif local_type == 3:
            label = "[图片]"
            content = "[图片]"
        elif local_type == 34:
            label = "[语音]"
            content = "[语音]"
        elif local_type == 43:
            label = "[视频]"
            content = "[视频]"
        elif local_type == 47:
            label = "[表情]"
            content = "[表情]"
        elif local_type == 49:
            label = "[链接/文件]"
        elif local_type >= 10000:
            label = "[系统]"
            # 系统消息内容通常是 XML/二进制混合，正文展开容易刷屏
            # 抽个 <title> 当摘要，否则不显示
            tm = re.search(r"<title>([^<]+)</title>", content) if isinstance(content, str) else None
            content = f" {tm.group(1).strip()}" if tm else ""
        else:
            label = f"[type={local_type}]"

        # 群消息内容里前缀 "wxid_xxx:\n" 需要剥掉
        if ctx["is_chatroom"] and content.startswith("wxid_"):
            m = re.match(r"^(wxid_[^:]+):\n?(.*)", content, re.DOTALL)
            if m:
                content = m.group(2).strip()

        out.append(f"[{when}] {sender}: {label}{content[:200]}")

    return "\n".join(out)


def search_messages(keyword: str, chat_name: str = "",
                    limit: int = 30) -> str:
    """搜消息内容关键词。

    若 chat_name 指定，只在该聊天里搜；否则全库扫（慢，建议加 limit）。
    """
    if not keyword:
        return "❌ 关键词不能为空"

    names = _contacts.get_contact_names()
    pat = f"%{keyword}%"

    if chat_name:
        ctx = _contacts.resolve_chat_context(chat_name)
        if not ctx:
            return f"❌ 找不到聊天对象: {chat_name}"
        location = find_message_table(ctx["username"])
        if not location:
            return f"❌ {ctx['display_name']} 没有消息表"
        db_rel, table = location
        conn = _cache.get(db_rel)
        rows = conn.execute(
            f"SELECT local_id, create_time, real_sender_id, message_content "
            f"FROM [{table}] "
            f"WHERE local_type=1 AND message_content LIKE ? "
            f"ORDER BY create_time DESC LIMIT ?",
            (pat, limit),
        ).fetchall()
        if not rows:
            return f"（{ctx['display_name']} 里没有「{keyword}」）"

        sender_map = _build_sender_map(db_rel)
        self_wxid = _contacts.get_self_username()

        out = [f"在 {ctx['display_name']} 里搜「{keyword}」（{len(rows)} 条）："]
        for r in rows:
            when = datetime.fromtimestamp(r["create_time"]).strftime(
                "%Y-%m-%d %H:%M"
            )
            sid = r["real_sender_id"]
            wxid = sender_map.get(sid, "")
            if wxid == self_wxid:
                sender = "me"
            elif wxid:
                sender = names.get(wxid, wxid)
            else:
                sender = ctx["display_name"]
            raw = r["message_content"] or ""
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            content = raw.replace("\n", " ")[:120]
            if ctx["is_chatroom"] and content.startswith("wxid_"):
                content = re.sub(r"^wxid_[^:]+:\s*", "", content)
            out.append(f"  [{when}] {sender}: {content}")
        return "\n".join(out)

    # 全库搜 — 遍历所有 Msg_* 表
    out = [f"全库搜「{keyword}」（limit {limit}）："]
    hits = 0
    for db_rel in _list_message_dbs():
        conn = _cache.get(db_rel)
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name LIKE 'Msg_%'"
        ).fetchall()
        for tbl_row in tables:
            tbl = tbl_row["name"]
            if not _is_safe_table_name(tbl):
                continue
            try:
                rows = conn.execute(
                    f"SELECT create_time, real_sender_id, message_content "
                    f"FROM [{tbl}] "
                    f"WHERE local_type=1 AND message_content LIKE ? "
                    f"ORDER BY create_time DESC LIMIT 5",
                    (pat,),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            for r in rows:
                when = datetime.fromtimestamp(r["create_time"]).strftime(
                    "%Y-%m-%d %H:%M"
                )
                raw = r["message_content"] or ""
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                content = raw.replace("\n", " ")[:100]
                out.append(f"  [{when}] {tbl[:14]}…: {content}")
                hits += 1
                if hits >= limit:
                    out.append(f"  ...（已达 {limit} 条上限，停止）")
                    return "\n".join(out)
    if hits == 0:
        return f"全库未搜到「{keyword}」"
    return "\n".join(out)


def get_chat_history_dict(chat_name: str, limit: int = 50,
                          start_time: str = "",
                          end_time: str = "",
                          oldest_first: bool = False) -> list[dict]:
    """结构化版本：用于 export 等场景。返回 list[dict]。"""
    from .content import decompress_content

    ctx = _contacts.resolve_chat_context(chat_name)
    if not ctx:
        return []
    location = find_message_table(ctx["username"])
    if not location:
        return []
    db_rel, table = location
    conn = _cache.get(db_rel)
    sender_map = _build_sender_map(db_rel)
    self_wxid = _contacts.get_self_username()
    names = _contacts.get_contact_names()

    where = ["1=1"]
    params: list = []
    start_ts = _parse_ts(start_time)
    end_ts = _parse_ts(end_time)
    if start_ts:
        where.append("create_time >= ?")
        params.append(start_ts)
    if end_ts:
        where.append("create_time <= ?")
        params.append(end_ts)

    order = "ASC" if oldest_first else "DESC"
    rows = conn.execute(
        f"SELECT local_id, create_time, local_type, real_sender_id, "
        f"message_content FROM [{table}] "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY create_time {order} LIMIT ?",
        params + [limit],
    ).fetchall()

    result = []
    for r in rows:
        sid = r["real_sender_id"]
        wxid = sender_map.get(sid, "")
        if wxid == self_wxid:
            sender_wxid = wxid
            sender_name = "me"
        elif wxid:
            sender_wxid = wxid
            sender_name = names.get(wxid, wxid)
        else:
            sender_wxid = ctx["username"]
            sender_name = ctx["display_name"]
        raw = r["message_content"] or ""
        raw = decompress_content(raw)
        result.append({
            "local_id": r["local_id"],
            "create_time": r["create_time"],
            "local_type": r["local_type"],
            "sender_wxid": sender_wxid,
            "sender_name": sender_name,
            "content": raw,
        })
    return result
