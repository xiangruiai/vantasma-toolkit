#!/usr/bin/env python3
"""从 story.json 自动批量解析所有 cast/highlights 人物的 wxid，注入回 story.json。

用法:
    python3 resolve_story_wxids.py --story /tmp/story.json --group "<群名>"

行为:
1. 扫 story.json，收集 timeline[].cast[].name + highlights[].name 全部 name（去重）
2. 调 vchat --json group-members 拉群全员
3. 用「nick_name 完全相等 → remark 完全相等 → nick_name 子串包含」三档匹配
4. 找到的 wxid 直接写回 story.json 的 cast[].wxid 和 highlights[].wxid
5. 缺漏的 name：调 vchat contacts 全库搜，列出候选 wxid 让 AI 二次确认（stderr）
6. 还缺的 → 退出码 2，stderr 报错；找全 → 退出码 0

不破坏已有 wxid（如果 cast 里已经填了 wxid，跳过不覆盖）。
"""
import argparse
import json
import os
import subprocess
import sys


def load_group_members(group_name: str) -> list[dict]:
    """调 vchat --json group-members 拉成员表。"""
    try:
        out = subprocess.check_output(
            ["vchat", "--json", "group-members", group_name],
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        sys.exit(f"vchat group-members 失败: {e.stderr.decode(errors='ignore')}")
    except FileNotFoundError:
        sys.exit("找不到 vchat CLI，请先装 vchat。")
    data = json.loads(out)
    return data.get("members", [])


def resolve_name_in_group(name: str, members: list[dict]) -> str | None:
    """从群成员表里找 name 对应的 wxid，三档匹配。"""
    # 档 1：nick_name 完全相等
    for m in members:
        if m.get("nick_name") == name:
            return m["username"]
    # 档 2：remark 完全相等
    for m in members:
        if m.get("remark") == name:
            return m["username"]
    # 档 3：nick_name 包含 name 或被 name 包含（带 emoji/后缀场景）
    for m in members:
        nick = m.get("nick_name", "")
        if nick and (name in nick or nick in name):
            return m["username"]
    # 档 4：remark 包含
    for m in members:
        remark = m.get("remark", "")
        if remark and (name in remark or remark in name):
            return m["username"]
    return None


def fallback_contacts_search(name: str) -> list[tuple[str, str]]:
    """档 5：从全库 contact 搜（人可能曾在群里但已退）。返回 [(wxid, nick), ...]"""
    try:
        out = subprocess.check_output(
            ["vchat", "contacts", name], stderr=subprocess.DEVNULL,
        ).decode(errors="ignore")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    candidates = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("wxid") or line.startswith("chenxing"):
            # 形如 "wxid_xxx  昵称: NAME" / 兜底 "<id>  昵称: NAME"
            parts = line.split(None, 1)
            if len(parts) == 2:
                wxid = parts[0]
                rest = parts[1]
                nick = rest.replace("昵称:", "").strip()
                candidates.append((wxid, nick))
    return candidates


def collect_names(story: dict) -> list[str]:
    """收集所有需要 wxid 的人名（去重，保持出现顺序）。"""
    seen = []
    for s in story.get("timeline", []):
        for c in s.get("cast", []):
            n = c.get("name")
            if n and n not in seen:
                seen.append(n)
    for h in story.get("highlights", []):
        n = h.get("name")
        if n and n not in seen:
            seen.append(n)
    return seen


def inject_wxids(story: dict, name_to_wxid: dict[str, str]) -> int:
    """把 name_to_wxid 注入 story 的 cast/highlights，不覆盖已有 wxid。返回注入次数。"""
    count = 0
    for s in story.get("timeline", []):
        for c in s.get("cast", []):
            if not c.get("wxid"):
                w = name_to_wxid.get(c["name"])
                if w:
                    c["wxid"] = w
                    count += 1
    for h in story.get("highlights", []):
        if not h.get("wxid"):
            w = name_to_wxid.get(h["name"])
            if w:
                h["wxid"] = w
                count += 1
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True, help="story.json 路径（会就地改写）")
    ap.add_argument("--group", required=True, help="微信群名（vchat 模糊匹配）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只报告不改写 story.json")
    args = ap.parse_args()

    story_path = os.path.expanduser(args.story)
    with open(story_path, encoding="utf-8") as f:
        story = json.load(f)

    names = collect_names(story)
    print(f"▶ story 里共 {len(names)} 个独立人物名", file=sys.stderr)

    print(f"▶ 拉 {args.group} 群成员表...", file=sys.stderr)
    members = load_group_members(args.group)
    print(f"  群里 {len(members)} 人", file=sys.stderr)

    name_to_wxid: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        w = resolve_name_in_group(name, members)
        if w:
            name_to_wxid[name] = w
            print(f"  ✓ {name} → {w}", file=sys.stderr)
        else:
            missing.append(name)
            print(f"  ✗ {name} 群成员表里没找到", file=sys.stderr)

    if missing:
        print(f"\n▶ {len(missing)} 个名字不在群里，尝试全库搜...", file=sys.stderr)
        for name in missing[:]:
            cands = fallback_contacts_search(name)
            if cands:
                print(f"  [{name}] 全库候选:", file=sys.stderr)
                for w, nick in cands[:5]:
                    print(f"    - {w}  (nick: {nick})", file=sys.stderr)
                # 自动选第一个，AI 看 stderr 决定是否人工干预
                name_to_wxid[name] = cands[0][0]
                missing.remove(name)
                print(f"    → 自动用第一个 {cands[0][0]}", file=sys.stderr)
            else:
                print(f"  [{name}] 全库也找不到", file=sys.stderr)

    injected = inject_wxids(story, name_to_wxid)
    print(f"\n▶ 注入 {injected} 个 wxid", file=sys.stderr)

    if not args.dry_run:
        with open(story_path, "w", encoding="utf-8") as f:
            json.dump(story, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 已写回 {story_path}", file=sys.stderr)

    if missing:
        print(f"\n❌ 仍有 {len(missing)} 个名字无法解析:", file=sys.stderr)
        for n in missing:
            print(f"    - {n}", file=sys.stderr)
        print("\n建议：把这些人名核对一遍（可能拼错或他已退群）。",
              file=sys.stderr)
        sys.exit(2)
    print(f"\n✅ 全部 {len(names)} 个名字都拿到 wxid", file=sys.stderr)


if __name__ == "__main__":
    main()
