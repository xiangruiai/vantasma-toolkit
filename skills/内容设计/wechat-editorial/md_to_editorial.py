#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Modified by 北京万涂幻象科技有限公司, 2026-08-22.
"""
万涂幻象公众号排版 v3 翠绿卡片风

视觉层移植自 isjiamu/gzh-design-skill 的 theme-moyu-green 组件库（脚本化确定性实现）。
管线沿用 v2：wikilink → base64、frontmatter 中文 key、附录截断、超长图 scrollbox、
SLIDER 滑动图组、生成后自动跑 validate_wx_html.py。

当前 v3：
- 封面图硬性前置，封面采用白色信息条卡
- 章节头采用超大灰数字 + 深黑标题，不生成滑动目录
- 黄色高亮、浅绿下划线与绿色加粗形成三层标记
- 默认追加可替换的 PNG + GIF 品牌尾卡
- 保留 WeChat 兼容铁律：禁 <div>/<ul>/<li>/<strong>，装饰空元素放 <span leaf=""><br></span>
"""
import re, os, sys, base64, mimetypes, html as html_mod
from pathlib import Path
from urllib.parse import quote

VAULT = os.environ.get("WECHAT_EDITORIAL_VAULT", "")
PLAIN_MODE = False  # --plain：关掉封面和固定品牌尾卡（合作稿用）
IMG_ROOT = os.environ.get("WECHAT_EDITORIAL_IMAGE_ROOT", "")
SRC = ""
OUT = "/tmp/wx_preview.html"

# ── 设计变量（theme-moyu-green 速查表） ──
C_MAIN = "#059669"        # emerald-600 主色
C_MAIN2 = "#10B981"       # emerald-500 辅色（渐变用）
C_UNDERLINE = "#A7F3D0"   # 绿色下划线（标记层默认）
C_GREEN_BORDER = "#BBF7D0"
C_GREEN_BG = "#ECFDF5"    # 浅绿背景
C_YELLOW = "#FDE68A"      # 黄色高亮（锚点层）
C_TITLE = "#111827"       # 标题色
C_TEXT = "#374151"        # 正文色
C_TEXT2 = "#4B5563"       # 次要文字
C_LABEL = "#6B7280"       # 注释/标签
C_FAINT = "#9CA3AF"       # 辅助文字
C_LINE = "#D1D5DB"        # 分隔线
C_BORDER = "#E5E7EB"      # 浅边框
C_GRAY_BG = "#F3F4F6"     # 浅灰背景
C_GRAY_BG2 = "#F9FAFB"    # 极浅灰

FONT = "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
MONO = "'SF Mono',Consolas,Monaco,monospace"
LEAF_BR = '<span leaf=""><br></span>'  # 装饰性空元素占位（微信兼容铁律）
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')  # 尾部动效 GIF
BRAND_NAME = os.environ.get("WECHAT_EDITORIAL_BRAND", "万涂幻象")
BRAND_TAGLINE = os.environ.get("WECHAT_EDITORIAL_TAGLINE", "让 AI 真的进业务")
FOOTER_CARD = os.environ.get(
    "WECHAT_EDITORIAL_FOOTER_CARD",
    os.path.join(ASSETS_DIR, "footer_profile_card.png"),
)
FOOTER_ACTIONS = os.environ.get(
    "WECHAT_EDITORIAL_FOOTER_ACTIONS",
    os.path.join(ASSETS_DIR, "footer_actions_brand.gif"),
)

def _resolve_img_path(name):
    """解析图片路径：绝对路径 → 文章目录 → image root → vault 全局搜索。"""
    if not name:
        return None
    candidate = Path(name).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if SRC:
        article_relative = Path(SRC).expanduser().resolve().parent / candidate
        if article_relative.exists():
            return article_relative
    if IMG_ROOT:
        image_root_relative = Path(IMG_ROOT).expanduser() / candidate
        if image_root_relative.exists():
            return image_root_relative
    if VAULT:
        vault_path = Path(VAULT).expanduser()
        if vault_path.exists():
            for found in vault_path.rglob(candidate.name):
                return found
    return None

def img_url(name):
    """wikilink 文件名 → base64 data URI；http(s)/data URL 直通；绝对路径直接读。"""
    if name.startswith(('http://', 'https://', 'data:')):
        return name
    p = _resolve_img_path(name)
    if p is None:
        return ''
    mime = mimetypes.guess_type(str(p))[0] or 'image/jpeg'
    try:
        with open(p, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
        return f'data:{mime};base64,{b64}'
    except Exception:
        return 'file://' + quote(str(p), safe='/:')

def inline(text):
    """内联渲染（三层视觉层级）：
    - **粗体**      → 6a 绿色加粗（用 span 不用 strong，公众号对 strong 后跟全角字符强插换行）
    - ==文字==      → 6c 黄色渐变高亮（锚点层，全文 ≤5 处）
    - ++文字++/<u>  → 6e 绿色下划线（标记层默认）
    - ~~文字~~      → 6i 删除线灰（被淘汰的概念）
    - 「文字」      → 浅灰胶囊（UI 按钮名）
    - `代码`        → 1c 行内代码（浅灰底 + 主色字）
    """
    stash = []
    def _stash(m):
        idx = len(stash)
        stash.append(html_mod.escape(m.group(1)))
        return f'\x00CODE{idx}\x00'
    text = re.sub(r'`([^`]+)`', _stash, text)

    # 6c 黄色渐变高亮
    text = re.sub(
        r'==([^=]+)==',
        rf'<span style="background:linear-gradient(120deg,{C_YELLOW} 0%,rgba(255,255,255,0) 100%);'
        rf'padding:0 4px;border-radius:2px;font-weight:600;color:{C_TITLE};">\1</span>',
        text
    )
    # 6i 删除线灰
    text = re.sub(
        r'~~([^~]+)~~',
        rf'<span style="background:{C_GRAY_BG};color:{C_LABEL};padding:2px 6px;border-radius:4px;'
        rf'font-size:13px;text-decoration:line-through;font-weight:600;">\1</span>',
        text
    )
    # 按钮胶囊「xxx」
    text = re.sub(
        r'「([^」]+)」',
        rf'<span style="background:{C_GRAY_BG};color:{C_TITLE};padding:2px 10px;border-radius:6px;'
        rf'font-size:0.92em;font-weight:600;margin:0 2px;">「\1」</span>',
        text
    )
    # 6a 绿色加粗（span 版）
    text = re.sub(
        r'\*\*(.+?)\*\*',
        rf'<span style="color:{C_MAIN};font-weight:700;">\1</span>',
        text
    )
    # 6e 绿色下划线（标记层）
    underline_span = (f'<span style="border-bottom:2px solid {C_UNDERLINE};'
                      f'font-weight:600;color:{C_TITLE};">\\1</span>')
    text = re.sub(r'\+\+(.+?)\+\+', underline_span, text)
    text = re.sub(r'<u>(.+?)</u>', underline_span, text)

    # 还原 inline code → 1c
    def _restore(m):
        content = stash[int(m.group(1))]
        return (f'<span style="background:#F1F5F9;color:{C_MAIN};padding:1px 6px;border-radius:4px;'
                f'font-family:{MONO};font-size:13px;font-weight:600;">{content}</span>')
    text = re.sub(r'\x00CODE(\d+)\x00', _restore, text)
    return text

_VOID_TAG = re.compile(r'<(img|br|hr|input|meta)[\s/>]', re.I)

def leafify(html_text):
    """公众号 leaf 规范（2026-07-07 实测翻车修正）：
    leaf 必须在最里层贴着文字；把 inline() 产物整个包进 <span leaf=""> 外壳，
    编辑器会把 leaf 当纯文本节点处理，内层样式 span（下划线/绿粗/高亮）粘贴后全被剥掉。
    本函数只给"顶层裸文本段"补 leaf，样式 span 保持原样（v2 时代 245 期验证裸样式 span 可用）。"""
    out, depth = [], 0
    for tok in re.split(r'(<[^>]+>)', html_text):
        if not tok:
            continue
        if tok.startswith('<'):
            out.append(tok)
            if tok.startswith('</'):
                depth = max(0, depth - 1)
            elif not tok.endswith('/>') and not _VOID_TAG.match(tok):
                depth += 1
        elif depth == 0 and tok.strip():
            out.append(f'<span leaf="">{tok}</span>')
        else:
            out.append(tok)
    return ''.join(out)

def parse_article():
    with open(SRC, encoding='utf-8') as f:
        content = f.read()
    m = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
    frontmatter = m.group(1) if m else ""
    body = content[m.end():] if m else content
    # 去尾部素材溯源/关联笔记/修订记录等附录（最早匹配位置切断）
    cut_m = re.search(r'\n(?:---\s*\n)?##\s+(素材溯源|关联笔记|修订记录|附录|参考资料)', body)
    if cut_m:
        body = body[:cut_m.start()]
    title_m = re.search(r'^标题:\s*(.+)$', frontmatter, re.M)
    subtitle_m = re.search(r'^副标题:\s*(.+)$', frontmatter, re.M)
    cover_m = re.search(r'^封面图:\s*(.+)$', frontmatter, re.M)
    date_m = re.search(r'^创建时间:\s*(.+)$', frontmatter, re.M)
    footer_m = re.search(r'^(?:固定尾卡|显示固定尾卡|尾部|显示尾部|尾部三连):\s*(.+)$', frontmatter, re.M)
    hide_footer_m = re.search(r'^隐藏尾部:\s*(.+)$', frontmatter, re.M)
    tags = re.findall(r'^\s*-\s+(.+?)$', re.search(r'标签:\s*\n((?:\s*-\s+.+\n)+)', frontmatter).group(1) if re.search(r'标签:\s*\n((?:\s*-\s+.+\n)+)', frontmatter) else '', re.M)
    meta_tags = [t.strip() for t in tags if not any(t.startswith(p) for p in ('类型/', '状态/', '来源/', '用途/')) and t.strip() != '公众号']
    def _strip_quotes(s):
        s = s.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            return s[1:-1]
        return s
    show_footer = True
    if footer_m:
        show_footer = _strip_quotes(footer_m.group(1)).lower() not in ('false', '0', 'no', '否', '不显示', '关闭')
    if hide_footer_m:
        show_footer = _strip_quotes(hide_footer_m.group(1)).lower() not in ('true', '1', 'yes', '是', '隐藏', '关闭')
    return {
        'title': _strip_quotes(title_m.group(1)) if title_m else '',
        'subtitle': _strip_quotes(subtitle_m.group(1)) if subtitle_m else '',
        'cover': _strip_quotes(cover_m.group(1)) if cover_m else '',
        'date': date_m.group(1).strip() if date_m else '',
        'tags': meta_tags,
        'show_footer': show_footer,
        'body': body.strip()
    }

# ── 章节预扫描（供 TOC + 编号用） ──
H2_LAST_WHITELIST = {'写在最后', '写在最後', '结语', '最后'}

def prescan_chapters(body):
    """收集 ## 标题 和 **N. 标题** 两种章节写法，按出现顺序返回标题列表。"""
    chapters = []
    in_code = False
    for line in body.split('\n'):
        if line.startswith('```'):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith('## ') and not line.startswith('###'):
            chapters.append(line[3:].strip())
            continue
        am = re.match(r'^\*\*(\d+)\.\s*([^*]+?)\*\*\s*$', line.rstrip())
        if am:
            chapters.append(am.group(2).strip())
    return chapters

def _chapter_no(idx, title, total):
    """章节编号显示：末章命中白名单 → ('///', 'LAST')，否则 ('01', 'PART')"""
    if title in H2_LAST_WHITELIST and idx == total - 1:
        return '///', 'LAST'
    return f'{idx + 1:02d}', 'PART'

# ── 组件渲染 ──

def render_paragraph(text):
    has_url = 'http' in text or 'github.com' in text
    align = 'text-align:left;' if has_url else 'text-align:justify;'
    return (f'<p style="margin:0 0 16px;font-size:14px;line-height:1.9;letter-spacing:0.5px;'
            f'color:{C_TEXT};{align}word-break:break-word;">{leafify(inline(text))}</p>')

def render_chapter(idx, title, total):
    """章节头（方案 D 终稿，2026-07-07 最终拍板）：极简减负
    58px 超大灰数字 + 22px 深黑标题同行，无小戳无横线无英文
    （品牌已在封面信息条和文末签名出现，章节头不再重复）"""
    no, _ = _chapter_no(idx, title, total)
    top = '28px' if idx == 0 else '56px'
    return f'''<section style="margin:{top} 0 24px;">
  <section style="display:flex;align-items:flex-end;gap:18px;">
    <span style="display:block;font-size:58px;font-weight:900;color:{C_LINE};line-height:0.95;letter-spacing:-2px;flex-shrink:0;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;"><span leaf="">{no}</span></span>
    <span style="flex:1;font-size:22px;font-weight:800;color:{C_TITLE};line-height:1.3;letter-spacing:-0.2px;padding-bottom:6px;">{leafify(inline(title))}</span>
  </section>
</section>'''

def render_h3(text):
    """组件 9c subtitle-highlight：黄色下划线小节标题"""
    return (f'<p style="margin:32px 0 16px;font-size:15px;font-weight:900;color:{C_TITLE};">'
            f'<span style="background:linear-gradient(180deg,transparent 65%,{C_YELLOW} 65%);padding:0 4px;">'
            f'{leafify(inline(text))}</span></p>')

def infer_caption_from_filename(name):
    stem = Path(name).stem
    stem = re.sub(r'^\d{1,2}[-_]', '', stem)
    for prefix in ('部署-', '场景-', '架构-', '对比-', '收束图-', '场景适配-'):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    return stem

def render_image_with_caption(img_name, caption):
    """组件 2a/2b：白卡图片容器 + 居中灰 caption；GIF 加浅绿角标；
    文件名含"全图/长图/scrollbox/longshot" → 固定高度滚动框"""
    src = img_url(img_name)
    cap = inline(caption) if caption else ''
    is_gif = img_name.lower().endswith('.gif')
    if is_gif and cap:
        # 角标只在有 caption 时出现；无 caption 的 GIF 不显示（孤零零一个"GIF 动图"当图注很怪）
        badge = (f'<span style="display:inline-block;background:{C_GREEN_BG};color:{C_MAIN};font-size:11px;'
                 f'font-weight:700;padding:1px 8px;border-radius:4px;margin-right:6px;"><span leaf="">GIF 动图</span></span>')
        cap_html = (f'<p style="text-align:center;margin:0 0 24px;">{badge}'
                    f'<span style="font-size:12px;color:{C_FAINT};">{leafify(cap)}</span></p>')
    else:
        cap_html = (f'<p style="font-size:12px;color:{C_FAINT};text-align:center;margin:0 0 24px;">'
                    f'{leafify(cap)}</p>') if cap else ''
    mb = '8px' if cap_html else '24px'

    is_scrollbox = any(k in img_name for k in ('全图', '长图', 'scrollbox', 'longshot'))
    if is_scrollbox:
        return (f'<section style="background:#fff;border-radius:12px;padding:6px;border:1px solid {C_BORDER};'
                f'box-shadow:0 4px 12px -2px rgba(0,0,0,0.08);margin:24px 0 8px;">'
                f'<section style="max-height:560px;overflow-y:auto;-webkit-overflow-scrolling:touch;border-radius:8px;">'
                f'<img src="{src}" style="width:100%;display:block;">'
                f'</section></section>'
                f'<p style="margin:0 0 8px;font-size:11px;color:{C_FAINT};letter-spacing:1px;text-align:center;">'
                f'<span leaf="">↕ 在框内上下滑动可浏览完整长图 ↕</span></p>'
                f'{cap_html}')

    return (f'<section style="background:#fff;border-radius:12px;padding:6px;border:1px solid {C_BORDER};'
            f'box-shadow:0 4px 12px -2px rgba(0,0,0,0.08);margin:24px 0 {mb};">'
            f'<section style="margin:0;border-radius:8px;overflow:hidden;">'
            f'<span leaf=""><img src="{src}" style="max-width:100%;height:auto;display:block;margin:0 auto;"></span>'
            f'</section></section>{cap_html}')

def render_table(rows):
    """组件 11f：绿表头 + 偶数行浅灰底"""
    if not rows:
        return ''
    head, body = rows[0], rows[1:]
    th = ''.join(
        f'<th style="background:{C_MAIN};color:#fff;font-weight:700;padding:8px 12px;text-align:left;font-size:13px;">{leafify(inline(c))}</th>'
        for c in head
    )
    trs = []
    for idx, row in enumerate(body):
        bg = f'background:{C_GRAY_BG2};' if idx % 2 == 1 else ''
        tds = ''.join(
            f'<td style="padding:8px 12px;border-bottom:1px solid {C_BORDER};color:{C_TEXT};font-size:13px;line-height:1.7;vertical-align:top;{bg}">{leafify(inline(c))}</td>'
            for c in row
        )
        trs.append(f'<tr>{tds}</tr>')
    return f'''<section style="margin:0 0 24px;overflow-x:auto;-webkit-overflow-scrolling:touch;">
  <table style="width:100%;border-collapse:collapse;font-size:13px;font-family:inherit;">
    <thead><tr>{th}</tr></thead>
    <tbody>{''.join(trs)}</tbody>
  </table>
</section>'''

def render_slider(items, title=''):
    """横向滑动图片组：浏览器可滑（scroll-snap），微信降级纵向。"""
    cards = []
    for img_name, caption in items:
        src = img_url(img_name)
        cap = inline(caption) if caption else ''
        cap_html = f'<p style="margin:10px 0 0;font-size:12px;color:{C_FAINT};line-height:1.7;text-align:center;">{leafify(cap)}</p>' if cap else ''
        cards.append(f'''<section style="flex:0 0 78%;max-width:360px;margin-right:14px;scroll-snap-align:start;">
  <section style="background:#fff;border-radius:12px;padding:6px;border:1px solid {C_BORDER};box-shadow:0 4px 12px -2px rgba(0,0,0,0.08);">
    <img src="{src}" style="width:100%;display:block;border-radius:8px;">
  </section>
  {cap_html}
</section>''')
    label = f'← SWIPE · {title} · 共 {len(items)} 张 →' if title else f'← SWIPE · 共 {len(items)} 张 →'
    return f'''<section style="margin:28px 0;">
  <p style="margin:0 0 14px;font-size:11px;color:{C_MAIN};letter-spacing:3px;font-weight:700;"><span leaf="">{label}</span></p>
  <section style="display:flex;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:14px;-webkit-overflow-scrolling:touch;">
    {''.join(cards)}
  </section>
</section>'''

def render_quote(text):
    """组件 9a quote-box：灰底虚线引用框（本主题风格特征）；纯 URL 降级成链接段"""
    stripped = text.strip()
    if re.match(r'^https?://\S+$', stripped):
        return (f'<p style="margin:0 0 20px;font-size:14px;line-height:1.85;word-break:break-all;">'
                f'<a href="{stripped}" style="color:{C_MAIN};text-decoration:underline;"><span leaf="">{stripped}</span></a></p>')
    return f'''<section style="background:{C_GRAY_BG2};border:1px dashed {C_LINE};border-radius:8px;padding:12px 16px;margin:0 0 24px;text-align:justify;">
  <p style="font-size:13px;color:{C_TEXT};margin:0;line-height:1.8;">{leafify(inline(text))}</p>
</section>'''

def render_oneliner(text):
    """组件 9b oneliner-card：一句话金句卡（居中绿字 + 黄底线，浅绿虚线框）。语法：`>> 金句`"""
    return f'''<section style="background:#fff;border:1px dashed {C_GREEN_BORDER};border-radius:8px;padding:14px 16px;margin:0 0 24px;text-align:center;">
  <p style="margin:0;line-height:1.8;">
    <span style="font-size:15px;color:{C_MAIN};font-weight:bold;border-bottom:3px solid {C_YELLOW};padding-bottom:2px;">{leafify(inline(text))}</span>
  </p>
</section>'''

def render_yellow_warning(text):
    """组件 10c yellow-warning：黄色警告框。语法：段落以 ⚠️ 开头"""
    return f'''<section style="background:#FFFBEB;border:1px solid {C_YELLOW};border-radius:12px;padding:12px 16px;margin:0 0 20px;">
  <p style="font-size:13px;color:#92400E;margin:0;font-weight:700;line-height:1.8;"><span leaf="">⚠️ </span>{leafify(inline(text))}</p>
</section>'''

def render_green_info(text):
    """组件 10d green-info：绿色信息框（亮点提示）。语法：段落以 💡 开头"""
    return f'''<section style="background:#F0FDF4;padding:12px 16px;border-radius:8px;border:1px solid {C_GREEN_BORDER};margin:0 0 20px;">
  <p style="font-size:13px;color:{C_TEXT};margin:0;line-height:1.8;text-align:justify;"><span leaf="">💡 </span>{leafify(inline(text))}</p>
</section>'''

def _code_line(ln):
    """代码行：HTML escape + 行首空格转全角（不用 white-space:pre，避免公众号大缩进翻车）"""
    ln = ln.replace('\t', '    ')
    m = re.match(r'^( +)', ln)
    if m:
        pad = '　' * max(1, len(m.group(1)) // 2)
        ln = pad + ln[len(m.group(1)):]
    esc = html_mod.escape(ln)
    return esc if esc.strip() else '&nbsp;'

def render_prompt_block(code):
    """提示词卡片：使用文章主题色完整展开，不使用深色代码框和滚动容器。"""
    lines = ''.join(
        f'<p style="margin:0 0 9px;font-size:14px;line-height:1.9;color:{C_TEXT};">'
        f'<span leaf="">{leafify(inline(ln)) if ln.strip() else "&nbsp;"}</span></p>'
        for ln in code.rstrip('\n').split('\n')
    )
    return f'''<section style="margin:30px 0 24px;background:{C_GRAY_BG2};border:1.5px dashed {C_GREEN_BORDER};border-radius:12px;padding:9px 18px 9px;">
  <p style="margin:-24px 0 12px 8px;line-height:1;">
    <span style="display:inline-block;background:{C_GRAY_BG2};border:1px solid {C_GREEN_BORDER};border-radius:999px;padding:4px 12px;color:{C_MAIN};font-size:12px;font-weight:800;letter-spacing:1px;">提示词</span>
  </p>
  {lines}
</section>'''

def render_code_block(code, lang=''):
    """通用库 1a 深色代码块：三色圆点顶栏 + 每行一个 <p style="margin:0">"""
    if lang.strip().lower() in ('text', 'prompt', '提示词'):
        return render_prompt_block(code)
    lang_html = (f'<span style="margin-left:12px;font-size:12px;color:#64748B;font-family:{MONO};'
                 f'letter-spacing:1px;"><span leaf="">{html_mod.escape(lang)}</span></span>') if lang else ''
    dots = ''.join(
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{c};'
        f'{"margin-right:7px;" if i < 2 else ""}font-size:0;line-height:0;overflow:hidden;">.</span>'
        for i, c in enumerate(('#FF5F56', '#FFBD2E', '#27C93F'))
    )
    lines = ''.join(
        f'<p style="margin:0;font-family:{MONO};font-size:13px;line-height:1.6;color:#E2E8F0;word-break:break-all;">'
        f'<span leaf="">{_code_line(ln)}</span></p>'
        for ln in code.rstrip('\n').split('\n')
    )
    return f'''<section style="margin:0 0 20px;border-radius:8px;overflow:hidden;background:#1E293B;box-shadow:0 4px 16px -8px rgba(15,23,42,0.4);">
  <section style="display:flex;align-items:center;padding:9px 14px;background:#0F172A;">
    {dots}{lang_html}
  </section>
  <section style="padding:11px 14px;">
    {lines}
  </section>
</section>'''

def render_ul(items):
    """无序列表：主色圆点 + 全 inline（禁 <ul>/<li>，公众号会拆行）"""
    items_html = ''.join(
        f'<section style="margin:6px 0;font-size:14px;line-height:1.9;letter-spacing:0.5px;color:{C_TEXT};">'
        f'<span style="color:{C_MAIN};font-size:12px;margin-right:8px;">●</span>'
        f'{leafify(inline(it))}'
        f'</section>'
        for it in items
    )
    return f'<section style="margin:0 0 16px;">{items_html}</section>'

def render_ol(items, start=1):
    """组件 11g ordered-list：绿色圆形编号 + flex 行"""
    rows = []
    for idx, it in enumerate(items, start=start):
        rows.append(
            f'<section style="display:flex;align-items:flex-start;gap:10px;margin-bottom:12px;">'
            f'<span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;'
            f'background:{C_MAIN};color:#fff;font-size:11px;font-weight:700;border-radius:50%;flex-shrink:0;margin-top:2px;">'
            f'<span leaf="">{idx}</span></span>'
            f'<p style="font-size:14px;color:{C_TEXT};margin:0;line-height:1.9;flex:1;">{leafify(inline(it))}</p>'
            f'</section>')
    return f'<section style="margin:0 0 24px;">{"".join(rows)}</section>'

def render_step_card(num, title, body=''):
    """组件 7a step-label：黑色 STEP 药丸 + 标题"""
    body_html = (f'<p style="font-size:14px;margin:0 0 16px;color:{C_TEXT2};line-height:1.9;text-align:justify;">'
                 f'{leafify(inline(body))}</p>') if body else ''
    return f'''<section style="margin:28px 0 16px;">
  <section style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
    <span style="display:inline-block;background:{C_TITLE};color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:12px;"><span leaf="">STEP {num:02d}</span></span>
    <p style="font-size:15px;font-weight:800;color:{C_TITLE};margin:0;">{leafify(inline(title))}</p>
  </section>
  {body_html}
</section>'''

def render_inline_heading(prefix, title, body=''):
    """组件 3c 序号药丸风：浅绿药丸前缀（第X件事/第X派）+ 粗黑标题"""
    body_html = (f'<p style="margin:0 0 16px;font-size:14px;line-height:1.9;color:{C_TEXT};text-align:justify;">'
                 f'{leafify(inline(body))}</p>') if body else ''
    return f'''<p style="margin:24px 0 12px;font-size:15px;font-weight:800;color:{C_TITLE};line-height:1.6;"><span style="display:inline-block;background:{C_GREEN_BG};color:{C_MAIN};border-radius:5px;padding:1px 9px;margin-right:8px;font-weight:900;"><span leaf="">{prefix}</span></span>{leafify(inline(title))}</p>
{body_html}'''

def render_tier_card(tier, title, desc, highlight=False):
    """客户三档卡：高亮档用绿渐变"""
    if highlight:
        bg = f'background:linear-gradient(135deg,{C_MAIN},{C_MAIN2});'
        border = 'border:1px solid transparent;'
        color, sub = '#fff', 'rgba(255,255,255,0.85)'
    else:
        bg = 'background:#fff;'
        border = f'border:1px solid {C_BORDER};'
        color, sub = C_TITLE, C_FAINT
    return f'''<section style="margin:0 0 12px;padding:16px 20px;{bg}border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.04);{border}">
  <section style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
    <span style="font-size:10px;font-weight:800;letter-spacing:2px;color:{sub};"><span leaf="">TIER {tier:02d}</span></span>
    <span style="font-size:14px;font-weight:800;color:{color};">{leafify(inline(title))}</span>
  </section>
  <p style="margin:0;font-size:13px;color:{sub};line-height:1.75;">{leafify(inline(desc))}</p>
</section>'''

STEP_MAP = {'第一步': 1, '第二步': 2, '第三步': 3, '第四步': 4, '第五步': 5}
TIER_MAP = {'第一档': 1, '第二档': 2, '第三档': 3}
STAGE_MAP = {'第一件事': 1, '第二件事': 2, '第三件事': 3}
FACTION_MAP = {'第一派': 1, '第二派': 2, '第三派': 3}
NUM_PREFIX = {**STAGE_MAP, **FACTION_MAP}

# 图注前缀识别：紧跟在图片后的 `> 配图来源：xxx` 等，作图注（而非引用块）
CAPTION_PREFIX_RE = re.compile(r'^>\s*(配图来源|图片来源|图注|图|来源|Source|Figure)\s*[:：]\s*(.+)$')

def _peek_caption(lines, i):
    if i + 1 >= len(lines):
        return '', 1
    j = i + 1
    while j < len(lines) and lines[j].strip() == '':
        j += 1
    if j >= len(lines):
        return '', 1
    nxt = lines[j].strip()
    cap_q = CAPTION_PREFIX_RE.match(nxt)
    if cap_q:
        return cap_q.group(2).strip(), j - i + 1
    if nxt.startswith('*') and nxt.endswith('*') and not nxt.startswith('**') and len(nxt) > 2:
        return nxt.strip('*').strip(), j - i + 1
    return '', 1

def md_to_html(body):
    """按行处理 markdown，输出 HTML 片段"""
    lines = body.split('\n')
    chapters = prescan_chapters(body)
    total = len(chapters)
    html = []
    i = 0
    chapter_counter = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        # 跳过 # 一级标题（封面已展示标题）
        if line.startswith('# ') and not line.startswith('## '):
            i += 1
            continue
        # 阿拉伯数字章节：**1. 标题** → chapter-title
        arabic_m = re.match(r'^\*\*(\d+)\.\s*([^*]+?)\*\*\s*$', line)
        if arabic_m:
            title = arabic_m.group(2).strip()
            html.append(render_chapter(chapter_counter, title, total))
            chapter_counter += 1
            i += 1
            continue
        # 第X步 → STEP 药丸；第X件事/第X派 → 序号药丸小标题
        num_m = re.match(r'^\*\*(第[一二三四五](?:步|件事|派))[，,:：]?\s*([^*]+?)\*\*。?(.*)$', line)
        if num_m:
            prefix = num_m.group(1)
            title = num_m.group(2).strip().rstrip('。')
            rest = num_m.group(3).strip()
            if prefix in STEP_MAP:
                html.append(render_step_card(STEP_MAP[prefix], title, rest))
            else:
                html.append(render_inline_heading(prefix, title, rest))
            i += 1
            continue
        # 客户三档：**第一档：XXX**。YYY
        tier_m = re.match(r'^\*\*(第[一二三]档)[:：]([^*]+?)\*\*。?\s*(.*)$', line)
        if tier_m and tier_m.group(1) in TIER_MAP:
            num = TIER_MAP[tier_m.group(1)]
            title = tier_m.group(2).strip()
            desc = tier_m.group(3).strip() or ''
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith('!') and not re.match(r'^\*\*第[一二三]档', lines[i]) and not lines[i].startswith('##') and not lines[i].startswith('**'):
                desc += ' ' + lines[i].strip()
                i += 1
            html.append(render_tier_card(num, title, desc, highlight=(num == 3)))
            continue
        # Markdown 表格
        if line.startswith('|') and line.endswith('|') and i+1 < len(lines) and re.match(r'^\|[\s\-:|]+\|$', lines[i+1].strip()):
            rows = [[c.strip() for c in line.strip('|').split('|')]]
            i += 2
            while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')])
                i += 1
            html.append(render_table(rows))
            continue
        # 滑动图组 <!-- SLIDER: 标题 --> ... <!-- /SLIDER -->
        slider_m = re.match(r'<!--\s*SLIDER(?::\s*([^-]+?))?\s*-->', line)
        if slider_m:
            slider_title = (slider_m.group(1) or '').strip()
            i += 1
            items = []
            while i < len(lines) and not re.match(r'<!--\s*/SLIDER\s*-->', lines[i].strip()):
                cur = lines[i].strip()
                im = re.match(r'!\[\[([^]]+)\]\]', cur)
                if im:
                    name = im.group(1)
                    cap = cur[im.end():].strip()
                    if not cap and i+1 < len(lines) and lines[i+1].startswith('*') and lines[i+1].rstrip().endswith('*') and not lines[i+1].startswith('**'):
                        cap = lines[i+1].strip('*').strip()
                        i += 1
                    items.append((name, cap))
                i += 1
            i += 1
            if items:
                html.append(render_slider(items, slider_title))
            continue
        # wikilink 图片 ![[xxx]]
        img_m = re.match(r'!\[\[([^]]+)\]\]', line)
        if img_m:
            name = img_m.group(1)
            caption, consumed = _peek_caption(lines, i)
            html.append(render_image_with_caption(name, caption))
            i += consumed
            continue
        # 标准 md 图片 ![alt](url)
        std_img_m = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$', line)
        if std_img_m:
            alt = std_img_m.group(1).strip()
            url = std_img_m.group(2).strip()
            caption, consumed = _peek_caption(lines, i)
            if not caption and alt:
                caption = alt
            html.append(render_image_with_caption(url, caption))
            i += consumed
            continue
        # ### 子节标题（必须先于 ##）
        if line.startswith('### '):
            html.append(render_h3(line[4:].strip()))
            i += 1
            continue
        # ## 章节标题 → chapter-title（编号与 TOC 对齐）
        if line.startswith('## '):
            h2_text = line[3:].strip()
            html.append(render_chapter(chapter_counter, h2_text, total))
            chapter_counter += 1
            i += 1
            continue
        # 代码块 ```
        if line.startswith('```'):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1
            html.append(render_code_block('\n'.join(code_lines), lang))
            continue
        # 金句卡 >> 文字（必须先于普通引用 > 判断）
        if line.startswith('>> '):
            html.append(render_oneliner(line[3:].strip()))
            i += 1
            continue
        # 引用 >（连续多行合一卡，<br> 换行）
        if line.startswith('> '):
            quote_lines = [line[2:]]
            i += 1
            while i < len(lines) and lines[i].startswith('> '):
                quote_lines.append(lines[i][2:])
                i += 1
            html.append(render_quote('<br>'.join(quote_lines)))
            continue
        # 分割线
        if line.strip() in ('---', '***', '___'):
            html.append(f'<hr style="border:0;height:1px;background:linear-gradient(to right,transparent,{C_LINE} 30%,{C_LINE} 70%,transparent);margin:36px 0;">')
            i += 1
            continue
        # 无序列表
        if line.startswith('- '):
            items = [line[2:]]
            i += 1
            while i < len(lines) and lines[i].startswith('- '):
                items.append(lines[i][2:])
                i += 1
            html.append(render_ul(items))
            continue
        # 有序列表
        ol_match = re.match(r'^\d+\.\s+(.+)', line)
        if ol_match:
            items = [ol_match.group(1)]
            i += 1
            while i < len(lines):
                m = re.match(r'^\d+\.\s+(.+)', lines[i])
                if not m: break
                items.append(m.group(1))
                i += 1
            html.append(render_ol(items, start=int(ol_match.group(0).split('.')[0])))
            continue
        # 外链 URL 单独一行
        if line.startswith('http'):
            html.append(f'<p style="margin:0 0 16px;font-size:13px;word-break:break-all;"><a href="{line}" style="color:{C_MAIN};text-decoration:underline;"><span leaf="">{line}</span></a></p>')
            i += 1
            continue
        # 黄色警告框：段落以 ⚠️ 开头
        if line.startswith(('⚠️', '⚠')):
            html.append(render_yellow_warning(line.lstrip('⚠️⚠').strip()))
            i += 1
            continue
        # 绿色信息框：段落以 💡 开头
        if line.startswith('💡'):
            html.append(render_green_info(line.lstrip('💡').strip()))
            i += 1
            continue
        # 原样 HTML 直通：手写组件库组件（pill-list/flow-cards/timeline 等）直接贴进草稿，
        # 连续行原样输出到空行为止（组件库全集见 skill 目录 references/）
        if line.startswith(('<section', '<p ', '<table', '<img', '<hr')):
            raw = [line]
            i += 1
            while i < len(lines) and lines[i].strip():
                raw.append(lines[i])
                i += 1
            html.append('\n'.join(raw))
            continue
        # 普通段落
        html.append(render_paragraph(line))
        i += 1
    return '\n'.join(html)

def get_cover(a):
    """frontmatter `封面图:`（或旧写法 `副标题: 图:xxx`）→ 封面图文件名/路径；没有返回 ''"""
    cover = a.get('cover', '').strip()
    subtitle = a['subtitle'].strip()
    if not cover and (subtitle.startswith('图:') or subtitle.startswith('图：')):
        cover = subtitle[2:].strip()
    return cover

def render_cover(a):
    """封面卡（方案 B 定稿，2026-07-07 四方案对比选出）：
    图贴卡顶对齐圆角边框 + 白色信息条（绿点 + 品牌语深灰字 / 标签·日期浅灰字）。
    封面区绿色只保留一个 6px 圆点，不跟封面图配色打架。
    封面图是硬性前置：没有封面图不排版（main 里拦截提醒），不存在无图的文字封面。
    """
    date = (a['date'] or '').replace('-', '.')
    tags = a.get('tags', [])
    top_label = ' × '.join(tags[:2]) if tags else BRAND_NAME
    meta_right = f'{top_label} · {date}' if date else top_label
    return f'''<section style="margin:0 0 32px;background:#fff;border:1px solid {C_BORDER};border-radius:20px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);width:100%;">
  <section style="margin:0;"><img src="{img_url(get_cover(a))}" style="width:100%;display:block;"></section>
  <section style="padding:12px 20px;display:flex;align-items:center;justify-content:space-between;border-top:1px solid {C_GRAY_BG};">
    <section style="display:flex;align-items:center;gap:8px;">
      <span style="width:6px;height:6px;background:{C_MAIN};border-radius:50%;">{LEAF_BR}</span>
      <span style="font-size:11px;font-weight:700;letter-spacing:1px;color:{C_TEXT2};"><span leaf="">{BRAND_NAME} · {BRAND_TAGLINE}</span></span>
    </section>
    <span style="font-size:10px;color:{C_FAINT};letter-spacing:1px;"><span leaf="">{meta_right}</span></span>
  </section>
</section>'''

def render_footer():
    """渲染唯一固定品牌尾卡（2026-08-06 LibTV 名片 + 品牌互动 GIF）。

    上半张是完整个人名片，下半条是同宽黑底荧光绿动效。
    两张图贴合为一个视觉整体，同时保留公众号内可播放的 GIF 互动效果。
    """
    return f'''<section style="width:100%;max-width:100%;box-sizing:border-box;margin:42px 0 10px;background:#000000;border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;line-height:0;box-shadow:0 8px 24px rgba(17,24,39,0.10);">
  <img src="{img_url(FOOTER_CARD)}" style="max-width:100%;height:auto;display:block;margin:0 auto;">
  <img src="{img_url(FOOTER_ACTIONS)}" style="max-width:100%;height:auto;display:block;margin:-1px auto 0;">
</section>'''

def render_full(a):
    title = a['title']
    body_html = md_to_html(a['body'])

    if PLAIN_MODE:
        head = (f'<p style="margin:0 0 20px;font-size:20px;font-weight:700;color:{C_TITLE};line-height:1.55;">'
                f'<span leaf="">{a["subtitle"]}</span></p>') if a['subtitle'] else ''
        footer = ''
    else:
        head = render_cover(a)
        footer = render_footer() if a.get('show_footer', True) else ''

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>
<style>
body{{margin:0;background:#f5f5f5;padding:40px 0;}}
#copy-btn{{position:fixed;top:20px;right:20px;z-index:9999;background:{C_MAIN};color:#fff;border:0;padding:12px 20px;border-radius:999px;font-size:13px;font-weight:700;letter-spacing:1px;cursor:pointer;box-shadow:0 4px 16px rgba(5,150,105,0.3);font-family:'PingFang SC',sans-serif;transition:all 0.2s;}}
#copy-btn:hover{{transform:translateY(-2px);box-shadow:0 6px 20px rgba(5,150,105,0.4);}}
#copy-btn.done{{background:{C_TITLE};}}
</style>
</head><body>
<button id="copy-btn" onclick="copyArticle()">📋  复制到公众号</button>
<section id="article-body" style="width:100%;max-width:677px;margin:0 auto;background:#ffffff;font-family:{FONT};color:{C_TEXT};line-height:1.75;letter-spacing:0.5px;padding:36px 20px;overflow-x:hidden;box-sizing:border-box;">
{head}
{body_html}
{footer}
</section>
<script>
function copyArticle() {{
  const el = document.getElementById('article-body');
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  try {{
    document.execCommand('copy');
    const btn = document.getElementById('copy-btn');
    btn.textContent = '✓  已复制，去公众号粘贴';
    btn.classList.add('done');
    setTimeout(() => {{
      btn.textContent = '📋  复制到公众号';
      btn.classList.remove('done');
    }}, 2500);
  }} catch (e) {{
    alert('复制失败，请手动 Cmd+A 全选');
  }}
  sel.removeAllRanges();
}}
</script>
</body></html>'''

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='微信公众号排版（翠绿卡片风 v3）')
    parser.add_argument('md_path', help='源 markdown 路径')
    parser.add_argument('--vol', type=int, help='（已废弃，v3 不再显示期号，参数保留兼容）')
    parser.add_argument('--out', default='/tmp/wx_preview.html', help='输出 HTML 路径')
    parser.add_argument('--open', action='store_true', help='生成后用浏览器打开')
    parser.add_argument('--plain', action='store_true', help='关掉封面和固定品牌尾卡（合作稿用）')
    parser.add_argument('--vault', help='可选：Obsidian Vault 或素材库根目录')
    parser.add_argument('--image-root', help='可选：图片优先搜索目录')
    parser.add_argument('--brand-name', help='封面信息条品牌名')
    parser.add_argument('--tagline', help='封面信息条品牌语')
    parser.add_argument('--footer-card', help='自定义尾卡静态图片路径')
    parser.add_argument('--footer-actions', help='自定义尾卡互动 GIF 路径')
    args = parser.parse_args()

    SRC = args.md_path
    OUT = args.out
    if args.vault:
        VAULT = args.vault
    if args.image_root:
        IMG_ROOT = args.image_root
    if args.brand_name:
        BRAND_NAME = args.brand_name
    if args.tagline:
        BRAND_TAGLINE = args.tagline
    if args.footer_card:
        FOOTER_CARD = args.footer_card
    if args.footer_actions:
        FOOTER_ACTIONS = args.footer_actions
    if args.plain:
        PLAIN_MODE = True

    art = parse_article()
    # 封面图硬校验（祥瑞的规矩 2026-07-07）：没有封面图不排版，提醒补图
    if not PLAIN_MODE:
        cover = get_cover(art)
        if not cover:
            print("✗ 未排版：frontmatter 缺少 `封面图:`。")
            print("  规矩：没有封面图不排版。先做封面图（1080 宽横图），")
            print("  在 frontmatter 加一行 `封面图: <文件名或绝对路径>` 再重新跑。")
            sys.exit(1)
        if not cover.startswith(('http://', 'https://', 'data:')) and _resolve_img_path(cover) is None:
            print(f"✗ 未排版：封面图文件找不到：{cover}")
            print("  确认文件名拼写，或使用相对路径、--image-root、--vault、绝对路径。")
            sys.exit(1)
    html = render_full(art)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✓ {OUT} ({len(html)//1024}KB)")
    print(f"  title: {art['title']}")
    print(f"  章节: {len(prescan_chapters(art['body']))} 个")

    # 合规自检（改→验→修闭环，规则见同目录 validate_wx_html.py）
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from validate_wx_html import validate, report
        v_errors, v_warnings = validate(html)
        report(v_errors, v_warnings, OUT)
        if v_errors:
            sys.exit(1)
    except ImportError:
        print("  ⚠ validate_wx_html.py 不在同目录，跳过合规自检")

    if args.open:
        import subprocess
        subprocess.run(['open', OUT])
