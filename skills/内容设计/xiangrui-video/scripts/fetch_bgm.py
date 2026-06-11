#!/usr/bin/env python3
"""按视频调性(mood)自动找免版权 BGM。

爆款 BGM 的正确姿势：站外用"同风格免版权曲"垫底保成片完整；
发布时若平台（抖音/视频号）站内曲库有热门同风格音乐，可在平台编辑器里替换，
站内热门音乐自带流量加成且零版权风险。

用法:
  python3 fetch_bgm.py list                          # 看 mood 表
  python3 fetch_bgm.py grab --mood tech --out bgm.mp3 [--index 0] [--duration 90]
  python3 fetch_bgm.py grab --query "自定义搜索词" --out bgm.mp3
"""
import argparse
import json
import os
import subprocess
import sys

PROXY = os.environ.get("CHAPING_PROXY", "http://127.0.0.1:7897")

# mood -> 免版权曲搜索词（NCS / no copyright 系，按吐槽式知识视频调性精选）
MOODS = {
    "tech":     {"desc": "科技感/未来感，AI·硬核科普默认",
                 "queries": ["NCS no copyright electronic future bass instrumental",
                             "no copyright music tech house minimal background"]},
    "upbeat":   {"desc": "轻快/正能量，生活向·好消息",
                 "queries": ["NCS no copyright upbeat funk groove instrumental",
                             "no copyright happy uplifting pop background music"]},
    "suspense": {"desc": "悬疑/紧张，反转叙事·避坑·黑幕",
                 "queries": ["no copyright suspense tension dark ambient background",
                             "no copyright music mysterious investigation beat"]},
    "chill":    {"desc": "舒缓/lo-fi，慢节奏讲解·情感向",
                 "queries": ["no copyright lofi chill hip hop instrumental",
                             "NCS chill ambient calm background music"]},
    "epic":     {"desc": "宏大/史诗，里程碑事件·大格局结尾",
                 "queries": ["no copyright epic cinematic inspiring background music",
                             "NCS no copyright orchestral epic trailer"]},
    "funny":    {"desc": "诙谐/搞怪，吐槽密集·梗多的片",
                 "queries": ["no copyright quirky comedy funny background music",
                             "no copyright music playful ukulele upbeat"]},
    "news":     {"desc": "新闻速报感，快节奏资讯·breaking news",
                 "queries": ["no copyright news report background music fast beat",
                             "no copyright breaking news intro music loop"]},
}


def ytdlp(args_, timeout=300):
    base = [sys.executable, "-m", "yt_dlp", "--no-warnings"]
    # 直连优先，失败换代理（与 tts.py edge 同策略）
    for extra in ([], ["--proxy", PROXY] if PROXY else []):
        r = subprocess.run(base + extra + args_, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout
    raise RuntimeError(f"yt_dlp 失败: {r.stderr.strip()[-400:]}")


def search(query, n=5):
    out = ytdlp([f"ytsearch{n}:{query}", "--flat-playlist", "-J"], timeout=120)
    entries = json.loads(out).get("entries") or []
    return [{"title": e.get("title"), "id": e.get("id"),
             "duration": e.get("duration"), "channel": e.get("channel")}
            for e in entries if e.get("id")]


def grab(query, out_path, index=0, min_dur=60):
    cands = [c for c in search(query, 6) if (c["duration"] or 0) >= min_dur]
    if not cands:
        raise RuntimeError(f"无候选: {query}")
    pick = cands[min(index, len(cands) - 1)]
    print(f"选中: {pick['title']} ({pick['duration']}s, {pick['channel']})")
    ytdlp([f"https://www.youtube.com/watch?v={pick['id']}",
           "-x", "--audio-format", "mp3", "--audio-quality", "5",
           "-o", out_path.replace(".mp3", ".%(ext)s")])
    if not os.path.exists(out_path):
        raise RuntimeError("下载后文件不存在")
    print(f"✅ {out_path}")
    print(f'   sb.json 写: "bgm": "{os.path.abspath(out_path)}", "bgm_volume": 0.12')
    return pick


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    g = sub.add_parser("grab")
    g.add_argument("--mood", choices=sorted(MOODS))
    g.add_argument("--query")
    g.add_argument("--out", required=True)
    g.add_argument("--index", type=int, default=0)
    g.add_argument("--duration", type=int, default=60, help="最短秒数（≥成片时长为佳）")
    a = ap.parse_args()
    if a.cmd == "list":
        for k, v in MOODS.items():
            print(f"{k:9s} {v['desc']}")
        return
    if not (a.mood or a.query):
        ap.error("--mood 或 --query 至少给一个")
    queries = [a.query] if a.query else MOODS[a.mood]["queries"]
    last = None
    for q in queries:
        try:
            grab(q, a.out, a.index, a.duration)
            return
        except Exception as e:
            last = e
            print(f"  换词重试: {e}")
    raise SystemExit(f"全部搜索词失败: {last}")


if __name__ == "__main__":
    main()
