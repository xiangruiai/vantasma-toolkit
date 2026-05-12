#!/bin/bash
# group-daily skill 一键安装 Python 依赖 + 跑环境自检
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "▶ 装必装 Python 依赖..."
pip3 install --quiet Pillow --break-system-packages 2>&1 | tail -3 || pip3 install --quiet Pillow

echo "▶ 装可选 Python 依赖（语音转写用，跳过失败不影响主流程）..."
pip3 install --quiet openai-whisper silk-python --break-system-packages 2>&1 | tail -3 || true

echo ""
echo "▶ 跑环境自检..."
python3 "$SCRIPT_DIR/scripts/check_env.py"

echo ""
echo "▶ 提示："
echo "  - 如果环境自检有 ❌，按提示修复后重跑 install.sh"
echo "  - 如果想把 styles 存到 Obsidian Vault 里，设置环境变量:"
echo "      export GROUP_DAILY_VAULT=/path/to/your/vault"
echo "    并写到 ~/.zshrc 持久化"
echo ""
echo "✅ 安装结束。在 Claude Code 里说「给 XX 群做群日报」即可触发。"
