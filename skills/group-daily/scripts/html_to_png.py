#!/usr/bin/env python3
"""把群日报 HTML 转换成长图 PNG（用 Chrome headless + Pillow 自适应裁底）。

用法:
    python3 html_to_png.py --html /path/to/page.html --out /path/to/page.png
"""
import argparse
import os
import shutil
import subprocess
import sys
from collections import Counter

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_chrome():
    for p in CHROME_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    cmd = shutil.which("google-chrome") or shutil.which("chromium")
    if cmd:
        return cmd
    sys.exit("没找到 Chrome / Chromium。请安装其一。")


def shoot(chrome, html_path, png_path, width, height):
    cmd = [
        chrome, "--headless", "--disable-gpu", "--no-sandbox",
        "--virtual-time-budget=4000", "--hide-scrollbars",
        f"--window-size={width},{height}",
        f"--screenshot={png_path}",
        f"file://{os.path.abspath(html_path)}",
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def trim_bottom(png_path, tol=10, pad=40):
    """检测页面背景色 + 裁掉底部空白"""
    try:
        from PIL import Image
    except ImportError:
        sys.exit("缺少 Pillow。请执行: pip3 install Pillow --break-system-packages")

    img = Image.open(png_path).convert("RGB")
    w, h = img.size
    pixels = img.load()

    # 取底部 50% 的主色作为背景
    sample = []
    for y in range(h // 2, h, 50):
        for x in range(0, w, 30):
            sample.append(pixels[x, y])
    bg = Counter(sample).most_common(1)[0][0]

    def is_bg(y):
        return all(abs(pixels[x, y][i] - bg[i]) <= tol
                   for x in range(0, w, 30) for i in range(3))

    last = h - 1
    for y in range(h - 1, -1, -1):
        if not is_bg(y):
            last = y
            break

    cropped_h = min(h, last + pad)
    img.crop((0, 0, w, cropped_h)).save(png_path, optimize=True)
    return w, cropped_h, bg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=900)
    ap.add_argument("--height", type=int, default=18000,
                    help="截图高度上限（实际会被自适应裁掉空白）")
    args = ap.parse_args()

    html_path = os.path.expanduser(args.html)
    png_path = os.path.expanduser(args.out)
    if not os.path.exists(html_path):
        sys.exit(f"HTML 不存在: {html_path}")
    os.makedirs(os.path.dirname(png_path), exist_ok=True)

    chrome = find_chrome()
    print(f"▶ 用 {chrome} 截图 {args.width}×{args.height}...", file=sys.stderr)
    shoot(chrome, html_path, png_path, args.width, args.height)

    print(f"▶ 自适应裁底...", file=sys.stderr)
    w, h, bg = trim_bottom(png_path)
    print(f"  bg = RGB{bg}", file=sys.stderr)
    print(f"  最终尺寸 {w}×{h}", file=sys.stderr)

    size_kb = os.path.getsize(png_path) / 1024
    print(f"✅ PNG 生成: {png_path} ({size_kb:.1f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
