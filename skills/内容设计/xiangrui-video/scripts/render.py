#!/usr/bin/env python3
"""万涂幻象知识视频渲染器：storyboard JSON -> 成片 MP4。

用法:
  python3 render.py --storyboard sb.json --workdir WORK [--out final.mp4] [--keep-temp]

前置: 先跑 tts.py --storyboard 生成 WORK/audio/manifest.json（没跑会自动补跑）。
schema 见 references/storyboard-schema.md。
"""
import argparse
import json
import os
import re
import subprocess
import sys

FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
if not os.path.exists(FFMPEG):
    FFMPEG, FFPROBE = "ffmpeg", "ffprobe"

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX_DIR = os.path.join(SKILL_DIR, "assets", "sfx")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import html_still  # noqa: E402  万涂幻象动画场景（HTML+CSS 动画）

HTML_TYPES = {"concept_card", "whiteboard", "diagram", "screenshot",
              "impact_text", "ending", "demo", "editorial", "logo_card"}
MEDIA_TYPES = {"media", "image_full", "broll"}
RECORD_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "record_scene.js")

PAD = 0.35          # 每句口播后的呼吸间隙
MIN_SCENE = 1.6     # 场景最短时长
FPS = 30

# ---------- 基础工具 ----------

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败:\n{' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r


def probe_duration(path):
    r = subprocess.run([FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())


# ---------- 字幕切分 ----------

def split_subs(text, max_chars):
    """按标点切口播为字幕短句，过长再硬切，去尾部标点。"""
    parts = re.split(r"([，。！？；…,!?;]|——)", text)
    chunks, buf = [], ""
    for p in parts:
        if re.fullmatch(r"[，。！？；…,!?;]|——", p or ""):
            if buf.strip():
                chunks.append(buf.strip())
            buf = ""
        else:
            buf += p or ""
    if buf.strip():
        chunks.append(buf.strip())
    out = []
    for c in chunks:
        while len(c) > max_chars:
            cut = max_chars
            # 不拦腰砍英文单词/数字（"token"被切成 tok+en 的事故）
            while cut > 6 and c[cut - 1].isascii() and c[cut - 1].isalnum() \
                    and cut < len(c) and c[cut].isascii() and c[cut].isalnum():
                cut -= 1
            out.append(c[:cut])
            c = c[cut:]
        if c:
            out.append(c)
    return out or ([text] if text else [])


_WHISPER_MODEL = None


def whisper_align(mp3, chunks):
    """用本地 whisper 词级时间戳精对齐字幕（祥瑞反馈：比例估时会出现'话说完字幕还赖着'）。
    只取时间不取文本（TTS 文本是 ground truth）。失败回退原比例 chunks。"""
    global _WHISPER_MODEL
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import whisper
        if _WHISPER_MODEL is None:
            _WHISPER_MODEL = whisper.load_model("base")
        r = _WHISPER_MODEL.transcribe(mp3, word_timestamps=True,
                                      language="zh", fp16=False)
        words = [w for s in r["segments"] for w in s["words"]]
        if len(words) < 3:
            return chunks
        w_total = sum(len(w["word"].strip()) for w in words)
        o_total = sum(len(c[0]) for c in chunks) or 1
        aligned, cum_o, cum_w, wi = [], 0, 0, 0
        t_prev = max(0.05, float(words[0]["start"]))
        for text, _, _ in chunks:
            cum_o += len(text)
            target = cum_o / o_total * w_total
            while wi < len(words) - 1 and cum_w + len(words[wi]["word"].strip()) < target:
                cum_w += len(words[wi]["word"].strip())
                wi += 1
            cum_w += len(words[wi]["word"].strip())
            t_end = float(words[wi]["end"])
            wi = min(wi + 1, len(words) - 1)
            if t_end <= t_prev:
                t_end = t_prev + 0.3
            aligned.append((text, t_prev, t_end))
            t_prev = float(words[wi]["start"]) if wi < len(words) else t_end
            t_prev = max(t_prev, t_end)
        return aligned
    except Exception as e:
        print(f"[align] whisper 对齐失败回退比例: {e}", file=sys.stderr)
        return chunks


# ---------- 场景动画 ----------

def make_chunks(narration, ndur, max_chars):
    """口播 -> 字幕条时间轴 [(text, t0, t1)]。
    句读规则（祥瑞 2026-06-10 定）：逗号/句号等 = 一条字幕的边界，说哪句显示哪句，
    不合并短句（白条闪跳已由"框体常驻文字淡换"解决）；顿号（、）不切，列举完整展示。
    时间先按字数比例铺，再由 whisper_align 用真实语音时间戳精校。"""
    if not narration or ndur <= 0:
        return []
    parts = split_subs(narration, max_chars)
    total = sum(len(p) for p in parts) or 1
    chunks, cur = [], 0.05
    for p in parts:
        d = ndur * len(p) / total
        chunks.append((p, cur, cur + d))
        cur += d
    return chunks


def record_frames(scene, meta, chunks, dur, W, H, workdir, idx):
    """动画 HTML -> 逐帧 PNG 序列（带 alpha），返回帧目录。
    headless Chrome 偶发 CDP 断连（机器负载/瞬时抽风），自动重试 3 次——
    2026-06-12 实测连续两次整片渲染分别在第 3/5 镜被瞬时崩溃打断的教训。"""
    import shutil
    import time
    html = html_still.build_html(scene, meta, W, H, workdir, idx, dur, chunks)
    fdir = os.path.join(workdir, "temp", f"frames_{idx:03d}")
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    last_err = None
    for attempt in range(3):
        try:
            run([node, RECORD_JS, html, fdir, str(W), str(H), f"{dur:.3f}", str(FPS)])
            return fdir
        except RuntimeError as e:
            last_err = e
            shutil.rmtree(fdir, ignore_errors=True)
            print(f"[retry] scene {idx} 录制失败(第{attempt + 1}次)，3s 后重试...",
                  file=sys.stderr)
            time.sleep(3)
    raise last_err


def record_html_scene(scene, meta, chunks, dur, W, H, workdir, idx):
    """动画 HTML（固定品牌框架）-> 逐帧录制 -> 无声视频。"""
    import shutil
    out = os.path.join(workdir, "temp", f"vis_{idx:03d}.mp4")
    fdir = record_frames(scene, meta, chunks, dur, W, H, workdir, idx)
    run([FFMPEG, "-y", "-v", "error", "-framerate", str(FPS),
         "-i", os.path.join(fdir, "f_%05d.png"),
         "-vf", "format=yuv420p", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", out])
    shutil.rmtree(fdir, ignore_errors=True)
    return out


def normalize_shots(scene, dur):
    """media/image_full/broll 场景 -> shots 列表 + 时间轴。
    shots: [{"media": "image"|"video", "src", "video_start", "source"}]
    旧字段 image/video 自动转单 shot。时长按 weight（默认均分）。"""
    shots = scene.get("shots")
    if not shots:
        if scene.get("video"):
            shots = [{"media": "video", "src": scene["video"],
                      "video_start": scene.get("video_start", 0),
                      "fit": scene.get("fit", "cover"),
                      "source": scene.get("source", "")}]
        else:
            shots = [{"media": "image", "src": scene["image"],
                      "fit": scene.get("fit", "cover"),
                      "source": scene.get("source", "")}]
    total_w = sum(s.get("weight", 1) for s in shots)
    timed, cur = [], 0.0
    for s in shots:
        seg = dur * s.get("weight", 1) / total_w
        timed.append((s, cur, cur + seg))
        cur += seg
    scene["_shots_timed"] = [(s.get("source", ""), t0, t1, dur) for s, t0, t1 in timed]
    return timed


def render_media_scene(scene, meta, chunks, dur, W, H, workdir, idx):
    """多素材轮换场景：逐 shot 出窗口尺寸片段（图=缓推，视频=裁切）→ 拼接垫底
    → 透明窗洞框架（PNG 序列带 alpha）盖上层，窗内角标/caption 不被素材盖住。"""
    import shutil
    timed = normalize_shots(scene, dur)
    fdir = record_frames(scene, meta, chunks, dur, W, H, workdir, idx)
    cx, cy, cw, ch = html_still.content_rect(W, H)
    parts = []
    for j, (sh, t0, t1) in enumerate(timed):
        seg = t1 - t0
        part = os.path.join(workdir, "temp", f"shot_{idx:03d}_{j}.mp4")
        # 画面适配窗口：默认 cover 填满裁切（祥瑞 2026-06-11 确认这样最好，干净不突兀）。
        # 极少数"必须看清整张内容"的素材可标 "fit":"contain"（完整缩放+模糊铺底），一般不用。
        if sh.get("fit") == "card":
            # 文档/截图嵌入卡（祥瑞 2026-06-12 二订：圆角版）：缩 84% + 米白细边 +
            # geq 圆角 alpha + 品牌深底 overlay——文档素材像展品嵌着，不裸铺不方角
            R = 26
            # 自适应卡装(祥瑞 2026-06-12 四订):宽用足 94%;高度上限 70% 且中心上移 42px——
            # 给顶部章节条(58px)和底部字幕条(H-168 起)各留呼吸,卡不贴条
            contain = (
                f"scale={int(cw*0.94)}:{int(ch*0.70)}:force_original_aspect_ratio=decrease,"
                f"pad=iw+16:ih+16:8:8:color=0xf2efe4,format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='if(gt(abs(W/2-X),W/2-{R})*gt(abs(H/2-Y),H/2-{R}),"
                f"if(lte(hypot({R}-(W/2-abs(W/2-X)),{R}-(H/2-abs(H/2-Y))),{R}),255,0),255)'[cardfg];"
                f"color=c=0x141815:s={cw}x{ch}:r={FPS}[cardbg];"
                f"[cardbg][cardfg]overlay=(W-w)/2:(H-h)/2-42:format=auto,fps={FPS}")
        elif sh.get("fit", "cover") == "contain":
            contain = (f"split=2[bg][fg];"
                       f"[bg]scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},"
                       f"gblur=sigma=24,eq=brightness=-0.12[bgb];"
                       f"[fg]scale={cw}:{ch}:force_original_aspect_ratio=decrease[fgs];"
                       f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,fps={FPS}")
        else:
            contain = (f"scale={cw}:{ch}:force_original_aspect_ratio=increase,"
                       f"crop={cw}:{ch},fps={FPS}")
        if sh["media"] == "image":
            # 图片静置+淡入：不加 zoompan（像素抖动，祥瑞 2026-06-10 否决"晃动放大"效果）
            fc = f"[0:v]{contain},fade=t=in:d=0.22,format=yuv420p[out]"
            run([FFMPEG, "-y", "-v", "error", "-loop", "1", "-t", f"{seg:.3f}",
                 "-i", sh["src"],
                 "-filter_complex", fc, "-map", "[out]", "-t", f"{seg:.3f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", part])
        else:
            ss = sh.get("video_start", 0)
            avail = max(0.1, probe_duration(sh["src"]) - ss)
            fc = f"[0:v]{contain}"
            if avail < seg:
                fc += f",tpad=stop_mode=clone:stop_duration={seg - avail + 0.5:.3f}"
            # 视频 shot 直切不加 fade（黑闪转场观感差，切换节奏感由 tick 音效给）
            fc += ",format=yuv420p[out]"
            run([FFMPEG, "-y", "-v", "error", "-ss", str(ss), "-i", sh["src"],
                 "-filter_complex", fc, "-map", "[out]", "-t", f"{seg:.3f}",
                 "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", part])
        parts.append(part)
    clist = os.path.join(workdir, "temp", f"shots_{idx:03d}.txt")
    with open(clist, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    shots_clip = os.path.join(workdir, "temp", f"shotsclip_{idx:03d}.mp4")
    run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", clist, "-c", "copy", shots_clip])
    out = os.path.join(workdir, "temp", f"vis_{idx:03d}b.mp4")
    # 黑底 → 素材垫到窗位 → 带洞框架盖顶
    run([FFMPEG, "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=0x0a0a0a:s={W}x{H}:r={FPS}",
         "-i", shots_clip,
         "-framerate", str(FPS), "-i", os.path.join(fdir, "f_%05d.png"),
         "-filter_complex",
         f"[0:v][1:v]overlay={cx}:{cy}:eof_action=repeat[base];"
         f"[base][2:v]overlay=0:0,format=yuv420p[out]",
         "-map", "[out]", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", out])
    shutil.rmtree(fdir, ignore_errors=True)
    return out


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out")
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--skip-lint", action="store_true",
                    help="跳过图主文辅质量闸门（仅排查用，正常出片别用）")
    args = ap.parse_args()

    sb = json.load(open(args.storyboard))

    # 渲染前硬关卡：图主文辅 / 反模板化 lint（祥瑞 2026-06-13 定）。
    # 铁律写在 SKILL.md 没有强制力——模型会偷懒套纯文字版式，这里拒绝渲染才真正治本。
    if not args.skip_lint:
        import lint_storyboard
        ok, report = lint_storyboard.lint(sb)
        print(lint_storyboard.format_report(report))
        if not ok:
            print("\n渲染已拒绝。按上面改法重排 sb.json 再跑；确需强渲染加 --skip-lint。",
                  file=sys.stderr)
            sys.exit(1)

    workdir = os.path.abspath(args.workdir)
    os.makedirs(os.path.join(workdir, "temp"), exist_ok=True)
    global FPS
    # 帧率跟素材对齐：主力素材 25fps（如飞书/B站录屏）时写 "fps": 25，
    # 避免 25→30 重复帧造成的卡顿感；默认 30
    FPS = int(sb.get("fps", FPS))
    aspect = sb.get("aspect", "portrait")
    W, H = (1080, 1920) if aspect == "portrait" else (1920, 1080)
    out_path = args.out or os.path.join(workdir, "final.mp4")
    meta = {"show_title": sb.get("show_title") or [sb.get("title", "")],
            "logo": sb.get("logo"),
            "vol": sb.get("vol", "VOL.01"),
            "tags": sb.get("tags", []),
            "chapters": sb.get("chapters") or [],
            "brand": sb.get("brand") or {}}

    # 1. 音频 manifest（缺则补跑 TTS）
    mpath = os.path.join(workdir, "audio", "manifest.json")
    if not os.path.exists(mpath):
        print("manifest 不存在，先跑 TTS...")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import tts
        tts.run_storyboard(args.storyboard, workdir)
    manifest = json.load(open(mpath))
    if len(manifest) != len(sb["scenes"]):
        raise RuntimeError("manifest 与 storyboard 场景数不一致，重跑 tts.py")

    # 2. 逐场景渲染（视频+音频合成单元）；先算全部时长给顶部进度条用
    # 智能剪口播（祥瑞 2026-06-12 定）：画面最多比口播长 max_gap 秒（默认 1.0），
    # min_dur 再大也被钳住——人声断档是留存杀手，信息密的画面该用更长口播去配，
    # 不是用静默画面去等。例外：scene 显式给 dur（绝对时长）或 max_gap 单场景覆盖。
    max_gap_global = float(sb.get("max_gap", 1.0))
    durs = []
    for i, scene in enumerate(sb["scenes"]):
        ndur = manifest[i]["duration"]
        gap_cap = float(scene.get("max_gap", max_gap_global))
        d = max(ndur + PAD, min(float(scene.get("min_dur", MIN_SCENE)), ndur + gap_cap))
        if scene.get("dur"):
            d = max(d, float(scene["dur"]))
        durs.append(d)
    total_planned = sum(durs) or 1.0

    # 章节时间占比(横版顶部章节分段条用):按各章首镜累计时长算分界
    chaps = sb.get("chapters") or []
    if chaps:
        bounds = [sum(durs[:int(c.get("from", 0))]) / total_planned for c in chaps] + [1.0]
        meta["chapters_t"] = [{"t": c["t"], "f0": bounds[k], "f1": bounds[k + 1]}
                              for k, c in enumerate(chaps)]

    timeline, units, cursor = [], [], 0.0
    for i, scene in enumerate(sb["scenes"]):
        m = manifest[i]
        ndur = m["duration"]
        dur = durs[i]
        print(f"[{i + 1}/{len(sb['scenes'])}] {scene['type']}  {dur:.2f}s")
        chunks = make_chunks(scene.get("narration", "").strip(), ndur,
                             18 if H > W else 26)
        if chunks and m.get("file"):
            chunks = whisper_align(m["file"], chunks)
        meta_i = {**meta, "prog": (cursor / total_planned,
                                   (cursor + dur) / total_planned)}
        if scene["type"] in MEDIA_TYPES:
            vis = render_media_scene(scene, meta_i, chunks, dur, W, H, workdir, i)
        elif scene["type"] in HTML_TYPES:
            vis = record_html_scene(scene, meta_i, chunks, dur, W, H, workdir, i)
        else:
            raise ValueError(f"未知场景类型: {scene['type']}")
        # 单元音频用无损 PCM + atrim 精确到采样点（2026-06-12 音画同步根修：
        # AAC 每单元时长向上取整到 1024 采样帧边界，几十个镜头累积零点几秒"画面快于声音"）
        unit = os.path.join(workdir, "temp", f"unit_{i:03d}.mov")
        if m["file"]:
            run([FFMPEG, "-y", "-v", "error", "-i", vis, "-i", m["file"],
                 "-filter_complex",
                 f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                 f"apad=whole_dur={dur:.3f},atrim=0:{dur:.3f}[a]",
                 "-map", "0:v", "-map", "[a]", "-t", f"{dur:.3f}",
                 "-c:v", "copy", "-c:a", "pcm_s16le", unit])
        else:
            run([FFMPEG, "-y", "-v", "error", "-i", vis,
                 "-f", "lavfi", "-t", f"{dur:.3f}",
                 "-i", "anullsrc=r=44100:cl=stereo",
                 "-map", "0:v", "-map", "1:a", "-t", f"{dur:.3f}",
                 "-c:v", "copy", "-c:a", "pcm_s16le", unit])
        units.append(unit)
        timeline.append({"scene": scene, "start": cursor, "end": cursor + dur,
                         "narration_dur": ndur})
        cursor += dur
    total = cursor

    # 3. 拼接（场景间智能转场，自实现的剪映式效果，不依赖剪映引擎）
    joined = os.path.join(workdir, "temp", "joined.mov")
    durs = [t["end"] - t["start"] for t in timeline]
    use_trans = sb.get("transitions", True) and len(units) > 1
    if use_trans:
        # 转场是镜头语言，按相邻镜头叙事关系选，不机械统一（祥瑞 2026-06-11）：
        # 每个 scene 可指定 transition（cut硬切/dissolve叠化/fadeblack黑场/fadewhite闪白/
        # slideup滑动/wipeleft划像/circleopen圈开/zoomin推进 等 ffmpeg xfade 类型）+ transition_dur。
        # AI 写 storyboard 时按关系选：并列递进→cut、时间流逝/关联→dissolve、转折冲击→fadewhite、
        # 段落结束/沉淀→fadeblack、空间转换→slide/wipe。不指定时按类型给克制默认（多数硬切）。
        DEFAULT = {"impact_text": "fadewhite", "concept_card": "fadeblack", "ending": "fadeblack"}
        inp = []
        for u in units:
            inp += ["-i", u]
        vf, af, pv, pa, off = [], [], "0:v", "0:a", 0.0
        new_starts = [0.0]
        for i in range(1, len(units)):
            sc = timeline[i]["scene"]
            tr = sc.get("transition") or DEFAULT.get(sc["type"], "fade")
            if tr == "cut":          # 硬切：极短叠化近似干净切，保持节奏
                tr, want_T = "fade", 0.06
            else:
                want_T = float(sc.get("transition_dur", 0.3))
            T = min(want_T, durs[i - 1] * 0.4, durs[i] * 0.4)  # 短场景自动收窄
            off += durs[i - 1] - T
            vf.append(f"[{pv}][{i}:v]xfade=transition={tr}:duration={T:.3f}:offset={off:.3f}[v{i}]")
            af.append(f"[{pa}][{i}:a]acrossfade=d={T:.3f}:c1=tri:c2=tri[a{i}]")
            pv, pa = f"v{i}", f"a{i}"
            new_starts.append(off)
        run([FFMPEG, "-y", "-v", "error"] + inp +
            ["-filter_complex", ";".join(vf + af),
             "-map", f"[{pv}]", "-map", f"[{pa}]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             "-c:a", "pcm_s16le", joined])
        # 转场缩短了时间轴：重算每个场景 start，SFX 跟着对
        for i, t in enumerate(timeline):
            t["start"] = new_starts[i]
            t["end"] = new_starts[i] + durs[i]
        total = new_starts[-1] + durs[-1]
    else:
        concat_list = os.path.join(workdir, "temp", "concat.txt")
        with open(concat_list, "w") as f:
            for u in units:
                f.write(f"file '{u}'\n")
        run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", concat_list, "-c", "copy", joined])

    # 4. 终混：SFX + BGM（字幕已在 HTML 框架的贴纸条里）
    inputs = [FFMPEG, "-y", "-v", "error", "-i", joined]
    n_in = 1
    sfx_specs = []  # (input_index, delay_ms)
    for item in timeline:
        sfx = item["scene"].get("sfx")
        if sfx:
            path = os.path.join(SFX_DIR, f"{sfx}.wav")
            if os.path.exists(path):
                inputs += ["-i", path]
                sfx_specs.append((n_in, int(item["start"] * 1000) + 50))
                n_in += 1
        # 表情包弹出配 pop 音
        for mm in item["scene"].get("memes") or []:
            path = os.path.join(SFX_DIR, "pop.wav")
            if os.path.exists(path):
                inputs += ["-i", path]
                sfx_specs.append((n_in, int((item["start"] + float(mm.get("at", 1.0))) * 1000)))
                n_in += 1
        # 多 shot 素材切换自动垫轻 tick（可用 "shot_sfx": false 关闭）
        if item["scene"].get("shot_sfx", True):
            tick = os.path.join(SFX_DIR, "tick.wav")
            for (_, st0, _, _) in (item["scene"].get("_shots_timed") or [])[1:]:
                if os.path.exists(tick):
                    inputs += ["-i", tick]
                    sfx_specs.append((n_in, int((item["start"] + st0) * 1000)))
                    n_in += 1
    bgm = sb.get("bgm")
    bgm_idx = None
    if bgm and os.path.exists(bgm):
        inputs += ["-stream_loop", "-1", "-i", bgm]
        bgm_idx = n_in
        n_in += 1

    fc, amix_in = [], ["[voice]"] if bgm_idx is not None else ["[0:a]"]
    for j, (idx, delay) in enumerate(sfx_specs):
        fc.append(f"[{idx}:a]adelay={delay}|{delay},volume=0.9[sfx{j}]")
        amix_in.append(f"[sfx{j}]")
    if bgm_idx is not None:
        # 人声 sidechain 压 BGM（ducking）：说话时 BGM 自动让位，停顿时浮上来
        vol = sb.get("bgm_volume", 0.16)
        fc.append("[0:a]asplit=2[voice][sc]")
        fc.append(f"[{bgm_idx}:a]atrim=0:{total:.3f},volume={vol},"
                  f"afade=t=in:d=1.2,afade=t=out:st={max(0, total - 1.8):.3f}:d=1.8[bgmpre]")
        fc.append("[bgmpre][sc]sidechaincompress=threshold=0.02:ratio=6:"
                  "attack=80:release=500:makeup=1[bgm]")
        amix_in.append("[bgm]")
    if len(amix_in) > 1:
        fc.append(f"{''.join(amix_in)}amix=inputs={len(amix_in)}:normalize=0:duration=first[amixed]")
        amap = "[amixed]"
    else:
        amap = "[0:a]"

    # 结尾渐隐（祥瑞 2026-06-11）：画面淡黑 + 音频淡出，给"结束了"的收尾感。
    # 可用 sb["fade_out"] 调时长（默认 0.9s），设 0 关闭。
    fade_d = float(sb.get("fade_out", 0.9))
    fade_st = max(0.0, total - fade_d)
    if fade_d > 0:
        fc.append(f"{amap}afade=t=out:st={fade_st:.3f}:d={fade_d:.3f}[afade]")
        amap = "[afade]"
        vf = f"eq=saturation=1.07:contrast=1.02,fade=t=out:st={fade_st:.3f}:d={fade_d:.3f}"
    else:
        vf = "eq=saturation=1.07:contrast=1.02"
    cmd = inputs + ["-filter_complex", ";".join(fc)] + \
        ["-map", "0:v", "-map", amap,
         "-vf", vf,
         "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", "-t", f"{total:.3f}", out_path]
    print("终混渲染中...")
    run(cmd)

    # 双版本（祥瑞 2026-06-12 定）：配了 BGM 时额外输出无伴奏版，发布平台自选配乐
    if bgm_idx is not None:
        nob = os.path.splitext(out_path)[0] + "_nobgm.mp4"
        inputs2 = inputs[:-4]  # 去掉 ["-stream_loop","-1","-i",bgm]
        fc2, amix2 = [], ["[0:a]"]
        for j, (idx, delay) in enumerate(sfx_specs):
            fc2.append(f"[{idx}:a]adelay={delay}|{delay},volume=0.9[sfx{j}]")
            amix2.append(f"[sfx{j}]")
        if len(amix2) > 1:
            fc2.append(f"{''.join(amix2)}amix=inputs={len(amix2)}:normalize=0:duration=first[am2]")
            amap2 = "[am2]"
        else:
            amap2 = "[0:a]"
        if fade_d > 0:
            fc2.append(f"{amap2}afade=t=out:st={fade_st:.3f}:d={fade_d:.3f}[af2]")
            amap2 = "[af2]"
        run(inputs2 + ["-filter_complex", ";".join(fc2)] +
            ["-map", "0:v", "-map", amap2, "-vf", vf,
             "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", "-t", f"{total:.3f}", nob])
        print(f"   无伴奏版: {nob}")

    if not args.keep_temp:
        pass  # temp 保留给排查，由调用方清理

    # 自动封面：钩子场景中点帧（社区实践：hook 帧做封面优于末帧/随机帧）
    cover = os.path.splitext(out_path)[0] + "_cover.jpg"
    try:
        run([FFMPEG, "-y", "-v", "error", "-ss", f"{durs[0] * 0.55:.2f}",
             "-i", out_path, "-frames:v", "1", "-q:v", "2", cover])
        print(f"封面: {cover}")
    except Exception:
        pass

    final_dur = probe_duration(out_path)
    print(f"\n✅ 成片: {out_path}")
    print(f"   时长 {final_dur:.1f}s | {W}x{H} | {len(sb['scenes'])} 场景")
    print(f"   自检: 抽帧确认视觉效果 -> ffmpeg -ss N -i {out_path} -frames:v 1 check.jpg")


if __name__ == "__main__":
    main()
