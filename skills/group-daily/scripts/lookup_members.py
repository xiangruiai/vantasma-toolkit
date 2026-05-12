#!/usr/bin/env python3
"""根据群名查 chatroom 成员，输出 wxid + 昵称 + 备注 映射。

用法:
    python3 lookup_members.py --group-name "祥瑞和Ta的社区朋友们"
    python3 lookup_members.py --group-name "XX群" --names 示例联系人A,示例联系人C --out /tmp/members.json
"""
import argparse
import json
import os
import sqlite3
import sys

def _resolve_default_db() -> str:
    """解析联系人数据库默认路径。

    优先级:
      1. VCHAT_DATA_DIR 环境变量 + /decrypted/contact/contact.db
      2. ~/Projects/wechat-decrypt/decrypted/contact/contact.db
    """
    root = os.environ.get("VCHAT_DATA_DIR",
                          "~/Projects/wechat-decrypt")
    return os.path.expanduser(f"{root}/decrypted/contact/contact.db")


DEFAULT_DB = _resolve_default_db()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB,
                    help="解密后的 contact.db 路径")
    ap.add_argument("--group-name", required=True, help="群名（nick_name）")
    ap.add_argument("--names",
                    help="逗号分隔的成员显示名（nick_name 或 remark）。"
                         "留空则返回群内全部成员。")
    ap.add_argument("--out", help="输出 JSON 路径（{显示名: wxid}）。"
                                  "留空则打印到 stdout。")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"contact.db 不存在: {args.db}\n"
                 "请确保微信数据已解密。")

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()

    # 1. 找群 id
    cur.execute(
        "SELECT id, username FROM contact "
        "WHERE local_type=2 AND (nick_name=? OR remark=?) LIMIT 1",
        (args.group_name, args.group_name),
    )
    row = cur.fetchone()
    if not row:
        # 兜底：模糊查
        cur.execute(
            "SELECT id, username, nick_name FROM contact "
            "WHERE local_type=2 AND nick_name LIKE ? LIMIT 5",
            (f"%{args.group_name}%",),
        )
        candidates = cur.fetchall()
        if not candidates:
            sys.exit(f"找不到群: {args.group_name}")
        if len(candidates) > 1:
            print("找到多个候选群，请用更精确的名字：", file=sys.stderr)
            for c in candidates:
                print(f"  - id={c[0]} username={c[1]} nick_name={c[2]}",
                      file=sys.stderr)
            sys.exit(1)
        row = candidates[0][:2]

    room_id = row[0]
    print(f"  群 id = {room_id}, username = {row[1]}", file=sys.stderr)

    # 2. 拉成员
    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
        placeholders = ",".join("?" * len(names))
        sql = (
            f"SELECT c.username, c.nick_name, c.remark "
            f"FROM chatroom_member cm JOIN contact c ON cm.member_id = c.id "
            f"WHERE cm.room_id = ? AND "
            f"(c.nick_name IN ({placeholders}) OR c.remark IN ({placeholders}))"
        )
        cur.execute(sql, [room_id] + names + names)
    else:
        cur.execute(
            "SELECT c.username, c.nick_name, c.remark "
            "FROM chatroom_member cm JOIN contact c ON cm.member_id = c.id "
            "WHERE cm.room_id = ?",
            (room_id,),
        )

    members = {}
    for username, nick, remark in cur.fetchall():
        display = remark or nick or username
        members[display] = username

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(members, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 导出 {len(members)} 位成员 → {args.out}", file=sys.stderr)
    else:
        json.dump(members, sys.stdout, ensure_ascii=False, indent=2)
        print()


if __name__ == "__main__":
    main()
