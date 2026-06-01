#!/usr/bin/env python3
"""主编排脚本：吃 story.json，依次跑 头像导出 → HTML 渲染 → PNG 长图。

用法（AI 准备好 story.json 后调用）:
    python3 make_daily.py \\
        --story /tmp/story.json \\
        --out-dir ~/Desktop

输出:
    ~/Desktop/群日报_<群名>_<日期>.html
    ~/Desktop/群日报_<群名>_<日期>.png
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def collect_wxids(story):
    """从 story 中收集需要头像的人物 → wxid 映射。

    story.timeline[].cast: [{name, wxid}] 或 story.timeline[].protagonists +
    story.timeline[].wxids 平行数组都支持。
    story.highlights[].name + .wxid 也收集。
    """
    mapping = {}

    for s in story.get("timeline", []):
        cast = s.get("cast")
        if cast:
            for c in cast:
                if c.get("wxid"):
                    mapping[c["wxid"]] = c["name"]
        else:
            names = s.get("protagonists", [])
            wxids = s.get("wxids", [])
            for n, w in zip(names, wxids):
                if w:
                    mapping[w] = n

    for hl in story.get("highlights", []):
        if hl.get("wxid"):
            mapping[hl["wxid"]] = hl["name"]

    return mapping


def normalize_protagonists(story):
    """把 timeline[].cast 形式归一化为 protagonists + wxids 平行数组"""
    for s in story.get("timeline", []):
        if "cast" in s and not s.get("protagonists"):
            cast = s["cast"]
            s["protagonists"] = [c["name"] for c in cast]
            s["wxids"] = [c.get("wxid", "") for c in cast]


def run(cmd, **kwargs):
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True, **kwargs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True, help="story.json 路径")
    ap.add_argument("--out-dir", default="~/Desktop",
                    help="输出目录（默认桌面）")
    ap.add_argument("--name-suffix", default="",
                    help="文件名后缀，例如 _draft")
    ap.add_argument("--no-open", action="store_true",
                    help="生成后不自动打开")
    args = ap.parse_args()

    story_path = os.path.expanduser(args.story)
    with open(story_path, encoding="utf-8") as f:
        story = json.load(f)

    normalize_protagonists(story)
    # 写回归一化后的 story（render_html.py 用 protagonists）
    norm_story_path = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(story, norm_story_path, ensure_ascii=False)
    norm_story_path.close()

    out_dir = Path(os.path.expanduser(args.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    group = story.get("group_name", "群")
    date = story.get("date", "未知日期")
    stem = f"群日报_{group}_{date}{args.name_suffix}"
    html_path = out_dir / f"{stem}.html"
    png_path = out_dir / f"{stem}.png"

    # 1. 头像
    wxid_map = collect_wxids(story)
    avatars_path = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False
    ).name
    if wxid_map:
        names_map_path = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(wxid_map, names_map_path, ensure_ascii=False)
        names_map_path.close()

        run([
            sys.executable, str(SCRIPT_DIR / "extract_avatars.py"),
            "--names-map", names_map_path.name,
            "--out", avatars_path,
        ])
    else:
        # 空头像也得有文件
        with open(avatars_path, "w") as f:
            json.dump({}, f)

    # 2. HTML
    run([
        sys.executable, str(SCRIPT_DIR / "render_html.py"),
        "--story", norm_story_path.name,
        "--avatars", avatars_path,
        "--out", str(html_path),
    ])

    # 3. PNG
    run([
        sys.executable, str(SCRIPT_DIR / "html_to_png.py"),
        "--html", str(html_path),
        "--out", str(png_path),
    ])

    print(f"\n✅ 生成完成", file=sys.stderr)
    print(f"   HTML: {html_path}", file=sys.stderr)
    print(f"   PNG:  {png_path}", file=sys.stderr)

    if not args.no_open and sys.platform == "darwin":
        subprocess.run(["open", str(html_path)])
        subprocess.run(["open", str(png_path)])


if __name__ == "__main__":
    main()
