#!/usr/bin/env python3
"""B 站 B-roll 素材搜索与下载（绕 412 验证路径：buvid cookie + html5 playurl）。

用法:
  搜索:   python3 fetch_broll.py search "量子计算 动画" [--limit 10]
  下载:   python3 fetch_broll.py download BV1xxx --out clip.mp4 [--start 10 --duration 8]
  兜底:   B 站路径失效时改用 python3 -m yt_dlp（YouTube 等其他站直接用 yt_dlp）

注意:
  - html5 platform 的 playurl 风控最松，但清晰度有限（360p-720p），做底素材够用
  - 下载整片后用 --start/--duration 裁剪，省流量可以接受（单文件一般 <50MB）
  - 商用需注意素材版权；成片左上角标"素材来源"（render.py 的 source 字段）
"""
import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
import os
if not os.path.exists(FFMPEG):
    FFMPEG = "ffmpeg"


def http_json(url, cookie="", referer="https://www.bilibili.com/"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer, "Cookie": cookie})
    return json.load(urllib.request.urlopen(req, timeout=30))


def get_buvid():
    d = http_json("https://api.bilibili.com/x/frontend/finger/spi")
    return f"buvid3={d['data']['b_3']}; buvid4={d['data']['b_4']}"


def search(keyword, limit=10):
    cookie = get_buvid()
    kw = urllib.parse.quote(keyword)
    d = http_json(
        f"https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={kw}",
        cookie=cookie, referer="https://search.bilibili.com/")
    results = (d.get("data") or {}).get("result") or []
    out = []
    for v in results[:limit]:
        title = re.sub(r"</?em[^>]*>", "", v.get("title", ""))
        out.append({"bvid": v.get("bvid"), "title": title,
                    "duration": v.get("duration"), "author": v.get("author"),
                    "play": v.get("play")})
    return out


def download(bvid, out_path, start=None, duration=None, qn=64):
    cookie = get_buvid()
    view = http_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                     cookie=cookie)
    if view.get("code") != 0:
        raise RuntimeError(f"view API 失败: {view.get('message')}")
    cid = view["data"]["cid"]
    title = view["data"]["title"]
    play = http_json(
        f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}"
        f"&qn={qn}&platform=html5&high_quality=1",
        cookie=cookie, referer=f"https://www.bilibili.com/video/{bvid}")
    if play.get("code") != 0:
        raise RuntimeError(f"playurl 失败: {play.get('message')}（可改用 python3 -m yt_dlp 兜底）")
    url = play["data"]["durl"][0]["url"]
    # CDN 拒绝 ffmpeg 直连，先 urllib 整段下载（验证过的路径），再本地裁剪
    tmp = out_path + ".full.mp4"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    if start is None and duration is None:
        os.replace(tmp, out_path)
    else:
        cmd = [FFMPEG, "-y", "-v", "error"]
        if start is not None:
            cmd += ["-ss", str(start)]
        cmd += ["-i", tmp]
        if duration is not None:
            cmd += ["-t", str(duration)]
        cmd += ["-c", "copy", out_path]
        subprocess.run(cmd, check=True)
        os.remove(tmp)
    print(f"ok: {title} -> {out_path}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("keyword")
    s.add_argument("--limit", type=int, default=10)
    d = sub.add_parser("download")
    d.add_argument("bvid")
    d.add_argument("--out", required=True)
    d.add_argument("--start", type=float)
    d.add_argument("--duration", type=float)
    args = ap.parse_args()
    if args.cmd == "search":
        for r in search(args.keyword, args.limit):
            print(f"{r['bvid']} | {r['duration']} | {r['play']}播放 | {r['author']} | {r['title']}")
    else:
        download(args.bvid, args.out, args.start, args.duration)


if __name__ == "__main__":
    main()
