#!/bin/bash
# group-activity-base skill 依赖检查 + 安装
set -e

echo "▶ 检查 Python 依赖..."
python3 -c "import zstandard" 2>/dev/null && echo "  ✅ zstandard" || {
  echo "  ⏳ 安装 zstandard..."
  pip3 install --quiet zstandard --break-system-packages 2>/dev/null || pip3 install --quiet zstandard
  echo "  ✅ zstandard 已安装"
}

echo ""
echo "▶ 检查 vchat（微信本地数据 CLI）..."
if command -v vchat >/dev/null 2>&1; then
  echo "  ✅ vchat 已安装: $(command -v vchat)"
  vchat ls 1 >/dev/null 2>&1 && echo "  ✅ vchat 数据可读" || echo "  ⚠️  vchat 装了但读不到数据，先按 cli/vchat/README.md 完成微信本地库解密"
else
  echo "  ❌ 未安装。本仓库自带："
  echo "     cd <仓库根>/cli/vchat && ./install.sh"
fi

echo ""
echo "▶ 检查 lark-cli（飞书官方 CLI）..."
if command -v lark-cli >/dev/null 2>&1; then
  echo "  ✅ lark-cli 已安装: $(lark-cli --version 2>/dev/null | head -1)"
  echo "  ℹ️  如未授权，运行: lark-cli auth && lark-cli doctor"
else
  echo "  ❌ 未安装。运行："
  echo "     npm i -g @larksuite/cli && lark-cli auth"
fi

echo ""
echo "▶ 检查环境变量..."
if [ -n "$GAB_SELF_NAME" ]; then
  echo "  ✅ GAB_SELF_NAME=$GAB_SELF_NAME"
else
  echo "  ⚠️  未设置 GAB_SELF_NAME（你自己的显示名，vchat 里本人是 \"me\"）"
  echo "     export GAB_SELF_NAME=\"你的名字\"   # 写进 ~/.zshrc"
fi

echo ""
echo "✅ 检查结束。全绿后把本目录拷到 ~/.claude/skills/ 并重启 Claude Code，"
echo "   说「做 XX 群的活跃度表」即可触发。"
