#!/usr/bin/env python3
"""gongzhonghao-typeset CLI 入口。

默认 panel 模式：把 md 渲染结果嵌入 preview.html 模板，输出带控制面板的预览页。
左侧实时预览公众号文章 + 右侧主题控制面板（品牌/配色/排版/图片 + 三种吸色 + 一键复制）。

用法:
    python3 cli.py <md_path>                       # 默认（panel 模式 + 浏览器打开）
    python3 cli.py <md_path> --theme my.json       # 自定义主题
    python3 cli.py <md_path> --img-dir /path       # 图片搜索目录
    python3 cli.py <md_path> --out /tmp/x.html     # 输出路径
    python3 cli.py <md_path> --vol 188             # 覆盖期号
    python3 cli.py <md_path> --no-panel            # 裸模式（无控制面板，wechat-editorial 风格）
    python3 cli.py <md_path> --plain               # 关刊头刊尾（合作稿，仅 --no-panel 生效）
    python3 cli.py <md_path> --no-open             # 不自动打开浏览器
"""
import argparse
import json
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import Theme, render_article, render_article_body, build_theme_css_vars


def _replace_article_section(template, new_inner):
    """在 preview.html 模板里找 `<section class="article" id="article">...</section>`（最外层
    article 标签，正确处理嵌套 section），把内部内容替换为 new_inner。"""
    start_tag = '<section class="article" id="article">'
    start_idx = template.find(start_tag)
    if start_idx < 0:
        return template
    pos = start_idx + len(start_tag)
    depth = 1
    while depth > 0 and pos < len(template):
        next_open = template.find('<section', pos)
        next_close = template.find('</section>', pos)
        if next_close < 0:
            return template
        if 0 <= next_open < next_close:
            depth += 1
            pos = next_open + len('<section')
        else:
            depth -= 1
            if depth == 0:
                close_end = next_close + len('</section>')
                new_block = f'{start_tag}\n{new_inner}\n    </section>'
                return template[:start_idx] + new_block + template[close_end:]
            pos = next_close + len('</section>')
    return template


def _inject_theme_css_vars(template, theme):
    """把 theme.json 的实际值注入到 preview.html 的 :root 块（替换公众号主题相关变量）。
    UI 控制面板自身的变量（--ui-*）保留不动。"""
    new_vars = build_theme_css_vars(theme)
    # 找第一个 :root { ... 注释或下个块开始 } 区段
    # preview.html 的 :root 块以 ' /* UI 变量' 注释作为公众号主题段和 UI 段的分界
    start_marker = ':root {'
    sep_marker = '/* UI 变量'
    s = template.find(start_marker)
    if s < 0:
        return template
    sep = template.find(sep_marker, s)
    if sep < 0:
        return template
    inner_start = s + len(start_marker)
    # 替换公众号主题段，UI 段保留
    return template[:inner_start] + '\n    ' + new_vars.replace(';', ';\n    ') + '\n    ' + template[sep:]


def render_panel_mode(md_path, theme, img_dir):
    """读 preview.html 模板 + 替换 article body + 注入 theme :root 变量。"""
    template_path = Path(__file__).parent.parent / 'templates' / 'preview.html'
    template = template_path.read_text(encoding='utf-8')

    md_text = md_path.read_text(encoding='utf-8')
    inner, _art = render_article_body(md_text, theme, img_dir=img_dir, plain=False)

    output = _replace_article_section(template, inner)
    output = _inject_theme_css_vars(output, theme)
    return output


def main():
    parser = argparse.ArgumentParser(description='公众号排版 · agent 写完的 markdown → 公众号 HTML')
    parser.add_argument('md_path', help='源 markdown 路径')
    parser.add_argument('--theme', default=None, help='theme.json 路径（默认读 skill 目录下 theme.json）')
    parser.add_argument('--img-dir', default=None, help='图片搜索目录（默认 md 同目录）')
    parser.add_argument('--out', default='/tmp/wx_preview.html', help='输出 HTML 路径')
    parser.add_argument('--vol', type=int, default=None, help='期号（覆盖 theme.json）')
    parser.add_argument('--no-panel', action='store_true', help='裸模式（无控制面板）')
    parser.add_argument('--plain', action='store_true', help='关刊头刊尾（仅 --no-panel 生效）')
    parser.add_argument('--no-open', dest='no_open', action='store_true', help='不自动打开浏览器')
    args = parser.parse_args()

    md_path = Path(args.md_path).expanduser().resolve()
    if not md_path.exists():
        print(f"✗ md 文件不存在: {md_path}", file=sys.stderr)
        sys.exit(1)

    if args.theme:
        theme_path = Path(args.theme).expanduser().resolve()
    else:
        theme_path = Path(__file__).parent.parent / 'theme.json'
    if not theme_path.exists():
        print(f"✗ theme.json 不存在: {theme_path}", file=sys.stderr)
        sys.exit(1)

    theme_data = json.loads(theme_path.read_text(encoding='utf-8'))
    theme = Theme(theme_data)
    if args.vol is not None:
        theme.brand['issue_number'] = args.vol

    img_dir = Path(args.img_dir).expanduser().resolve() if args.img_dir else md_path.parent

    if args.no_panel:
        md_text = md_path.read_text(encoding='utf-8')
        html = render_article(md_text, theme, img_dir=img_dir, plain=args.plain)
        mode = '裸模式'
    else:
        html = render_panel_mode(md_path, theme, img_dir)
        mode = 'panel 模式'

    out_path = Path(args.out).expanduser().resolve()
    out_path.write_text(html, encoding='utf-8')
    print(f"✓ {out_path} ({len(html)//1024}KB, {mode})")

    if not args.no_open:
        subprocess.run(['open', str(out_path)])


if __name__ == '__main__':
    main()
