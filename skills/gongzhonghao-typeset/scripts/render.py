#!/usr/bin/env python3
"""公众号排版引擎（gongzhonghao-typeset）。

移植自 wechat-editorial/md_to_editorial.py，但有两个核心改造：
1. 所有颜色用 CSS 变量 `var(--c-xxx)` 而不是 inline 写死，配合控制面板实时切色
2. 复制时由前端 `flattenStyles()` 把 CSS 变量解析成 inline 写死值再写剪贴板

保留 9 条 HTML 输出实现规范：
  1. 列表用 section+span，禁用 ul/li
  2. 加粗用 span 不用 strong（公众号对 strong 后跟全角字符强插换行）
  3. 图片 max-width:100% + height:auto（不用 width:100% 拉伸小图）
  4. H3 左侧主色竖条 + 17px 粗体
  5. 超长 PNG（文件名含「全图/长图/scrollbox/longshot」）自动 scrollbox
  6. 多行引用块用 <br> join 不用空格 join
  7. frontmatter 中文 key（标题/副标题/创建时间/标签）
"""
import re
import base64
import mimetypes
import html as html_mod
from pathlib import Path
from urllib.parse import quote


class Theme:
    """theme.json 包装：colors / brand / typography 访问 + 默认值兜底。"""
    DEFAULTS = {
        'colors': {
            'bg': '#ffffff', 'main': '#22a667', 'soft': '#a3d97d',
            'soft_bg': '#e8f5e9', 'img_border': '#a5d6a7', 'accent': '#e84a6d',
            'highlight_pink': '#ffe5ec', 'btn_bg': '#f3f4f6', 'step_bg': '#1a1a1a',
            'text': '#3a3a3a', 'text_strong': '#1a1a1a', 'mute': '#737373', 'faint': '#a3a3a3',
        },
        'brand': {
            'name': '万涂幻象', 'magazine_suffix': 'MAGAZINE', 'chapter_stamp': '万涂幻象 ─',
            'issue_prefix': 'VOL.', 'issue_number': 1, 'case_prefix': 'CASE',
            'feature_label': 'ISSUE FEATURE',
        },
        'typography': {
            'body_font_size_px': 15, 'body_line_height': 1.85,
            'chapter_number_size_px': 58, 'h3_size_px': 17,
        },
    }

    def __init__(self, data):
        self.colors = {**self.DEFAULTS['colors'], **(data.get('colors') or {})}
        self.brand = {**self.DEFAULTS['brand'], **(data.get('brand') or {})}
        self.typo = {**self.DEFAULTS['typography'], **(data.get('typography') or {})}
        try:
            self.brand['issue_number'] = int(self.brand['issue_number'])
        except (ValueError, TypeError):
            self.brand['issue_number'] = 1


def build_theme_css_vars(theme):
    """从 theme 生成 :root CSS 变量定义字符串（供 <style> 注入）。"""
    c = theme.colors
    t = theme.typo
    return (
        f"--c-bg:{c['bg']};"
        f"--c-main:{c['main']};"
        f"--c-soft:{c['soft']};"
        f"--c-soft-bg:{c['soft_bg']};"
        f"--c-img-border:{c['img_border']};"
        f"--c-highlight-pink:{c['highlight_pink']};"
        f"--c-btn-bg:{c['btn_bg']};"
        f"--c-text:{c['text']};"
        f"--c-text-strong:{c['text_strong']};"
        f"--c-mute:{c['mute']};"
        f"--c-faint:{c['faint']};"
        f"--body-font-size:{t['body_font_size_px']}px;"
        f"--body-line-height:{t['body_line_height']};"
        f"--chapter-num-size:{t['chapter_number_size_px']}px;"
        f"--h3-size:{t['h3_size_px']}px;"
        f"--img-radius:16px;"
        f"--img-border-width:2px;"
        f"--img-shadow-blur:16px;"
    )


def img_to_data_uri(name, search_dirs):
    if name.startswith(('http://', 'https://', 'data:')):
        return name
    for d in search_dirs:
        if not d:
            continue
        p = Path(d) / name
        if not p.exists():
            for found in Path(d).rglob(name):
                p = found
                break
        if p.exists():
            mime = mimetypes.guess_type(str(p))[0] or 'image/jpeg'
            try:
                with open(p, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode('ascii')
                return f'data:{mime};base64,{b64}'
            except Exception:
                return 'file://' + quote(str(p), safe='/:')
    return ''


# === 内联 ===

def inline(text, theme=None):
    # 先 stash inline code（HTML escape 内部内容 + 用占位符避免被其他规则吞掉，
    # 例如 `**xxx**` 里的 ** 不应该被粗体规则误伤）
    code_stash = []

    def _stash(m):
        idx = len(code_stash)
        code_stash.append(html_mod.escape(m.group(1)))
        return f'\x00CODE{idx}\x00'

    text = re.sub(r'`([^`]+)`', _stash, text)

    text = re.sub(
        r'==([^=]+)==',
        r'<mark style="background:var(--c-highlight-pink);color:var(--c-text-strong);padding:1px 6px;border-radius:3px;font-weight:600;">\1</mark>',
        text,
    )
    text = re.sub(
        r'「([^」]+)」',
        r'<span style="background:var(--c-btn-bg);color:var(--c-text-strong);padding:2px 10px;border-radius:6px;font-size:0.92em;font-weight:600;margin:0 2px;">「\1」</span>',
        text,
    )
    text = re.sub(
        r'\*\*(.+?)\*\*',
        r'<span style="color:var(--c-text-strong);font-weight:700;">\1</span>',
        text,
    )

    # 把占位符还原为 <code>（内部内容已 escape）
    for idx, escaped in enumerate(code_stash):
        replacement = (
            f'<code style="background:var(--c-soft-bg);padding:1px 7px;'
            f'border-radius:5px;font-family:Menlo,Monaco,monospace;'
            f'font-size:0.92em;color:var(--c-main);font-weight:600;">{escaped}</code>'
        )
        text = text.replace(f'\x00CODE{idx}\x00', replacement)

    return text


# === Frontmatter ===

def parse_article(md_text):
    m = re.match(r'^---\n(.*?)\n---\n', md_text, re.DOTALL)
    frontmatter = m.group(1) if m else ''
    body = md_text[m.end():] if m else md_text
    cut = re.search(r'\n(?:---\s*\n)?##\s+(素材溯源|关联笔记|修订记录|附录|参考资料)', body)
    if cut:
        body = body[:cut.start()]
    title_m = re.search(r'^标题:\s*(.+)$', frontmatter, re.M)
    subtitle_m = re.search(r'^副标题:\s*(.+)$', frontmatter, re.M)
    date_m = re.search(r'^创建时间:\s*(.+)$', frontmatter, re.M)
    tags = []
    tag_m = re.search(r'标签:\s*\n((?:\s*-\s+.+\n)+)', frontmatter)
    if tag_m:
        tags = re.findall(r'^\s*-\s+(.+?)$', tag_m.group(1), re.M)
    meta_tags = [t.strip() for t in tags
                 if not any(t.startswith(p) for p in ('类型/', '状态/', '来源/', '用途/'))
                 and t.strip() != '公众号']
    feature = ' × '.join(meta_tags[:3])

    def strip_quotes(s):
        s = s.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            return s[1:-1]
        return s

    return {
        'title': strip_quotes(title_m.group(1)) if title_m else '',
        'subtitle': strip_quotes(subtitle_m.group(1)) if subtitle_m else '',
        'date': date_m.group(1).strip() if date_m else '',
        'feature': feature,
        'body': body.strip(),
    }


# === 段落与组件（颜色全用 CSS 变量）===

def render_paragraph(text, theme):
    has_url = 'http' in text or 'github.com' in text
    align = 'text-align:left;' if has_url else 'text-align:justify;'
    return (f'<p style="margin:0 0 18px;font-size:16px;line-height:1.9;letter-spacing:0.5px;'
            f'color:var(--c-text);{align}word-break:break-word;">{inline(text, theme)}</p>')


def render_image(name, caption, theme, search_dirs):
    src = img_to_data_uri(name, search_dirs)
    cap = inline(caption, theme) if caption else ''
    # caption 不再嵌套在 section 内（公众号编辑器把 section 当 inline 时会撞段），
    # 改用独立 <p> 平铺在外层 section 之后。<p> 之间的间距公众号保留得最好。
    cap_html = (f'<p style="margin:12px 0 32px;font-size:13px;color:var(--c-mute);'
                f'line-height:1.7;text-align:center;">{cap}</p>') if cap else ''
    is_scrollbox = any(k in name for k in ('全图', '长图', 'scrollbox', 'longshot'))
    if is_scrollbox:
        return (f'<section style="margin:32px auto 0;text-align:center;">'
                f'<section style="max-height:560px;overflow-y:auto;-webkit-overflow-scrolling:touch;'
                f'border-radius:var(--img-radius);border:var(--img-border-width) solid var(--c-img-border);'
                f'box-shadow:0 8px var(--img-shadow-blur) rgba(0,0,0,0.12);background:#ede4cd;">'
                f'<img src="{src}" style="width:100%;display:block;border-radius:0;">'
                f'</section></section>'
                f'<p style="margin:8px 0 0;font-size:11px;color:var(--c-mute);letter-spacing:1px;text-align:center;">'
                f'↕ 在框内上下滑动可浏览完整长图 ↕</p>'
                f'{cap_html}')
    return (f'<section style="margin:32px auto 0;text-align:center;">'
            f'<img src="{src}" style="max-width:100%;height:auto;display:block;margin:0 auto;'
            f'border-radius:var(--img-radius);border:var(--img-border-width) solid var(--c-img-border);'
            f'box-shadow:0 8px var(--img-shadow-blur) rgba(0,0,0,0.12);">'
            f'</section>{cap_html}')


def render_table(rows, theme):
    if not rows:
        return ''
    head, body = rows[0], rows[1:]
    th = ''.join(
        f'<th style="padding:10px 12px;font-size:13px;font-weight:700;color:#fff;'
        f'background:var(--c-main);text-align:left;letter-spacing:0.5px;'
        f'border-right:1px solid rgba(255,255,255,0.15);">{inline(x, theme)}</th>'
        for x in head
    )
    trs = []
    for idx, row in enumerate(body):
        bg = '#fafaf7' if idx % 2 == 0 else '#ffffff'
        tds = ''.join(
            f'<td style="padding:10px 12px;font-size:13.5px;color:var(--c-text);line-height:1.7;'
            f'border-bottom:1px solid #e5e5e5;border-right:1px solid #f0efe9;vertical-align:top;">'
            f'{inline(x, theme)}</td>'
            for x in row
        )
        trs.append(f'<tr style="background:{bg};">{tds}</tr>')
    return (f'<section style="margin:28px 0;overflow-x:auto;-webkit-overflow-scrolling:touch;">'
            f'<table style="width:100%;border-collapse:collapse;font-family:inherit;'
            f'border:1px solid #e5e5e5;border-radius:8px;overflow:hidden;">'
            f'<thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></section>')


def render_quote(text, theme):
    stripped = text.strip()
    if re.match(r'^https?://\S+$', stripped):
        return (f'<p style="margin:22px 0;font-size:15px;line-height:1.85;word-break:break-all;">'
                f'<a href="{stripped}" style="color:var(--c-main);text-decoration:underline;">'
                f'{stripped}</a></p>')
    return (f'<section style="margin:26px 0;background:#ffffff;border:1px solid #e5e5e5;'
            f'border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,0.04);overflow:hidden;">'
            f'<section style="padding:14px 14px 0 14px;">'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 9 9" style="display:block;flex-shrink:0;"><circle cx="4.5" cy="4.5" r="4.5" fill="#c4c4c4"/></svg>'
            f'</section>'
            f'<section style="padding:10px 26px 22px 26px;">'
            f'<p style="margin:0;font-size:15px;line-height:1.9;color:var(--c-text);">'
            f'{inline(text, theme)}</p></section></section>')


def render_code_block(code, theme):
    line_style = ('margin:0;padding:0;color:var(--c-text-strong);'
                  'font-family:Menlo,Monaco,"Courier New",monospace;'
                  'font-size:14px;line-height:1.9;white-space:pre-wrap;word-break:break-all;')
    lines = []
    for ln in code.rstrip('\n').split('\n'):
        esc = html_mod.escape(ln)
        if not esc.strip():
            esc = '&nbsp;'
        lines.append(f'<div style="{line_style}">{esc}</div>')
    return (f'<section style="margin:26px 0;background:#ffffff;border:1px solid #e5e5e5;'
            f'border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,0.04);overflow:hidden;">'
            f'<section style="padding:14px 14px 0 14px;">'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 9 9" style="display:block;flex-shrink:0;"><circle cx="4.5" cy="4.5" r="4.5" fill="#c4c4c4"/></svg>'
            f'</section>'
            f'<section style="padding:10px 26px 22px 26px;">{"".join(lines)}</section></section>')


def render_h2(text, theme):
    return (f'<section style="margin:48px 0 24px;display:flex;align-items:center;'
            f'justify-content:center;gap:14px;">'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="2" viewBox="0 0 28 2" style="display:block;flex-shrink:0;color:var(--c-main);"><rect width="28" height="2" rx="1" fill="currentColor"/></svg>'
            f'<span style="font-size:22px;font-weight:800;color:var(--c-main);line-height:1.4;'
            f'letter-spacing:0.5px;">{inline(text, theme)}</span>'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="2" viewBox="0 0 28 2" style="display:block;flex-shrink:0;color:var(--c-main);"><rect width="28" height="2" rx="1" fill="currentColor"/></svg>'
            f'</section>')


def render_h3(text, theme):
    return (f'<section style="margin:34px 0 14px;display:flex;align-items:center;gap:10px;">'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="20" viewBox="0 0 4 20" style="display:block;flex-shrink:0;color:var(--c-main);"><rect width="4" height="20" rx="2" fill="currentColor"/></svg>'
            f'<span style="font-size:var(--h3-size);font-weight:800;color:var(--c-text-strong);'
            f'line-height:1.4;letter-spacing:0.3px;">{inline(text, theme)}</span></section>')


def render_ul(items, theme):
    items_html = ''.join(
        f'<section style="margin:6px 0;font-size:15px;line-height:1.85;letter-spacing:0.5px;'
        f'color:var(--c-text);">'
        f'<span style="color:var(--c-main);font-size:13px;margin-right:8px;">●</span>'
        f'<span>{inline(it, theme)}</span></section>'
        for it in items
    )
    return f'<section style="margin:18px 0;">{items_html}</section>'


def render_ol(items, theme):
    items_html = ''.join(
        f'<section style="margin:8px 0;font-size:15px;line-height:1.85;letter-spacing:0.5px;'
        f'color:var(--c-text);">'
        f'<span style="display:inline-block;min-width:28px;color:var(--c-main);font-weight:800;'
        f'font-size:14px;letter-spacing:0.5px;">{idx + 1:02d}</span>'
        f'<span>{inline(it, theme)}</span></section>'
        for idx, it in enumerate(items)
    )
    return f'<section style="margin:18px 0;">{items_html}</section>'


def render_step_card(num, title, theme, label_text=None):
    b = theme.brand
    stamp = b['chapter_stamp'].replace(' ─', '').replace('─', '').strip()
    label = label_text if label_text is not None else f'{b["case_prefix"]} {num:02d}'
    label_html = (f'<span style="flex-shrink:0;font-size:11px;color:var(--c-faint);'
                  f'letter-spacing:2px;font-weight:600;padding-bottom:6px;">/ {label}</span>'
                  if label else '')
    return (f'<section style="margin:56px 0 28px;">'
            f'<section style="display:flex;align-items:flex-end;gap:20px;padding-bottom:14px;'
            f'border-bottom:1px solid #e5e5e5;">'
            f'<section style="flex-shrink:0;">'
            f'<section style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
            f'<span style="font-size:9px;color:var(--c-main);letter-spacing:3px;font-weight:800;">'
            f'{stamp}</span>'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="1" viewBox="0 0 14 1" style="display:block;flex-shrink:0;color:var(--c-main);"><rect width="14" height="1" fill="currentColor"/></svg></section>'
            f'<span style="display:block;font-size:var(--chapter-num-size);font-weight:900;'
            f'color:#d4d4d4;line-height:0.95;letter-spacing:-2px;'
            f'font-family:-apple-system,BlinkMacSystemFont,\'Helvetica Neue\',sans-serif;">'
            f'{num:02d}</span></section>'
            f'<span style="flex:1;font-size:22px;font-weight:800;color:var(--c-text-strong);'
            f'line-height:1.3;letter-spacing:-0.2px;padding-bottom:4px;">{inline(title, theme)}</span>'
            f'{label_html}</section></section>')


# === 主流程 ===

H2_LITE_WHITELIST = {'写在最后'}
CAPTION_PREFIX_RE = re.compile(r'^>\s*(配图来源|图片来源|图注|图|来源|Source|Figure)\s*[:：]\s*(.+)$')

# 分级前缀关键词 → 编号（用于 inline_heading 和 tier_card 调度）
STAGE_MAP = {'第一件事': 1, '第二件事': 2, '第三件事': 3, '第四件事': 4, '第五件事': 5}
FACTION_MAP = {'第一派': 1, '第二派': 2, '第三派': 3, '第四派': 4}
STEP_MAP = {'第一步': 1, '第二步': 2, '第三步': 3, '第四步': 4, '第五步': 5}
TIER_MAP = {'第一档': 1, '第二档': 2, '第三档': 3}
INLINE_HEADING_PREFIX = {**STAGE_MAP, **FACTION_MAP, **STEP_MAP}


def infer_caption_from_filename(name):
    """无 caption 时，从文件名推断：去扩展名 + 去数字编号 + 去常见语义前缀。"""
    from pathlib import Path as _P
    stem = _P(name).stem
    stem = re.sub(r'^\d{1,2}[-_]', '', stem)
    for prefix in ('部署-', '场景-', '架构-', '对比-', '收束图-', '场景适配-'):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    return stem


def render_slider(items, theme, search_dirs, title=''):
    """横向滑动图片组：浏览器预览可左右滑（scroll-snap），微信粘贴后降级为纵向小图。
    items: [(img_name, caption_text), ...]
    """
    cards = []
    for img_name, caption in items:
        src = img_to_data_uri(img_name, search_dirs)
        cap = inline(caption, theme) if caption else ''
        cap_html = (f'<p style="margin:10px 0 0;font-size:12px;color:var(--c-mute);'
                    f'line-height:1.7;text-align:center;">{cap}</p>') if cap else ''
        cards.append(
            f'<section style="flex:0 0 78%;max-width:360px;margin-right:14px;scroll-snap-align:start;">'
            f'<img src="{src}" style="width:100%;display:block;border-radius:14px;'
            f'border:var(--img-border-width) solid var(--c-img-border);'
            f'box-shadow:0 8px 24px rgba(0,0,0,0.12),0 2px 6px rgba(0,0,0,0.06);">'
            f'{cap_html}</section>'
        )
    title_label = f'← SWIPE · {title} · 共 {len(items)} 张 →' if title else f'← SWIPE · 共 {len(items)} 张 →'
    return (f'<section style="margin:36px 0;">'
            f'<p style="margin:0 0 14px;font-size:12px;color:var(--c-main);'
            f'letter-spacing:3px;font-weight:700;">{title_label}</p>'
            f'<section style="display:flex;overflow-x:auto;scroll-snap-type:x mandatory;'
            f'padding-bottom:14px;-webkit-overflow-scrolling:touch;">'
            f'{"".join(cards)}</section></section>')


def render_inline_heading(prefix, title, theme, body=''):
    """轻量 inline 小标题（第X件事 / 第X派 / 第X步）：主色序号 + 粗体标题一行。"""
    body_html = (f'<p style="margin:0 0 18px;font-size:16px;line-height:1.9;">'
                 f'{inline(body, theme)}</p>') if body else ''
    return (f'<p style="margin:28px 0 14px;font-size:17px;font-weight:700;'
            f'color:var(--c-text);line-height:1.55;">'
            f'<span style="color:var(--c-main);margin-right:10px;">{prefix}</span>'
            f'{inline(title, theme)}</p>'
            f'{body_html}')


def render_warn_card(title, body, theme):
    """警告/提醒卡（暖色底 + 焦橙描边）"""
    return (f'<section style="margin:32px 0;padding:22px 26px;background:#fff7ed;'
            f'border-radius:16px;border:1px solid #fed7aa;">'
            f'<section style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">'
            f'<span style="font-size:18px;">⚠️</span>'
            f'<p style="margin:0;font-size:14px;font-weight:800;color:#c2410c;'
            f'letter-spacing:0.5px;">{inline(title, theme)}</p>'
            f'</section>'
            f'<p style="margin:0;font-size:14px;color:var(--c-text);line-height:1.8;">'
            f'{inline(body, theme)}</p></section>')


def render_big_quote(text, theme):
    """金句大字屏：深色底 + 主色 THE POINT 标签 + 居中白字"""
    return (f'<section style="margin:44px 0;padding:44px 32px;'
            f'background:var(--c-text-strong);color:#fff;text-align:center;">'
            f'<p style="margin:0 0 14px;font-size:10px;color:var(--c-main);'
            f'letter-spacing:5px;font-weight:800;">◆ THE POINT</p>'
            f'<p style="margin:0;font-size:20px;font-weight:800;line-height:1.6;'
            f'letter-spacing:0.5px;">{inline(text, theme)}</p>'
            f'</section>')


def render_tier_card(tier, title, desc, theme, highlight=False):
    """套餐/分档卡（第X档：xxx）"""
    bg = 'var(--c-main)' if highlight else '#ffffff'
    color = '#fff' if highlight else 'var(--c-text)'
    sub_color = 'rgba(255,255,255,0.8)' if highlight else 'var(--c-mute)'
    border = 'transparent' if highlight else '#f0efe9'
    return (f'<section style="margin:14px 0;padding:18px 22px;background:{bg};'
            f'border-radius:14px;box-shadow:0 2px 10px rgba(0,0,0,0.05);'
            f'border:1px solid {border};">'
            f'<section style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">'
            f'<span style="font-size:10px;font-weight:800;letter-spacing:2px;color:{sub_color};">'
            f'TIER {tier:02d}</span>'
            f'<span style="font-size:15px;font-weight:800;color:{color};">{inline(title, theme)}</span>'
            f'</section>'
            f'<p style="margin:0;font-size:13px;color:{sub_color};line-height:1.75;">'
            f'{inline(desc, theme)}</p></section>')


def _peek_caption(lines, i):
    if i + 1 >= len(lines):
        return '', 1
    nxt = lines[i + 1].strip()
    cap_q = CAPTION_PREFIX_RE.match(nxt)
    if cap_q:
        return cap_q.group(2).strip(), 2
    if nxt.startswith('*') and nxt.endswith('*') and not nxt.startswith('**') and len(nxt) > 2:
        return nxt.strip('*').strip(), 2
    return '', 1


def md_to_html(body, theme, search_dirs):
    lines = body.split('\n')
    out = []
    i = 0
    chapter_counter = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        if line.startswith('# ') and not line.startswith('## '):
            i += 1
            continue
        arabic_m = re.match(r'^\*\*(\d+)\.\s*([^*]+?)\*\*\s*$', line)
        if arabic_m:
            chapter_counter += 1
            out.append(render_step_card(chapter_counter, arabic_m.group(2).strip(), theme))
            i += 1
            continue
        # 分级识别：第X步 / 第X件事 / 第X派 → 轻量 inline 小标题
        num_m = re.match(r'^\*\*(第[一二三四五](?:步|件事|派))[，,:：]?\s*([^*]+?)\*\*。?(.*)$', line)
        if num_m and num_m.group(1) in INLINE_HEADING_PREFIX:
            prefix = num_m.group(1)
            title = num_m.group(2).strip().rstrip('。')
            rest = num_m.group(3).strip()
            out.append(render_inline_heading(prefix, title, theme, rest))
            i += 1
            continue
        # 客户三档识别：**第X档：XXX**。YYY（YYY 可跨行）
        tier_m = re.match(r'^\*\*(第[一二三]档)[:：]([^*]+?)\*\*。?\s*(.*)$', line)
        if tier_m and tier_m.group(1) in TIER_MAP:
            num = TIER_MAP[tier_m.group(1)]
            title = tier_m.group(2).strip()
            desc = tier_m.group(3).strip() or ''
            i += 1
            while (i < len(lines) and lines[i].strip()
                   and not lines[i].startswith('!')
                   and not re.match(r'^\*\*第[一二三]档', lines[i])
                   and not lines[i].startswith('##')
                   and not lines[i].startswith('**')):
                desc += ' ' + lines[i].strip()
                i += 1
            out.append(render_tier_card(num, title, desc, theme))
            continue
        # 滑动图组：<!-- SLIDER: 标题 --> ... <!-- /SLIDER -->
        slider_m = re.match(r'<!--\s*SLIDER(?::\s*([^-]+?))?\s*-->', line)
        if slider_m:
            slider_title = (slider_m.group(1) or '').strip()
            i += 1
            items = []
            while i < len(lines) and not re.match(r'<!--\s*/SLIDER\s*-->', lines[i].strip()):
                cur = lines[i].strip()
                im = re.match(r'!\[\[([^\]]+)\]\]', cur)
                if im:
                    name = im.group(1)
                    cap = ''
                    trailing = cur[im.end():].strip()
                    if trailing:
                        cap = trailing
                    elif (i + 1 < len(lines) and lines[i + 1].startswith('*')
                          and lines[i + 1].rstrip().endswith('*')
                          and not lines[i + 1].startswith('**')):
                        cap = lines[i + 1].strip('*').strip()
                        i += 1
                    items.append((name, cap))
                i += 1
            i += 1  # 跳过 </SLIDER>
            if items:
                out.append(render_slider(items, theme, search_dirs, slider_title))
            continue
        if (line.startswith('|') and line.endswith('|')
                and i + 1 < len(lines) and re.match(r'^\|[\s\-:|]+\|$', lines[i + 1].strip())):
            rows = [[x.strip() for x in line.strip('|').split('|')]]
            i += 2
            while (i < len(lines) and lines[i].strip().startswith('|')
                   and lines[i].strip().endswith('|')):
                rows.append([x.strip() for x in lines[i].strip().strip('|').split('|')])
                i += 1
            out.append(render_table(rows, theme))
            continue
        img_m = re.match(r'!\[\[([^\]]+)\]\]', line)
        if img_m:
            caption, consumed = _peek_caption(lines, i)
            out.append(render_image(img_m.group(1), caption, theme, search_dirs))
            i += consumed
            continue
        std_img_m = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$', line)
        if std_img_m:
            alt = std_img_m.group(1).strip()
            url = std_img_m.group(2).strip()
            caption, consumed = _peek_caption(lines, i)
            if not caption and alt:
                caption = alt
            out.append(render_image(url, caption, theme, search_dirs))
            i += consumed
            continue
        if line.startswith('### '):
            out.append(render_h3(line[4:].strip(), theme))
            i += 1
            continue
        if line.startswith('## '):
            h2_text = line[3:].strip()
            if h2_text in H2_LITE_WHITELIST:
                out.append(render_h2(h2_text, theme))
            else:
                chapter_counter += 1
                out.append(render_step_card(chapter_counter, h2_text, theme, label_text=''))
            i += 1
            continue
        if line.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1
            out.append(render_code_block('\n'.join(code_lines), theme))
            continue
        if line.startswith('> '):
            quote_lines = [line[2:]]
            i += 1
            while i < len(lines) and lines[i].startswith('> '):
                quote_lines.append(lines[i][2:])
                i += 1
            out.append(render_quote('<br>'.join(quote_lines), theme))
            continue
        if line.strip() in ('---', '***', '___'):
            out.append('<hr style="border:0;height:1px;background:linear-gradient(to right,'
                       'transparent,#d4d4d4 30%,#d4d4d4 70%,transparent);margin:40px 0;">')
            i += 1
            continue
        if line.startswith('- '):
            items = [line[2:]]
            i += 1
            while i < len(lines) and lines[i].startswith('- '):
                items.append(lines[i][2:])
                i += 1
            out.append(render_ul(items, theme))
            continue
        ol_m = re.match(r'^\d+\.\s+(.+)', line)
        if ol_m:
            items = [ol_m.group(1)]
            i += 1
            while i < len(lines):
                m = re.match(r'^\d+\.\s+(.+)', lines[i])
                if not m:
                    break
                items.append(m.group(1))
                i += 1
            out.append(render_ol(items, theme))
            continue
        if line.startswith('http'):
            out.append(f'<p style="margin:12px 0;font-size:13px;word-break:break-all;">'
                       f'<a href="{line}" style="color:var(--c-main);text-decoration:underline;'
                       f'text-underline-offset:3px;">{line}</a></p>')
            i += 1
            continue
        out.append(render_paragraph(line, theme))
        i += 1
    return '\n'.join(out)


def render_article_body(md_text, theme, img_dir=None, plain=False):
    """渲染纯 article body 片段（CSS 变量驱动），用于嵌入 panel 模板。
    返回 (article_html_inner, meta_dict)
    """
    art = parse_article(md_text)
    search_dirs = [img_dir] if img_dir else []
    body_html = md_to_html(art['body'], theme, search_dirs)

    b = theme.brand
    date = art['date'].replace('-', '.')
    subtitle = art['subtitle']
    feature = art.get('feature', '')

    if plain:
        head = (f'<p style="margin:0 0 20px;font-size:22px;font-weight:700;color:var(--c-text);'
                f'line-height:1.55;letter-spacing:0.2px;">{subtitle}</p>') if subtitle else ''
        tail = ''
    else:
        magazine_line = f'{b["name"]} {b["magazine_suffix"]}'
        vol_line = f'{b["issue_prefix"]}{b["issue_number"]:03d} · {date}'
        head = (
            f'<section style="border-top:1px solid var(--c-main);border-bottom:1px solid #e5e5e5;'
            f'padding:10px 0;margin-bottom:26px;display:flex;justify-content:space-between;'
            f'align-items:center;">'
            f'<span style="font-size:12px;font-weight:800;letter-spacing:4px;color:var(--c-main);">'
            f'{magazine_line}</span>'
            f'<span style="font-size:11px;color:var(--c-mute);letter-spacing:2px;font-weight:500;">'
            f'{vol_line}</span></section>'
            f'<section style="margin-bottom:18px;display:flex;align-items:center;gap:10px;">'
            f'<span style="display:inline-block;font-size:10px;background:var(--c-main);color:#fff;'
            f'padding:4px 12px;letter-spacing:2px;font-weight:700;border-radius:4px;">'
            f'{b["feature_label"]}</span>'
            f'<span style="font-size:11px;color:var(--c-mute);letter-spacing:1px;">{feature}</span>'
            f'</section>'
            f'<p style="margin:0 0 18px;font-size:22px;font-weight:700;color:var(--c-text-strong);'
            f'line-height:1.55;letter-spacing:0.2px;">{subtitle}</p>'
            f'<section style="display:flex;gap:4px;margin-bottom:36px;">'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="36" height="3" viewBox="0 0 36 3" style="display:block;flex-shrink:0;color:var(--c-main);"><rect width="36" height="3" rx="2" fill="currentColor"/></svg>'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="3" viewBox="0 0 14 3" style="display:block;flex-shrink:0;color:var(--c-soft);"><rect width="14" height="3" rx="2" fill="currentColor"/></svg>'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="6" height="3" viewBox="0 0 6 3" style="display:block;flex-shrink:0;"><rect width="6" height="3" rx="2" fill="#d4d4d4"/></svg>'
            f'</section>'
        )
        tail = (
            f'<section style="margin:56px 0 0;padding-top:22px;border-top:1px solid var(--c-main);'
            f'display:flex;align-items:center;justify-content:space-between;">'
            f'<span style="font-size:11px;color:var(--c-main);letter-spacing:3px;font-weight:700;">'
            f'{magazine_line}</span>'
            f'<span style="font-size:10px;color:var(--c-faint);letter-spacing:2px;">{vol_line}</span>'
            f'</section>'
        )

    inner = f'{head}\n{body_html}\n{tail}'
    return inner, art


def render_article(md_text, theme, img_dir=None, plain=False):
    """裸文档模式：完整 HTML 文档（含 :root + article body + 简单复制按钮）。
    用于 cli.py --no-panel 模式。panel 模式由 cli.py 直接读 preview.html 模板。
    """
    inner, art = render_article_body(md_text, theme, img_dir, plain)
    title = art['title']
    css_vars = build_theme_css_vars(theme)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{title}</title>
<style>
:root {{ {css_vars} }}
body{{margin:0;background:#ffffff;padding:40px 0;}}
#copy-btn{{position:fixed;top:20px;right:20px;z-index:9999;background:var(--c-main);color:#fff;border:0;padding:12px 20px;border-radius:999px;font-size:13px;font-weight:700;letter-spacing:1px;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,0.15);font-family:'PingFang SC',sans-serif;transition:all 0.2s;}}
#copy-btn:hover{{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,0.2);}}
#copy-btn.done{{background:#1a1a1a;}}
</style>
</head><body>
<button id="copy-btn" onclick="copyArticle()">复制到公众号</button>
<section id="article" style="max-width:677px;margin:0 auto;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Noto Sans SC','Hiragino Sans GB','Microsoft YaHei','Helvetica Neue',sans-serif;color:var(--c-text);line-height:1.85;padding:44px 24px;overflow:hidden;">
{inner}
</section>
<script>
function copyArticle() {{
  const el = document.getElementById('article');
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  try {{
    document.execCommand('copy');
    const btn = document.getElementById('copy-btn');
    btn.textContent = '已复制，去公众号粘贴';
    btn.classList.add('done');
    setTimeout(() => {{
      btn.textContent = '复制到公众号';
      btn.classList.remove('done');
    }}, 2500);
  }} catch (e) {{
    alert('复制失败，请手动 Cmd+A 全选');
  }}
  sel.removeAllRanges();
}}
</script>
</body></html>"""
