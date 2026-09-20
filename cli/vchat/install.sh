#!/bin/bash
# vchat 安装脚本
#   1. 把 vchat 软链到 ~/.local/bin/
#   2. 提示 PATH 配置
#   3. 检测数据目录是否就绪
#   4. 提示可选依赖（whisper / silk-python，只有 voice transcribe 子命令需要）
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VCHAT="$SCRIPT_DIR/vchat"

if [ ! -f "$VCHAT" ]; then
  echo "❌ vchat 文件不存在: $VCHAT"
  exit 1
fi

# ───────────────────────────────────────────────────────────────
# 1. 装到 ~/.local/bin/
#    macOS / Linux: 软链到真实脚本
#    Windows (Git-Bash / MSYS / Cygwin): `ln -s` 会退化成复制，而复制品既丢
#    vchat_core 的 import 路径，`#!/usr/bin/env python3` 也解析不了（Windows 只装
#    python.exe）。所以 Windows 上改成一个 shim（可用 PYTHON=/path/to/python 覆盖）。
# ───────────────────────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
chmod +x "$VCHAT"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    PYTHON_BIN="${PYTHON:-$(command -v python3 || command -v python || true)}"
    if [ -z "$PYTHON_BIN" ]; then
      echo "❌ 没找到 python（Windows 上通常只装 python.exe，没有 python3）。"
      echo "   装好 Python 后重跑，或显式指定：PYTHON=/c/path/to/python.exe bash install.sh"
      exit 1
    fi
    # 关键：shim 里要写 Windows 能认的路径。Git-Bash 的 /c/Users/... 直接喂给
    # 原生 python.exe 会变成 C:\c\Users\... 而报 “No such file”。cygpath -m 转成
    # C:/Users/... （正斜杠，原生程序也认）。
    if command -v cygpath >/dev/null 2>&1; then
      PYTHON_WIN="$(cygpath -m "$PYTHON_BIN")"
      VCHAT_WIN="$(cygpath -m "$VCHAT")"
    else
      PYTHON_WIN="$PYTHON_BIN"
      VCHAT_WIN="$VCHAT"
    fi
    printf '#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n' "$PYTHON_WIN" "$VCHAT_WIN" > "$BIN_DIR/vchat"
    chmod +x "$BIN_DIR/vchat"
    echo "✅ 已生成 shim: $BIN_DIR/vchat → $PYTHON_WIN $VCHAT_WIN"
    ;;
  *)
    ln -sf "$VCHAT" "$BIN_DIR/vchat"
    echo "✅ vchat 已软链到 $BIN_DIR/vchat"
    ;;
esac

# ───────────────────────────────────────────────────────────────
# 2. PATH 检查
# ───────────────────────────────────────────────────────────────
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo ""
  echo "⚠️  ~/.local/bin 不在你的 PATH 中。"
  echo "    把下面这行加到 ~/.zshrc / ~/.bash_profile / ~/.bashrc 末尾:"
  echo ""
  echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ───────────────────────────────────────────────────────────────
# 3. 数据目录检测
#    优先级跟 vchat_core.get_data_dir() 一致：
#      VCHAT_DATA_DIR > WECHAT_DECRYPT_PATH > ~/.vchat/data > ~/Projects/wechat-decrypt
# ───────────────────────────────────────────────────────────────
DATA_DIR=""
for candidate in \
  "$VCHAT_DATA_DIR" \
  "$WECHAT_DECRYPT_PATH" \
  "$HOME/.vchat/data" \
  "$HOME/Projects/wechat-decrypt"; do
  if [ -n "$candidate" ] && [ -d "$candidate/decrypted" ]; then
    DATA_DIR="$candidate"
    break
  fi
done

echo ""
if [ -n "$DATA_DIR" ]; then
  DB_COUNT=$(find "$DATA_DIR/decrypted" -name "*.db" 2>/dev/null | wc -l | tr -d ' ')
  echo "✅ 检测到数据目录: $DATA_DIR ($DB_COUNT 个 db)"
else
  echo "⚠️  没找到已解密的微信数据。"
  echo ""
  echo "    vchat 只查询，不做解密。先用任意一个开源工具解密一次："
  echo "      · PyWxDump        https://github.com/xaoyaoo/PyWxDump"
  echo "      · wechat-decrypt  https://github.com/ylytdeng/wechat-decrypt"
  echo "      · WeChatMsg       https://github.com/LC044/WeChatMsg"
  echo ""
  echo "    然后把产物（含 decrypted/ 子目录）放到下面任一位置，或显式指定："
  echo "      export VCHAT_DATA_DIR=/path/to/your/data"
  echo ""
  echo "    Windows 微信 4.x 就地取密钥（4.1.8 起密钥不落内存，需挂钩派生现场）："
  echo "      python tools/win_key_capture.py --mode attach_all --seconds 900"
  echo "      vchat decrypt"
  echo ""
  echo "    期望的目录结构见 docs/DATA_LAYOUT.md。"
fi

# ───────────────────────────────────────────────────────────────
# 4. 可选依赖提示
# ───────────────────────────────────────────────────────────────
echo ""
if ! python3 -c "import zstandard" 2>/dev/null; then
  echo "ℹ️  推荐: zstandard（公众号文章 biz / 部分系统消息内容是 zstd 压缩的）"
  echo "      pip3 install zstandard"
fi
if ! python3 -c "import whisper" 2>/dev/null; then
  echo "ℹ️  可选: openai-whisper（仅 vchat voice transcribe 需要）"
  echo "      pip3 install openai-whisper"
fi
if ! python3 -c "import pysilk" 2>/dev/null; then
  echo "ℹ️  可选: silk-python（仅 vchat voice transcribe 需要）"
  echo "      pip3 install silk-python"
fi

# ───────────────────────────────────────────────────────────────
# 5. 验证
# ───────────────────────────────────────────────────────────────
echo ""
echo "▶ 验证安装："
"$VCHAT" --help 2>&1 | head -5

echo ""
echo "✅ 安装完成。"
echo ""
echo "▶ 数据目录没就绪？一键解密："
echo "    sudo vchat setup        # macOS · 自动 codesign + 解 17 个 db"
echo "    Windows 微信 4.x：python tools/win_key_capture.py --mode attach_all 然后 vchat decrypt"
echo ""
echo "▶ 已有数据目录，试试这些："
echo "    vchat doctor            # 检查数据完整性"
echo "    vchat ls 20             # 最近 20 个会话"
echo "    vchat --help            # 看全部 60+ 子命令"
echo ""
echo "▶ 装 shell completion (可选)："
echo "    bash: vchat completion bash > ~/.local/share/bash-completion/completions/vchat"
echo "    zsh:  vchat completion zsh  > \"\${fpath[1]}/_vchat\""
echo "    fish: vchat completion fish > ~/.config/fish/completions/vchat.fish"
