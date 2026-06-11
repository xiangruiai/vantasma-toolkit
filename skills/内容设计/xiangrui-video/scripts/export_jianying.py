#!/usr/bin/env python3
"""把 xiangrui-video 工程导出为剪映草稿（CLI 生成，剪映里精修+导出）。

形态：每个场景一段视频（带品牌框架的无声场景片段）+ 对应 TTS 音频段 + 字幕文本段，
三轨对齐铺进剪映时间线。在剪映里可以：调场景顺序/时长、替换素材、加剪映的
花字/转场/贴纸/曲库 BGM，然后手动导出（macOS 剪映无自动导出接口）。

前提：render.py 跑过一次（temp/ 里有 vis_NNN[b].mp4 场景片段，audio/ 有逐句 mp3）。
注意：剪映打开草稿并保存后会转加密格式，CLI 无法回读——单向导出，改完以剪映为准。

用法:
  python3 export_jianying.py --storyboard sb.json --workdir . [--name 草稿名]
依赖:
  pip install pyjianyingdraft   （剪映专业版 5+，macOS/Windows 草稿目录自动探测）
"""
import argparse
import json
import os
import re
import subprocess
import sys

FFPROBE = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
if not os.path.exists(FFPROBE):
    FFPROBE = "ffprobe"

DRAFT_DIRS = [
    os.path.expanduser("~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft"),  # macOS
    os.path.expanduser("~/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft"),  # Windows
]


def probe_dur(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())


def split_subs(text):
    """与 render.py 同款句读：逗号/句号切条，顿号不切。"""
    parts = re.split(r"[，。！？!?,.；;]", text)
    return [p.strip() for p in parts if p.strip()]


def render_bare_layers(sb, wd, W, H):
    """为剪映分层导出渲染各层素材：
    - HTML 设计场景 → bare 背景段（无文字，文字交给剪映轨道）bare_NNN.mp4
    - 媒体场景 → 每个 shot 的原始素材段（真实素材，可在剪映单独换/调）
    返回 [{type, clips:[路径], scene}] 按场景。"""
    import render
    from html_still import MEDIA_TYPES
    render.FPS = int(sb.get("fps", 30))
    layers = []
    for i, scene in enumerate(sb["scenes"]):
        mp3 = os.path.join(wd, "audio", f"scene_{i:03d}.mp3")
        dur = probe_dur(mp3) if os.path.exists(mp3) else 3.0
        if scene["type"] in MEDIA_TYPES and scene.get("shots"):
            # 媒体场景：原始素材逐 shot 独立成段（用户要的"拆开"）
            clips = [sh["src"] for sh in scene["shots"] if os.path.exists(sh.get("src", ""))]
            layers.append({"type": "media", "clips": clips, "scene": scene, "dur": dur})
        else:
            # HTML 设计场景：渲染 bare 背景（无文字全局元素）
            bare_meta = {"show_title": sb.get("show_title"), "vol": sb.get("vol"),
                         "tags": sb.get("tags", []), "brand": sb.get("brand") or {}, "bare": True}
            out = render.record_html_scene(scene, bare_meta, [], dur, W, H, wd, 900 + i)
            bare = os.path.join(wd, "temp", f"bare_{i:03d}.mp4")
            os.replace(out, bare)
            layers.append({"type": "html", "clips": [bare], "scene": scene, "dur": dur})
    return layers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--effects", action="store_true",
                    help="实验性：加剪映内置转场/文字动画（先确认基础草稿能开再用）")
    ap.add_argument("--layered", action="store_true",
                    help="全分层可编辑：背景/素材/字幕/logo/期数/标题各自独立成轨")
    a = ap.parse_args()
    a.plain = not a.effects  # 默认纯净三轨，优先保证草稿一定能打开

    try:
        import pyJianYingDraft as draft
        from pyJianYingDraft import TrackType, Timerange
    except ImportError:
        raise SystemExit("缺依赖: python3 -m pip install --user --break-system-packages pyjianyingdraft")

    draft_root = next((d for d in DRAFT_DIRS if os.path.isdir(d)), None)
    if not draft_root:
        raise SystemExit(f"找不到剪映草稿目录（剪映专业版没装？），找过: {DRAFT_DIRS}")

    # 剪映运行时操作草稿目录会损坏草稿（内存态覆盖冲突）——先退出剪映
    jy_running = subprocess.run(["pgrep", "-f", "VideoFusion-macOS"],
                                capture_output=True, text=True).stdout.strip()
    if jy_running:
        print("检测到剪映在运行，先退出（避免草稿被运行态覆盖损坏）...")
        subprocess.run(["osascript", "-e", 'quit app "VideoFusion-macOS"'],
                       capture_output=True)
        import time
        time.sleep(3)

    wd = os.path.abspath(a.workdir)
    sb = json.load(open(a.storyboard))
    W, H = (1080, 1920) if sb.get("aspect", "portrait") == "portrait" else (1920, 1080)
    name = a.name or f"{sb.get('vol', 'VOL')}-{sb.get('title', '草稿')}"

    folder = draft.DraftFolder(draft_root)
    sf = folder.create_draft(name, W, H, allow_replace=True)
    us = lambda s: int(s * 1_000_000)  # 剪映时间单位：微秒（全程整数防累计误差重叠）
    cursor = 0
    n_sub = 0

    if a.layered:
        from pyJianYingDraft import ClipSettings
        print("分层渲染各场景背景/素材（HTML 场景出无文字底，媒体场景用真实素材）...")
        layers = render_bare_layers(sb, wd, W, H)
        # 轨道：底→顶。视频(背景/素材) / 音频(配音) / 文字四层(字幕/标题/logo/期数)
        sf.add_track(TrackType.video).add_track(TrackType.audio)
        sf.add_track(TrackType.text, track_name="字幕")
        sf.add_track(TrackType.text, track_name="标题")
        sf.add_track(TrackType.text, track_name="logo")
        sf.add_track(TrackType.text, track_name="期数")
        GREEN = (0.133, 0.651, 0.404)
        for i, (Ly, scene) in enumerate(zip(layers, sb["scenes"])):
            sdur = us(Ly["dur"])
            clips = Ly["clips"]
            if not clips:
                cursor += sdur
                continue
            # 视频轨：媒体场景每个 shot 独立成段（可单独换/调）；HTML 场景单段背景
            per = sdur // len(clips)
            for k, cp in enumerate(clips):
                seg_len = per if k < len(clips) - 1 else sdur - per * (len(clips) - 1)
                # 统一截取：留一帧余量防整帧取整越界（HTML/媒体段都适用）
                src_end = max(40000, min(seg_len, us(probe_dur(cp)) - 40000))
                sf.add_segment(draft.VideoSegment(draft.VideoMaterial(cp),
                               Timerange(cursor + k * per, seg_len),
                               source_timerange=Timerange(0, src_end)))
            # 音频 + 字幕
            mp3 = os.path.join(wd, "audio", f"scene_{i:03d}.mp3")
            if os.path.exists(mp3) and scene.get("narration"):
                adur = min(us(probe_dur(mp3)), sdur)
                sf.add_segment(draft.AudioSegment(draft.AudioMaterial(mp3),
                               Timerange(cursor, adur), source_timerange=Timerange(0, adur)))
                subs = split_subs(scene["narration"])
                if subs:
                    sp = adur // len(subs)
                    for j, txt in enumerate(subs):
                        sl = sp if j < len(subs) - 1 else adur - sp * (len(subs) - 1)
                        sf.add_segment(draft.TextSegment(txt, Timerange(cursor + j * sp, sl),
                            style=draft.TextStyle(size=8.0, color=(1, 1, 1)),
                            clip_settings=ClipSettings(transform_y=-0.62)),
                            track_name="字幕")
                        n_sub += 1
            cursor += sdur
        total = cursor
        brand = sb.get("brand") or {}
        # 常驻文字层：标题/logo/期数 全片一段，剪映里可直接改文字
        title_txt = "".join(re.sub(r'\(\(|\)\)', '', t) for t in (sb.get("show_title") or []))
        if title_txt:
            sf.add_segment(draft.TextSegment(title_txt, Timerange(0, total),
                style=draft.TextStyle(size=15.0, color=(1, 1, 1)),
                clip_settings=ClipSettings(transform_x=-0.05, transform_y=-0.30)),
                track_name="标题")
        sf.add_segment(draft.TextSegment(brand.get("name", "万涂幻象"), Timerange(0, total),
            style=draft.TextStyle(size=7.0, color=GREEN),
            clip_settings=ClipSettings(transform_x=-0.72, transform_y=0.82)),
            track_name="logo")
        sf.add_segment(draft.TextSegment(sb.get("vol", "VOL.01"), Timerange(0, total),
            style=draft.TextStyle(size=5.5, color=(1, 1, 1)),
            clip_settings=ClipSettings(transform_x=0.60, transform_y=0.82)),
            track_name="期数")
        print(f"分层完成: 视频/配音/字幕/标题/logo/期数 6 轨")
    else:
        sf.add_track(TrackType.video).add_track(TrackType.audio).add_track(TrackType.text)
        for i, scene in enumerate(sb["scenes"]):
            # 场景视频片段：HTML 场景=vis_NNN.mp4，媒体场景=vis_NNNb.mp4
            clip = None
            for cand in (f"vis_{i:03d}b.mp4", f"vis_{i:03d}.mp4"):
                p = os.path.join(wd, "temp", cand)
                if os.path.exists(p):
                    clip = p
                    break
            if not clip:
                print(f"⚠️ 场景 {i} 缺片段（先跑 render.py），跳过")
                continue
            vdur = us(probe_dur(clip))
            vseg = draft.VideoSegment(draft.VideoMaterial(clip), Timerange(cursor, vdur))
            if not a.plain and i < len(sb["scenes"]) - 1:
                from pyJianYingDraft import TransitionType
                t = TransitionType.闪黑 if scene["type"] in ("impact_text", "concept_card") \
                    else TransitionType.叠化
                try:
                    vseg.add_transition(t, duration="0.3s")
                except Exception:
                    pass
            sf.add_segment(vseg)
            mp3 = os.path.join(wd, "audio", f"scene_{i:03d}.mp3")
            if os.path.exists(mp3) and scene.get("narration"):
                adur = min(us(probe_dur(mp3)), vdur)
                sf.add_segment(draft.AudioSegment(
                    draft.AudioMaterial(mp3),
                    Timerange(cursor, adur),
                    source_timerange=Timerange(0, adur)))
                subs = split_subs(scene["narration"])
                if subs:
                    per = adur // len(subs)
                    for j, txt in enumerate(subs):
                        seg_len = per if j < len(subs) - 1 else adur - per * (len(subs) - 1)
                        tseg = draft.TextSegment(
                            txt, Timerange(cursor + j * per, seg_len),
                            style=draft.TextStyle(size=8.0, color=(1.0, 1.0, 1.0)))
                        if not a.plain:
                            from pyJianYingDraft import TextIntro
                            try:
                                tseg.add_animation(TextIntro.渐显, duration="0.2s")
                            except Exception:
                                pass
                        sf.add_segment(tseg)
                        n_sub += 1
            cursor += vdur

    sf.save()

    ddir = os.path.join(draft_root, name)
    import shutil

    # 关键①：剪映是沙盒应用，无权访问 ~/Projects 下的素材（显示"暂无访问权限"）。
    # 把素材复制进草稿目录 materials/（剪映对自己草稿目录有完整权限），并改写 JSON 路径。
    matdir = os.path.join(ddir, "materials")
    os.makedirs(matdir, exist_ok=True)
    main_json = os.path.join(ddir, "draft_content.json")
    txt = open(main_json).read()
    path_map = {}
    for p in set(re.findall(r'/[^"]*?\.(?:mp4|mp3|jpg|png|wav)', txt)):
        if os.path.exists(p) and matdir not in p:
            dst = os.path.join(matdir, os.path.basename(p))
            shutil.copy(p, dst)
            path_map[p] = dst
    for s, d in path_map.items():
        txt = txt.replace(s, d)
    open(main_json, "w").write(txt)
    print(f"   素材自包含: {len(path_map)} 个复制进草稿（解决沙盒权限）")

    # 关键②：剪映 10.6 草稿主文件名是 draft_info.json，pyJianYingDraft 只写 draft_content.json，
    # 剪映按索引找 draft_info.json 找不到 → 草稿箱显示损坏/打不开。补一份同名文件。
    shutil.copy(main_json, os.path.join(ddir, "draft_info.json"))
    # 补缩略图：剪映草稿箱要 cover 才显示卡片（取工程封面或首场景帧）
    cover = os.path.join(wd, "final_cover.jpg")
    if os.path.exists(cover):
        shutil.copy(cover, os.path.join(ddir, "draft_cover.jpg"))
        shutil.copy(cover, os.path.join(ddir, "draft_local_cover.jpg"))

    # 修复 meta：pyJianYingDraft 保存后 tm_duration=0，剪映可能据此判草稿损坏
    meta_path = os.path.join(ddir, "draft_meta_info.json")
    try:
        meta = json.load(open(meta_path))
        meta["tm_duration"] = cursor
        meta["tm_draft_modified"] = cursor
        json.dump(meta, open(meta_path, "w"), ensure_ascii=False)
    except Exception as e:
        print(f"   (meta 修复跳过: {e})")

    print(f"✅ 剪映草稿已生成: {name}")
    print(f"   {len(sb['scenes'])} 场景 | {n_sub} 条字幕 | 总时长 {cursor / 1_000_000:.1f}s")
    print(f"   位置: {os.path.join(draft_root, name)}")
    print("   现在手动打开剪映 → 草稿列表能看到它（脚本不自动开，避免运行态冲突）。")
    print("   ⚠️ 剪映保存后草稿转加密，CLI 不能再读回，以剪映内为准。")


if __name__ == "__main__":
    main()
