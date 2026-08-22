#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Modified by 北京万涂幻象科技有限公司, 2026-08-22.
"""公众号 HTML 合规校验器（wechat-editorial 专用）。

把 SKILL.md 里「HTML 输出实现规范」从文档自觉变成确定性兜底：
md_to_editorial.py 生成后自动跑一遍，ERROR 清零才算排版完成。

规则来源：
- 万涂幻象自家铁律（禁 <ul>/<li>、禁 <strong>、禁 <div>，全部有真实翻车记录）
- isjiamu/gzh-design-skill 的平台红线（style/script/class/id/position/float/grid 等）
- 半角标点 / 直引号检查（代码区豁免）

用法:
    validate_wx_html.py <file.html>          # 校验预览页（自动抽取正文片段）
    validate_wx_html.py --stdin < file.html

退出码: 1 = 有 ERROR; 0 = 通过。
"""

import argparse
import re
import sys
from html.parser import HTMLParser

# (正则, 级别, 说明)
# ERROR = 公众号会过滤/改写/渲染崩，或本 skill 有翻车记录的写法
FORBIDDEN = [
    (re.compile(r"<style[\s>]", re.I), "ERROR", "<style> 标签会被过滤，样式必须内联"),
    (re.compile(r"<script[\s>]", re.I), "ERROR", "<script> 标签会被过滤"),
    (re.compile(r"<link[\s>]", re.I), "ERROR", "外部 <link>（CSS/字体）会被过滤"),
    (re.compile(r"</?div[\s>]", re.I), "ERROR", "<div> 会被公众号改写，请用 <section>"),
    (re.compile(r"</?ul[\s>]", re.I), "ERROR",
     "<ul>/<li> 公众号当块元素渲染，圆点和文字垂直分离 → 用 <section>+<span> 全 inline（规范 §1）"),
    (re.compile(r"</?ol[\s>]", re.I), "ERROR", "<ol> 同 <ul>，用 render_ol 的 section 写法（规范 §1）"),
    (re.compile(r"<li[\s>]", re.I), "ERROR", "<li> 禁用（规范 §1）"),
    (re.compile(r"<strong[\s>]", re.I), "ERROR",
     "<strong> 后跟全角字符公众号强插换行 → 用 <span style=\"font-weight:700\">（规范 §2）"),
    (re.compile(r"\sclass\s*=", re.I), "ERROR", "class 属性会被剥离，请用内联 style"),
    (re.compile(r"\sid\s*=", re.I), "ERROR", "id 属性会被剥离"),
    (re.compile(r"position\s*:\s*(fixed|absolute|sticky)", re.I), "ERROR",
     "position fixed/absolute/sticky 会被公众号过滤"),
    (re.compile(r"float\s*:", re.I), "ERROR", "float 不被支持"),
    (re.compile(r"@media", re.I), "ERROR", "@media 不被支持"),
    (re.compile(r"@keyframes", re.I), "ERROR", "@keyframes 不被支持"),
    (re.compile(r"@import", re.I), "ERROR", "@import 不被支持"),
    (re.compile(r"display\s*:\s*grid", re.I), "ERROR", "display:grid 不被支持，请用 flex"),
    (re.compile(r"var\s*\(\s*--", re.I), "ERROR", "CSS 变量不被支持，请写死色值"),
    (re.compile(r"\x00"), "ERROR",
     "残留 \\x00 占位符——inline() 的 code stash 没还原干净，模板 bug"),
    (re.compile(r'src=""'), "ERROR",
     'img src 为空——img_url() 没找到图片文件（wikilink 文件名拼错或图不在 Vault）'),
]

CJK = re.compile(r"[一-鿿㐀-䶿]")
# 中文字后紧跟半角逗号/分号/叹号/问号（应改全角）；只查"中文在前"避免中英混排误伤
HALF_PUNCT = re.compile(r"[一-鿿㐀-䶿][,;!?]")
ASCII_QUOTE = re.compile(r"[\"']")
# 代码区特征：等宽字体 —— 其内半角符号是正常的
CODE_STYLE = re.compile(r"monospace|menlo|monaco|courier|consolas", re.I)


def extract_fragment(html):
    """预览页（含 DOCTYPE/head/复制按钮外壳）→ 抽出实际粘贴进公众号的正文片段。
    md_to_editorial.py 的结构固定：<section id="article-body" ...>正文</section>\n<script>
    抽不到（比如给的就是干净片段）则原样返回。
    """
    m = re.search(r'<section id="article-body"[^>]*>(.*)</section>\s*<script>',
                  html, re.S)
    return m.group(1) if m else html


class TextAuditor(HTMLParser):
    """扫正文文本节点：半角标点 / 英文直引号（等宽代码区豁免）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # [(tag, is_code)]
        self.code_depth = 0
        self.half_punct = []

    def handle_starttag(self, tag, attrs):
        style = dict(attrs).get("style", "") or ""
        is_code = tag == "code" or bool(CODE_STYLE.search(style))
        if is_code:
            self.code_depth += 1
        self.stack.append((tag, is_code))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for _, was_code in self.stack[i:]:
                    if was_code:
                        self.code_depth -= 1
                del self.stack[i:]
                break

    def handle_data(self, data):
        text = data.strip()
        if not text or not CJK.search(text):
            return
        if self.code_depth == 0 and (HALF_PUNCT.search(text)
                                     or ASCII_QUOTE.search(text)):
            snippet = text[:24] + ("…" if len(text) > 24 else "")
            self.half_punct.append(snippet)


def validate(html):
    """返回 (errors, warnings)。传入预览页全文或干净片段都行。"""
    frag = extract_fragment(html)
    # base64 图先压掉：不影响任何规则，避免正则扫几十 MB 的 data URI
    slim = re.sub(r'data:[^"\']{64,}', 'data:__b64__', frag)

    errors, warnings = [], []
    for rx, level, msg in FORBIDDEN:
        hits = len(rx.findall(slim))
        if hits:
            (errors if level == "ERROR" else warnings).append(
                f"{msg}（命中 {hits} 处）")

    # img 用 width:100%（非 max-width）——滚动框/SLIDER/封面卡里是有意的，按上下文豁免
    EXEMPT_CONTEXT = ('overflow-y:auto', 'scroll-snap-align',
                      'border-radius:20px;overflow:hidden')  # scrollbox / SLIDER / 封面卡
    w100 = 0
    for m in re.finditer(r'<img[^>]*style="[^"]*(?<![-\w])width\s*:\s*100%', slim):
        ctx = slim[max(0, m.start() - 400):m.start()]
        if not any(k in ctx for k in EXEMPT_CONTEXT):
            w100 += 1
    if w100:
        warnings.append(
            f"{w100} 张普通配图 <img> 用了 width:100%——必须 max-width:100%"
            "（小图会被拉糊，规范 §3；滚动框/SLIDER/封面卡已自动豁免）")

    auditor = TextAuditor()
    try:
        auditor.feed(slim)
    except Exception as e:
        warnings.append(f"HTML 解析中断: {e}")
    if auditor.half_punct:
        sample = "；".join(f"「{s}」" for s in auditor.half_punct[:5])
        warnings.append(
            f"{len(auditor.half_punct)} 处正文疑似半角标点/英文直引号，建议改全角"
            f"（代码区不计）。例：{sample}")

    return errors, warnings


def report(errors, warnings, name="<input>"):
    print(f"📋 公众号 HTML 合规校验: {name}")
    if errors:
        print(f"❌ ERROR ×{len(errors)}（必须修复，否则粘贴后翻车）:")
        for e in errors:
            print(f"   • {e}")
    if warnings:
        print(f"⚠️  WARNING ×{len(warnings)}（人工确认）:")
        for w in warnings:
            print(f"   • {w}")
    if not errors and not warnings:
        print("✅ 完全合规，可直接粘贴到公众号编辑器")
    elif not errors:
        print("✅ 无致命问题，可粘贴（warning 请人工确认）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="HTML 文件路径")
    ap.add_argument("--stdin", action="store_true", help="从标准输入读取")
    args = ap.parse_args()

    if args.stdin or not args.file:
        html = sys.stdin.read()
        name = "<stdin>"
    else:
        with open(args.file, encoding="utf-8", errors="replace") as f:
            html = f.read()
        name = args.file

    errors, warnings = validate(html)
    report(errors, warnings, name)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
