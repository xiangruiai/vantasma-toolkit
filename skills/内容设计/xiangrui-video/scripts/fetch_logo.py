#!/usr/bin/env python3
"""品牌 logo 获取（口播点名软件/大厂时配 logo 徽章用，祥瑞 2026-06-12 定）。

来源链：Simple Icons（开源 SVG，主流科技品牌）→ 官方站 favicon 高清兜底。
用法:
    python3 fetch_logo.py claude --out assets/logos/claude.svg
    python3 fetch_logo.py doubao --domain doubao.com --out assets/logos/doubao.png
    python3 fetch_logo.py openai --color ffffff --out assets/logos/openai_w.svg  # 单色化(深底用)

设计规范（写进分镜时遵守）：
- logo 不改色不变形（单色化白/黑除外，深底玻璃卡内用白色单色更克制）
- 统一装进"徽章"容器：白底圆角方章 52-64px，logo 居中占 70%；像 App 图标排排坐
- 口播点名时与名字同时出现，不点名不出现，不满屏乱飞
- 合规：科普/评论展示商标属合理使用，不暗示官方背书
"""
import argparse
import os
import sys
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", help="simpleicons slug（如 claude/openai/github）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--color", default="", help="单色化 hex（不带#），深底用 ffffff")
    ap.add_argument("--domain", default="", help="兜底 favicon 域名（国产品牌常用）")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)

    # 1. Simple Icons
    url = f"https://cdn.simpleicons.org/{a.slug}"
    if a.color:
        url += f"/{a.color}"
    try:
        data = fetch(url)
        if data[:4] in (b"<svg", b"<?xm") or b"<svg" in data[:200]:
            open(a.out, "wb").write(data)
            print(f"✅ simpleicons: {a.out} ({len(data)}B)")
            return
    except Exception as e:
        print(f"simpleicons 无 {a.slug}: {e}")

    # 2. favicon 兜底
    if a.domain:
        try:
            data = fetch(f"https://www.google.com/s2/favicons?domain={a.domain}&sz=128")
            out = a.out if a.out.endswith(".png") else a.out.rsplit(".", 1)[0] + ".png"
            open(out, "wb").write(data)
            print(f"✅ favicon兜底: {out} ({len(data)}B)")
            return
        except Exception as e:
            print(f"favicon 失败: {e}")
    print("❌ 未取到 logo（试 --domain 兜底）")
    sys.exit(1)


if __name__ == "__main__":
    main()
