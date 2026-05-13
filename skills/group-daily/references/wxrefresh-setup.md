# wxrefresh + NOPASSWD 一次性配置（v2.3）

Step 0 要求每次跑日报前 `sudo -n wxrefresh` 强制刷新解密。`-n` 是 sudo 的 non-interactive 模式：没 NOPASSWD 就直接退出。所以 AI 想自动跑得满足两个前提：

1. 装好 `wxrefresh` 脚本（包装 `vchat decrypt`）
2. 给 `wxrefresh` 配 NOPASSWD

> 这是 macOS 特定流程。Windows / Linux 路径不同。

## 一、装 wxrefresh

`wxrefresh` 不在 skill 包里分发，是个独立的小脚本。建议放 `~/.local/bin/wxrefresh`：

```bash
#!/usr/bin/env bash
# wxrefresh — 一键刷新微信 4.x 解密 db（基于 vchat decrypt）
# 用法: sudo wxrefresh  或 sudo -n wxrefresh（NOPASSWD 已配时）
# 前提: WeChat 4.x 正在运行
set -euo pipefail

VCHAT_REAL="$(readlink -f "$(command -v vchat)" 2>/dev/null || true)"
STAMP="$HOME/.cache/wxrefresh.stamp"

if [[ $EUID -ne 0 ]]; then
    echo "需要 sudo（task_for_pid 要 root）：sudo wxrefresh" >&2
    exit 1
fi

if [[ -z "$VCHAT_REAL" || ! -x "$VCHAT_REAL" ]]; then
    echo "找不到 vchat。先按 cli/vchat/install.sh 装好。" >&2
    exit 1
fi

WX_PID=$(pgrep -f '/Applications/WeChat.app/Contents/MacOS/WeChat$' | head -1 || true)
if [[ -z "$WX_PID" ]]; then
    echo "WeChat 主进程没在跑，先打开微信再来一次" >&2
    exit 2
fi

echo "[1/2] 调 vchat decrypt 全量刷新…"
"$VCHAT_REAL" decrypt

# root 写出来的 keys.json / decrypted/ 归还原 user
REAL_USER="${SUDO_USER:-$USER}"
chown -R "$REAL_USER:staff" "/Users/$REAL_USER/.vchat/data" 2>/dev/null || true

mkdir -p "$(dirname "$STAMP")"
date +%s > "$STAMP"
chown "$REAL_USER:staff" "$STAMP" 2>/dev/null || true

echo "[2/2] 完成。stamp: $STAMP"
```

注意：`sudo` 默认重置 `$PATH`，所以脚本里要么用 `readlink -f $(command -v vchat)` 在 sudo 前解析路径（如上），要么显式写 vchat 绝对路径。

```bash
chmod +x ~/.local/bin/wxrefresh
```

## 二、配 NOPASSWD

写一个 sudoers 片段（**注意把 `<your-username>` 换成你的用户名**）：

```bash
cat > /tmp/wxrefresh_sudoers <<'EOF'
# Allow <your-username> to run wxrefresh without password.
<your-username> ALL=(root) NOPASSWD: /Users/<your-username>/.local/bin/wxrefresh
EOF
```

校验语法（不需要 sudo）：

```bash
'visudo' -c -f /tmp/wxrefresh_sudoers
```

装到 `/etc/sudoers.d/`（这一步需要 TouchID 一次，之后永久免密）：

```bash
sudo install -o root -g wheel -m 0440 /tmp/wxrefresh_sudoers /etc/sudoers.d/wxrefresh
```

验证生效：

```bash
sudo -n -l /Users/<your-username>/.local/bin/wxrefresh
# 输出绝对路径表示 NOPASSWD 生效；输出 "a password is required" 表示没生效
```

## 三、端到端 smoke test

```bash
sudo -n wxrefresh
cat ~/.cache/wxrefresh.stamp \
  && python3 -c "import time; t=int(open('$HOME/.cache/wxrefresh.stamp'.replace('\$HOME', __import__('os').path.expanduser('~'))).read()); print('stamp:', time.strftime('%F %T', time.localtime(t)), '·', int(time.time()-t),'秒前')"
vchat ls 3   # 看最新会话时间是否 ≈ 现在
```

## 四、安全模型

- NOPASSWD 范围**只针对 `wxrefresh` 这一个绝对路径**，不开放任意 sudo
- sudoers 走 `/etc/sudoers.d/wxrefresh`（root:wheel 0440），不污染主 `sudoers`
- wxrefresh 脚本本身在 user 家目录下，可被 user 自己改——这是用户已 admin 的本机，接受这个 TOCTOU 风险；要更严可把 wxrefresh 拷到 root-owned 路径（如 `/usr/local/sbin/wxrefresh`，0755 root:wheel）并改 sudoers 指它

## 五、卸载

```bash
sudo rm /etc/sudoers.d/wxrefresh
rm ~/.local/bin/wxrefresh ~/.cache/wxrefresh.stamp
```
