#!/bin/bash
# group-activity-base skill 依赖检查 + 自动安装（每一步都先征求同意）
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

ask() {  # ask "提示语" && 同意返回0
  read -r -p "$1 [y/N] " reply
  [[ "$reply" == "y" || "$reply" == "Y" ]]
}

echo "▶ 0/4 检查微信版本（vchat 只支持 macOS 微信 4.x）..."
WXV=$(defaults read /Applications/WeChat.app/Contents/Info.plist CFBundleShortVersionString 2>/dev/null || echo "未安装")
case "$WXV" in
  4.*) echo "  ✅ 微信 $WXV（4.x，支持）" ;;
  未安装) echo "  ❌ 未检测到 /Applications/WeChat.app" ;;
  *) echo "  ❌ 微信 $WXV 不支持（需要 4.x；3.x 数据库结构完全不同）" ;;
esac

echo ""
echo "▶ 1/4 检查 Python 依赖 zstandard..."
if python3 -c "import zstandard" 2>/dev/null; then
  echo "  ✅ zstandard"
else
  if ask "  缺 zstandard，现在 pip3 安装？"; then
    pip3 install --quiet zstandard --break-system-packages 2>/dev/null || pip3 install --quiet zstandard
    echo "  ✅ 已安装"
  else
    echo "  ⏭  跳过（脚本运行时会报错，记得手动装）"
  fi
fi

echo ""
echo "▶ 2/4 检查 vchat（微信本地数据 CLI）..."
if command -v vchat >/dev/null 2>&1; then
  echo "  ✅ vchat 已安装: $(command -v vchat)"
  if vchat ls 1 >/dev/null 2>&1; then
    echo "  ✅ vchat 数据可读"
  else
    echo "  ⚠️  vchat 装了但读不到数据。首次使用需解密微信本地库："
    echo "      sudo vchat setup     （原理与安全说明见 cli/vchat/README.md）"
  fi
else
  if [ -f "$REPO_ROOT/cli/vchat/install.sh" ] && ask "  未安装 vchat，用本仓库 cli/vchat/install.sh 安装？"; then
    (cd "$REPO_ROOT/cli/vchat" && ./install.sh)
  else
    echo "  ⏭  跳过。手动安装：cd <仓库根>/cli/vchat && ./install.sh"
  fi
fi

echo ""
echo "▶ 3/4 检查 lark-cli（飞书官方 CLI）..."
if command -v lark-cli >/dev/null 2>&1; then
  echo "  ✅ lark-cli 已安装: $(lark-cli --version 2>/dev/null | head -1)"
  echo "  ℹ️  如未授权，运行: lark-cli auth && lark-cli doctor"
else
  if command -v npm >/dev/null 2>&1 && ask "  未安装 lark-cli，现在 npm i -g @larksuite/cli 安装？"; then
    npm i -g @larksuite/cli
    echo "  ✅ 已安装。接着完成授权: lark-cli auth && lark-cli doctor"
  else
    echo "  ⏭  跳过。手动安装：npm i -g @larksuite/cli && lark-cli auth"
  fi
fi

echo ""
echo "▶ 4/4 检查环境变量..."
if [ -n "$GAB_SELF_NAME" ]; then
  echo "  ✅ GAB_SELF_NAME=$GAB_SELF_NAME"
else
  echo "  ⚠️  未设置 GAB_SELF_NAME（你自己的显示名，vchat 里本人是 \"me\"）"
  echo "     export GAB_SELF_NAME=\"你的名字\"   # 写进 ~/.zshrc"
fi

echo ""
echo "✅ 检查结束。全绿后把本目录拷到 ~/.claude/skills/ 并重启 Claude Code，"
echo "   说“做 XX 群的活跃度表”即可触发。"
