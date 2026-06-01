#!/usr/bin/env python3
"""从解密的 head_image.db 导出指定 wxid 列表的头像，输出为 base64 data URI 的 JSON 映射。

用法:
    python3 extract_avatars.py --wxids wxid1,wxid2,... --out /tmp/avatars.json
    python3 extract_avatars.py --wxids-file /tmp/wxids.txt --out /tmp/avatars.json
    python3 extract_avatars.py --names-map names.json --out /tmp/avatars.json
"""
import argparse
import base64
import json
import os
import sqlite3
import sys

def _resolve_default_db() -> str:
    """解析头像数据库默认路径。

    优先级:
      1. VCHAT_DATA_DIR
      2. WECHAT_DECRYPT_PATH (旧名兼容)
      3. ~/.vchat/data (vchat 默认)
      4. ~/Projects/wechat-decrypt (老 fallback)
    """
    for env in ("VCHAT_DATA_DIR", "WECHAT_DECRYPT_PATH"):
        v = os.environ.get(env)
        if v:
            return os.path.expanduser(f"{v}/decrypted/head_image/head_image.db")
    for default in ("~/.vchat/data", "~/Projects/wechat-decrypt"):
        p = os.path.expanduser(f"{default}/decrypted/head_image/head_image.db")
        if os.path.exists(p):
            return p
    return os.path.expanduser("~/.vchat/data/decrypted/head_image/head_image.db")


DEFAULT_DB = _resolve_default_db()


def load_wxids(args):
    """从命令行/文件/JSON 三种方式取 wxid 列表 + 可选的 wxid → 显示名映射"""
    if args.names_map:
        with open(args.names_map, encoding="utf-8") as f:
            mapping = json.load(f)  # {wxid: 显示名}
        return mapping
    if args.wxids_file:
        with open(args.wxids_file, encoding="utf-8") as f:
            wxids = [line.strip() for line in f if line.strip()]
        return {w: w for w in wxids}
    if args.wxids:
        return {w.strip(): w.strip() for w in args.wxids.split(",") if w.strip()}
    sys.exit("需要提供 --wxids / --wxids-file / --names-map 之一")


def detect_mime(buf: bytes) -> str:
    if buf[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if buf[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if buf[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB,
                    help="解密后的 head_image.db 路径")
    ap.add_argument("--wxids", help="逗号分隔的 wxid 列表")
    ap.add_argument("--wxids-file", help="每行一个 wxid 的文本文件")
    ap.add_argument("--names-map",
                    help="JSON 文件，格式 {wxid: 显示名}，结果按显示名做 key")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"head_image.db 不存在: {args.db}\n"
                 "请先确保微信数据已解密（vchat decrypt 产出路径）。")

    mapping = load_wxids(args)
    wxids = list(mapping.keys())

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    placeholders = ",".join("?" * len(wxids))
    cur.execute(
        f"SELECT username, image_buffer FROM head_image "
        f"WHERE username IN ({placeholders})",
        wxids,
    )

    result = {}
    found_wxids = set()
    for username, buf in cur.fetchall():
        display = mapping[username]
        mime = detect_mime(buf)
        b64 = base64.b64encode(buf).decode("ascii")
        result[display] = f"data:{mime};base64,{b64}"
        found_wxids.add(username)
        print(f"  ✓ {display} ({username}): {len(buf)} bytes / {mime}",
              file=sys.stderr)

    missing = set(wxids) - found_wxids
    for m in missing:
        print(f"  ✗ {mapping[m]} ({m}): 头像未找到", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    print(f"\n✅ 导出 {len(result)} / {len(wxids)} 个头像 → {args.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
