#!/usr/bin/env python3
"""万涂幻象视频 v4：固定品牌框架 + 内容窗口轮换（WaytoAGI 式骨架，万涂幻象皮肤）。

整片一个恒定框架（每帧都在，跨场景不重置）：
  做旧墨绿纹理底 / 左上「万涂幻象」logo条 / 白描边大内容窗口 /
  窗口下白底黑字贴纸字幕条（随口播逐句切换）/ 下方超大斜体主题字（翠绿强调+粉莓笔刷线）/
  右下超大做旧水印 logo。
场景之间只有窗口内容和字幕条在换，框架不动 → 整体感。

窗口内容类型：word_card(开场大字) / image(满窗图) / diagram(flow|compare|list) /
screenshot(高亮+缓移) / impact(大字弹出) / ending(互动卡) / broll(留空窗，ffmpeg 叠视频)。

配 record_scene.js 逐帧录制（document.getAnimations 拨表，全确定性）。
"""
import os

GREEN = "#22a667"
GREEN_LIGHT = "#a5d6a7"
GREEN_BG = "#e8f5e9"
BERRY = "#e84a6d"
PEACH = "#ffe5ec"
INK = "#161616"
GRAY = "#8a8a8a"
PAPER = "#fbfbf8"

GRAIN = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'>"
         "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3'/>"
         "<feColorMatrix type='saturate' values='0'/></filter>"
         "<rect width='220' height='220' filter='url(%23n)' opacity='0.6'/></svg>")


# Keynote 玻璃语言公共件（2026-06-10 祥瑞定稿：全部卡片苹果风深底玻璃）
GLASS = ("backdrop-filter:blur(20px);background:rgba(255,255,255,.07);"
         "border:1.5px solid rgba(255,255,255,.16);"
         "box-shadow:0 20px 60px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.12)")
BGGLOW = ('<div style="position:absolute;inset:0;background:'
          'radial-gradient(ellipse 700px 500px at 20% 0%,rgba(34,166,103,.28),transparent 60%),'
          'radial-gradient(ellipse 600px 500px at 95% 90%,rgba(232,74,109,.20),transparent 55%),'
          'linear-gradient(170deg,#101412,#0a0d0b)"></div>')
LITE_G, LITE_P = "#7ed8a8", "#ff8fae"

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
BG_PORTRAIT = os.path.join(ASSETS, "bg_portrait.png")
# 标题字体：阿里巴巴普惠体 Heavy（正体重型，祥瑞 2026-06-10 弃用自带斜度的优设标题黑）
# CSS 族名仍叫 YSBTH（历史别名，免改全部模板）
FONT_TITLE_PATH = os.path.join(ASSETS, "fonts", "AlibabaPuHuiTi-Heavy.ttf")



import json as _json

# 品牌配置：~/.config/xiangrui-video/config.json 的 "brand" 段（开源换皮入口）
_BRAND_DEFAULTS = {
    "name": "万涂幻象",            # 左上角 logo 块
    "name_en": "VANTASMA",        # 备用英文名
    "logo": "万涂幻象",            # 右下幽灵水印
    "sig_tag": "VNT-2026",        # 左下等宽签名后缀
    "search_text": "李祥瑞",       # 结尾搜索框打字内容
    "search_hint": "全网搜索 · 同名账号",
    "host": "我是祥瑞",            # 结尾自介（口播文案由分镜自定）
}

def brand_config():
    cfg = dict(_BRAND_DEFAULTS)
    try:
        user = _json.load(open(os.path.expanduser("~/.config/xiangrui-video/config.json")))
        cfg.update(user.get("brand", {}))
    except Exception:
        pass
    return cfg


def layout(W, H):
    """框架几何（窗口内容区给 ffmpeg 叠 broll 用）。
    竖屏按手机平台安全区收纳：顶部 ~150px 被状态栏/顶栏挡、底部 ~330px 被文案/操作区挡，
    信息元素（logo/进度条/窗口/字幕/主题字/tags）全部压进安全区，
    纯装饰（baseline/SIG/幽灵水印）留在底部遮挡区填构图。"""
    if H > W:  # portrait
        safe_top, safe_bottom = int(H * 0.078), int(H * 0.172)
        wx, wy = 32, safe_top + int(H * 0.0595)
        ww, wh = W - 2 * wx, int(H * 0.425)
    else:      # landscape
        safe_top, safe_bottom = 0, 0
        wx, wy = 40, int(H * 0.12)
        ww, wh = int(W * 0.54), int(H * 0.70)
    bw = 5  # 窗口白描边
    cw = (ww - 2 * bw) // 2 * 2   # 偶数对齐，libx264 不收奇数尺寸
    ch = (wh - 2 * bw) // 2 * 2
    return {"wx": wx, "wy": wy, "ww": ww, "wh": wh, "border": bw,
            "cx": wx + bw, "cy": wy + bw, "cw": cw, "ch": ch,
            "safe_top": safe_top, "safe_bottom": safe_bottom}


def content_rect(W, H):
    L = layout(W, H)
    return L["cx"], L["cy"], L["cw"], L["ch"]


def _accent(text):
    """((词)) -> 翠绿强调 + 粉莓笔刷下划线"""
    out, acc = "", False
    i = 0
    while i < len(text):
        if text[i:i + 2] == "((":
            out += '<span class="acc">'
            i += 2
        elif text[i:i + 2] == "))":
            out += "</span>"
            i += 2
        else:
            out += text[i]
            i += 1
    return out


def _frame_css(W, H, dur, L, title_lines=None):
    import re as _re, math as _math
    portrait = H > W
    title_lines = title_lines if isinstance(title_lines, list) else []
    plain = lambda t: _re.sub(r"\(\(|\)\)", "", t)
    maxchars = max((len(plain(t)) for t in title_lines), default=4)
    base_tfs = int(W * (0.10 if portrait else 0.055))
    avail_w = (W - 2 * L["wx"] - 56) if portrait else int(W * 0.5)  # 容器可用宽（留竖条+gap）
    # 标题字号自适应：长标题自动缩小，确保最长行不溢出容器宽（中文字宽≈tfs*1.06 含字距）
    tfs = min(base_tfs, int(avail_w / max(maxchars, 1) / 1.06))
    tfs = max(tfs, int(W * 0.052))  # 字号下限
    cpl = max(1, int(avail_w / (tfs * 1.06)))  # 每行能放的字数
    est_lines = sum(max(1, _math.ceil(len(plain(t)) / cpl)) for t in title_lines) or 1
    bars_top = L["wy"] + L["wh"] + 18
    prog_top = 0  # 进度条贴最顶（祥瑞定：可出安全区）
    toprow_top = L["safe_top"] - 10 if portrait else int(L["wy"] * 0.22)
    title_h = int(tfs * 1.34 * est_lines)  # 按实际渲染行数算高，标签据此避让
    if portrait:
        bars_bottom = bars_top + 104
        zone = (H - L["safe_bottom"]) - bars_bottom
        block = title_h + 40 + 52                     # 标题 + 间隙 + tags 行
        show_top = bars_bottom + max(24, (zone - block) // 2)
        tags_top = show_top + title_h + 40
    else:
        show_top = bars_top + int(H * 0.072)
        tags_top = show_top + title_h + 24
    return f"""
@font-face{{font-family:'YSBTH';src:url('file://{FONT_TITLE_PATH}')}}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden}}
body{{font-family:'PingFang SC','Hiragino Sans GB',sans-serif;position:relative;color:#fff;
  background:
    radial-gradient(ellipse {int(W*1.0)}px {int(H*0.4)}px at 50% -6%, rgba(34,166,103,.16), transparent 62%),
    repeating-linear-gradient(0deg, rgba(255,255,255,.055) 0 1px, transparent 1px 54px),
    repeating-linear-gradient(90deg, rgba(255,255,255,.055) 0 1px, transparent 1px 54px),
    #0c0d0c}}
.grain{{position:absolute;inset:0;background-image:url("{GRAIN}");opacity:.05;mix-blend-mode:overlay;
  pointer-events:none;z-index:90}}
.vig{{position:absolute;inset:0;background:radial-gradient(ellipse 130% 115% at 50% 42%,transparent 62%,rgba(0,0,0,.4));
  pointer-events:none;z-index:80}}
/* 顶部全片进度条（爆款留存标配） */
.prog{{position:absolute;left:0;top:{prog_top}px;height:10px;background:linear-gradient(90deg,{GREEN},{GREEN_LIGHT} 70%,{BERRY});
  border-radius:0 6px 6px 0;z-index:30;box-shadow:0 0 14px rgba(34,166,103,.6)}}
/* 顶部 logo 条：绿块贴纸 + 右侧小字 */
.top{{position:absolute;left:{L['wx']}px;right:{L['wx']}px;top:{toprow_top}px;
  display:flex;align-items:center;justify-content:space-between;z-index:10}}
.top .name{{background:{GREEN};color:#fff;font-family:'YSBTH';font-size:48px;letter-spacing:5px;
  padding:8px 30px 10px;border-radius:12px;box-shadow:0 10px 30px rgba(34,166,103,.35)}}
.top .r{{font-size:26px;letter-spacing:.12em;color:rgba(255,255,255,.72);font-weight:600;
  font-family:ui-monospace,'SF Mono',Menlo,monospace}}
/* 内容窗口：细边微光（科技感，非赛博） */
.win{{position:absolute;left:{L['wx']}px;top:{L['wy']}px;width:{L['ww']}px;height:{L['wh']}px;
  border:{L['border']}px solid rgba(255,255,255,.85);border-radius:22px;overflow:hidden;
  background:{PAPER};box-shadow:0 30px 70px rgba(0,0,0,.6),0 0 28px rgba(34,166,103,.18);z-index:5}}
.win .inner{{position:absolute;inset:0}}
/* HUD 角括号（框架层，永远盖在素材上） */
.cnr{{position:absolute;width:34px;height:34px;border:3px solid rgba(165,214,167,.9);z-index:25}}
.c1{{left:{L['wx']-8}px;top:{L['wy']-8}px;border-right:none;border-bottom:none;border-radius:6px 0 0 0}}
.c2{{right:{L['wx']-8}px;top:{L['wy']-8}px;border-left:none;border-bottom:none;border-radius:0 6px 0 0}}
.c3{{left:{L['wx']-8}px;top:{L['wy']+L['wh']-26}px;border-right:none;border-top:none;border-radius:0 0 0 6px}}
.c4{{right:{L['wx']-8}px;top:{L['wy']+L['wh']-26}px;border-left:none;border-top:none;border-radius:0 0 6px 0}}
/* 扫光（缓慢下行的微绿光带） */
.scan{{position:absolute;left:0;right:0;height:140px;z-index:2;pointer-events:none;
  background:linear-gradient(180deg,transparent,rgba(34,166,103,.06),transparent);
  animation:scanmove 8s linear infinite}}
@keyframes scanmove{{from{{transform:translateY(-140px)}}to{{transform:translateY({H}px)}}}}
/* 左缘刻度 + 等宽字信号标注 */
.ticks{{position:absolute;left:0;top:0;bottom:0;width:12px;z-index:2;
  background:repeating-linear-gradient(180deg,rgba(255,255,255,.14) 0 2px,transparent 2px 54px)}}
.sig{{position:absolute;left:{L['wx']}px;bottom:18px;font-family:ui-monospace,'SF Mono',Menlo,monospace;
  font-size:22px;letter-spacing:.18em;color:rgba(255,255,255,.32);z-index:10}}
.live{{display:inline-block;width:14px;height:14px;border-radius:50%;background:{GREEN};
  margin-right:12px;vertical-align:1px;animation:blink 1.6s ease-in-out infinite}}
@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.25}}}}
/* 字幕：无框大字白字 + 柔投影 + 居中绿短线锚（文字交叉淡换） */
.bars{{position:absolute;left:{L['wx']}px;right:{L['wx']}px;top:{bars_top}px;height:104px;z-index:20}}
.bar-frame{{position:absolute;inset:0}}
.bar-frame::after{{content:'';position:absolute;left:50%;bottom:-6px;transform:translateX(-50%);
  width:64px;height:6px;border-radius:4px;background:{GREEN};opacity:.9}}
.bar-text{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:#fff;font-family:'YSBTH';font-size:52px;letter-spacing:2px;
  text-shadow:0 4px 26px rgba(0,0,0,.85),0 1px 3px rgba(0,0,0,.9);
  white-space:nowrap;overflow:hidden;opacity:0}}
/* 固定主题大字：优设标题黑（自带8°斜），左侧绿竖条 */
.showwrap{{position:absolute;left:{L['wx']}px;right:{L['wx']}px;top:{show_top}px;z-index:10;
  display:flex;gap:30px;align-items:stretch}}
.vbar{{width:20px;background:{GREEN};border-radius:5px;box-shadow:4px 4px 0 rgba(0,0,0,.4)}}
.show{{font-family:'YSBTH';line-height:1.3;font-size:{tfs}px;color:#fff;
  text-shadow:5px 6px 0 rgba(0,0,0,.55);letter-spacing:3px}}
.show .l1{{font-size:{int(tfs*0.8)}px;opacity:.94}}
.show .acc{{color:{GREEN_LIGHT};background:linear-gradient(transparent 76%,{BERRY} 76%,{BERRY} 97%,transparent 97%);
  padding:0 10px}}
/* 标签胶囊行（主题大字下方，#AI #科普 这类领域标签） */
.tags{{position:absolute;left:{L['wx'] + 50}px;right:{L['wx']}px;top:{tags_top}px;
  display:flex;gap:18px;z-index:10}}
.tag{{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:31px;letter-spacing:.06em;
  color:{GREEN_LIGHT};border:2px solid rgba(34,166,103,.55);border-radius:999px;
  padding:9px 28px;background:rgba(34,166,103,.10)}}
/* 底部收边线（解决头重脚轻，给构图一个地基） */
.baseline{{position:absolute;left:{L['wx']}px;right:{L['wx']}px;bottom:62px;height:3px;border-radius:2px;
  background:linear-gradient(90deg,rgba(34,166,103,.65),rgba(255,255,255,.10) 70%,transparent)}}
/* 右下水印：幽灵字（实心超低透明度，贴底出血，不抢画面） */
.logo{{position:absolute;right:20px;bottom:96px;font-size:{int(W*0.175)}px;font-family:'YSBTH';
  color:rgba(165,214,167,.075);letter-spacing:6px;z-index:3;white-space:nowrap}}
/* 通用动画 */
.in{{opacity:0;animation:rise .65s cubic-bezier(.2,.8,.2,1) forwards}}
@keyframes rise{{from{{opacity:0;transform:translateY(46px)}}to{{opacity:1;transform:none}}}}
.pop{{opacity:0;animation:popin .5s cubic-bezier(.3,1.55,.4,1) forwards}}
@keyframes popin{{from{{opacity:0;transform:scale(.6)}}to{{opacity:1;transform:scale(1)}}}}
.slideL{{opacity:0;animation:slL .6s cubic-bezier(.2,.8,.2,1) forwards}}
.slideR{{opacity:0;animation:slR .6s cubic-bezier(.2,.8,.2,1) forwards}}
@keyframes slL{{from{{opacity:0;transform:translateX(-80px)}}to{{opacity:1;transform:none}}}}
@keyframes slR{{from{{opacity:0;transform:translateX(80px)}}to{{opacity:1;transform:none}}}}
@keyframes fadein{{to{{opacity:1}}}}
.kb{{animation:kenburns {max(dur,5):.2f}s linear forwards}}
@keyframes kenburns{{from{{transform:scale(1)}}to{{transform:scale(1.04)}}}}
.dotsP{{position:absolute;inset:0;background-image:radial-gradient(circle,rgba(0,0,0,.08) 2.4px,transparent 2.8px);
  background-size:42px 42px}}
"""


def _bars_html_css(chunks, dur):
    """字幕条：白条本体常驻不动，只有文字交叉淡入淡出（群反馈：白条闪跳难受）。"""
    if not chunks:
        return "", ""
    items, css = "", ""
    for i, (text, t0, t1) in enumerate(chunks):
        p0 = max(0.0, t0 / dur * 100)
        p1 = min(100.0, t1 / dur * 100)
        fade = max(0.6, 15.0 / dur)  # 约 0.15s 的淡入淡出
        pin = min(p0 + fade, p1 - 0.1)
        pout = max(p1 - fade, pin + 0.1)
        css += (f"@keyframes bart{i}{{0%{{opacity:0}}{p0:.2f}%{{opacity:0}}"
                f"{pin:.2f}%{{opacity:1}}{pout:.2f}%{{opacity:1}}"
                f"{p1:.2f}%{{opacity:0}}100%{{opacity:0}}}}\n")
        items += (f'<div class="bar-text" style="animation:bart{i} {dur:.3f}s linear forwards">{text}</div>')
    html = f'<div class="bar-frame">{items}</div>'
    return html, css


# ---------- 窗口内容 ----------

def win_word_card(s, L):
    """开场大字卡（Keynote 玻璃）：光晕深底 + 发光大主词 + 亮绿英文小标"""
    title = s.get("title", "")
    sub = s.get("subtitle", "")
    fs = int(L["cw"] * 0.78 / max(2, len(title)))
    chars = "".join(f'<span style="display:inline-block;opacity:0;'
                    f'animation:chup .55s {0.25 + i*0.08:.2f}s cubic-bezier(.2,.9,.3,1.35) forwards">{c}</span>'
                    for i, c in enumerate(title))
    css = "@keyframes chup{from{opacity:0;transform:translateY(60px)}to{opacity:1;transform:none}}"
    html = f"""{BGGLOW}
<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:44px;z-index:1">
  <div style="font-family:'YSBTH';font-size:{fs}px;color:#fff;letter-spacing:6px;
    text-shadow:0 0 70px rgba(34,166,103,.8),0 0 24px rgba(255,255,255,.35)">{chars}</div>
  <div class="in" style="font-size:{int(L['cw']*0.032)}px;font-weight:600;letter-spacing:.4em;
    color:{LITE_G};animation-delay:.8s">{sub}</div>
  <div class="in" style="animation-delay:1.0s;display:flex;gap:10px;align-items:center">
    <i style="width:64px;height:7px;background:{GREEN};border-radius:9px;display:block;box-shadow:0 0 16px rgba(34,166,103,.8)"></i>
    <i style="width:24px;height:7px;background:{BERRY};border-radius:9px;display:block"></i>
    <i style="width:10px;height:7px;background:rgba(255,255,255,.4);border-radius:9px;display:block"></i>
  </div>
</div>"""
    return html, css


def win_image(s, L):
    """满窗图片 + CSS KenBurns + 玻璃 caption 胶囊 + 来源角标"""
    img = s.get("image", "")
    cap = s.get("caption", "")
    cap_html = ""
    if cap:
        cap_html = (f'<div class="in" style="position:absolute;left:26px;bottom:26px;{GLASS};'
                    f'color:#fff;font-size:{int(L["cw"]*0.042)}px;font-weight:800;padding:16px 34px;'
                    f'border-radius:999px;animation-delay:.7s;z-index:3">{cap}</div>')
    src_html = ""
    if s.get("source"):
        src_html = (f'<div style="position:absolute;right:18px;top:18px;background:rgba(0,0,0,.65);'
                    f'backdrop-filter:blur(8px);color:#ddd;font-size:24px;padding:7px 18px;'
                    f'border-radius:10px;z-index:3">{s["source"]}</div>')
    html = f"""
<img class="kb" src="file://{img}" style="position:absolute;left:0;top:0;width:100%;height:100%;
  object-fit:cover;transform-origin:50% 40%">
{src_html}{cap_html}"""
    return html, ""


PAPER_NOISE = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'>"
               "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/>"
               "<feColorMatrix type='saturate' values='0'/></filter>"
               "<rect width='200' height='200' filter='url(%23n)' opacity='0.12'/></svg>")


def _diagram_shell(kicker, title_html, inner, css=""):
    """图解骨架公共壳（Keynote 玻璃）：光晕深底 + 亮绿 kicker + 发光标题 + 渐变规线。"""
    base_css = f"""
.dgwrap{{position:absolute;left:7%;right:7%;top:7%;bottom:6%;display:flex;flex-direction:column;z-index:1}}
.kicker{{font-family:Menlo,monospace;font-size:26px;letter-spacing:.4em;color:{LITE_G};font-weight:700}}
.dgtitle{{font-size:78px;font-weight:900;color:#fff;line-height:1.12;margin:14px 0 0;
  text-shadow:0 0 50px rgba(34,166,103,.5)}}
.dgtitle em{{font-style:normal;color:{LITE_G}}}
.rule{{height:3px;background:linear-gradient(90deg,rgba(34,166,103,.8),rgba(255,255,255,.1) 70%,transparent);
  margin-top:28px;border-radius:2px}}
.dgbody{{flex:1;display:flex;flex-direction:column;justify-content:center}}
.gcard{{{GLASS};border-radius:26px}}
""" + css
    html = f"""{BGGLOW}
<div class="dgwrap">
  <div class="kicker in" style="animation-delay:.1s">{kicker}</div>
  {title_html}
  <div class="rule in" style="animation-delay:.3s"></div>
  <div class="dgbody">{inner}</div>
</div>"""
    return html, base_css


def win_diagram(s, L):
    """B+C 融合：杂志编辑骨架（超大斜体序号/规线/标签框）+ 手作点缀（微旋转/胶带/马克笔/手绘感）。"""
    d = s.get("diagram", {})
    kind = d.get("kind", "list")
    title = d.get("title", "")
    kicker = d.get("kicker") or f"{(L.get('brand') or brand_config())['name_en']} NOTES"
    title_html = (f'<div class="dgtitle in" style="animation-delay:.18s">{title}</div>') if title else ""

    if kind == "compare":
        Lc, Rc = d.get("left", {}), d.get("right", {})

        def col(c, accent, lite, glow, mark, cls, dly):
            pts = "".join(
                f'<div class="in" style="display:flex;gap:14px;margin-top:22px;align-items:flex-start;'
                f'animation-delay:{dly+0.2+j*0.13:.2f}s">'
                f'<div style="font-size:40px;font-weight:900;color:{lite};line-height:1.3">{mark}</div>'
                f'<div style="font-size:40px;color:rgba(255,255,255,.88);line-height:1.5;font-weight:600">{p}</div></div>'
                for j, p in enumerate(c.get("points", [])))
            return (f'<div class="{cls}" style="flex:1;animation-delay:{dly}s">'
                    f'<div class="gcard" style="position:relative;padding:46px 40px;'
                    f'border-top:3px solid {lite}">'
                    f'<div style="font-size:60px;font-weight:900;color:#fff;'
                    f'text-shadow:0 0 40px {glow}">{c.get("title","")}</div>'
                    f'{pts}</div></div>')
        css = ("@keyframes vsin{from{opacity:0;transform:translate(-50%,-50%) scale(0)}"
               "to{opacity:1;transform:translate(-50%,-50%) scale(1)}}")
        inner = (f'<div style="display:flex;gap:30px;position:relative;margin-top:40px">'
                 f'{col(Lc, GREEN, LITE_G, "rgba(34,166,103,.8)", "✓", "slideL", 0.35)}'
                 f'{col(Rc, BERRY, LITE_P, "rgba(232,74,109,.8)", "✕", "slideR", 0.5)}'
                 f'<div style="position:absolute;left:50%;top:42%;width:88px;height:88px;border-radius:50%;'
                 f'backdrop-filter:blur(16px);background:rgba(255,255,255,.1);'
                 f'border:1.5px solid rgba(255,255,255,.25);color:#fff;display:flex;align-items:center;'
                 f'justify-content:center;font-size:36px;font-weight:900;'
                 f'box-shadow:0 10px 32px rgba(0,0,0,.4);opacity:0;'
                 f'animation:vsin .55s .9s cubic-bezier(.3,1.5,.4,1) forwards;transform:translate(-50%,-50%)">VS</div></div>')
        return _diagram_shell(kicker, title_html, inner, css)

    # flow / list：玻璃行卡 + 发光超大序号 + 玻璃标签
    items = d.get("items", [])
    rows = []
    for i, it in enumerate(items):
        dly = 0.4 + i * 0.3
        last = i == len(items) - 1 and kind == "flow"
        lite = LITE_P if last else LITE_G
        glow = "rgba(232,74,109,.8)" if last else "rgba(34,166,103,.8)"
        tag = it.get("tag", "")
        tag_html = (f'<div style="display:inline-block;font-family:Menlo,monospace;font-size:23px;'
                    f'border:1.5px solid {lite};color:{lite};border-radius:999px;'
                    f'padding:4px 18px;margin-top:12px;font-weight:700">{tag}</div>') if tag else ""
        rows.append(
            f'<div class="slideL" style="animation-delay:{dly:.2f}s;margin-top:{0 if i == 0 else 22}px">'
            f'<div class="gcard" style="display:flex;gap:34px;padding:30px 38px;align-items:center">'
            f'<div style="font-size:100px;font-weight:900;line-height:.9;color:#fff;min-width:128px;'
            f'font-family:\'YSBTH\';text-shadow:0 0 44px {glow}">{i+1:02d}</div>'
            f'<div><div style="font-size:48px;font-weight:900;color:#fff">{it.get("t","")}</div>'
            f'<div style="font-size:30px;color:rgba(255,255,255,.6);margin-top:8px;line-height:1.45;font-weight:600">{it.get("d","")}</div>'
            f'{tag_html}</div></div></div>')
    inner = "".join(rows)
    return _diagram_shell(kicker, title_html, inner)


def win_screenshot(s, L):
    img = s.get("image", "")
    hl = s.get("highlight")
    hl_html = ""
    css = "@keyframes panup{from{transform:translateY(0)}to{transform:translateY(-10%)}}" \
          "@keyframes hldraw{to{transform:scaleX(1)}}"
    if hl:
        x0, y0, x1, y1 = hl
        hl_html = (f'<div style="position:absolute;left:{x0*100}%;top:{y0*100}%;width:{(x1-x0)*100}%;'
                   f'height:{(y1-y0)*100}%;background:rgba(232,74,109,.20);border:5px solid {BERRY};'
                   f'border-radius:12px;transform-origin:left center;transform:scaleX(0);'
                   f'animation:hldraw .45s 1.0s cubic-bezier(.2,.8,.2,1) forwards"></div>')
    html = f"""
<div style="position:absolute;inset:0;overflow:hidden">
  <div style="position:relative;animation:panup 7s 1.2s linear forwards">
    <img src="file://{img}" style="display:block;width:100%">{hl_html}
  </div>
</div>"""
    return html, css


def win_impact(s, L):
    """砸字卡（Keynote 玻璃语言）：光晕底 + 玻璃胶囊引导行 + 发光大字 + 依据小注。"""
    text = s.get("text", "")
    kicker = s.get("kicker", "")
    sub = s.get("sub", "")
    fs = int(L["cw"] * 0.78 / max(2, len(text)))
    css = ("@keyframes smash{0%{opacity:0;transform:scale(2.4)}55%{opacity:1;"
           "transform:scale(.95)}100%{opacity:1;transform:scale(1)}}"
           "@keyframes kin{0%,8%{opacity:0;transform:translateY(-28px)}16%{opacity:1;transform:none}100%{opacity:1}}"
           "@keyframes sin{0%,42%{opacity:0;transform:translateY(28px)}52%{opacity:1;transform:none}100%{opacity:1}}")
    glass = ("backdrop-filter:blur(20px);background:rgba(255,255,255,.07);"
             "border:1.5px solid rgba(255,255,255,.16);border-radius:999px;"
             "box-shadow:0 20px 60px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.12)")
    kicker_html = (f'<div style="{glass};padding:16px 44px;font-size:{int(L["cw"]*0.035)}px;font-weight:700;'
                   f'color:#cfe8d8;opacity:0;animation:kin 6s linear forwards">{kicker}</div>') if kicker else ""
    sub_html = (f'<div style="font-family:Menlo,monospace;font-size:{int(L["cw"]*0.024)}px;'
                f'color:rgba(255,255,255,.45);letter-spacing:.08em;opacity:0;'
                f'animation:sin 6s linear forwards">{sub}</div>') if sub else ""
    html = f"""
<div style="position:absolute;inset:0;background:
  radial-gradient(ellipse 700px 500px at 20% 0%,rgba(34,166,103,.28),transparent 60%),
  radial-gradient(ellipse 600px 500px at 95% 90%,rgba(232,74,109,.20),transparent 55%),
  linear-gradient(170deg,#101412,#0a0d0b)"></div>
<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:52px;z-index:1;padding:0 5%">
  {kicker_html}
  <div class="smash" style="font-family:'YSBTH';font-size:{fs}px;font-weight:900;color:#fff;letter-spacing:4px;
    text-shadow:0 0 70px rgba(34,166,103,.85),0 0 24px rgba(255,255,255,.4);opacity:0;
    animation:smash .5s .15s cubic-bezier(.2,.9,.3,1.2) forwards">{text}</div>
  {sub_html}
</div>"""
    return html, css


def win_ending(s, L):
    """结尾卡：黑底格子延续 + 大字问题 + 绿色 CTA 按钮 + 小落款（全部摆正）。"""
    text = s.get("text", "评论区聊聊")
    question = s.get("question", "")
    _b = L.get("brand") or brand_config()
    host = s.get("host", _b["host"])
    search_text = s.get("search_text", _b["search_text"])
    search_hint = s.get("search_hint", _b["search_hint"])
    search_spans = "".join(
        f'<span style="opacity:0;animation:typein .01s {1.3 + i * 0.25:.2f}s forwards">{c}</span>'
        for i, c in enumerate(search_text))
    css = ("@keyframes ctapulse{from{box-shadow:0 10px 36px rgba(34,166,103,.35)}"
           "to{box-shadow:0 14px 60px rgba(34,166,103,.6)}}"
           "@keyframes typein{to{opacity:1}}"
           "@keyframes blinkc{0%,49%{opacity:1}50%,100%{opacity:0}}")
    q_html = ""
    if question:
        qfs = int(L["cw"] * 0.8 / max(4, len(question)))
        # 问题文字 + 下方居中绿短横（明确间距，不与文字重合）
        q_html = (f'<div class="in" style="display:flex;flex-direction:column;align-items:center;'
                  f'gap:24px;animation-delay:.3s">'
                  f'<div style="font-family:\'YSBTH\';font-size:{qfs}px;color:#fff;'
                  f'letter-spacing:3px;text-align:center;line-height:1.3">{question}</div>'
                  f'<div style="width:76px;height:7px;background:{GREEN};border-radius:4px;'
                  f'box-shadow:0 0 16px rgba(34,166,103,.5)"></div></div>')
    html = f"""
<div style="position:absolute;inset:0;background:
  radial-gradient(ellipse 700px 500px at 20% 0%,rgba(34,166,103,.28),transparent 60%),
  radial-gradient(ellipse 600px 500px at 95% 90%,rgba(232,74,109,.20),transparent 55%),
  linear-gradient(170deg,#101412,#0a0d0b)"></div>
<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:44px;padding:0 6%">
  <div class="in" style="font-size:{int(L['cw']*0.026)}px;letter-spacing:.5em;color:{GREEN_LIGHT};
    font-family:ui-monospace,Menlo,monospace;animation-delay:.1s">ONE MORE THING</div>
  {q_html}
  <div class="pop" style="animation-delay:.7s">
    <div style="background:{GREEN};color:#fff;font-size:{int(L['cw']*0.05)}px;font-weight:800;
      padding:24px 64px;border-radius:999px;animation:ctapulse 1.6s ease-in-out infinite alternate">{text}</div>
  </div>
  <div class="in" style="animation-delay:1.0s;display:flex;flex-direction:column;align-items:center;gap:18px">
    <div style="{GLASS};border-radius:999px;padding:20px 44px;display:flex;align-items:center;gap:20px;
      min-width:{int(L['cw']*0.6)}px">
      <span style="font-size:{int(L['cw']*0.042)}px">🔍</span>
      <span style="font-family:'YSBTH';font-size:{int(L['cw']*0.05)}px;color:#fff;letter-spacing:4px">{search_spans}</span>
      <span style="display:inline-block;width:5px;height:{int(L['cw']*0.05)}px;background:{LITE_G};
        animation:blinkc 1s step-end infinite"></span>
    </div>
    <div style="font-family:Menlo,monospace;font-size:{int(L['cw']*0.023)}px;letter-spacing:.3em;
      color:rgba(255,255,255,.5)">{search_hint}</div>
  </div>
  <div class="in" style="font-size:{int(L['cw']*0.022)}px;color:rgba(255,255,255,.4);
    letter-spacing:.2em;animation-delay:1.2s">{_b["name"]}出品</div>
</div>"""
    return html, css


def win_media(s, L):
    """多素材轮换窗：留空黑底，媒体由 ffmpeg 按 content_rect 叠进来；
    来源角标按 shot 时间轴显隐（_shots_timed = [(source, t0, t1, dur)]）。"""
    chips, css = "", ""
    for i, (src, t0, t1, dur) in enumerate(s.get("_shots_timed", [])):
        if not src:
            continue
        p0 = max(0.0, t0 / dur * 100)
        p1 = min(100.0, t1 / dur * 100)
        css += (f"@keyframes chip{i}{{0%{{opacity:0}}{p0:.2f}%{{opacity:0}}"
                f"{min(p0+1.5, p1):.2f}%{{opacity:1}}{p1:.2f}%{{opacity:1}}"
                f"{min(p1+0.4,100):.2f}%{{opacity:0}}100%{{opacity:0}}}}\n")
        chips += (f'<div style="position:absolute;right:18px;top:18px;background:rgba(0,0,0,.68);'
                  f'color:#ddd;font-size:25px;padding:7px 18px;border-radius:8px;z-index:3;'
                  f'opacity:0;animation:chip{i} {dur:.3f}s linear forwards">{src}</div>')
    cap_html = ""
    if s.get("caption"):
        cap_html = (f'<div class="in" style="position:absolute;left:24px;bottom:24px;{GLASS};'
                    f'color:#fff;font-size:{int(L["cw"]*0.042)}px;font-weight:800;padding:15px 32px;'
                    f'border-radius:999px;z-index:4;animation-delay:.6s">{s["caption"]}</div>')
    # 钩子大字：砸在素材上层（开场 hook 场景用，3 秒冲突原则）
    hook_html = ""
    if s.get("hook_text"):
        ht = s["hook_text"]
        hfs = int(L["cw"] * 0.80 / max(2, len(ht)))
        css += ("@keyframes bandin{0%{opacity:0;transform:translateY(-50%) scaleY(.2)}"
                "100%{opacity:1;transform:translateY(-50%) scaleY(1)}}\n"
                "@keyframes hooksmash{0%{opacity:0;transform:scale(1.8)}"
                "60%{opacity:1;transform:scale(.97)}100%{opacity:1;transform:scale(1)}}\n")
        hook_html = (
            f'<div style="position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);'
            f'z-index:5;pointer-events:none;opacity:0;animation:bandin .35s .2s ease-out forwards">'
            f'<div style="background:rgba(8,10,9,.58);backdrop-filter:blur(14px);'
            f'border-top:1.5px solid rgba(255,255,255,.22);border-bottom:1.5px solid rgba(255,255,255,.22);'
            f'padding:{int(L["cw"]*0.045)}px 0;display:flex;justify-content:center">'
            f'<div data-anim="smash" style="font-family:\'YSBTH\';font-size:{hfs}px;color:#fff;letter-spacing:8px;'
            f'text-shadow:0 0 60px rgba(34,166,103,.8),0 0 20px rgba(255,255,255,.35);opacity:0;'
            f'animation:hooksmash .5s .35s cubic-bezier(.2,.9,.3,1.2) forwards">{ht}</div></div></div>')
    # 窗内不铺底色：媒体由 ffmpeg 垫在框架下层，这里只留角标/caption/钩子字浮在上面
    return f'{chips}{cap_html}{hook_html}', css


def win_demo(s, L):
    """定制演示动画场景：AI 按本片内容现写的 HTML 动画（打破千篇一律的核心武器）。
    字段：demo_html（窗口内 body 片段）、demo_css（keyframes 等）、demo_bg=paper|dark。
    可在 demo_js 里用 rough.js（手绘草图，去AI味）/ echarts（数据图）—— 已本地引入。"""
    # 统一苹果风深底（demo_bg 参数保留但 paper 也走深色光晕）
    return f'{BGGLOW}{s.get("demo_html", "")}', s.get("demo_css", "")


def win_editorial(s, L):
    """编辑杂志式版面（去 AI 味核心，祥瑞 2026-06-11 定）：左对齐大标题 + 超大编号列表
    + 细线分隔 + 竖网格 + 英文眉头，无玻璃卡无 emoji，像专业杂志版面不像 AI 铺的卡。
    字段：kicker(英文眉头) / title(大标题,含((accent))) / idx_label(右上标注) /
    items=[{no,cap,tag,desc}]（编号列表，3-4 条）。元素带 .in 由 GSAP 接管错落入场。"""
    cw, ch = L["cw"], L["ch"]
    kicker = s.get("kicker", "")
    title = _accent(s.get("title", ""))
    idx_label = s.get("idx_label", "")
    items = s.get("items", [])
    rows = ""
    for i, it in enumerate(items):
        on = " on" if i == 0 else ""
        tag = f'<span class="etag">{it["tag"]}</span>' if it.get("tag") else ""
        desc = f'<div class="edesc">{it.get("desc", "")}</div>' if it.get("desc") else ""
        rows += (f'<div class="erow{on} in" style="animation-delay:{0.3 + i * 0.12:.2f}s">'
                 f'<div class="eno">{it.get("no", "")}</div>'
                 f'<div><span class="ecap">{_accent(it.get("cap", ""))}</span>{tag}{desc}</div></div>')
    css = (
        f".egrid{{position:absolute;inset:0;background:repeating-linear-gradient(90deg,"
        f"rgba(255,255,255,.04) 0 1px,transparent 1px {int(cw * 0.083)}px);opacity:.55}}"
        f".ekick{{position:absolute;left:{int(cw * 0.05)}px;top:{int(ch * 0.055)}px;"
        f"font:600 {int(cw * 0.019)}px ui-monospace,Menlo;letter-spacing:.3em;color:{GREEN_LIGHT}}}"
        f".eh1{{position:absolute;left:{int(cw * 0.046)}px;top:{int(ch * 0.088)}px;"
        f"font-family:'YSBTH';font-size:{int(cw * 0.082)}px;line-height:.98}}"
        f".eidx{{position:absolute;right:{int(cw * 0.055)}px;top:{int(ch * 0.072)}px;"
        f"font-family:'YSBTH';font-size:{int(cw * 0.028)}px;color:rgba(255,255,255,.22);letter-spacing:.1em}}"
        f".erows{{position:absolute;left:{int(cw * 0.046)}px;right:{int(cw * 0.046)}px;top:{int(ch * 0.37)}px}}"
        f".erow{{display:grid;grid-template-columns:{int(cw * 0.13)}px 1fr;align-items:baseline;"
        f"gap:{int(cw * 0.024)}px;padding:{int(ch * 0.03)}px 0;border-top:1.5px solid rgba(255,255,255,.12)}}"
        f".erow:last-child{{border-bottom:1.5px solid rgba(255,255,255,.12)}}"
        f".eno{{font-family:'YSBTH';font-size:{int(cw * 0.072)}px;line-height:.8;color:rgba(255,255,255,.16)}}"
        f".erow.on .eno{{color:{GREEN}}}"
        f".ecap{{font-family:'YSBTH';font-size:{int(cw * 0.045)}px;letter-spacing:1px}}"
        f".edesc{{font-size:{int(cw * 0.024)}px;color:rgba(255,255,255,.5);margin-top:8px}}"
        f".etag{{display:inline-block;font:600 {int(cw * 0.017)}px ui-monospace,Menlo;letter-spacing:.15em;"
        f"color:{GREEN_LIGHT};border:1.5px solid rgba(34,166,103,.5);border-radius:6px;"
        f"padding:3px 12px;margin-left:14px;vertical-align:middle}}"
    )
    html = (f'{BGGLOW}<div class="egrid"></div>'
            f'<div class="ekick">{kicker}</div>'
            f'<div class="eh1">{title}</div>'
            f'<div class="eidx">{idx_label}</div>'
            f'<div class="erows">{rows}</div>')
    return html, css


WIN_BUILDERS = {
    "demo": win_demo,
    "editorial": win_editorial,
    "concept_card": win_word_card,
    "whiteboard": win_image,
    "diagram": win_diagram,
    "screenshot": win_screenshot,
    "impact_text": win_impact,
    "ending": win_ending,
    # 实拍素材类（图/视频混排多 shot）统一走 media 空窗 + ffmpeg 叠加
    "media": win_media,
    "image_full": win_media,
    "broll": win_media,
}


MEDIA_TYPES = {"media", "image_full", "broll"}


def build_html(scene, meta, W, H, workdir, idx, dur, chunks=None):
    """场景 -> 固定框架动画 HTML。chunks=[(text,t0,t1)] 字幕条时间轴。
    媒体场景出"透明窗洞"框架（视频由 ffmpeg 垫底，框架带洞盖上层，角标/caption 不被盖）。"""
    L = layout(W, H)
    brand = brand_config()
    brand.update(meta.get("brand") or {})
    L["brand"] = brand
    inner, extra_css = WIN_BUILDERS[scene["type"]](scene, L)
    bars_html, bars_css = _bars_html_css(chunks or [], dur)
    title_lines = meta.get("show_title") or []
    if len(title_lines) >= 2:
        show = (f'<span class="l1">{_accent(title_lines[0])}</span><br>'
                + "<br>".join(_accent(t) for t in title_lines[1:]))
    else:
        show = "<br>".join(_accent(t) for t in title_lines)
    logo = meta.get("logo") or brand["logo"]
    vol = meta.get("vol", "VOL.01")
    tags_html = "".join(f'<div class="tag">#{t}</div>' for t in (meta.get("tags") or [])[:4])
    tags_html = f'<div class="tags">{tags_html}</div>' if tags_html else ""
    # 表情包弹出：punchline 处在窗口内弹梗图（框架层，盖在素材/卡片上）
    memes_html, memes_css = "", ""
    mw = int(L["cw"] * 0.30)
    pos_map = {"br": f"right:{L['wx']+30}px;top:{L['wy']+L['wh']-mw-30}px",
               "bl": f"left:{L['wx']+30}px;top:{L['wy']+L['wh']-mw-30}px",
               "tr": f"right:{L['wx']+30}px;top:{L['wy']+30}px",
               "tl": f"left:{L['wx']+30}px;top:{L['wy']+30}px"}
    for mi, mm in enumerate(scene.get("memes") or []):
        t0 = float(mm.get("at", 1.0))
        t1 = min(t0 + float(mm.get("dur", 1.8)), dur - 0.1)
        mp0, mp1 = t0 / dur * 100, t1 / dur * 100
        pin = min(mp0 + max(0.8, 8.0 / dur), mp1 - 0.1)
        pout = max(mp1 - max(0.6, 5.0 / dur), pin + 0.1)
        memes_css += (f"@keyframes meme{mi}{{0%{{opacity:0;transform:scale(.3)}}"
                      f"{mp0:.2f}%{{opacity:0;transform:scale(.3)}}"
                      f"{pin:.2f}%{{opacity:1;transform:scale(1)}}"
                      f"{pout:.2f}%{{opacity:1;transform:scale(1)}}"
                      f"{mp1:.2f}%{{opacity:0;transform:scale(.6)}}100%{{opacity:0}}}}\n")
        memes_html += (f'<div style="position:absolute;{pos_map.get(mm.get("pos", "br"), pos_map["br"])};'
                       f'width:{mw}px;z-index:26;opacity:0;'
                       f'animation:meme{mi} {dur:.3f}s cubic-bezier(.3,1.4,.4,1) forwards">'
                       f'<img src="file://{mm["src"]}" style="display:block;width:100%;border-radius:18px;'
                       f'border:5px solid #fff;box-shadow:0 14px 36px rgba(0,0,0,.5)"></div>')
    # 全片进度条：本场景从 p0% 匀速涨到 p1%
    p0, p1 = meta.get("prog", (0.0, 1.0))
    prog_css = (f"@keyframes progw{{from{{width:{p0*100:.2f}%}}to{{width:{p1*100:.2f}%}}}}\n"
                f".prog{{animation:progw {dur:.3f}s linear forwards}}\n")
    hole = scene["type"] in MEDIA_TYPES
    hole_css, bg_div = "", ""
    if hole:
        hole_css = f"""
body{{background:transparent !important}}
.bgimg{{position:absolute;inset:0;background:
  radial-gradient(ellipse {int(W*1.0)}px {int(H*0.4)}px at 50% -6%, rgba(34,166,103,.16), transparent 62%),
  repeating-linear-gradient(0deg, rgba(255,255,255,.055) 0 1px, transparent 1px 54px),
  repeating-linear-gradient(90deg, rgba(255,255,255,.055) 0 1px, transparent 1px 54px),
  #0c0d0c}}
.win{{background:transparent !important}}
.holed{{-webkit-mask-image:linear-gradient(#fff 0 0),linear-gradient(#fff 0 0);
  -webkit-mask-size:100% 100%,{L['cw']}px {L['ch']}px;
  -webkit-mask-position:0 0,{L['cx']}px {L['cy']}px;
  -webkit-mask-repeat:no-repeat;-webkit-mask-composite:xor;mask-composite:exclude}}
"""
        bg_div = '<div class="bgimg holed"></div>'
    vig_cls = "vig holed" if hole else "vig"
    grain_cls = "grain holed" if hole else "grain"
    # bare 模式（剪映分层导出用）：只渲染背景+窗口内容+HUD框+扫光刻度，
    # 关闭所有文字全局元素（logo/期数/字幕/标题/标签/水印/进度条），它们交给剪映可编辑轨道
    bare = meta.get("bare", False)
    if bare:
        top_block = bars_block = show_block = tags_block = ""
        baseline_block = sig_block = logo_block = prog_block = ""
    else:
        top_block = (f'<div class="top"><div class="name">{brand["name"]}</div>'
                     f'<div class="r"><span class="live"></span>{vol}</div></div>')
        bars_block = f'<div class="bars">{bars_html}</div>'
        show_block = f'<div class="showwrap"><div class="vbar"></div><div class="show">{show}</div></div>'
        tags_block = tags_html
        baseline_block = '<div class="baseline"></div>'
        sig_block = f'<div class="sig">SIG.{idx:02d} / {brand["sig_tag"]}</div>'
        logo_block = f'<div class="logo">{logo}</div>'
        prog_block = '<div class="prog"></div>'
    # GSAP 统一接管：所有场景引入 gsap，自动把框架标准动画类(.in/.pop/.slideL/.slideR/.smash)
    # 从 CSS 缓动升级为 GSAP 弹性缓动（back/power），保留各元素原有 animation-delay 时序。
    # 录制器逐帧 seek globalTimeline，确定性。demo 场景的 demo_js 在接管之后追加执行。
    gsap_path = os.path.join(ASSETS, "vendor", "gsap.min.js")
    demo_js = scene.get("demo_js") or ""
    takeover = """
(function(){
  if(!window.gsap)return;
  var M={in:{y:46,opacity:0,ease:'power3.out',d:.62},
         pop:{scale:.55,opacity:0,ease:'back.out(2)',d:.52},
         slideL:{x:-80,opacity:0,ease:'power3.out',d:.6},
         slideR:{x:80,opacity:0,ease:'power3.out',d:.6},
         smash:{scale:1.7,opacity:0,ease:'back.out(1.6)',d:.5}};
  document.querySelectorAll('.in,.pop,.slideL,.slideR,.smash,[data-anim]').forEach(function(el){
    var delay=parseFloat(getComputedStyle(el).animationDelay)||0;
    el.style.animation='none';
    el.style.opacity='1';  // 恢复最终态：元素 inline/class 写了 opacity:0（本靠CSS动画到1），禁用动画后要还原，否则 GSAP from 0→0 永不可见
    var k=el.dataset.anim||(el.classList.contains('pop')?'pop':
          el.classList.contains('slideL')?'slideL':
          el.classList.contains('slideR')?'slideR':
          el.classList.contains('smash')?'smash':'in');
    var m=M[k]||M.in, v={duration:m.d,ease:m.ease,delay:delay};
    for(var p in m){if(p!=='ease'&&p!=='d')v[p]=m[p];}
    gsap.from(el,v);
  });
})();
"""
    # 按需引入开源库（demo_js 用到才引）：rough.js 手绘 / echarts 数据图（设计语言三支柱）
    libs = f'<script src="file://{gsap_path}"></script>\n'
    if "rough" in demo_js:
        libs += f'<script src="file://{os.path.join(ASSETS, "vendor", "rough.min.js")}"></script>\n'
    if "echarts" in demo_js:
        libs += f'<script src="file://{os.path.join(ASSETS, "vendor", "echarts.min.js")}"></script>\n'
    gsap_block = libs + f'<script>{takeover}\n{demo_js}</script>'
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_frame_css(W, H, dur, L, title_lines)}{extra_css}{bars_css}{hole_css}{prog_css}{memes_css}</style></head>
<body>
{bg_div}<div class="scan"></div><div class="ticks"></div>{prog_block}
{top_block}
<div class="win"><div class="inner">{inner}</div></div>
<div class="cnr c1"></div><div class="cnr c2"></div><div class="cnr c3"></div><div class="cnr c4"></div>
{memes_html}
{bars_block}
{show_block}
{tags_block}
{baseline_block}
{sig_block}
{logo_block}
<div class="{vig_cls}"></div><div class="{grain_cls}"></div>
{gsap_block}
</body></html>"""
    temp = os.path.join(workdir, "temp")
    os.makedirs(temp, exist_ok=True)
    hpath = os.path.join(temp, f"scene_{idx:03d}.html")
    with open(hpath, "w", encoding="utf-8") as f:
        f.write(html)
    return hpath


if __name__ == "__main__":
    out = os.path.expanduser("~/Projects/xiangrui-videos/_htmltest")
    meta = {"show_title": ["1分钟看懂", "记忆的((Bug))"]}
    demo = [
        ({"type": "concept_card", "title": "曼德拉效应", "subtitle": "THE MANDELA EFFECT"},
         [("你有没有想过", 0.3, 2.2), ("你的记忆一直在骗你", 2.2, 4.5)]),
        ({"type": "diagram", "diagram": {"kind": "flow", "title": "记忆的三关",
          "items": [{"t": "编码", "d": "看到的瞬间就开始失真"},
                    {"t": "存储", "d": "睡一觉细节被改写"},
                    {"t": "提取", "d": "每回忆一次就重写一次"}]}},
         [("记忆要过三关", 0.3, 2.5), ("每一关都在改你的数据", 2.5, 5.5)]),
        ({"type": "impact_text", "text": "越回忆越失真"},
         [("越回忆 越失真", 0.2, 3.0)]),
    ]
    for i, (s, ch) in enumerate(demo):
        p = build_html(s, meta, 1080, 1920, out, i, 6.0, ch)
        print("ok", p)
