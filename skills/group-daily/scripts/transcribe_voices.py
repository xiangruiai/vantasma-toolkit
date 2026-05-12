#!/usr/bin/env python3
"""微信语音转写助手。

工作流（AI 在 SKILL.md Step 1.5 调用）:
    1. 调 mcp__wechat__get_voice_messages 拿语音列表
    2. 对每条调 mcp__wechat__decode_voice 解码为 wav（落到
       ~/Projects/wechat-decrypt/decoded_voices/）
    3. 调本脚本 transcribe_voices.py 批量转写所有指定 wav
    4. 脚本输出 JSON: {local_id: {time, duration, text}}

转写引擎: openai-whisper（本地，base 模型，139MB）
缓存策略: 已转写过的 wav 跳过（基于文件 mtime 和 sha 双重 key）

用法:
    transcribe_voices.py \\
        --wav-dir ~/Projects/wechat-decrypt/decoded_voices/ \\
        --filter "57093713457@chatroom" \\
        --out /tmp/voices_<群名>_<日期>.json \\
        --model base

参数:
    --wav-dir   解码后 wav 文件所在目录
    --filter    文件名子串过滤（一般是群 chatroom username）
    --out       输出 JSON 路径
    --model     whisper 模型名（默认 base，可选 tiny / small / medium）
    --language  语言（默认 zh）
    --min-duration  最短时长秒数，短于此跳过（默认 3）
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

CACHE_PATH = Path.home() / ".claude/skills/group-daily/voice_cache.json"


def load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def wav_duration(path):
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return None


def file_sig(path):
    """文件签名：mtime + size，足够区分是否变化"""
    st = path.stat()
    return f"{int(st.st_mtime)}-{st.st_size}"


def parse_filename(name):
    """从文件名解析 chatroom_id 和 local_id。

    文件名格式: <chatroom>_<YYYYMMDD>_<HHMMSS>_<local_id>.wav
    例: 57093713457@chatroom_20260512_002749_11239.wav
    """
    m = re.match(r"(.+?)_(\d{8})_(\d{6})_(\d+)\.wav$", name)
    if m:
        chatroom, date, time, local_id = m.groups()
        return {
            "chatroom": chatroom,
            "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
            "time": f"{time[:2]}:{time[2:4]}:{time[4:]}",
            "local_id": int(local_id),
        }
    return None


def transcribe(wav_path, model="base", language="zh"):
    """跑 whisper CLI 转写。返回纯文本（去掉每行空白和重复）。"""
    out_dir = Path("/tmp/whisper_out")
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "whisper", str(wav_path),
        "--model", model,
        "--language", language,
        "--output_format", "txt",
        "--output_dir", str(out_dir),
        "--verbose", "False",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    except subprocess.CalledProcessError as e:
        return None, f"whisper failed: {e.stderr.decode()[:200]}"
    except FileNotFoundError:
        return None, ("whisper CLI not found. "
                      "Run: pip3 install openai-whisper --break-system-packages")
    except subprocess.TimeoutExpired:
        return None, "whisper timed out (>10 min)"

    txt_path = out_dir / f"{wav_path.stem}.txt"
    if not txt_path.exists():
        return None, "whisper output txt missing"
    text = txt_path.read_text(encoding="utf-8").strip()
    return text, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav-dir", required=True,
                    help="解码后 wav 文件所在目录")
    ap.add_argument("--filter", default="",
                    help="文件名子串过滤（一般是群 chatroom username）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    ap.add_argument("--model", default="base",
                    help="whisper 模型名（tiny/base/small/medium，默认 base）")
    ap.add_argument("--language", default="zh", help="语言（默认 zh）")
    ap.add_argument("--min-duration", type=float, default=3.0,
                    help="最短时长秒数，短于此跳过（默认 3）")
    ap.add_argument("--max-files", type=int, default=200,
                    help="最多处理多少个文件（默认 200）")
    args = ap.parse_args()

    wav_dir = Path(os.path.expanduser(args.wav_dir))
    if not wav_dir.exists():
        sys.exit(f"目录不存在: {wav_dir}")

    cache = load_cache()
    cache_key_prefix = f"{args.model}|{args.language}|"

    results = {}
    skipped_short = 0
    cached_hits = 0
    new_transcribed = 0

    files = sorted(p for p in wav_dir.glob("*.wav")
                   if args.filter in p.name)[:args.max_files]
    print(f"扫到 {len(files)} 个候选 wav 文件", file=sys.stderr)

    for wav in files:
        info = parse_filename(wav.name)
        if not info:
            print(f"  ✗ 跳过（文件名格式不识别）: {wav.name}", file=sys.stderr)
            continue

        dur = wav_duration(wav)
        if dur is not None and dur < args.min_duration:
            skipped_short += 1
            print(f"  ⏭ 跳过（{dur:.1f}s < {args.min_duration}s）: {wav.name}",
                  file=sys.stderr)
            continue

        cache_key = cache_key_prefix + file_sig(wav)
        if cache_key in cache:
            cached_hits += 1
            text = cache[cache_key]
            print(f"  ✓ 缓存命中: local_id={info['local_id']} {dur:.1f}s",
                  file=sys.stderr)
        else:
            print(f"  ▶ 转写中: local_id={info['local_id']} {dur:.1f}s ...",
                  file=sys.stderr)
            text, err = transcribe(wav, model=args.model, language=args.language)
            if text is None:
                print(f"    ✗ 失败: {err}", file=sys.stderr)
                continue
            cache[cache_key] = text
            new_transcribed += 1

        results[str(info["local_id"])] = {
            "time": f"{info['date']} {info['time']}",
            "duration_s": round(dur or 0, 1),
            "text": text,
        }

    save_cache(cache)
    Path(os.path.expanduser(args.out)).write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n✅ 完成", file=sys.stderr)
    print(f"   转写 {len(results)} 条（新 {new_transcribed} + 缓存 {cached_hits}）",
          file=sys.stderr)
    print(f"   跳过过短 {skipped_short} 条", file=sys.stderr)
    print(f"   输出: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
