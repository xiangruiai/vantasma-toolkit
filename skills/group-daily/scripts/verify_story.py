#!/usr/bin/env python3
"""事实核查：吃 story.json + chat_target.txt，逐条 quote 核对原文，列出错位。

用法:
    python3 verify_story.py --story /tmp/story.json --chat /tmp/chat_target.txt

核对维度（每个 quote 必过）:
  A. sender 是否在原文中出现过该 quote（按子串匹配）
  B. quote 文字是否能在原文找到（按 50% 字符匹配的最长片段）
  C. 文字出现的时间是否在 timeline 节点的 time 范围内
  D. cast 里的人是否在 time 范围内有真实发言

D 是结构核查；A/B/C 是引用核查。

输出报告：每条 quote 一行 ✓/⚠/✗，结尾给统计。
退出码：全 ✓ 退 0；有 ⚠ 退 1；有 ✗ 退 2。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime


MSG_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] (.+?): (.*)$")
# vchat 多行消息的延续行可能是 "wxid_xxx:" 这种 sender id 行
WXID_LINE_RE = re.compile(r"^[a-zA-Z0-9_\-]+:\s*$")


def load_chat(path: str) -> list[tuple[str, str, str, int]]:
    """读 chat_target.txt，处理 vchat 多行消息格式。

    vchat 把带 wxid 的消息拆成多行：
        [时间] sender: wxid_xxx:
        正文行 1
        正文行 2
    我们把后续不匹配 MSG_RE 的行都 append 到上一条消息的 content。
    """
    msgs = []  # 用 list[list] 方便修改最后一条
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            stripped = line.rstrip("\n")
            m = MSG_RE.match(stripped)
            if m:
                ts, sender, content = m.groups()
                # content 可能是 "wxid_xxx:" 这种 id 行，去掉
                if WXID_LINE_RE.match(content.strip()):
                    content = ""
                msgs.append([ts, sender, content, i])
            elif msgs and stripped:
                # 续行：追加到上一条的 content
                if msgs[-1][2]:
                    msgs[-1][2] += "\n" + stripped
                else:
                    msgs[-1][2] = stripped
    return [tuple(m) for m in msgs]


def parse_time_range(time_str: str) -> tuple[str, str] | None:
    """解析 "08:14 – 09:30" / "22:45 → 09:16 次日" 为 (start, end)。"""
    # 取所有 HH:MM
    times = re.findall(r"\d{1,2}:\d{2}", time_str)
    if len(times) >= 2:
        return times[0], times[-1]
    if len(times) == 1:
        return times[0], times[0]
    return None


def ts_to_hhmm(ts: str) -> str:
    return ts[11:16]


def time_in_range(ts: str, start: str, end: str, allow_next_day: bool) -> bool:
    """ts (YYYY-MM-DD HH:MM) 是否落在 [start, end] HH:MM 区间内。"""
    hhmm = ts_to_hhmm(ts)
    if allow_next_day:
        # 跨日：start..23:59 或 00:00..end 都算
        return hhmm >= start or hhmm <= end
    return start <= hhmm <= end


def find_quote_in_chat(text: str, sender_hint: str,
                       msgs: list[tuple[str, str, str, int]]) -> list[tuple[str, str, int]]:
    """在 chat 里搜 quote 文本。返回所有命中：[(ts, sender, line_no), ...]
    匹配规则：从 quote 取最长 12 字符连续片段做子串查（容忍标点差异）。
    """
    # 取最长 12 字片段
    # 处理 "句1 / 句2" 写法：拆开各取片段，命中任一即可
    segments = [s.strip() for s in re.split(r"\s*/\s*", text) if s.strip()]
    snippets = []
    for seg in segments:
        clean = re.sub(r'[「」『』"\s]', "", seg)
        if len(clean) >= 4:
            snippets.append(clean[:12])
            if len(clean) >= 24:
                snippets.append(clean[12:24])
        elif clean:
            snippets.append(clean)
    if not snippets:
        return []
    hits = []
    for ts, sender, content, ln in msgs:
        content_clean = re.sub(r'[「」『』"\s]', "", content)
        if any(sn in content_clean for sn in snippets):
            hits.append((ts, sender, ln))
    return hits


# 当前账号在 vchat 输出里显示为 "me"。如果你想让 story 里直接用你的真名
# （而不是 "me"），把真名加到环境变量 SELF_ALIAS（逗号分隔多个）：
#   export SELF_ALIAS="me,张三"
import os as _os
SELF_ALIAS = set(
    s.strip() for s in _os.environ.get("SELF_ALIAS", "me").split(",")
    if s.strip()
) | {"me"}


def sender_matches(actual: str, expected: str) -> bool:
    """actual 是聊天 sender（可能带括号/emoji），expected 是 story 里的写法。"""
    if not expected:
        return True
    if actual == expected:
        return True
    # me / 真名 互通（取决于 SELF_ALIAS 环境变量配置）
    if actual in SELF_ALIAS and expected in SELF_ALIAS:
        return True
    # 双向 contains（处理括号后缀、emoji 等）
    return expected in actual or actual in expected


def collect_senders_in_range(msgs, start: str, end: str,
                             allow_next_day: bool) -> set[str]:
    s = set()
    for ts, sender, _, _ in msgs:
        if time_in_range(ts, start, end, allow_next_day):
            s.add(sender)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True)
    ap.add_argument("--chat", required=True, help="chat_target.txt（按时段切过）")
    args = ap.parse_args()

    with open(os.path.expanduser(args.story), encoding="utf-8") as f:
        story = json.load(f)
    msgs = load_chat(os.path.expanduser(args.chat))
    print(f"▶ 加载聊天记录 {len(msgs)} 条", file=sys.stderr)

    total = ok = warn = err = 0
    issues = []

    for s in story.get("timeline", []):
        no = s.get("no", "?")
        time_str = s.get("time", "")
        rng = parse_time_range(time_str)
        if not rng:
            issues.append(f"节 {no}: time 字段无法解析 '{time_str}'")
            err += 1
            continue
        start, end = rng
        allow_next_day = "次日" in time_str or start > end

        # === D. cast 真实性 ===
        cast_names = [c.get("name", "") for c in s.get("cast", [])]
        senders_in_range = collect_senders_in_range(msgs, start, end,
                                                    allow_next_day)
        for name in cast_names:
            in_group = any(sender_matches(snd, name) for snd in senders_in_range)
            if not in_group:
                issues.append(
                    f"节 {no} [{time_str}] cast「{name}」在时段内没找到发言"
                )
                warn += 1

        # === A/B/C. quote 三件套 ===
        for q in s.get("quotes", []):
            total += 1
            who = q.get("who", "")
            text = q.get("text", "")
            # 截 who 的核心部分（去掉括注）
            who_core = re.sub(r"[（(].*?[）)]", "", who).strip()
            who_core = re.sub(r"被复读.*", "", who_core).strip()
            who_core = re.sub(r"\s*/.*", "", who_core).strip()

            hits = find_quote_in_chat(text, who_core, msgs)
            if not hits:
                issues.append(
                    f"节 {no} [{time_str}] quote 文字在原文找不到: "
                    f"「{text[:30]}」by {who}"
                )
                err += 1
                continue

            sender_ok = any(sender_matches(snd, who_core) for _, snd, _ in hits)
            time_ok = any(
                time_in_range(ts, start, end, allow_next_day)
                for ts, _, _ in hits
            )

            if sender_ok and time_ok:
                ok += 1
            elif not sender_ok:
                actual_senders = ",".join(
                    sorted({snd for _, snd, _ in hits}))
                issues.append(
                    f"节 {no} [{time_str}] quote sender 错位: "
                    f"story 写 '{who_core}'，原文是 '{actual_senders}' "
                    f"line {hits[0][2]}「{text[:30]}」"
                )
                err += 1
            else:
                actual_times = ",".join(
                    sorted({ts_to_hhmm(ts) for ts, _, _ in hits}))
                issues.append(
                    f"节 {no} [{time_str}] quote 时间跨节: "
                    f"实际在 {actual_times}「{text[:30]}」"
                )
                warn += 1

    print(f"\n▶ Quote 核查: 总 {total}, ✓ OK {ok}, ⚠ 跨节 {warn}, "
          f"✗ 错位 {err}", file=sys.stderr)
    if issues:
        print(f"\n问题列表（{len(issues)} 条）:", file=sys.stderr)
        for s in issues:
            print(f"  - {s}", file=sys.stderr)
    else:
        print("\n✅ 全部 quote 都核对通过", file=sys.stderr)

    if err > 0:
        sys.exit(2)
    if warn > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
