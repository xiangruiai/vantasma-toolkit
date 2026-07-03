#!/usr/bin/env python3
"""角色/插画抠图管线：深底线稿 PNG → 透明背景 PNG（带完整性自检）。

适用：seedream 等生图模型产出的“深色背景 + 浅色线稿”角色图/插画，
抠掉背景后可直接 <img> 进 demo 场景，融进任意深底渐变。

处理流程：
1. 黑框提取（可选，默认开）——模型常把"纯黑背景"画成白纸上的黑色画框，
   自动取最大暗色连通域为画布，内缩去掉手绘框线
2. 连通域抠底——只删与边缘连通的暗色区域，人物内部的黑色块（裤子/杯子）保留
3. 去游离噪点（小于 min_area 的孤立不透明块）
4. 触边自检——不透明像素触到边缘则告警（人物可能被生成时裁切）
5. 裁掉多余透明边，四周留 pad 呼吸

用法：
  python3 char_cutout.py in.png out.png                # 默认参数
  python3 char_cutout.py in.png out.png --no-panel     # 背景已是纯黑，跳过黑框提取
  python3 char_cutout.py in.png out.png --thresh 60    # 背景偏亮时调高阈值
退出码：0=完整通过；2=触边告警（图能用但建议重新生成）
"""
import argparse
import sys

import cv2
import numpy as np


def extract_panel(im, dark_thresh=100, inset_ratio=0.035):
    """找最大暗色连通域（黑画框/黑画布），内缩裁掉手绘框线。"""
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    dark = (gray < dark_thresh).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=4)
    if n < 2:
        return im
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = stats[big, cv2.CC_STAT_AREA]
    h, w = im.shape[:2]
    if area < 0.25 * h * w:   # 暗区太小，不像画布，原图直出
        return im
    x, y = stats[big, cv2.CC_STAT_LEFT], stats[big, cv2.CC_STAT_TOP]
    pw, ph = stats[big, cv2.CC_STAT_WIDTH], stats[big, cv2.CC_STAT_HEIGHT]
    if pw > 0.97 * w and ph > 0.97 * h:  # 暗区就是整图（本来就是纯黑底）
        return im
    inset = int(min(pw, ph) * inset_ratio)
    return im[y + inset:y + ph - inset, x + inset:x + pw - inset]


def cutout(im, thresh=46, feather=2, min_area=600, pad=60):
    h, w = im.shape[:2]
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    dark = (gray < thresh).astype(np.uint8)
    n, labels = cv2.connectedComponents(dark, connectivity=4)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border.discard(0)
    bgmask = np.isin(labels, list(border)) & (dark == 1)
    keep = (~bgmask).astype(np.uint8)
    n2, lab2, stats2, _ = cv2.connectedComponentsWithStats(keep, connectivity=8)
    for i in range(1, n2):
        if stats2[i, cv2.CC_STAT_AREA] < min_area:
            keep[lab2 == i] = 0
    alpha = cv2.GaussianBlur((keep * 255).astype(np.uint8), (feather * 2 + 1,) * 2, 0)
    out = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    out[:, :, 3] = alpha

    op = alpha > 128
    if not op.any():
        print("❌ 抠完全空——阈值不对或图不是深底线稿", file=sys.stderr)
        sys.exit(1)
    edges = {"上": int(op[0, :].sum()), "下": int(op[-1, :].sum()),
             "左": int(op[:, 0].sum()), "右": int(op[:, -1].sum())}
    touch = {k: v for k, v in edges.items() if v > 0}

    ys, xs = np.where(op)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, h)
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, w)
    return out[y0:y1, x0:x1], touch


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--thresh", type=int, default=46, help="背景判暗阈值（默认 46）")
    ap.add_argument("--no-panel", action="store_true", help="跳过黑框提取（背景已是纯黑整图）")
    ap.add_argument("--min-area", type=int, default=600, help="小于此面积的孤立噪点删除")
    ap.add_argument("--pad", type=int, default=60, help="裁切后四周保留的透明呼吸边")
    args = ap.parse_args()

    im = cv2.imread(args.input)
    if im is None:
        print(f"❌ 读不到 {args.input}", file=sys.stderr)
        sys.exit(1)
    if not args.no_panel:
        im = extract_panel(im)
    out, touch = cutout(im, thresh=args.thresh, min_area=args.min_area, pad=args.pad)
    cv2.imwrite(args.output, out)
    h, w = out.shape[:2]
    if touch:
        # 少量触边（如地面线延伸出画）可接受；大面积触边=人物被裁
        bad = {k: v for k, v in touch.items() if v > 0.3 * (w if k in ("上", "下") else h)}
        flag = ("⚠️ 大面积触边——可能是地面线(可用)也可能人物被裁,必须 Read 输出图确认"
                if bad else "ⓘ 轻微触边(地面线/桌沿延伸,通常可用)")
        print(f"{flag}: {touch} -> {args.output} ({w}x{h})")
        sys.exit(2 if bad else 0)
    print(f"✓ 完整通过: {args.output} ({w}x{h})")


if __name__ == "__main__":
    main()
