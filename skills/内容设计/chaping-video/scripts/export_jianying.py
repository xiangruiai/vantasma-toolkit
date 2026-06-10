#!/usr/bin/env python3
"""把 chaping-video 工程导出为剪映草稿（CLI 生成，剪映里精修+导出）。

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--effects", action="store_true",
                    help="实验性：加剪映内置转场/文字动画（先确认基础草稿能开再用）")
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
    sf.add_track(TrackType.video).add_track(TrackType.audio).add_track(TrackType.text)

    us = lambda s: int(s * 1_000_000)  # 剪映时间单位：微秒（全程整数防累计误差重叠）
    cursor = 0
    n_sub = 0
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
        # 剪映内置转场：媒体场景间叠化更顺，冲击/钩子场景用快切闪黑（最后一场不加）
        if not a.plain and i < len(sb["scenes"]) - 1:
            from pyJianYingDraft import TransitionType
            t = TransitionType.闪黑 if scene["type"] in ("impact_text", "concept_card") \
                else TransitionType.叠化
            try:
                vseg.add_transition(t, duration="0.3s")
            except Exception:
                pass
        sf.add_segment(vseg)

        # TTS 音频段
        mp3 = os.path.join(wd, "audio", f"scene_{i:03d}.mp3")
        if os.path.exists(mp3) and scene.get("narration"):
            adur = min(us(probe_dur(mp3)), vdur)
            sf.add_segment(draft.AudioSegment(
                draft.AudioMaterial(mp3),
                Timerange(cursor, adur),
                source_timerange=Timerange(0, adur)))

            # 字幕段：按句读切条均分音频时长（剪映里可再微调）
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
    import re
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
