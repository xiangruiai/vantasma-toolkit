#!/usr/bin/env bash
# xiangrui-video 一键体检 + 安装（开源用户首次使用入口）
# 用法: bash setup.sh          只体检
#       bash setup.sh --install 体检并自动安装缺失的必备依赖
set -uo pipefail
INSTALL=false; [[ "${1:-}" == "--install" ]] && INSTALL=true
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ok(){ printf "  ✅ %s\n" "$1"; }
miss(){ printf "  ❌ %s\n     ↳ %s\n" "$1" "$2"; }
opt(){ printf "  ⓘ  %s\n     ↳ %s\n" "$1" "$2"; }

echo "== 必备依赖 =="
# 1. ffmpeg 全功能版（需要 subtitles/drawtext 滤镜）
if /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -hide_banner -h filter=subtitles >/dev/null 2>&1; then
  ok "ffmpeg-full"
elif ffmpeg -hide_banner -h filter=subtitles >/dev/null 2>&1; then
  ok "ffmpeg（系统版含全滤镜）"
else
  miss "ffmpeg 全功能版" "brew install ffmpeg-full（或任何含 libass 的 ffmpeg 构建）"
  $INSTALL && brew install ffmpeg-full
fi
# 2. Node + 录制依赖
if command -v node >/dev/null; then ok "node $(node -v)"; else miss "node" "brew install node"; $INSTALL && brew install node; fi
if [[ -d "$SKILL_DIR/scripts/node_modules/puppeteer-core" && -d "$SKILL_DIR/scripts/node_modules/ws" ]]; then
  ok "puppeteer-core + ws"
else
  miss "puppeteer-core/ws（逐帧录制+播客TTS）" "cd scripts && npm install puppeteer-core ws"
  $INSTALL && (cd "$SKILL_DIR/scripts" && npm install --quiet puppeteer-core ws)
fi
# 3. Chrome
[[ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]] && ok "Google Chrome" || miss "Google Chrome" "场景渲染需要，请安装 Chrome"
# 4. Python 依赖
for mod in "edge_tts:edge-tts（免费TTS兜底）" "whisper:openai-whisper（字幕逐句对齐）" "tiktoken:tiktoken（token演示数据实测）"; do
  m="${mod%%:*}"; desc="${mod#*:}"
  if python3 -c "import ${m}" 2>/dev/null; then ok "$desc"
  else
    pkg="${m/_/-}"; [[ "$m" == "whisper" ]] && pkg="openai-whisper"
    miss "$desc" "python3 -m pip install --user --break-system-packages $pkg"
    $INSTALL && python3 -m pip install --user --break-system-packages --quiet "$pkg"
  fi
done
# 5. 音效库
[[ -f "$SKILL_DIR/assets/sfx/ding.wav" ]] && ok "音效库" || { miss "音效库" "python3 scripts/make_sfx.py"; $INSTALL && python3 "$SKILL_DIR/scripts/make_sfx.py"; }
# 6. 标题字体
[[ -f "$SKILL_DIR/assets/fonts/AlibabaPuHuiTi-Heavy.ttf" ]] && ok "阿里巴巴普惠 Heavy（已随 skill 附带，免费商用）" || miss "标题字体" "从 github.com/wordshub/free-font 下载 Alibaba-PuHuiTi-Heavy.ttf 放入 assets/fonts/"

echo ""
echo "== 可选增强（缺了有兜底，配了更强） =="
opt "品牌换皮" "编辑 ~/.config/xiangrui-video/config.json 的 brand 段（logo/水印/结尾搜索框文案）"
python3 -c "import sys,os; sys.path.insert(0,'$SKILL_DIR/scripts'); import tts; a,t=tts.podcast_creds(); print('  ✅ 火山播客TTS（最佳音质）' if a and t else '  ⓘ  火山播客TTS未配置\n     ↳ console.volcengine.com/speech 开通后存 env 或钥匙串（见 SKILL.md）；缺省走 edge-tts')"
command -v opencli >/dev/null && opt "opencli 已装（链接转视频抓公众号最稳）" "已就绪" || opt "opencli（链接转视频抓公众号）" "npm install -g @jackwener/opencli 并装浏览器扩展；缺省用 WebFetch/defuddle 兜底"
opt "seedream 生图（插画/底图）" "需火山方舟 API key；缺省用纯 CSS 设计，不影响出片"
opt "aihot 信源（AI资讯实时核实）" "安装与用法见 references/sources.md"
opt "WaytoAGI 知识库信源" "公开飞书 wiki，用 lark-wiki 读，见 references/sources.md"
python3 -c "import yt_dlp" 2>/dev/null && opt "yt-dlp（BGM 自动匹配 fetch_bgm.py）" "已就绪" || opt "yt-dlp（BGM 自动匹配）" "python3 -m pip install --user --break-system-packages yt-dlp；缺省无 BGM，不影响出片"
python3 -c "import pyJianYingDraft" 2>/dev/null && opt "pyjianyingdraft（导出剪映草稿精修）" "已就绪" || opt "pyjianyingdraft（导出剪映草稿）" "pip install pyjianyingdraft + 剪映专业版；缺省直接用成片，不影响出片"
[ -f "$SKILL_DIR/assets/vendor/gsap.min.js" ] && opt "GSAP 动画引擎（demo 高级动效）" "已附带" || opt "GSAP 动画引擎" "curl -sL https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js -o assets/vendor/gsap.min.js；缺省 demo 用 CSS 动画"
echo ""
echo "体检完成。必备项全 ✅ 即可出片：python3 scripts/tts.py --storyboard sb.json --workdir . && python3 scripts/render.py --storyboard sb.json --workdir ."
