#!/usr/bin/env python3
"""图片元数据探测器。

用法：
  python3 image_probe.py /tmp/<群名>_images/  > /tmp/image_probe.json
  python3 image_probe.py /tmp/<群名>_images/ --date 20260511 --min-kb 20

输出 JSON 数组，每张图：
  {
    "path": "/tmp/.../20260511_213357_xxx.png",
    "filename": "...",
    "ts": "21:33",          # 从文件名解析
    "width": 1920,
    "height": 1080,
    "aspect": 1.78,         # w/h
    "shape": "landscape",   # landscape / portrait / square
    "kb": 824,
    "suggested_layout": {
      "role": "hero-figure" | "banner-image" | "person-card" | "qr" | "inline-narrow" | "decoration",
      "max_width_px": 600,  # 在 A3 1090 内容宽下推荐的最大显示宽
      "display_height_px": 338  # 按比例算出来的对应显示高
    }
  }

设计原则：
- 不缩放图片，只测量。具体 layout 由 AI 决定
- 给 suggested_layout 只是参考，AI 可以覆盖
- 不需要先看图（这是 probe，不是判断内容；内容判断让 AI 用 Read 工具自己看）
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("需要 Pillow：pip install Pillow")


# A3 一栏内容宽参考（1123px - 边距 ≈ 1090px）
A3_CONTENT_WIDTH = 1090


def classify_shape(aspect):
    if aspect > 1.4:
        return "landscape"
    if aspect < 0.7:
        return "portrait"
    return "square"


def suggest_layout(width, height, aspect, shape, kb):
    """根据图比例 + 内容大小推荐 layout 角色和显示尺寸。

    这只是首选项。AI 看了图实际内容后可以覆盖。
    """
    # 极小图（< 30KB） → 多半是 emoji / 表情 / 头像 / 二维码缩略图
    if kb < 30:
        return {
            "role": "decoration",
            "max_width_px": 120,
            "display_height_px": int(120 / aspect) if aspect else 120,
            "note": "极小图，可能是表情/装饰，慎用"
        }

    # 二维码（接近 1:1 + 黑白多）→ 通常是入群码
    if shape == "square" and width < 800:
        return {
            "role": "qr",
            "max_width_px": 280,
            "display_height_px": 280,
            "note": "可能是二维码，第 N 版 tomorrow.qr 位"
        }

    # 横图 → 适合做 banner / 跨栏
    if shape == "landscape":
        # 宽度 ≤ 800：适合 hero 配图（半栏）；> 800：适合 banner（跨栏）
        if width <= 800:
            return {
                "role": "hero-figure",
                "max_width_px": 480,
                "display_height_px": int(480 / aspect),
                "note": "中等横图，hero 主稿配图位"
            }
        else:
            disp_h = int(A3_CONTENT_WIDTH / aspect)
            return {
                "role": "banner-image",
                "max_width_px": A3_CONTENT_WIDTH,
                "display_height_px": min(disp_h, 500),
                "note": "大横图，副刊/深度版 banner 跨栏首选"
            }

    # 竖图 → 适合 person_card / inline-narrow
    if shape == "portrait":
        if height < 1200:
            return {
                "role": "person-card",
                "max_width_px": 340,
                "display_height_px": int(340 / aspect),
                "note": "竖图，关键人物 profile 卡或 inline-narrow"
            }
        else:
            # 超长竖图（截屏长截图）
            return {
                "role": "inline-narrow",
                "max_width_px": 280,
                "display_height_px": min(int(280 / aspect), 800),
                "note": "超长竖截图，inline-narrow 侧栏；可能要裁剪"
            }

    # 正方形（非二维码）
    return {
        "role": "hero-figure",
        "max_width_px": 400,
        "display_height_px": 400,
        "note": "方图，hero 配图或 person_card"
    }


def parse_ts(filename):
    m = re.match(r'^\d{8}_(\d{2})(\d{2})(\d{2})_', filename)
    if m:
        return f'{m.group(1)}:{m.group(2)}'
    return ""


def probe_dir(directory, date_prefix=None, min_kb=5):
    results = []
    for fname in sorted(os.listdir(directory)):
        if not re.match(r'.+\.(png|jpg|jpeg)$', fname, re.I):
            continue
        if date_prefix and not fname.startswith(date_prefix):
            continue
        path = os.path.join(directory, fname)
        try:
            kb = os.path.getsize(path) // 1024
            if kb < min_kb:
                continue
            with Image.open(path) as img:
                w, h = img.size
        except Exception as e:
            print(f"skip {fname}: {e}", file=sys.stderr)
            continue
        aspect = w / h if h else 1
        shape = classify_shape(aspect)
        results.append({
            "path": path,
            "filename": fname,
            "ts": parse_ts(fname),
            "width": w,
            "height": h,
            "aspect": round(aspect, 2),
            "shape": shape,
            "kb": kb,
            "suggested_layout": suggest_layout(w, h, aspect, shape, kb),
        })
    return results


def main():
    ap = argparse.ArgumentParser(
        description="扫描候选图，输出元数据 + 推荐 layout 角色"
    )
    ap.add_argument("directory", help="图片目录")
    ap.add_argument("--date", help="日期前缀（YYYYMMDD），筛选当天图")
    ap.add_argument("--min-kb", type=int, default=5, help="过滤小于此 KB 的图（默认 5）")
    args = ap.parse_args()

    if not os.path.isdir(args.directory):
        sys.exit(f"目录不存在：{args.directory}")

    results = probe_dir(args.directory, args.date, args.min_kb)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n# 共 {len(results)} 张候选图（{'date='+args.date if args.date else '全部日期'}, min-kb={args.min_kb}）",
          file=sys.stderr)


if __name__ == "__main__":
    main()
