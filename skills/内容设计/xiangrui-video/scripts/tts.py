#!/usr/bin/env python3
"""万涂幻象知识视频 TTS：火山豆包语音合成优先，edge-tts 兜底，macOS say 保底。

用法:
  单句:   python3 tts.py --text "你好" --out /path/out.mp3
  整板:   python3 tts.py --storyboard sb.json --workdir /path/work
          (对每个 scene.narration 合成 audio/scene_NNN.mp3，写 audio/manifest.json)
  查后端: python3 tts.py --check

配置（可选）: ~/.config/xiangrui-video/config.json
{
  "tts": {
    "backend": "auto",            // auto | volc | edge | say
    "volc": {"appid": "", "token": "", "voice": "zh_male_yangguangqingnian_moon_bigtts",
              "speed_ratio": 1.1, "cluster": "volcano_tts"},
    "edge": {"voice": "zh-CN-YunjianNeural", "rate": "+8%",
              "proxy": "http://127.0.0.1:7897"}
  }
}
火山豆包开通方式: console.volcengine.com/speech → 语音合成大模型 → 创建应用拿 appid + access_token。
没配 volc 时自动走 edge-tts（免费，需代理可达微软端点）。
"""
import argparse
import base64
import json
import os
import subprocess
import sys

FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
if not __import__("os").path.exists(FFMPEG):
    FFMPEG = "ffmpeg"
import uuid

FFPROBE = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
if not os.path.exists(FFPROBE):
    FFPROBE = "ffprobe"

CONFIG_PATH = os.path.expanduser("~/.config/xiangrui-video/config.json")
DEFAULTS = {
    "backend": "auto",
    # 播客 TTS（群日报播客同款，音色=大义先生）：凭证 env/钥匙串，不明文落盘
    "podcast": {"speaker": "zh_male_dayixiansheng_v2_saturn_bigtts"},
    "volc": {"appid": "", "token": "", "voice": "zh_male_yangguangqingnian_moon_bigtts",
             "speed_ratio": 1.1, "cluster": "volcano_tts"},
    "edge": {"voice": "zh-CN-YunxiNeural", "rate": "+4%",
             "proxy": "http://127.0.0.1:7897"},
}


def podcast_creds():
    """播客 TTS 凭证：env 优先，其次 macOS 钥匙串（service=xiangrui-video-volc）。"""
    appid = os.environ.get("VOLC_PODCAST_APPID", "")
    token = os.environ.get("VOLC_PODCAST_TOKEN", "")
    if appid and token:
        return appid, token
    try:
        appid = subprocess.run(
            ["security", "find-generic-password", "-s", "xiangrui-video-volc",
             "-a", "appid", "-w"], capture_output=True, text=True).stdout.strip()
        token = subprocess.run(
            ["security", "find-generic-password", "-s", "xiangrui-video-volc",
             "-a", "token", "-w"], capture_output=True, text=True).stdout.strip()
    except Exception:
        return "", ""
    return appid, token


def tts_podcast_batch(texts, out_paths, cfg):
    """一次会话合成全部句子（prosody 连贯），逐 round 落到 out_paths。"""
    import shutil
    import tempfile
    appid, token = podcast_creds()
    if not (appid and token):
        raise RuntimeError("播客 TTS 未配置凭证（env 或钥匙串）")
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_podcast.mjs")
    with tempfile.TemporaryDirectory() as td:
        lines_json = os.path.join(td, "lines.json")
        json.dump({"lines": texts}, open(lines_json, "w"), ensure_ascii=False)
        env = dict(os.environ, VOLC_PODCAST_APPID=appid, VOLC_PODCAST_TOKEN=token)
        r = subprocess.run([node, script, "--in", lines_json, "--outdir", td,
                            "--speaker", cfg["podcast"].get(
                                "speaker", "zh_male_dayixiansheng_v2_saturn_bigtts")],
                           capture_output=True, text=True, env=env, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"播客 TTS 失败: {(r.stderr or r.stdout).strip()[-400:]}")
        for i, dst in enumerate(out_paths):
            src = os.path.join(td, f"line_{i:03d}.mp3")
            if not os.path.exists(src):
                raise RuntimeError(f"播客 TTS 缺第 {i} 句音频")
            os.replace(src, dst)


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(CONFIG_PATH):
        try:
            user = json.load(open(CONFIG_PATH)).get("tts", {})
            for k, v in user.items():
                if isinstance(v, dict):
                    cfg.setdefault(k, {}).update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            print(f"[tts] 配置解析失败，用默认: {e}", file=sys.stderr)
    return cfg


def duration_of(path):
    out = subprocess.run([FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(out.stdout.strip())


def tts_volc(text, out_path, cfg):
    import urllib.request
    v = cfg["volc"]
    if not (v.get("appid") and v.get("token")):
        raise RuntimeError("volc 未配置 appid/token")
    body = {
        "app": {"appid": v["appid"], "token": v["token"], "cluster": v.get("cluster", "volcano_tts")},
        "user": {"uid": "xiangrui-video"},
        "audio": {"voice_type": v["voice"], "encoding": "mp3",
                  "speed_ratio": v.get("speed_ratio", 1.1)},
        "request": {"reqid": str(uuid.uuid4()), "text": text, "operation": "query"},
    }
    req = urllib.request.Request(
        "https://openspeech.bytedance.com/api/v1/tts",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer;{v['token']}"})
    resp = json.load(urllib.request.urlopen(req, timeout=60))
    if resp.get("code") != 3000:
        raise RuntimeError(f"volc TTS 失败 code={resp.get('code')} msg={resp.get('message')}")
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(resp["data"]))


def tts_edge(text, out_path, cfg):
    import time
    e = cfg["edge"]
    base = [sys.executable, "-m", "edge_tts", "--voice", e["voice"],
            "--rate", e.get("rate", "+8%"), "--text", text, "--write-media", out_path]
    # 直连/代理交替，重试 3 轮（偶发超时不能让它溜到难听的兜底音）
    last = ""
    for attempt in range(3):
        for extra in ([], ["--proxy", e["proxy"]] if e.get("proxy") else []):
            r = subprocess.run(base + extra, capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                return
            last = r.stderr.strip()[-300:]
        time.sleep(1.5)
    raise RuntimeError(f"edge-tts 失败(已重试3轮): {last}")


def tts_say(text, out_path, cfg):
    aiff = out_path + ".aiff"
    subprocess.run(["say", "-v", "Tingting", "-o", aiff, text], check=True)
    subprocess.run([FFPROBE.replace("ffprobe", "ffmpeg"), "-y", "-v", "error",
                    "-i", aiff, out_path], check=True)
    os.remove(aiff)


def synthesize(text, out_path, cfg=None):
    """合成一句，返回 (backend, duration)。"""
    cfg = cfg or load_config()
    backend = cfg.get("backend", "auto")
    # auto 不含 say：婷婷机器音宁可报错也不混进成片（2026-06-10 静默降级事故）
    order = {"auto": ["volc", "edge"], "volc": ["volc"],
             "edge": ["edge"], "say": ["say"]}[backend]
    last_err = None
    for b in order:
        if b == "volc" and not (cfg["volc"].get("appid") and cfg["volc"].get("token")):
            continue
        try:
            {"volc": tts_volc, "edge": tts_edge, "say": tts_say}[b](text, out_path, cfg)
            return b, duration_of(out_path)
        except Exception as e:
            last_err = e
            print(f"[tts] {b} 失败: {e}", file=sys.stderr)
    raise RuntimeError(f"所有 TTS 后端均失败，最后错误: {last_err}")


def run_storyboard(sb_path, workdir):
    sb = json.load(open(sb_path))
    audio_dir = os.path.join(workdir, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    cfg = load_config()
    scenes = sb["scenes"]
    manifest = [None] * len(scenes)

    def trim_silence(path):
        """裁掉 TTS 头尾静音（祥瑞 2026-06-12 定：头部 0.12-0.26s 静音导致每镜'图先出来话后到'）。
        头部留 0.04s 起音、尾部留 0.12s 收尾。"""
        import subprocess as sp
        tmp = path + ".trim.mp3"
        r = sp.run([FFMPEG, "-y", "-v", "error", "-i", path, "-af",
                    # 只裁头部(2026-06-12 翻车教训:stop_periods 会在句内第一个停顿处截断整句!)
                    "silenceremove=start_periods=1:start_silence=0.04:start_threshold=-38dB",
                    "-c:a", "libmp3lame", "-q:a", "2", tmp], capture_output=True)
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
            os.replace(tmp, path)
        else:
            try: os.remove(tmp)
            except OSError: pass

    # 播客后端可用时整批合成（一次会话 prosody 连贯，音色=群日报播客同款）
    appid, token = podcast_creds()
    use_podcast = cfg.get("backend", "auto") in ("auto", "podcast") and appid and token
    if use_podcast:
        idxs = [i for i, s in enumerate(scenes) if s.get("narration", "").strip()]
        texts = [scenes[i]["narration"].strip() for i in idxs]
        outs = [os.path.join(audio_dir, f"scene_{i:03d}.mp3") for i in idxs]
        try:
            tts_podcast_batch(texts, outs, cfg)
            for i, out in zip(idxs, outs):
                trim_silence(out)
                dur = duration_of(out)
                manifest[i] = {"index": i, "file": out, "duration": round(dur, 3),
                               "text": scenes[i]["narration"].strip(), "backend": "podcast"}
                print(f"scene {i:03d} [podcast] {dur:.2f}s  {scenes[i]['narration'][:30]}")
        except Exception as e:
            print(f"[tts] 播客后端整批失败，回退逐句: {e}", file=sys.stderr)
            use_podcast = False
    if not use_podcast:
        for i, scene in enumerate(scenes):
            text = scene.get("narration", "").strip()
            if not text:
                continue
            out = os.path.join(audio_dir, f"scene_{i:03d}.mp3")
            backend, dur = synthesize(text, out, cfg)
            trim_silence(out)
            dur = duration_of(out)
            manifest[i] = {"index": i, "file": out, "duration": round(dur, 3),
                           "text": text, "backend": backend}
            print(f"scene {i:03d} [{backend}] {dur:.2f}s  {text[:30]}")
    for i, scene in enumerate(scenes):
        if manifest[i] is None:
            manifest[i] = {"index": i, "file": None, "duration": 0.0, "text": ""}
    mpath = os.path.join(audio_dir, "manifest.json")
    json.dump(manifest, open(mpath, "w"), ensure_ascii=False, indent=1)
    total = sum(m["duration"] for m in manifest)
    print(f"\n共 {len(manifest)} 句，总时长 {total:.1f}s，manifest: {mpath}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--out")
    ap.add_argument("--storyboard")
    ap.add_argument("--workdir")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    if args.check:
        volc_ok = bool(cfg["volc"].get("appid") and cfg["volc"].get("token"))
        print(f"volc(豆包): {'已配置' if volc_ok else '未配置 (console.volcengine.com/speech 开通后写入 ' + CONFIG_PATH + ')'}")
        try:
            import edge_tts  # noqa: F401
            print(f"edge-tts: 已安装, voice={cfg['edge']['voice']}, proxy={cfg['edge'].get('proxy')}")
        except ImportError:
            print("edge-tts: 未安装 (pip install edge-tts)")
        return
    if args.text and args.out:
        backend, dur = synthesize(args.text, args.out, cfg)
        print(f"[{backend}] {dur:.2f}s -> {args.out}")
    elif args.storyboard and args.workdir:
        run_storyboard(args.storyboard, args.workdir)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
