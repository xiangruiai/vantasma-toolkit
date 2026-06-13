#!/usr/bin/env python3
"""storyboard 质量闸门：强制「图主文辅 / 反模板化」。

铁律只写在 SKILL.md 里没有强制力——模型执行时会偷懒套最省事的纯文字版式
(editorial / impact_text)，导致整片千篇一律、零图像级现场设计。本脚本把铁律
变成 render.py 渲染前的硬关卡：不过就拒绝渲染。

检测项（来自 SKILL.md「图主文辅」「招牌场景不跨片复用」「反模板化」三条铁律）：
  E1  纯文字版面（editorial / impact_text / concept_card 这类无图像主视觉的）总数 > MAX_TEXT(2) → 报错
  E2  连续 ≥ MAX_RUN(3) 镜同一 type（套同一版式） → 报错
  E3  全片零个图像级镜头（VISUAL=0） → 报错（这正是上一版 Token 篇的翻车形态）
  W*  warning（不拦渲染，只提示）：图像级占比偏低 / diagram-list 当纯文字用 等

用法：
  python3 lint_storyboard.py sb.json          # 独立跑，打印分布 + 判定，退出码 0/1
  python3 lint_storyboard.py sb.json --quiet   # 只在失败时输出
  from lint_storyboard import lint             # render.py import 调用
"""
import argparse
import json
import sys
from collections import Counter

# ---------- 呈现类型分类（决定一个 type 算不算「图像级现场设计」）----------
# VISUAL = 图像级主视觉：真实素材 / 现场写的 HTML 动画 / 自己生成的插画 / 数据图。
#          这些才是「图主文辅」里的「图」，每片应当占绝大多数。
VISUAL = {
    "demo",         # 现场写 HTML 动画（Rough.js 手绘 / ECharts 数据图 / 数字滚动…），最自由最该用
    "whiteboard",   # seedream 白底插画
    "broll",        # 视频片段
    "screenshot",   # 截图证据
    "image_full",   # 全屏图
    "media",        # 多素材轮换
}
# SEMI = 半图像：有视觉结构但偏固定模板（auto 图解 / logo 章）。允许，但不算「现场设计」，
#        过多仍然单调——计入分布、参与连续同版式检测，但不计入纯文字红线。
SEMI = {
    "diagram",      # flow / compare / list 自动图解卡（手绘 Rough 渲染）
    "logo_card",    # 品牌 logo 定格章
}
# TEXT = 纯文字版面：无任何图像主视觉，整屏就是排版好的文字。这是要被红线卡住的对象。
TEXT = {
    "impact_text",  # 全屏砸字
    "editorial",    # 编辑杂志式版面（大标题 + 编号列表）
    "concept_card", # 开场概念卡（超大标题）
}
# EXEMPT = 豁免：品牌强制元素，不参与红线统计（但仍计入连续同版式检测）
EXEMPT = {"ending"}

MAX_TEXT = 2     # 全片纯文字版面上限（祥瑞 2026-06-13 定）
MAX_RUN = 3      # 连续同一 type 的上限（命中即「套版式」）
MIN_VISUAL_RATIO = 0.45  # 图像级镜头占比低于此值给 warning（图主文辅的软提示）


def category(scene_type):
    if scene_type in VISUAL:
        return "VISUAL"
    if scene_type in SEMI:
        return "SEMI"
    if scene_type in TEXT:
        return "TEXT"
    if scene_type in EXEMPT:
        return "EXEMPT"
    return "UNKNOWN"


def lint(sb, max_text=MAX_TEXT, max_run=MAX_RUN):
    """返回 (ok: bool, report: dict)。report 含 lines(可打印行)/errors/warnings。"""
    scenes = sb.get("scenes", [])
    n = len(scenes)
    errors, warnings, lines = [], [], []

    rows, type_counts, cat_counts = [], Counter(), Counter()
    for i, sc in enumerate(scenes):
        t = sc.get("type", "?")
        cat = category(t)
        type_counts[t] += 1
        cat_counts[cat] += 1
        rows.append((i, t, cat))

    # ---- 分布表 ----
    lines.append(f"镜头总数：{n}")
    lines.append("逐镜呈现类型：")
    for i, t, cat in rows:
        mark = {"VISUAL": "🟢图", "SEMI": "🟡解", "TEXT": "🔴字",
                "EXEMPT": "⚪牌", "UNKNOWN": "❓?"}.get(cat, cat)
        lines.append(f"  [{i:>2}] {mark}  {t}")
    lines.append("类型分布：" + "  ".join(f"{t}×{c}" for t, c in type_counts.most_common()))
    vis, semi, txt, exn = (cat_counts["VISUAL"], cat_counts["SEMI"],
                           cat_counts["TEXT"], cat_counts["EXEMPT"])
    denom = max(1, n - exn)  # 占比不算品牌结尾卡
    ratio = vis / denom
    lines.append(f"分类分布：图像级 VISUAL×{vis} | 图解 SEMI×{semi} | "
                 f"纯文字 TEXT×{txt} | 品牌 EXEMPT×{exn}")
    lines.append(f"图主文辅占比：图像级 {vis}/{denom} = {ratio:.0%}（建议 ≥{MIN_VISUAL_RATIO:.0%}）")

    # ---- E0：未知 type ----
    unknown = [(i, t) for i, t, cat in rows if cat == "UNKNOWN"]
    for i, t in unknown:
        errors.append(f"E0 镜 [{i}] 未知 type「{t}」，无法分类（拼写错误？）")

    # ---- E1：纯文字版面超限 ----
    text_idx = [i for i, t, cat in rows if cat == "TEXT"]
    if len(text_idx) > max_text:
        offenders = "、".join(f"[{i}]{rows[i][1]}" for i in text_idx)
        errors.append(
            f"E1 纯文字版面 {len(text_idx)} 镜 > 上限 {max_text} 镜——违反「图主文辅」。"
            f"\n     命中：{offenders}"
            f"\n     改法：除留 ≤{max_text} 镜做节奏点缀，其余全部换成图像级现场设计"
            f"（demo 动画 / Rough 手绘 / ECharts 数据图 / seedream 生图 / broll 素材 / logo_card）。")

    # ---- E2：连续同版式 ----
    run_start = 0
    for k in range(1, n + 1):
        same = k < n and rows[k][1] == rows[run_start][1]
        if not same:
            run_len = k - run_start
            if run_len >= max_run:
                seg = "、".join(f"[{j}]" for j in range(run_start, k))
                errors.append(
                    f"E2 连续 {run_len} 镜都是「{rows[run_start][1]}」（{seg}）——套同一版式。"
                    f"\n     改法：同一个意思换种呈现，打散这段连续。")
            run_start = k

    # ---- E3：全片零图像级镜头 ----
    if vis == 0 and n > 0:
        errors.append(
            "E3 全片 0 个图像级镜头（VISUAL=0）——这正是要根治的「零现场设计」翻车形态。"
            "\n     至少要有真实素材 / demo 动画 / 手绘图 / 生图撑起主视觉。")

    # ---- Warnings（不拦渲染）----
    if not errors and ratio < MIN_VISUAL_RATIO:
        warnings.append(
            f"W1 图像级占比 {ratio:.0%} < 建议 {MIN_VISUAL_RATIO:.0%}——SEMI/图解偏多，"
            f"考虑把部分 diagram 升级成 demo 现场设计，更不像模板。")
    # diagram-list 容易被当纯文字编号清单用
    list_diagrams = [i for i, sc in enumerate(scenes)
                     if sc.get("type") == "diagram"
                     and (sc.get("diagram") or {}).get("kind") == "list"]
    if len(list_diagrams) >= 2:
        warnings.append(
            f"W2 diagram-list 用了 {len(list_diagrams)} 次（{'、'.join(f'[{i}]' for i in list_diagrams)}）"
            f"——list 图解接近纯文字清单，别拿它当 editorial 替身。")

    ok = len(errors) == 0
    report = {"ok": ok, "lines": lines, "errors": errors, "warnings": warnings,
              "stats": {"n": n, "visual": vis, "semi": semi, "text": txt,
                        "exempt": exn, "ratio": ratio}}
    return ok, report


def format_report(report, quiet=False):
    out = []
    if not quiet:
        out.extend(report["lines"])
        out.append("")
    for w in report["warnings"]:
        out.append(f"⚠️  {w}")
    if report["ok"]:
        if not quiet:
            out.append("✅ lint 通过：图主文辅达标，未套版式。")
    else:
        out.append("❌ lint 不通过，拒绝渲染：")
        for e in report["errors"]:
            out.append(f"   {e}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="storyboard 图主文辅质量闸门")
    ap.add_argument("storyboard", help="sb.json 路径")
    ap.add_argument("--quiet", action="store_true", help="只在失败/告警时输出")
    ap.add_argument("--max-text", type=int, default=MAX_TEXT)
    ap.add_argument("--max-run", type=int, default=MAX_RUN)
    args = ap.parse_args()

    try:
        sb = json.load(open(args.storyboard, encoding="utf-8"))
    except Exception as e:
        print(f"❌ 无法读取 storyboard: {e}", file=sys.stderr)
        sys.exit(2)

    ok, report = lint(sb, max_text=args.max_text, max_run=args.max_run)
    text = format_report(report, quiet=args.quiet)
    if text.strip():
        print(text)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
