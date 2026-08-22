# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 北京万涂幻象科技有限公司
"""生成万涂幻象公众号固定尾卡资产。

输入是一张由 LibTV 生成的完整品牌名片图。脚本自动裁掉其中的静态黑色互动栏，
保留上半张个人名片，并生成与其无缝衔接的黑底荧光绿四动作 GIF。

用法：
    python3 gen_branded_footer.py /absolute/path/to/libtv-card.png
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat


ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CARD_OUT = ASSETS_DIR / "footer_profile_card.png"
ACTIONS_OUT = ASSETS_DIR / "footer_actions_brand.gif"

TARGET_W = 1280
BAR_H = 244
BLACK = (0, 0, 0)
WHITE = (248, 250, 247)
MUTED = (154, 161, 151)
NEON = (198, 255, 0)
GLOW = (83, 111, 0)
DIVIDER = (48, 52, 46)

FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_LABEL = ImageFont.truetype(FONT_PATH, 31, index=0)
FONT_KICKER = ImageFont.truetype(FONT_PATH, 25, index=0)
FONT_BRAND = ImageFont.truetype(FONT_PATH, 17, index=0)

ITEMS = ("like", "share", "heart", "comment")
LABELS = {"like": "赞", "share": "转发", "heart": "推荐", "comment": "写留言"}


def locate_black_bar(image: Image.Image) -> int:
    """定位 LibTV 图中连续的纯黑互动栏起点。"""
    start = int(image.height * 0.62)
    for y in range(start, image.height - 3):
        row = image.crop((0, y, image.width, y + 1)).convert("RGB")
        brightness = sum(ImageStat.Stat(row).mean) / 3
        if brightness < 8:
            next_row = image.crop((0, y + 2, image.width, y + 3)).convert("RGB")
            next_brightness = sum(ImageStat.Stat(next_row).mean) / 3
            if next_brightness < 8:
                return y
    raise RuntimeError("没有识别到 LibTV 图中的黑色互动栏")


def make_profile_card(source: Path) -> None:
    image = Image.open(source).convert("RGB")
    bar_y = locate_black_bar(image)
    card = image.crop((0, 0, image.width, bar_y))
    target_h = round(card.height * TARGET_W / card.width)
    card = card.resize((TARGET_W, target_h), Image.Resampling.LANCZOS)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    card.save(CARD_OUT, optimize=True)


def heart_points(cx: int, cy: int, scale: float) -> list[tuple[int, int]]:
    points = []
    for degree in range(0, 361, 8):
        t = math.radians(degree)
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((round(cx + x * scale), round(cy - y * scale)))
    return points


def draw_like(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple[int, int, int], width: int, scale: float) -> None:
    def p(dx: float, dy: float) -> tuple[int, int]:
        return round(cx + dx * scale), round(cy + dy * scale)

    outline = [
        p(-24, 24), p(18, 24), p(27, 18), p(31, 6), p(30, -6), p(23, -12),
        p(7, -12), p(11, -30), p(6, -38), p(-1, -35), p(-10, -13), p(-23, -8),
    ]
    draw.line(outline + [outline[0]], fill=color, width=width, joint="curve")
    draw.rounded_rectangle([p(-36, -8), p(-24, 28)], radius=max(2, round(4 * scale)), outline=color, width=width)


def draw_share(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple[int, int, int], width: int, scale: float) -> None:
    def p(dx: float, dy: float) -> tuple[int, int]:
        return round(cx + dx * scale), round(cy + dy * scale)

    path = [p(-34, 23), p(-26, 7), p(-9, -4), p(14, -7), p(14, -21)]
    draw.line(path, fill=color, width=width, joint="curve")
    draw.line([p(14, -29), p(35, -9), p(14, 12)], fill=color, width=width, joint="curve")


def draw_heart(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple[int, int, int], width: int, scale: float) -> None:
    points = heart_points(cx, cy + round(2 * scale), 2.35 * scale)
    draw.line(points + [points[0]], fill=color, width=width, joint="curve")


def draw_comment(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple[int, int, int], width: int, scale: float) -> None:
    x0, y0 = round(cx - 34 * scale), round(cy - 28 * scale)
    x1, y1 = round(cx + 34 * scale), round(cy + 20 * scale)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=round(9 * scale), outline=color, width=width)
    draw.line([(round(cx - 12 * scale), y1), (round(cx - 24 * scale), round(cy + 34 * scale)), (round(cx + 2 * scale), y1)], fill=color, width=width, joint="curve")
    draw.line([(round(cx - 11 * scale), round(cy - 4 * scale)), (round(cx + 11 * scale), round(cy - 4 * scale))], fill=color, width=width)
    draw.line([(cx, round(cy - 15 * scale)), (cx, round(cy + 7 * scale))], fill=color, width=width)


DRAWERS = {"like": draw_like, "share": draw_share, "heart": draw_heart, "comment": draw_comment}


def draw_icon(draw: ImageDraw.ImageDraw, item: str, cx: int, cy: int, active: bool, scale: float) -> None:
    drawer = DRAWERS[item]
    if active:
        drawer(draw, cx, cy, GLOW, 14, scale * 1.05)
        drawer(draw, cx, cy, NEON, 7, scale)
    else:
        drawer(draw, cx, cy, WHITE, 6, scale)


def centered_text(draw: ImageDraw.ImageDraw, center_x: int, y: int, text: str, font: ImageFont.FreeTypeFont, fill: tuple[int, int, int]) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((center_x - (box[2] - box[0]) / 2, y), text, font=font, fill=fill)


def make_frame(active_count: int, focus: int | None = None, pressed: bool = False, burst: bool = False) -> Image.Image:
    image = Image.new("RGB", (TARGET_W, BAR_H), BLACK)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((58, 79, 108, 86), radius=4, fill=NEON)
    draw.text((58, 100), "THANKS FOR READING", font=FONT_KICKER, fill=WHITE)
    draw.text((59, 139), "WANTU HUANXIANG", font=FONT_BRAND, fill=MUTED)
    draw.line((362, 54, 362, 190), fill=DIVIDER, width=2)

    centers = (474, 687, 900, 1113)
    for index, item in enumerate(ITEMS):
        is_active = index < active_count or (focus == index and not pressed)
        is_focus = focus == index
        offset_y = -8 if is_focus and not pressed else (5 if is_focus and pressed else 0)
        scale = 0.90 if is_focus and pressed else (1.08 if is_focus else 1.0)
        cx = centers[index]
        cy = 91 + offset_y
        draw_icon(draw, item, cx, cy, is_active, scale)
        centered_text(draw, cx, 151 + offset_y // 3, LABELS[item], FONT_LABEL, NEON if is_active else MUTED)
        if is_active:
            draw.rounded_rectangle((cx - 22, 205, cx + 22, 210), radius=3, fill=NEON)
        if burst and is_focus:
            for k in range(8):
                angle = math.pi * 2 * k / 8
                bx = round(cx + math.cos(angle) * 62)
                by = round(cy + math.sin(angle) * 58)
                draw.ellipse((bx - 4, by - 4, bx + 4, by + 4), fill=NEON)
    return image


def make_actions_gif() -> None:
    specs: list[tuple[Image.Image, int]] = [(make_frame(0), 850)]
    for index in range(4):
        specs.append((make_frame(index, focus=index, pressed=True), 120))
        specs.append((make_frame(index + 1, focus=index, burst=True), 210))
        specs.append((make_frame(index + 1), 480))
    specs.append((make_frame(4), 1250))

    frames = [frame.quantize(colors=96, method=Image.Quantize.MEDIANCUT) for frame, _ in specs]
    durations = [duration for _, duration in specs]
    frames[0].save(
        ACTIONS_OUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("请传入 LibTV 名片图的绝对路径")
    source = Path(sys.argv[1]).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"找不到文件：{source}")
    make_profile_card(source)
    make_actions_gif()
    print(f"个人名片：{CARD_OUT} ({Image.open(CARD_OUT).size})")
    gif = Image.open(ACTIONS_OUT)
    print(f"互动动效：{ACTIONS_OUT} ({gif.size}, {gif.n_frames} 帧, {ACTIONS_OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
