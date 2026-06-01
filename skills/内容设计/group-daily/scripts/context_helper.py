#!/usr/bin/env python3
"""群风格指纹的目录助手。

仅沉淀群文化（不沉淀个人画像）。脚本只做：检查文件是否存在、给出路径。
真正的读写由 AI 用 Read / Write / Edit 工具完成。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path


def resolve_vault_root() -> Path:
    """解析群日报数据根目录。

    优先级:
      1. 环境变量 GROUP_DAILY_VAULT
      2. ~/Documents/GroupDaily（开箱即用默认）

    返回的目录会被作为 styles/ 和 story.json 归档的父目录。
    """
    env = os.environ.get("GROUP_DAILY_VAULT")
    if env:
        return Path(os.path.expanduser(env))
    return Path.home() / "Documents/GroupDaily"


GROUP_DAILY_DIR = resolve_vault_root()
STYLES_DIR = GROUP_DAILY_DIR / "styles"


def safe_name(name):
    """文件名做安全处理：替换路径分隔符和 macOS 不允许的字符"""
    return re.sub(r'[/\\:]', '_', name).strip()


def cmd_check_style(args):
    """查群风格指纹是否存在。"""
    path = STYLES_DIR / f"{safe_name(args.group_name)}.md"
    result = {
        "group_name": args.group_name,
        "path": str(path),
        "exists": path.exists(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_list_styles(args):
    """列出所有已有的群风格指纹。"""
    if not STYLES_DIR.exists():
        print(json.dumps({"styles": [], "count": 0}, ensure_ascii=False, indent=2))
        return
    styles = sorted(p.stem for p in STYLES_DIR.glob("*.md"))
    print(json.dumps({"styles": styles, "count": len(styles)},
                     ensure_ascii=False, indent=2))


def cmd_bootstrap_dirs(args):
    """初始化目录。"""
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✅ 已创建目录: {STYLES_DIR}")


def cmd_path(args):
    """返回某个 style 应该写到的路径（不创建文件）。"""
    if args.style:
        path = STYLES_DIR / f"{safe_name(args.style)}.md"
    else:
        sys.exit("需要 --style <群名>")
    print(str(path))


def main():
    ap = argparse.ArgumentParser(
        description="群风格指纹的目录助手（仅 styles，不再包含 personas）"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("check-style", help="查群风格指纹是否存在")
    p1.add_argument("--group-name", required=True)
    p1.set_defaults(func=cmd_check_style)

    p2 = sub.add_parser("list-styles", help="列出所有已有 styles")
    p2.set_defaults(func=cmd_list_styles)

    p3 = sub.add_parser("bootstrap-dirs", help="初始化 styles 目录")
    p3.set_defaults(func=cmd_bootstrap_dirs)

    p4 = sub.add_parser("path", help="返回某个 style 应该写到的路径")
    p4.add_argument("--style", required=True, help="群名")
    p4.set_defaults(func=cmd_path)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
