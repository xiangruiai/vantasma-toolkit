#!/usr/bin/env python3
"""全网图片素材搜索下载（DuckDuckGo Images，自动走本机代理）。

用法:
  搜索:  python3 fetch_image.py search "曼德拉 葬礼 2013" [--limit 8]
  下载:  python3 fetch_image.py download "<图片URL>" --out /path/img.jpg
  一步:  python3 fetch_image.py grab "关键词" --out /path/img.jpg [--index 0]

下载后必须 Read 确认内容再用进分镜；scene 标 "source": "素材来源：网络"。
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
def _user_proxy():
    """代理三级解析(开源开箱:无代理用户直连):config.json proxy 字段 → XIANGRUI_PROXY 环境变量 → 空(直连)。"""
    import json as _j, os as _o
    cfg = _o.path.expanduser("~/.config/xiangrui-video/config.json")
    try:
        p = _j.load(open(cfg)).get("proxy", "")
        if p:
            return p
    except Exception:
        pass
    return _o.environ.get("XIANGRUI_PROXY", "")

PROXY = _user_proxy()


def opener(use_proxy):
    handlers = []
    if use_proxy:
        if PROXY:
            handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    op = urllib.request.build_opener(*handlers)
    op.addheaders = [("User-Agent", UA)]
    return op


def http_get(url, use_proxy=False, referer=None):
    op = opener(use_proxy)
    if referer:
        op.addheaders = [("User-Agent", UA), ("Referer", referer)]
    return op.open(url, timeout=40).read()


def ddg_search(keyword, limit=8):
    """DDG 图片搜索：先拿 vqd token 再调 i.js。直连失败自动走代理。"""
    q = urllib.parse.quote(keyword)
    last_err = None
    for use_proxy in (False, True):
        try:
            html = http_get(f"https://duckduckgo.com/?q={q}&iax=images&ia=images",
                            use_proxy).decode("utf-8", "ignore")
            m = re.search(r'vqd=["\']?([\d-]+)', html)
            if not m:
                raise RuntimeError("拿不到 vqd token")
            vqd = m.group(1)
            data = json.loads(http_get(
                f"https://duckduckgo.com/i.js?l=wt-wt&o=json&q={q}&vqd={vqd}&f=,,,&p=1",
                use_proxy, referer="https://duckduckgo.com/"))
            results = data.get("results", [])[:limit]
            return [{"image": r.get("image"), "thumbnail": r.get("thumbnail"),
                     "title": r.get("title", "")[:60], "w": r.get("width"),
                     "h": r.get("height"), "from": r.get("url", "")[:80]}
                    for r in results], use_proxy
        except Exception as e:
            last_err = e
    raise RuntimeError(f"DDG 搜索失败（直连+代理都试过）: {last_err}")


def download(url, out_path, use_proxy=None):
    tries = [use_proxy] if use_proxy is not None else [False, True]
    last_err = None
    for p in tries:
        try:
            data = http_get(url, p)
            if len(data) < 5000:
                raise RuntimeError(f"文件过小({len(data)}B)，可能是防盗链占位图")
            with open(out_path, "wb") as f:
                f.write(data)
            return out_path
        except Exception as e:
            last_err = e
    raise RuntimeError(f"下载失败: {last_err}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("keyword")
    s.add_argument("--limit", type=int, default=8)
    d = sub.add_parser("download")
    d.add_argument("url")
    d.add_argument("--out", required=True)
    g = sub.add_parser("grab")
    g.add_argument("keyword")
    g.add_argument("--out", required=True)
    g.add_argument("--index", type=int, default=0)
    args = ap.parse_args()

    if args.cmd == "search":
        results, via = ddg_search(args.keyword, args.limit)
        print(f"# via {'proxy' if via else 'direct'}")
        for i, r in enumerate(results):
            print(f"[{i}] {r['w']}x{r['h']} | {r['title']} | {r['image']}")
    elif args.cmd == "download":
        print("saved:", download(args.url, args.out))
    else:
        results, via = ddg_search(args.keyword, max(8, args.index + 1))
        if not results:
            sys.exit("无结果")
        r = results[min(args.index, len(results) - 1)]
        try:
            out = download(r["image"], args.out, None)
        except Exception:
            out = download(r["thumbnail"], args.out, None)  # 原图防盗链时退缩略图
        print(f"saved: {out}  ({r['w']}x{r['h']} {r['title']})")


if __name__ == "__main__":
    main()
