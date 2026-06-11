#!/usr/bin/env python3
"""用 ffmpeg 合成知识视频音效库（无版权，纯合成）。

用法: python3 make_sfx.py [输出目录]
默认输出到 skill 的 assets/sfx/。已存在的文件跳过，--force 重新生成。
"""
import os
import subprocess
import sys

FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
if not os.path.exists(FFMPEG):
    FFMPEG = "ffmpeg"

# 名称 -> (filter_complex 音频合成表达式, 时长)
SFX = {
    # 叮：高频泛音 + 指数衰减，花字/重点出现时用
    "ding": (
        "sine=frequency=1568:duration=0.7[a];"
        "sine=frequency=3136:duration=0.7,volume=0.3[b];"
        "[a][b]amix=inputs=2:normalize=0,"
        "volume='exp(-7*t)':eval=frame,volume=1.6",
        0.7,
    ),
    # 咻：粉噪声扫频感，转场/弹入时用
    "whoosh": (
        "anoisesrc=color=pink:duration=0.5:amplitude=0.6,"
        "highpass=f=500,lowpass=f=5000,"
        "volume='if(lt(t,0.18),t/0.18,exp(-9*(t-0.18)))':eval=frame,volume=1.4",
        0.5,
    ),
    # 砰：低频冲击，砸字/概念卡出现时用
    "impact": (
        "sine=frequency=55:duration=0.5[a];"
        "sine=frequency=110:duration=0.5,volume=0.5[b];"
        "anoisesrc=color=brown:duration=0.5:amplitude=0.8[c];"
        "[a][b][c]amix=inputs=3:normalize=0,"
        "volume='exp(-10*t)':eval=frame,volume=2.2",
        0.5,
    ),
    # 噗：短促弹出音，贴纸/小元素出现时用
    "pop": (
        "sine=frequency=660:duration=0.12[a];"
        "sine=frequency=330:duration=0.12,volume=0.6[b];"
        "[a][b]amix=inputs=2:normalize=0,"
        "volume='exp(-22*t)':eval=frame,volume=1.8",
        0.12,
    ),
    # 嗒：轻打点，普通切镜时用
    "tick": (
        "sine=frequency=2000:duration=0.06,"
        "volume='exp(-40*t)':eval=frame,volume=1.2",
        0.06,
    ),
}


def main():
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]
    out_dir = args[0] if args else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sfx")
    os.makedirs(out_dir, exist_ok=True)
    for name, (expr, dur) in SFX.items():
        out = os.path.join(out_dir, f"{name}.wav")
        if os.path.exists(out) and not force:
            print(f"skip {name}.wav (已存在)")
            continue
        cmd = [FFMPEG, "-y", "-v", "error",
               "-filter_complex", expr + ",aformat=sample_rates=44100:channel_layouts=stereo",
               "-t", str(dur), out]
        subprocess.run(cmd, check=True)
        print(f"ok   {name}.wav ({dur}s)")


if __name__ == "__main__":
    main()
