#!/usr/bin/env python3
"""群日报·报纸版 v2.1：数据驱动 + 可变版数 + 自适应字号。

v2.0 改造：
- 所有版面可变内容外置到 layout-plan.json
- render 函数从 plan 读字段渲染，支持任意版数（page1..pageN）
- page5/page6 复用 page2/page3 模板，page_header 按 page_key 动态生成版号
- 跑新群只需写新 plan.json + 提供 story.json + avatars.json

v2.1 新增：
- page-banner-title 副标 .pbt-deck 字号按字数自动注入（autosize_banner_title）
- CSS word-break: keep-all + ` / ` 分隔保证 wrap 时每行结尾都是完整词

用法：
  python3 render_newspaper.py <story.json> <avatars.json> <plan.json> <out.html>
"""
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
    _has_pil = True
except ImportError:
    _has_pil = False


def auto_img_style(image_path, target_width_px=None, max_height_px=None):
    """读图算实际比例，注入 inline width/height style 让 figure 不变形。

    target_width_px: 目标显示宽度（A3 内常用 480/600/1090）
    max_height_px: 最大允许高度（防溢出）
    返回 'width:Wpx;height:Hpx;object-fit:cover;' 这种 style 字符串
    """
    if not _has_pil or not image_path or not image_path.startswith('file://'):
        return ''
    p = image_path.replace('file://', '')
    try:
        with Image.open(p) as img:
            w, h = img.size
    except Exception:
        return ''
    aspect = w / h if h else 1
    if target_width_px:
        disp_w = target_width_px
        disp_h = int(disp_w / aspect)
        if max_height_px and disp_h > max_height_px:
            disp_h = max_height_px
            disp_w = int(disp_h * aspect)
        return f'width:{disp_w}px;height:{disp_h}px;object-fit:contain;'
    return ''


def autosize_banner_title(theme_title_html):
    """根据 pbt-deck 副标字数自动注入 font-size，让单行装得下最优先。

    版面内容宽 ~1090px。pbt-deck 用宋体字宽 ≈ font-size，加 letter-spacing 后 ≈ font-size + 2px。
    每行能容字数 ≈ 1090 / (font-size + 2)。

    目标：单行装下 + 大字感最大化。
    - ≤ 16 字 → 42px（接近主标，最大气）
    - 17-22 字 → 36px（仍是大字单行）
    - 23-28 字 → 30px（单行或刚好 2 行）
    - 29-36 字 → 26px（最多 2 行，按 / 自然断）
    - 37+ 字  → 22px（最多 3 行）

    AI 写 layout 时建议用 ` / ` 分隔副标的多个语义块，确保 wrap 时每段是完整词。
    """
    m = re.search(r'<span\s+class="pbt-deck">(.*?)</span>',
                  theme_title_html, re.DOTALL)
    if not m:
        return theme_title_html
    text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    # 中文字符 + 数字 + 字母都按 1 字计；空格不计
    n = len(re.sub(r'\s+', '', text))
    if n <= 16:
        px = 42
    elif n <= 22:
        px = 36
    elif n <= 28:
        px = 30
    elif n <= 36:
        px = 26
    else:
        px = 22
    return re.sub(
        r'<span\s+class="pbt-deck">',
        f'<span class="pbt-deck" style="font-size:{px}px;">',
        theme_title_html, count=1
    )


def h(s):
    return html.escape(str(s)) if s is not None else ""


def avatar(name, wxid, avatars, size=24, cls="avatar"):
    src = avatars.get(name, "") or avatars.get(wxid or "", "")
    if src:
        return (f'<img class="{cls}" src="{src}" alt="{h(name)}" '
                f'style="width:{size}px;height:{size}px;" />')
    first = name[0] if name else "·"
    return (f'<span class="{cls} avatar-text" '
            f'style="width:{size}px;height:{size}px;line-height:{size}px;">'
            f'{h(first)}</span>')


def cast_row(cast_list, avatars, size=22):
    chips = []
    for c in cast_list:
        av = avatar(c["name"], c.get("wxid", ""), avatars, size)
        chips.append(
            f'<span class="cast-chip">{av}'
            f'<span class="cast-name">{h(c["name"])}</span></span>')
    return "".join(chips)


def merge_cast(*lists):
    seen = {}
    for lst in lists:
        for c in lst:
            key = c.get("wxid") or c["name"]
            if key not in seen:
                seen[key] = c
    return list(seen.values())


def quotes_box(quotes, cls="quotes-box"):
    if not quotes:
        return ""
    items = ""
    for q in quotes:
        items += (
            f'<div class="q">"{h(q["text"])}" '
            f'<span class="who">— {h(q["who"])}</span></div>'
        )
    return f'<div class="{cls}">{items}</div>'


def pick_quotes(timeline, picks):
    """从 timeline 按 [[ti, qi], ...] 挑 quote 列表。"""
    out = []
    for ti, qi in picks:
        try:
            out.append(timeline[ti]["quotes"][qi])
        except (IndexError, KeyError):
            pass
    return out


def page_header(page_no, page_name, masthead, date, vol):
    return f"""
<header class="page-header">
  <div class="ph-left">
    <span class="ph-num">第 {page_no} 版</span>
    <span class="ph-sec">{h(page_name)}</span>
  </div>
  <div class="ph-mid">{h(masthead.get('footer_brand', ''))}</div>
  <div class="ph-right">
    <div>{h(date)}</div>
    <div>VOL. {h(vol)}</div>
  </div>
</header>"""


def merged_hero_body(timeline, indices, break_html):
    parts = []
    for i, idx in enumerate(indices):
        if i > 0 and break_html:
            parts.append(f'<div class="story-break">{break_html}</div>')
        parts.append(f'<p>{h(timeline[idx]["story"])}</p>')
    return "".join(parts)


def merged_cast_from_indices(timeline, indices, extra_filter=None, max_n=6):
    casts = []
    for idx in indices:
        c = timeline[idx].get("cast", [])
        if extra_filter and extra_filter.get("idx") == idx:
            c = [x for x in c if x.get("name") == extra_filter["name"]]
        casts.append(c)
    return merge_cast(*casts)[:max_n]


# ============== 版面 1 · 头版 ==============
def render_page_1(story, avatars, plan):
    date = story.get("date", "")
    vol = date.replace("-", ".")
    weekday_map = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五",
                   6: "周六", 7: "周日"}
    try:
        wd = weekday_map[datetime.strptime(date, "%Y-%m-%d").isoweekday()]
    except Exception:
        wd = ""

    opening = story.get("opening", "")
    masthead = plan["masthead"]
    p = plan["page1"]
    h_p = p["hero"]
    a_p = p["aside"]

    hero_cast = merged_cast_from_indices(story["timeline"], h_p["timeline_indices"])
    hero_body = merged_hero_body(story["timeline"], h_p["timeline_indices"], h_p.get("story_break_html", ""))
    hero_quotes = pick_quotes(story["timeline"], h_p["quotes_pick"])

    briefing_html = "".join(
        f'<div class="brief-item"><div class="brief-time">{h(b["time"])}</div>'
        f'<div class="brief-title">{h(b["title"])}</div>'
        f'<div class="brief-desc">{h(b["desc"])}</div></div>'
        for b in a_p["briefings"]
    )

    fig = a_p["figure"]
    ps = p["photo_strip"]
    ds = p["day_stats"]

    return f"""
<section class="page page-1">

  <header class="masthead-row">

    <div class="mh-left">
      <div class="mh-name-block">
        <h1 class="mh-name"><span class="mn-r1">{h(masthead['name_top'])}</span><span class="mn-r2">{h(masthead['name_bot'])}</span></h1>
        <div class="mh-pinyin">{h(masthead['pinyin'])}</div>
      </div>
      <div class="mh-slogan-block">
        <div class="mh-slogan-en">{h(masthead['slogan_en'])}</div>
        <div class="mh-slogan">{masthead['slogan_cn_html']}</div>
      </div>
      <div class="mh-tag">{h(masthead['promo_tag'])}</div>
    </div>

    <div class="mh-box">
      <div class="mh-box-line">{h(date.split('-')[0])}年{h(date.split('-')[1])}月</div>
      <div class="mh-box-big">{h(date.split('-')[2])}</div>
      <div class="mh-box-line">{h(wd)}</div>
      <div class="mh-box-sep"></div>
      <div class="mh-box-small">{h(masthead['lunar'])}</div>
      <div class="mh-box-small">{h(masthead['publisher'])}</div>
      <div class="mh-box-small">{h(masthead['cn_no'])}</div>
      <div class="mh-box-small">{h(masthead['issue_code'])}</div>
      <div class="mh-box-small">{h(masthead['issue_no'])}</div>
      <div class="mh-box-small">{h(masthead['total_pages'])}</div>
    </div>

    <div class="mh-right">
      <div class="mh-kicker">{h(p['lead_kicker'])}</div>
      <h2 class="mh-headline">{story.get('lead_title', '').replace(chr(10), '<br>')}</h2>
      <p class="mh-lead">{h(opening)}</p>
    </div>

  </header>

  <div class="grid-12 hero-row p1-hero-row">

    <article class="hero col-span-8 p1-hero">
      <div class="hero-eyebrow">{h(h_p['eyebrow'])}</div>
      <h3 class="hero-title">{h_p['title_html']}</h3>
      <div class="hero-meta">
        <span class="time">{h(h_p['time'])}</span>
        <span class="badge">{h(h_p['badge'])}</span>
      </div>
      <div class="hero-cast">{cast_row(hero_cast, avatars, 22)}</div>
      <div class="hero-body four-col">
        {hero_body}
      </div>
      {quotes_box(hero_quotes)}
      <div class="produced">{h_p['produced_html']}</div>
    </article>

    <aside class="side col-span-4 p1-aside">

      <figure class="codex-figure">
        <img src="{h(fig['image'])}" alt="{h(fig.get('alt',''))}" style="{h(fig.get('img_style',''))}" />
        <figcaption>
          <div class="cf-eyebrow">{h(fig['eyebrow'])}</div>
          <div class="cf-text">{h(fig['text'])}</div>
          <div class="cf-credit">{h(fig['credit'])}</div>
        </figcaption>
      </figure>

      <div class="side-banner">{h(a_p['side_banner'])}</div>
      {briefing_html}

      <div class="side-quote">
        <div class="sq-text">{a_p['side_quote']['text_html']}</div>
        <div class="sq-attr">{h(a_p['side_quote']['attr'])}</div>
      </div>
    </aside>

  </div>

  <section class="photo-strip">
    <div class="ps-banner">{h(ps['banner'])}</div>
    <div class="ps-grid">
      {''.join(
        f'<div class="ps-item">'
        f'{avatar(hl["name"], hl.get("wxid",""), avatars, size=64, cls="ps-avatar")}'
        f'<div class="ps-name">{h(hl["name"])}</div>'
        f'<div class="ps-tag">{h(hl.get("tag",""))}</div>'
        f'</div>'
        for hl in story.get("highlights", [])[:8]
      )}
    </div>
    <div class="ps-caption">{h(ps['caption'])}</div>
  </section>

  <section class="day-stats">
    <div class="ds-banner">{h(ds['banner'])}</div>
    <div class="ds-grid">
      {''.join(f'<div class="ds-item"><div class="n">{h(it["n"])}</div><div class="l">{h(it["l"])}</div></div>' for it in ds['items'])}
    </div>
  </section>

  <footer class="page-foot">{h(p['foot'])}</footer>
</section>
"""


# ============== 版面 2 · 共建 · 人物卡整列 ==============
def render_page_2(story, avatars, plan, page_key="page2"):
    date = story.get("date", "")
    vol = date.replace("-", ".")
    masthead = plan["masthead"]
    p = plan[page_key]
    pc = p["person_card"]
    h_p = p["hero"]

    extra = None
    if h_p.get("cast_pick_extra_t8_filter_name"):
        extra = {"idx": h_p["timeline_indices"][1], "name": h_p["cast_pick_extra_t8_filter_name"]}
    hero_cast_indices = h_p.get("cast_pick_indices", h_p["timeline_indices"])
    hero_cast = merged_cast_from_indices(story["timeline"], hero_cast_indices)
    if extra:
        extra_idx = extra["idx"]
        extra_cast = [c for c in story["timeline"][extra_idx].get("cast", []) if c.get("name") == extra["name"]]
        hero_cast = merge_cast(hero_cast, extra_cast)[:5]

    hero_body = merged_hero_body(story["timeline"], h_p["timeline_indices"], h_p.get("story_break_html", ""))
    hero_quotes = pick_quotes(story["timeline"], h_p["quotes_pick"])

    jl_lines_html = "".join(
        f'<div class="jl-line"><span class="jl-t">{h(t)}</span>'
        f'<span class="jl-q">"{h(q)}"</span></div>'
        for t, q in pc["quote_block_lines"]
    )

    pl = p["produced_list"]
    pl_items_html = "".join(
        f'<div class="col-span-4 pl-item"><div class="pl-no">{h(it["no"])}</div>'
        f'<div class="pl-text"><b>{h(it["title"])}</b><br>{h(it["desc"])}</div></div>'
        for it in pl["items"]
    )

    ts = p["timeline_strip"]
    ts_items_html = "".join(
        f'<div class="ts-item"><div class="ts-time">{h(it["time"])}</div>'
        f'<div class="ts-text">{h(it["text"])}</div>'
        f'<div class="ts-who">{h(it["who"])}</div></div>'
        for it in ts["items"]
    )

    qw = p["quote_wall"]
    qw_items_html = "".join(
        f'<blockquote class="qw-item"><div class="t">"{h(it["t"])}"</div><cite>{h(it["cite"])}</cite></blockquote>'
        for it in qw["items"]
    )

    return f"""
<section class="page page-2">
  {page_header(int(page_key[4:]), p['name'], masthead, date, vol)}

  <h2 class="page-banner-title">
    {autosize_banner_title(p['theme_title_html'])}
    <span class="pbt-en">{h(p['theme_en'])}</span>
  </h2>

  <div class="grid-12 p2-body">

    <aside class="col-span-4 person-card-col">
      <div class="pc-eyebrow">{h(pc['eyebrow'])}</div>

      <figure class="person-card-figure">
        <img src="{h(pc['image'])}" alt="{h(pc.get('alt',''))}" style="{h(pc.get('img_style',''))}" />
      </figure>

      <div class="pc-quote-block">
        <div class="pc-qb-title">{h(pc['quote_block_title'])}</div>
        {jl_lines_html}
      </div>

      <div class="pc-caption">{pc['caption_html']}</div>
    </aside>

    <article class="hero col-span-8 p2-hero">
      <div class="hero-eyebrow">{h(h_p['eyebrow'])}</div>
      <h3 class="hero-title">{h_p['title_html']}</h3>
      <div class="hero-meta">
        <span class="time">{h(h_p['time'])}</span>
        <span class="badge">{h(h_p['badge'])}</span>
      </div>
      <div class="hero-cast">{cast_row(hero_cast, avatars, 22)}</div>

      <div class="hero-body three-col">
        {hero_body}
      </div>

      {quotes_box(hero_quotes)}

      <div class="produced">{h_p['produced_html']}</div>
    </article>

  </div>

  <section class="produced-list">
    <div class="pl-banner">{h(pl['banner'])}</div>
    <div class="grid-12 pl-grid">
      {pl_items_html}
    </div>
  </section>

  <section class="timeline-strip">
    <div class="ts-banner">{h(ts['banner'])}</div>
    <div class="ts-grid">
      {ts_items_html}
    </div>
  </section>

  <section class="quote-wall">
    <div class="qw-banner">{h(qw['banner'])}</div>
    <div class="qw-grid">
      {qw_items_html}
    </div>
  </section>

  <footer class="page-foot">{h(p['foot'])}</footer>
</section>
"""


# ============== 版面 3 · 副刊 · 横图 banner 顶置 ==============
def render_page_3(story, avatars, plan, page_key="page3"):
    date = story.get("date", "")
    vol = date.replace("-", ".")
    masthead = plan["masthead"]
    p = plan[page_key]
    bi = p["banner_image"]
    h_p = p["hero"]

    hero_cast = merged_cast_from_indices(story["timeline"], h_p["timeline_indices"], max_n=5)
    hero_body = merged_hero_body(story["timeline"], h_p["timeline_indices"], h_p.get("story_break_html", ""))
    hero_quotes = pick_quotes(story["timeline"], h_p["quotes_pick"])

    ts = p["timeline_strip"]
    ts_items_html = "".join(
        f'<div class="ts-item"><div class="ts-time">{h(it["time"])}</div>'
        f'<div class="ts-text">{h(it["text"])}</div>'
        f'<div class="ts-who">{h(it["who"])}</div></div>'
        for it in ts["items"]
    )

    lt = p["letters"]
    lt_items_html = "".join(
        f'<div class="col-span-4 lt-item">'
        f'<div class="lt-text">"{h(it["text"])}"</div>'
        f'<div class="lt-from">{h(it["from"])}</div></div>'
        for it in lt["items"]
    )

    lg = p["lingo"]
    lg_items_html = "".join(
        f'<div class="lg-item"><div class="w">{h(it["w"])}</div><div class="d">{h(it["d"])}</div></div>'
        for it in lg["items"]
    )

    return f"""
<section class="page page-3">
  {page_header(int(page_key[4:]), p['name'], masthead, date, vol)}

  <h2 class="page-banner-title">
    {autosize_banner_title(p['theme_title_html'])}
    <span class="pbt-en">{h(p['theme_en'])}</span>
  </h2>

  <figure class="banner-image-top">
    <img src="{h(bi['image'])}" alt="{h(bi.get('alt',''))}" style="{h(bi.get('img_style',''))}" />
    <figcaption>
      <div class="bit-eyebrow">{h(bi['eyebrow'])}</div>
      <div class="bit-title">{h(bi['title'])}</div>
      <div class="bit-text">{h(bi['text'])}</div>
      <div class="bit-credit">{h(bi['credit'])}</div>
    </figcaption>
  </figure>

  <article class="hero hero-full p3-hero">
    <div class="hero-eyebrow">{h(h_p['eyebrow'])}</div>
    <h3 class="hero-title">{h_p['title_html']}</h3>
    <div class="hero-meta">
      <span class="time">{h(h_p['time'])}</span>
      <span class="badge">{h(h_p['badge'])}</span>
    </div>
    <div class="hero-cast">{cast_row(hero_cast, avatars, 22)}</div>
    <div class="hero-body four-col">
      {hero_body}
    </div>
    {quotes_box(hero_quotes)}
    <div class="produced">{h_p['produced_html']}</div>
  </article>

  <section class="timeline-strip">
    <div class="ts-banner">{h(ts['banner'])}</div>
    <div class="ts-grid">
      {ts_items_html}
    </div>
  </section>

  <section class="letters">
    <div class="lt-banner">{h(lt['banner'])}</div>
    <div class="grid-12 lt-grid">
      {lt_items_html}
    </div>
  </section>

  <section class="lingo">
    <div class="lg-banner">{h(lg['banner'])}</div>
    <div class="lg-grid">
      {lg_items_html}
    </div>
  </section>

  <footer class="page-foot">{h(p['foot'])}</footer>
</section>
"""


# ============== 版面 4 · 人物 + 附录 ==============
def render_page_4(story, avatars, plan, page_key="page4"):
    date = story.get("date", "")
    vol = date.replace("-", ".")
    masthead = plan["masthead"]
    p = plan[page_key]
    tm = p["tomorrow"]

    hl_html = []
    for hl in story.get("highlights", []):
        av = avatar(hl["name"], hl.get("wxid", ""), avatars, size=56, cls="hl-avatar")
        hl_html.append(f"""
<div class="hl">
  {av}
  <div class="hl-info">
    <div class="hl-name">{h(hl['name'])}</div>
    <div class="hl-tag">{h(hl.get('tag',''))}</div>
    <div class="hl-desc">{h(hl.get('desc',''))}</div>
  </div>
</div>""")

    sop_html = []
    for sop in story.get("sops", []):
        steps = "".join(f"<li>{h(s)}</li>" for s in sop.get("steps", []))
        out = (f'<div class="sop-out"><b>OUTPUT ·</b> {h(sop["output"])}</div>'
               if sop.get("output") else "")
        sop_html.append(f"""
<div class="sop">
  <div class="sop-title">{h(sop.get('title',''))}</div>
  <div class="sop-meta">{h(sop.get('author',''))} · {h(sop.get('time',''))}</div>
  <ol class="sop-steps">{steps}</ol>
  {out}
</div>""")

    qa_html = []
    for qa in story.get("qas", []):
        ans = "".join(
            f'<div class="qa-a"><b>{h(a["who"])}：</b>{h(a["text"])}</div>'
            for a in qa.get("answers", [])
        )
        qa_html.append(f"""
<div class="qa">
  <div class="qa-q">Q：{h(qa.get('q',''))}
    <span class="asker">— {h(qa.get('asker',''))}</span></div>
  {ans}
</div>""")

    tm_items_html = "".join(
        f'<div class="tm-item">'
        f'<div class="tm-tag">{h(it["tag"])}</div>'
        f'<div class="tm-title">{h(it["title"])}</div>'
        f'<div class="tm-desc">{h(it["desc"])}</div></div>'
        for it in tm["items"]
    )

    qr = tm["qr"]
    stats = story.get("stats", {})
    fq = story.get("footer_quote", {})
    group = story.get("group_name", "")

    total_chars = stats.get('total_chars', 0)
    total_chars_fmt = f"{total_chars:,}" if isinstance(total_chars, int) else str(total_chars)

    return f"""
<section class="page page-4">
  {page_header(int(page_key[4:]), p['name'], masthead, date, vol)}

  <h2 class="page-banner-title">
    {autosize_banner_title(p['theme_title_html'])}
    <span class="pbt-en">{h(p['theme_en'])}</span>
  </h2>

  <section class="hl-grid">
    {''.join(hl_html)}
  </section>

  <div class="appendix-bar">{h(p['appendix_banner'])}</div>

  <div class="grid-12 appendix-grid">
    <div class="col-span-6 appendix-col">
      <h3 class="apx-title">{h(p['sop_title'])}</h3>
      {''.join(sop_html)}
    </div>
    <div class="col-span-6 appendix-col">
      <h3 class="apx-title">{h(p['qa_title'])}</h3>
      {''.join(qa_html)}
    </div>
  </div>

  <section class="tomorrow tomorrow-with-qr">
    <div class="tm-banner">{h(tm['banner'])}</div>
    <div class="grid-12 tm-grid">
      <div class="col-span-8 tm-text-col">
        {tm_items_html}
      </div>
      <figure class="col-span-4 tm-qr-col">
        <img src="{h(qr['image'])}" alt="{h(qr.get('alt',''))}" />
        <figcaption>
          <div class="qr-title">{qr['title_html']}</div>
          <div class="qr-desc">{h(qr['desc'])}</div>
        </figcaption>
      </figure>
    </div>
  </section>

  <footer class="colophon">
    <div class="colophon-stats">
      <div class="colophon-stat"><div class="n">{h(stats.get('total_messages','—'))}</div><div class="l">Messages</div></div>
      <div class="colophon-stat"><div class="n">{h(stats.get('unique_senders','—'))}</div><div class="l">People</div></div>
      <div class="colophon-stat"><div class="n">{total_chars_fmt}</div><div class="l">Characters</div></div>
      <div class="colophon-stat"><div class="n">{len(story.get('timeline',[]))}</div><div class="l">Stories</div></div>
      <div class="colophon-stat"><div class="n">+{stats.get('new_members',0)}</div><div class="l">Newcomer</div></div>
    </div>
    <div class="colophon-quote">
      <div class="t">"{h(fq.get('text',''))}"</div>
      <div class="a">— {h(fq.get('attr',''))}</div>
    </div>
    <div class="colophon-meta">
      <span>{h(group)} · {h(date)}</span>
      <span>{h(story.get('time_range',''))}</span>
      <span>本期完 · 明日续</span>
    </div>
  </footer>

  <footer class="page-foot">{h(p['foot'])}</footer>
</section>
"""


# ============== CSS（全部保留，与 v1.0 一致） ==============
CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;700;900&family=Noto+Sans+SC:wght@400;700;900&family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=Old+Standard+TT:wght@400;700&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  background: #2a241c;
  font-family: "Noto Serif SC", "Songti SC", "STSong", serif;
  color: #000;
  font-size: 11px;
  line-height: 1.65;
}

@page { size: A3 portrait; margin: 0; }
@media print {
  html, body { background: #fff; }
  .page {
    margin: 0 !important;
    box-shadow: none !important;
    page-break-after: always;
    page-break-inside: avoid;
    break-after: page;
    break-inside: avoid;
  }
  .page:last-child { page-break-after: auto; break-after: auto; }
}

.page {
  width: 1123px;
  min-height: 1587px;
  margin: 20px auto;
  padding: 16px 22px 18px;
  background: #fdfcf8;
  box-shadow: 0 8px 40px rgba(0,0,0,0.25);
  display: flex;
  flex-direction: column;
  position: relative;
}

.grid-12 { display: grid; grid-template-columns: repeat(12, 1fr); gap: 0 14px; }
.col-span-4 { grid-column: span 4; }
.col-span-6 { grid-column: span 6; }
.col-span-8 { grid-column: span 8; }
.col-span-12 { grid-column: span 12; }

/* 报头（第 1 版） */
.masthead-row {
  display: grid;
  grid-template-columns: 1.3fr 0.65fr 2.2fr;
  gap: 18px;
  align-items: stretch;
  padding-bottom: 14px;
  border-bottom: 2px solid #000;
  margin-bottom: 14px;
}
.mh-left {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding-right: 14px;
  padding-top: 4px;
  text-align: center;
}
.mh-name-block { text-align: center; }
.mh-name {
  font-family: "Noto Serif SC", "Songti SC", "STSong", serif;
  font-weight: 900;
  color: #c41e1e;
  margin-bottom: 6px;
  text-align: center;
  line-height: 1.0;
}
.mn-r1, .mn-r2 {
  display: block;
  font-size: 82px;
  letter-spacing: 6px;
  padding-left: 6px;
}
.mn-r2 { margin-top: 4px; }
.mh-pinyin {
  font-family: "Playfair Display", "Old Standard TT", serif;
  font-size: 14px;
  letter-spacing: 5px;
  color: #c41e1e;
  font-weight: 700;
  white-space: nowrap;
  text-align: center;
}
.mh-tag {
  font-family: "Old Standard TT", serif;
  font-size: 11px;
  color: #555;
  letter-spacing: 1.8px;
  text-align: center;
}
.mh-slogan-block {
  padding: 12px 0;
  border-top: 1px solid rgba(0,0,0,0.5);
  border-bottom: 1px solid rgba(0,0,0,0.5);
}
.mh-slogan-en {
  font-family: "Old Standard TT", "Playfair Display", serif;
  font-size: 10px;
  letter-spacing: 4px;
  color: #555;
  font-style: italic;
  margin-bottom: 6px;
}
.mh-slogan {
  font-family: "Songti SC", "Noto Serif SC", serif;
  font-size: 14px;
  letter-spacing: 4px;
  line-height: 1.5;
  color: #222;
  font-weight: 700;
}
.mh-box {
  border: 1px solid #000;
  padding: 14px 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  text-align: center;
  font-family: "Songti SC", serif;
  color: #000;
  font-size: 11px;
}
.mh-box-line { font-size: 12.5px; letter-spacing: 1.5px; margin: 2px 0; }
.mh-box-big {
  font-size: 50px;
  font-weight: 900;
  line-height: 1.05;
  margin: 4px 0;
  font-family: "Songti SC", serif;
}
.mh-box-sep { height: 8px; }
.mh-box-small { font-size: 11.5px; letter-spacing: 0.8px; margin: 2px 0; color: #222; }
.mh-right {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  padding-left: 4px;
  padding-bottom: 16px;
}
.mh-kicker {
  font-family: "Songti SC", serif;
  font-size: 11px;
  letter-spacing: 3px;
  color: #555;
  margin-bottom: 6px;
}
.mh-headline {
  font-family: "Songti SC", "Noto Serif SC", serif;
  font-weight: 900;
  font-size: 34px;
  letter-spacing: 3px;
  line-height: 1.2;
  margin-bottom: 12px;
  color: #000;
}
.mh-lead {
  font-family: "Noto Serif SC", "Songti SC", serif;
  font-size: 11px;
  line-height: 1.75;
  text-align: justify;
  column-count: 4;
  column-gap: 12px;
  column-rule: 1px solid rgba(0,0,0,0.25);
  color: #000;
}

/* 简版页眉（第 2-4 版） */
.page-header {
  border-bottom: 2px solid #000;
  padding: 6px 2px;
  margin-bottom: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: "Old Standard TT", serif;
}
.page-header .ph-left { display: flex; gap: 12px; align-items: baseline; }
.ph-num { font-family: "Noto Sans SC", sans-serif; font-size: 18px; font-weight: 900; color: #000; letter-spacing: 2px; }
.ph-sec { font-size: 10px; letter-spacing: 3px; color: #555; text-transform: uppercase; }
.page-header .ph-mid { font-family: "Noto Sans SC", "PingFang SC", "Heiti SC", sans-serif; font-size: 16px; font-weight: 900; letter-spacing: 6px; }
.page-header .ph-right { text-align: right; font-size: 9.5px; letter-spacing: 1.5px; line-height: 1.4; color: #555; text-transform: uppercase; }

.page-banner-title {
  font-family: "Songti SC", "Noto Serif SC", serif;
  font-size: 46px;
  font-weight: 900;
  letter-spacing: 3px;
  text-align: center;
  line-height: 1.18;
  padding: 14px 0 10px;
  border-top: 1px solid #000;
  border-bottom: 1px solid #000;
  margin: 8px 0 14px;
  word-break: keep-all;
}
.page-banner-title .pbt-deck {
  display: block;
  font-family: "Songti SC", "Noto Serif SC", serif;
  font-size: 36px;
  font-weight: 700;
  letter-spacing: 2px;
  margin-top: 8px;
  color: #1a1815;
  line-height: 1.22;
  word-break: keep-all;
}
.pbt-en {
  display: block;
  font-family: "Playfair Display", serif;
  font-weight: 400;
  font-style: italic;
  font-size: 14px;
  letter-spacing: 2.5px;
  color: #555;
  margin-top: 6px;
}

/* Hero 主稿 */
.hero { display: flex; flex-direction: column; padding-right: 14px; }
.hero-eyebrow { font-family: "Old Standard TT", serif; font-size: 10.5px; letter-spacing: 5px; color: #c41e1e; font-weight: 700; text-transform: uppercase; margin-bottom: 6px; }
.hero-title { font-family: "Songti SC", "Noto Serif SC", serif; font-size: 30px; font-weight: 900; letter-spacing: 2.5px; line-height: 1.22; margin-bottom: 8px; color: #000; }
.hero-title .deck { display: block; font-family: "Songti SC", serif; font-style: italic; font-weight: 400; font-size: 17px; letter-spacing: 1.5px; line-height: 1.4; color: #555; margin-top: 5px; }
.hero-meta { font-family: "Old Standard TT", serif; font-size: 10.5px; letter-spacing: 2px; color: #333; padding: 5px 0; border-top: 1px solid rgba(0,0,0,0.6); border-bottom: 1px solid rgba(0,0,0,0.6); display: flex; gap: 18px; }
.hero-meta .time { font-weight: 700; }
.hero-meta .badge { font-family: "Songti SC", serif; color: #c41e1e; font-weight: 700; }
.hero-cast { display: flex; flex-wrap: wrap; gap: 4px 12px; padding: 6px 0 8px; border-bottom: 1px solid rgba(0,0,0,0.2); margin-bottom: 10px; }
.cast-chip { display: inline-flex; align-items: center; gap: 5px; font-family: "Songti SC", serif; font-size: 10.5px; font-weight: 700; color: #c41e1e; letter-spacing: 0.5px; }
.cast-chip .avatar { border-radius: 50%; border: 1px solid #000; object-fit: cover; }
.avatar-text { display: inline-block; text-align: center; background: #fdfcf8; border: 1px solid #000; font-family: "Songti SC", serif; color: #000; font-weight: 700; }
.hero-body { font-family: "Noto Serif SC", "Songti SC", serif; font-size: 11px; line-height: 1.78; text-align: justify; color: #000; margin-bottom: 8px; }
.hero-body.four-col { column-count: 4; column-gap: 14px; column-rule: 1px solid rgba(0,0,0,0.2); }
.hero-body.three-col { column-count: 3; column-gap: 14px; column-rule: 1px solid rgba(0,0,0,0.2); }
.hero-body p { text-indent: 0; margin-bottom: 4px; }
.hero-body p::first-letter { font-size: 22px; font-family: "Songti SC", serif; font-weight: 900; color: #c41e1e; float: left; line-height: 1; padding-right: 4px; padding-top: 2px; }
.story-break { text-align: center; font-family: "Songti SC", serif; font-size: 11px; letter-spacing: 5px; color: #c41e1e; font-weight: 700; padding: 4px 0; margin: 6px 0; column-span: all; border-top: 1px solid rgba(0,0,0,0.3); border-bottom: 1px solid rgba(0,0,0,0.3); }

.quotes-box { margin: 8px 0; padding: 14px 14px; border-left: 3px solid #c41e1e; background: rgba(196,30,30,0.04); display: flex; flex-direction: column; gap: 8px; }
.hero .quotes-box { flex: 1; justify-content: space-around; }
.quotes-box .q { font-family: "Songti SC", "Noto Serif SC", serif; font-size: 13px; line-height: 1.55; font-style: italic; color: #000; }
.quotes-box .who { font-family: "Old Standard TT", serif; font-size: 10px; font-style: normal; color: #c41e1e; font-weight: 700; margin-left: 4px; }

.produced { font-family: "Songti SC", serif; font-size: 10.5px; line-height: 1.5; letter-spacing: 0.5px; padding: 7px 0; border-top: 2px solid #c41e1e; border-bottom: 2px solid #c41e1e; color: #000; margin-top: auto; }
.produced b { color: #c41e1e; letter-spacing: 2px; }

/* 第 1 版 */
.p1-hero-row { margin-bottom: 14px; }
.p1-hero { border-right: 1px solid rgba(0,0,0,0.3); display: flex; flex-direction: column; }
.p1-aside { display: flex; flex-direction: column; padding-left: 6px; }
.codex-figure { margin-bottom: 12px; display: flex; flex-direction: column; }
/* v2.2: figure 默认按图片比例自适应；可通过 layout-plan figure.style 覆盖 */
.codex-figure img { width: 100%; display: block; border: 1.5px solid #000; max-height: 420px; object-fit: contain; background: #2a3344; }
.codex-figure figcaption { padding: 6px 2px 8px; border-bottom: 1px solid rgba(0,0,0,0.3); }
.cf-eyebrow { font-family: "Old Standard TT", serif; font-size: 10px; letter-spacing: 4px; color: #c41e1e; font-weight: 700; text-transform: uppercase; margin-bottom: 4px; }
.cf-text { font-family: "Noto Serif SC", serif; font-size: 10.5px; line-height: 1.55; text-align: justify; color: #000; }
.cf-credit { font-family: "Old Standard TT", serif; font-size: 9px; letter-spacing: 1.2px; color: #555; font-style: italic; padding-top: 4px; }
.side-banner { background: #000; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 12px; font-weight: 900; letter-spacing: 4px; text-align: center; padding: 6px 0; margin-bottom: 8px; }
.brief-item { border-bottom: 1px solid rgba(0,0,0,0.2); padding: 6px 4px; }
.brief-item:last-child { border-bottom: none; }
.brief-time { font-family: "Old Standard TT", serif; font-size: 10px; letter-spacing: 2px; color: #c41e1e; font-weight: 700; }
.brief-title { font-family: "Songti SC", "Noto Serif SC", serif; font-size: 13px; font-weight: 900; letter-spacing: 1px; line-height: 1.3; margin: 2px 0 3px; color: #000; }
.brief-desc { font-family: "Noto Serif SC", serif; font-size: 10.5px; line-height: 1.55; color: #222; }
.side-quote { margin-top: auto; padding: 12px 14px; background: #000; color: #fdfcf8; text-align: center; }
.sq-text { font-family: "Songti SC", "Noto Serif SC", serif; font-size: 30px; font-weight: 900; letter-spacing: 8px; line-height: 1.3; }
.sq-attr { font-family: "Old Standard TT", serif; font-size: 10px; letter-spacing: 2px; color: #aaa; margin-top: 6px; }

.photo-strip { margin-top: 14px; border: 1.5px solid #000; }
.ps-banner { background: #000; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 13px; font-weight: 900; letter-spacing: 5px; text-align: center; padding: 6px 0; }
.ps-grid { display: grid; grid-template-columns: repeat(8, 1fr); gap: 0; padding: 10px 8px; }
.ps-item { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 0 4px; border-right: 1px solid rgba(0,0,0,0.15); }
.ps-item:last-child { border-right: none; }
.ps-avatar { border-radius: 50%; border: 1.5px solid #000; margin-bottom: 6px; }
.ps-name { font-family: "Noto Sans SC", "PingFang SC", sans-serif; font-size: 11px; font-weight: 900; line-height: 1.2; margin-bottom: 3px; }
.ps-tag { font-size: 9px; color: #c41e1e; letter-spacing: 0.3px; line-height: 1.35; font-family: "Songti SC", serif; }
.ps-caption { text-align: center; font-family: "Songti SC", serif; font-style: italic; font-size: 10px; letter-spacing: 1.5px; color: #555; padding: 4px 0 8px; border-top: 1px solid rgba(0,0,0,0.2); }

.day-stats { margin-top: 12px; border: 1.5px solid #000; }
.ds-banner { background: #000; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 12px; font-weight: 900; letter-spacing: 4px; text-align: center; padding: 5px 0; }
.ds-grid { display: grid; grid-template-columns: repeat(8, 1fr); padding: 8px 6px; }
.ds-item { text-align: center; border-right: 1px solid rgba(0,0,0,0.18); padding: 2px 6px; }
.ds-item:last-child { border-right: none; }
.ds-item .n { font-family: "Playfair Display", serif; font-size: 28px; font-weight: 900; line-height: 1; color: #c41e1e; }
.ds-item .l { font-family: "Songti SC", serif; font-size: 10px; letter-spacing: 1px; color: #333; margin-top: 4px; }

/* 第 2 版 · 人物卡 */
.p2-body { margin-bottom: 14px; }
.person-card-col { display: flex; flex-direction: column; padding-right: 14px; border-right: 1px solid rgba(0,0,0,0.3); }
.pc-eyebrow { font-family: "Old Standard TT", serif; font-size: 10.5px; letter-spacing: 5px; color: #c41e1e; font-weight: 700; text-transform: uppercase; text-align: center; padding-bottom: 6px; border-bottom: 2px solid #c41e1e; margin-bottom: 8px; }
.person-card-figure { margin-bottom: 10px; }
/* v2.2: 高度可被 layout-plan person_card.style 覆盖 */
.person-card-figure img { width: 100%; display: block; border: 1.5px solid #000; max-height: 600px; object-fit: cover; object-position: center top; }
.pc-quote-block { background: #1f2d4a; color: #fdfcf8; padding: 10px 12px; margin-bottom: 10px; }
.pc-qb-title { font-family: "Noto Sans SC", sans-serif; font-size: 11px; font-weight: 900; letter-spacing: 1.5px; line-height: 1.4; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.3); color: #fdfcf8; }
.jl-line { display: flex; gap: 8px; align-items: baseline; margin-bottom: 5px; }
.jl-t { font-family: "Old Standard TT", serif; font-size: 10.5px; font-weight: 700; color: #c4a574; letter-spacing: 1px; flex: 0 0 auto; }
.jl-q { font-family: "Songti SC", serif; font-size: 11.5px; font-style: italic; line-height: 1.45; color: #fdfcf8; }
.pc-caption { font-family: "Songti SC", serif; font-size: 10.5px; line-height: 1.55; color: #222; padding: 8px 4px 0; border-top: 1px solid rgba(0,0,0,0.3); margin-top: auto; }
.pc-caption b { color: #c41e1e; letter-spacing: 1px; }
.p2-hero { padding-left: 6px; display: flex; flex-direction: column; }

.produced-list { margin-top: 12px; border: 1.5px solid #000; }
.pl-banner { background: #1f2d4a; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 12px; font-weight: 900; letter-spacing: 4px; text-align: center; padding: 5px 0; }
.pl-grid { padding: 10px 12px; gap: 0 18px; }
.pl-item { display: flex; gap: 10px; align-items: flex-start; border-right: 1px solid rgba(0,0,0,0.18); padding-right: 14px; }
.pl-item:last-child { border-right: none; }
.pl-no { font-family: "Playfair Display", serif; font-size: 28px; font-weight: 900; color: #c41e1e; line-height: 1; flex: 0 0 auto; }
.pl-text { font-family: "Noto Serif SC", serif; font-size: 10.5px; line-height: 1.55; color: #000; }
.pl-text b { font-family: "Noto Sans SC", sans-serif; font-weight: 900; font-size: 12px; letter-spacing: 0.5px; display: inline-block; margin-bottom: 3px; }

/* timeline-strip */
.timeline-strip { margin-top: 12px; border: 1.5px solid #000; }
.ts-banner { background: #c41e1e; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 12px; font-weight: 900; letter-spacing: 4px; text-align: center; padding: 5px 0; }
.ts-grid { display: grid; grid-template-columns: repeat(6, 1fr); padding: 12px 14px; gap: 0 14px; }
.ts-item { border-right: 1px solid rgba(0,0,0,0.18); padding-right: 12px; display: flex; flex-direction: column; }
.ts-item:last-child { border-right: none; }
.ts-time { font-family: "Playfair Display", serif; font-size: 17px; font-weight: 900; color: #c41e1e; letter-spacing: 1px; line-height: 1; margin-bottom: 5px; }
.ts-text { font-family: "Noto Serif SC", serif; font-size: 10.5px; line-height: 1.5; color: #000; flex: 1; }
.ts-who { font-family: "Songti SC", serif; font-size: 9.5px; letter-spacing: 0.5px; color: #555; margin-top: 4px; font-style: italic; }

.quote-wall { margin-top: 12px; border: 1.5px solid #000; display: flex; flex-direction: column; flex: 1; }
.qw-banner { background: #1f2d4a; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 12px; font-weight: 900; letter-spacing: 4px; text-align: center; padding: 5px 0; }
.qw-grid { display: grid; grid-template-columns: repeat(4, 1fr); padding: 14px 14px; gap: 14px 18px; flex: 1; align-content: space-around; }
.qw-item { border-left: 3px solid #c41e1e; padding: 4px 0 4px 12px; margin: 0; display: flex; flex-direction: column; justify-content: space-between; }
.qw-item .t { font-family: "Noto Serif SC", "Songti SC", serif; font-size: 11.5px; line-height: 1.5; font-style: italic; color: #000; }
.qw-item cite { display: inline-block; margin-top: 5px; font-family: "Old Standard TT", serif; font-style: normal; font-size: 10px; letter-spacing: 1.5px; color: #1f2d4a; font-weight: 700; }

/* 第 3 版 · banner-image */
.banner-image-top { display: grid; grid-template-columns: 1.4fr 1fr; gap: 16px; margin-bottom: 14px; border: 1.5px solid #000; padding: 0; background: #fdfcf8; }
/* v2.2: 高度自适应，可被 layout-plan banner_image.style 覆盖 */
.banner-image-top img { width: 100%; max-height: 420px; display: block; object-fit: cover; border-right: 1.5px solid #000; }
.banner-image-top figcaption { padding: 14px 16px 14px 4px; display: flex; flex-direction: column; justify-content: center; }
.bit-eyebrow { font-family: "Old Standard TT", serif; font-size: 11px; letter-spacing: 5px; color: #c41e1e; font-weight: 700; text-transform: uppercase; margin-bottom: 6px; }
.bit-title { font-family: "Songti SC", "Noto Serif SC", serif; font-size: 22px; font-weight: 900; letter-spacing: 2px; line-height: 1.25; margin-bottom: 8px; color: #000; }
.bit-text { font-family: "Noto Serif SC", serif; font-size: 10.5px; line-height: 1.65; text-align: justify; color: #000; }
.bit-credit { font-family: "Old Standard TT", serif; font-size: 9.5px; letter-spacing: 1.5px; color: #555; font-style: italic; padding-top: 8px; margin-top: 8px; border-top: 1px solid rgba(0,0,0,0.3); }
.p3-hero { margin-bottom: 14px; }

.letters { border: 1.5px solid #000; margin-top: 12px; }
.lt-banner { background: #c41e1e; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 12px; font-weight: 900; letter-spacing: 4px; text-align: center; padding: 5px 0; }
.lt-grid { padding: 10px 12px; gap: 0 18px; }
.lt-item { border-right: 1px solid rgba(0,0,0,0.18); padding-right: 14px; }
.lt-item:last-child { border-right: none; }
.lt-text { font-family: "Songti SC", serif; font-style: italic; font-size: 12px; line-height: 1.55; color: #000; margin-bottom: 6px; }
.lt-from { font-family: "Old Standard TT", serif; font-size: 10px; letter-spacing: 1.5px; color: #c41e1e; font-weight: 700; }

.lingo { margin-top: 12px; border: 1.5px solid #000; display: flex; flex-direction: column; flex: 1; }
.lg-banner { background: #c41e1e; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 13px; font-weight: 900; letter-spacing: 5px; text-align: center; padding: 6px 0; }
.lg-grid { display: grid; grid-template-columns: repeat(3, 1fr); padding: 10px 14px; gap: 10px 20px; flex: 1; align-content: space-around; }
.lg-item { display: grid; grid-template-columns: auto 1fr; gap: 0 10px; align-items: start; }
.lg-item .w { font-family: "Noto Sans SC", "PingFang SC", sans-serif; font-size: 19px; font-weight: 900; color: #c41e1e; letter-spacing: 1px; line-height: 1.1; }
.lg-item .d { font-family: "Noto Serif SC", serif; font-size: 11px; line-height: 1.65; color: #222; }

/* 第 4 版 */
.hl-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px 18px; padding: 8px 0 10px; border-bottom: 2px solid #000; }
.hl { display: grid; grid-template-columns: auto 1fr; gap: 0 10px; align-items: flex-start; padding: 2px 0; }
.hl-avatar { border-radius: 50%; border: 1.5px solid #000; object-fit: cover; }
.hl-info { display: flex; flex-direction: column; gap: 2px; }
.hl-name { font-family: "Noto Sans SC", "PingFang SC", sans-serif; font-size: 14px; font-weight: 900; letter-spacing: 1px; color: #000; }
.hl-tag { font-family: "Songti SC", serif; font-size: 10px; color: #c41e1e; font-weight: 700; letter-spacing: 0.5px; }
.hl-desc { font-family: "Noto Serif SC", serif; font-size: 10px; line-height: 1.5; color: #222; margin-top: 2px; }

.appendix-bar { background: #000; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 11px; font-weight: 900; letter-spacing: 5px; text-align: center; padding: 4px 0; margin-top: 8px; }
.appendix-grid { padding: 8px 0 0; gap: 0 22px; }
.appendix-col { padding: 0 4px; border-right: 1px solid rgba(0,0,0,0.25); }
.appendix-col:last-child { border-right: none; }
.apx-title { font-family: "Songti SC", "Noto Serif SC", serif; font-size: 14px; font-weight: 900; letter-spacing: 3px; color: #c41e1e; text-align: center; padding-bottom: 4px; border-bottom: 1.5px solid #c41e1e; margin-bottom: 6px; }
.sop { margin-bottom: 6px; padding: 4px 4px; border-bottom: 1px solid rgba(0,0,0,0.2); }
.sop:last-child { border-bottom: none; margin-bottom: 0; }
.sop-title { font-family: "Noto Sans SC", sans-serif; font-size: 11px; font-weight: 900; letter-spacing: 0.5px; line-height: 1.3; margin-bottom: 2px; }
.sop-meta { font-family: "Old Standard TT", serif; font-size: 9.5px; letter-spacing: 1px; color: #c41e1e; font-weight: 700; margin-bottom: 3px; }
.sop-steps { font-family: "Noto Serif SC", serif; font-size: 10px; line-height: 1.5; padding-left: 16px; color: #000; }
.sop-steps li { margin-bottom: 1px; list-style-type: decimal; }
.sop-out { font-family: "Songti SC", serif; font-size: 10px; line-height: 1.45; padding: 3px 4px; margin-top: 3px; border-top: 1px solid rgba(196,30,30,0.4); color: #000; }
.sop-out b { color: #c41e1e; letter-spacing: 1.5px; }
.qa { margin-bottom: 5px; padding: 4px 4px; border-bottom: 1px solid rgba(0,0,0,0.2); }
.qa:last-child { border-bottom: none; margin-bottom: 0; }
.qa-q { font-family: "Noto Sans SC", sans-serif; font-size: 11px; font-weight: 900; line-height: 1.35; margin-bottom: 3px; }
.qa-q .asker { font-family: "Songti SC", serif; font-weight: 400; color: #c41e1e; font-size: 9.5px; margin-left: 6px; }
.qa-a { font-family: "Noto Serif SC", serif; font-size: 10px; line-height: 1.5; padding: 1px 0; color: #222; }
.qa-a b { font-family: "Noto Sans SC", sans-serif; color: #1f2d4a; }

.tomorrow { margin-top: 10px; border: 1.5px solid #000; }
.tm-banner { background: #1f2d4a; color: #fdfcf8; font-family: "Noto Sans SC", sans-serif; font-size: 11px; font-weight: 900; letter-spacing: 4px; text-align: center; padding: 4px 0; }
.tm-grid { padding: 8px 12px; gap: 0 14px; align-items: stretch; }
.tm-text-col { display: flex; flex-direction: column; justify-content: space-around; gap: 8px; padding-right: 18px; border-right: 1px solid rgba(0,0,0,0.3); }
.tm-tag { font-family: "Old Standard TT", serif; font-size: 10px; letter-spacing: 2px; color: #c41e1e; font-weight: 700; margin-bottom: 3px; }
.tm-title { font-family: "Noto Sans SC", sans-serif; font-size: 14px; font-weight: 900; letter-spacing: 1px; line-height: 1.3; margin-bottom: 4px; }
.tm-desc { font-family: "Noto Serif SC", serif; font-size: 10.5px; line-height: 1.55; color: #222; }
.tm-qr-col { display: flex; flex-direction: column; align-items: center; padding: 4px 0 0 4px; }
.tm-qr-col img { width: 100%; max-width: 165px; display: block; border: 1.5px solid #000; object-fit: contain; }
.tm-qr-col figcaption { text-align: center; margin-top: 6px; }
.qr-title { font-family: "Noto Sans SC", sans-serif; font-size: 12px; font-weight: 900; letter-spacing: 1px; line-height: 1.35; color: #000; }
.qr-desc { font-family: "Old Standard TT", serif; font-size: 9.5px; letter-spacing: 1px; color: #555; font-style: italic; margin-top: 4px; }

.colophon { margin-top: 10px; padding: 8px 8px 0; border-top: 2px solid #000; display: flex; flex-direction: column; gap: 6px; }
.colophon-stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0 10px; }
.colophon-stat { text-align: center; border-right: 1px solid rgba(0,0,0,0.2); padding: 0 4px; }
.colophon-stat:last-child { border-right: none; }
.colophon-stat .n { font-family: "Playfair Display", serif; font-size: 22px; font-weight: 900; color: #c41e1e; line-height: 1; }
.colophon-stat .l { font-family: "Old Standard TT", serif; font-size: 9.5px; letter-spacing: 2px; color: #555; margin-top: 3px; text-transform: uppercase; }
.colophon-quote { text-align: center; padding: 6px 0; border-top: 1px solid rgba(0,0,0,0.2); border-bottom: 1px solid rgba(0,0,0,0.2); }
.colophon-quote .t { font-family: "Songti SC", "Noto Serif SC", serif; font-size: 14px; font-style: italic; letter-spacing: 4px; line-height: 1.35; color: #000; }
.colophon-quote .a { font-family: "Old Standard TT", serif; font-size: 10px; letter-spacing: 1.5px; color: #c41e1e; font-weight: 700; margin-top: 4px; }
.colophon-meta { display: flex; justify-content: space-between; font-family: "Old Standard TT", serif; font-size: 9.5px; letter-spacing: 1.5px; color: #555; text-transform: uppercase; }

.page-foot { margin-top: auto; padding-top: 8px; border-top: 1px solid #000; font-family: "Songti SC", serif; font-size: 10px; letter-spacing: 4px; text-align: center; color: #555; }
"""


def render(story, avatars, plan):
    """支持可变版数。plan 里有哪几个 pageN 字段就渲染哪几版。"""
    group = story.get("group_name", "")
    date = story.get("date", "")

    # 支持任意版数：plan 里每个 pageN 可声明 template
    # 默认按 key 推断（page1=masthead, page2=communal, page3=feature, page4=cast,
    # page5+=feature 兜底，可被 template 字段覆盖）
    template_to_renderer = {
        "masthead": render_page_1,
        "communal": render_page_2,
        "feature": render_page_3,
        "cast": render_page_4,
    }
    default_template = {
        "page1": "masthead", "page2": "communal", "page3": "feature",
        "page4": "cast", "page5": "communal", "page6": "feature",
        "page7": "feature", "page8": "cast",
    }
    pages = []
    page_keys = sorted([k for k in plan.keys() if k.startswith("page")],
                       key=lambda x: int(x[4:]))
    for k in page_keys:
        p = plan[k]
        tpl = p.get("template", default_template.get(k, "feature"))
        fn = template_to_renderer[tpl]
        if tpl in ("communal", "feature", "cast"):
            pages.append(fn(story, avatars, plan, page_key=k))
        else:
            pages.append(fn(story, avatars, plan))
    n = len(pages)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>{h(group)} · {h(date)} 日报（共 {n} 版 · A3）</title>
<style>
{CSS}
</style>
</head>
<body>
{''.join(pages)}
</body>
</html>
"""


def main():
    if len(sys.argv) < 5:
        print("Usage: render_newspaper.py <story.json> <avatars.json> <plan.json> <out.html>")
        sys.exit(1)
    story = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    avatars = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    plan = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    out_path = sys.argv[4]
    html_str = render(story, avatars, plan)
    Path(out_path).write_text(html_str, encoding="utf-8")
    print(f"[OK] Wrote {out_path} ({len(html_str)} bytes)")


if __name__ == "__main__":
    main()
