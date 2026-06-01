#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════
# 🦞 didi-ride-skill — 一键安装器
# ═══════════════════════════════════════════════════════════
#
# 两种安装方式：
#
#   方式 1 — 远程安装（推荐分享给他人）:
#     zsh <(curl -fsSL https://raw.githubusercontent.com/Larkin0302/didi-ride-skill/main/install.sh)
#
#   方式 2 — 本地安装（clone 后执行）:
#     git clone https://github.com/Larkin0302/didi-ride-skill ~/.openclaw/skills/didi-ride
#     zsh ~/.openclaw/skills/didi-ride/install.sh
#
set -euo pipefail

# ─── 捕获脚本路径 ────────────────────────────────────────
SCRIPT_PATH="${0:A}"
SCRIPT_DIR="${SCRIPT_PATH:h}"

# ─── 常量 ────────────────────────────────────────────────
SKILL_NAME="didi-ride"
SKILL_DST="$HOME/.openclaw/skills/$SKILL_NAME"
PLUGIN_SPEC="@larksuiteoapi/feishu-openclaw-plugin"
PLUGIN_ID="feishu-openclaw-plugin"
STOCK_PLUGIN_ID="feishu"
REPO_URL="${DIDI_RIDE_REPO:-https://github.com/Larkin0302/didi-ride-skill.git}"
CONFIG="$HOME/.openclaw/openclaw.json"
MIN_PLUGIN_VERSION="2026.3.0"

# ─── 颜色 ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
ok()   { echo "${GREEN}✓${NC} $1"; }
warn() { echo "${YELLOW}⚠${NC} $1"; }
fail() { echo "${RED}✗${NC} $1"; }
info() { echo "${CYAN}→${NC} $1"; }

# ─── 辅助：读 openclaw.json ──────────────────────────────
_read_config() {
    python3 -c "
import json, sys
try:
    with open('$CONFIG') as f:
        cfg = json.load(f)
except:
    print('no_config'); sys.exit(0)

q = sys.argv[1]
if q == 'plugin_installed':
    print('yes' if sys.argv[2] in cfg.get('plugins', {}).get('installs', {}) else 'no')
elif q == 'plugin_enabled':
    print('yes' if cfg.get('plugins', {}).get('entries', {}).get(sys.argv[2], {}).get('enabled', True) else 'no')
elif q == 'plugin_version':
    ver = cfg.get('plugins', {}).get('installs', {}).get(sys.argv[2], {}).get('resolvedVersion', '')
    print(ver)
elif q == 'has_credentials':
    f = cfg.get('channels', {}).get('feishu', {})
    print('yes' if f.get('appId') and f.get('appSecret') else 'no')
elif q == 'has_env':
    val = cfg.get('env', {}).get(sys.argv[2], '')
    print('yes' if val else 'no')
elif q == 'get_env':
    val = cfg.get('env', {}).get(sys.argv[2], '')
    print(val)
elif q == 'current_model':
    print(cfg.get('agents', {}).get('defaults', {}).get('model', ''))
elif q == 'timeout':
    print(cfg.get('agents', {}).get('defaults', {}).get('timeoutSeconds', 0))
" "$@" 2>/dev/null
}

_version_ge() {
    python3 -c "
v1 = [int(x) for x in '$1'.split('.')]
v2 = [int(x) for x in '$2'.split('.')]
while len(v1) < 3: v1.append(0)
while len(v2) < 3: v2.append(0)
print('yes' if v1 >= v2 else 'no')
" 2>/dev/null
}

# ─── 判断运行模式 ────────────────────────────────────────
detect_mode() {
    if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/skill/SKILL.md" ]; then
        SKILL_SRC="$SCRIPT_DIR"
        MODE="local"
    elif [ -f "$(pwd)/skill/SKILL.md" ]; then
        SKILL_SRC="$(pwd)"
        MODE="local"
    else
        MODE="remote"
    fi
}

# ═══════════════════════════════════════════════════════════
# [1/7] 部署技能文件
# ═══════════════════════════════════════════════════════════
deploy_skill() {
    echo ""
    echo "${BOLD}[1/7] 部署 didi-ride 技能${NC}"
    echo ""

    if [ "$MODE" = "local" ]; then
        if [ "$SKILL_SRC" = "$SKILL_DST" ]; then
            ok "技能已在目标位置，无需复制"
        else
            mkdir -p "$HOME/.openclaw/skills"
            [ -d "$SKILL_DST" ] && rm -rf "$SKILL_DST"
            cp -R "$SKILL_SRC" "$SKILL_DST"
            ok "技能已部署到 $SKILL_DST"
        fi
    else
        if ! command -v git &>/dev/null; then
            fail "git 未安装，无法远程安装"
            exit 1
        fi
        mkdir -p "$HOME/.openclaw/skills"
        if [ -d "$SKILL_DST" ]; then
            info "更新已有技能..."
            (cd "$SKILL_DST" && git pull --ff-only 2>/dev/null) && ok "技能已更新" || {
                warn "git pull 失败，重新 clone"
                rm -rf "$SKILL_DST"
                git clone "$REPO_URL" "$SKILL_DST"
                ok "技能已重新部署"
            }
        else
            info "从 GitHub clone..."
            git clone "$REPO_URL" "$SKILL_DST"
            ok "技能已部署"
        fi
    fi

    # 验证关键文件
    local missing=0
    for f in skill/SKILL.md src/client.js src/cards.js src/handler.js src/register.js; do
        if [ ! -f "$SKILL_DST/$f" ]; then
            fail "缺少文件: $f"
            missing=1
        fi
    done
    [ $missing -eq 0 ] && ok "关键文件验证通过"
}

# ═══════════════════════════════════════════════════════════
# [2/7] 飞书官方插件（自动安装 / 自动更新）
# ═══════════════════════════════════════════════════════════
install_plugin() {
    echo ""
    echo "${BOLD}[2/7] 飞书官方插件${NC}"
    echo ""

    if ! command -v openclaw &>/dev/null; then
        fail "openclaw 未安装，跳过插件管理"
        warn "请先安装 OpenClaw: https://openclaw.com"
        return 0
    fi

    local installed=$(_read_config plugin_installed "$PLUGIN_ID")

    if [ "$installed" = "yes" ]; then
        local current_ver=$(_read_config plugin_version "$PLUGIN_ID")
        if [ -n "$current_ver" ]; then
            local is_ge=$(_version_ge "$current_ver" "$MIN_PLUGIN_VERSION")
            if [ "$is_ge" = "yes" ]; then
                ok "飞书官方插件已安装 (v$current_ver)"
            else
                info "当前版本 v$current_ver 低于要求的 v$MIN_PLUGIN_VERSION，自动更新..."
                if openclaw plugins install "$PLUGIN_SPEC" 2>&1 | tail -3; then
                    local new_ver=$(_read_config plugin_version "$PLUGIN_ID")
                    ok "插件已更新到 v${new_ver:-latest}"
                else
                    warn "自动更新失败，请手动执行: openclaw plugins install $PLUGIN_SPEC"
                fi
            fi
        else
            ok "飞书官方插件已安装（无法读取版本号）"
        fi
        openclaw plugins enable "$PLUGIN_ID" &>/dev/null || true
    else
        info "飞书官方插件未安装，自动安装中..."
        if openclaw plugins install "$PLUGIN_SPEC" 2>&1 | tail -5; then
            local new_ver=$(_read_config plugin_version "$PLUGIN_ID")
            ok "飞书官方插件安装成功 (v${new_ver:-latest})"
        else
            fail "安装失败"
            echo ""
            echo "  请手动执行:"
            echo "    openclaw plugins install $PLUGIN_SPEC"
            echo ""
        fi
    fi

    # 禁用 stock feishu 插件（避免冲突）
    local stock_enabled=$(_read_config plugin_enabled "$STOCK_PLUGIN_ID")
    if [ "$stock_enabled" != "no" ]; then
        openclaw plugins disable "$STOCK_PLUGIN_ID" &>/dev/null 2>&1 || {
            python3 -c "
import json
try:
    with open('$CONFIG', 'r') as f: cfg = json.load(f)
    cfg.setdefault('plugins', {}).setdefault('entries', {})['$STOCK_PLUGIN_ID'] = {'enabled': False}
    with open('$CONFIG', 'w') as f: json.dump(cfg, f, indent=2, ensure_ascii=False)
except: pass
" 2>/dev/null
        }
        ok "Stock feishu 插件已禁用（避免冲突）"
    else
        ok "Stock feishu 插件已是禁用状态"
    fi
}

# ═══════════════════════════════════════════════════════════
# [3/7] 部署工具代码到插件目录 + Patch
# ═══════════════════════════════════════════════════════════
deploy_and_patch() {
    echo ""
    echo "${BOLD}[3/7] 部署工具代码 + Patch 插件${NC}"
    echo ""

    local PLUGIN_DIR="$HOME/.openclaw/extensions/$PLUGIN_ID"
    local TOOL_DIR="$PLUGIN_DIR/src/tools/didi-ride"
    local INDEX_FILE="$PLUGIN_DIR/index.js"
    local MONITOR_FILE="$PLUGIN_DIR/src/channel/monitor.js"

    if [ ! -d "$PLUGIN_DIR" ]; then
        fail "插件目录不存在: $PLUGIN_DIR"
        warn "请确认飞书插件已安装成功"
        return 1
    fi

    # --- 复制 4 个 JS 文件 ---
    info "复制工具代码..."
    mkdir -p "$TOOL_DIR"
    cp "$SKILL_DST/src/client.js"   "$TOOL_DIR/"
    cp "$SKILL_DST/src/cards.js"    "$TOOL_DIR/"
    cp "$SKILL_DST/src/handler.js"  "$TOOL_DIR/"
    cp "$SKILL_DST/src/register.js" "$TOOL_DIR/"
    ok "工具代码已部署到 $TOOL_DIR"

    # --- Patch index.js: import ---
    if [ -f "$INDEX_FILE" ]; then
        if grep -q 'didi-ride/register.js' "$INDEX_FILE"; then
            ok "index.js import 已存在，跳过"
        else
            info "Patch index.js: 添加 import..."
            sed -i.bak '/^import { trace } from "\.\/src\/core\/trace\.js";/a\
import { registerDiDiRideTool } from "./src/tools/didi-ride/register.js";' "$INDEX_FILE"
            rm -f "$INDEX_FILE.bak"
            ok "index.js import 已添加"
        fi

        # --- Patch index.js: register call ---
        if grep -q 'registerDiDiRideTool(api)' "$INDEX_FILE"; then
            ok "index.js 注册调用已存在，跳过"
        else
            info "Patch index.js: 添加注册调用..."
            sed -i.bak '/registerFeishuOAuthBatchAuthTool(api);/a\
        // Register DiDi ride tool (query pricing + send interactive card)\
        registerDiDiRideTool(api);' "$INDEX_FILE"
            rm -f "$INDEX_FILE.bak"
            ok "index.js 注册调用已添加"
        fi
    else
        warn "index.js 不存在，跳过 patch（请手动注册工具）"
    fi

    # --- Patch monitor.js: card action routing ---
    if [ -f "$MONITOR_FILE" ]; then
        if grep -q 'action.startsWith("didi_")' "$MONITOR_FILE"; then
            ok "monitor.js 路由已存在，跳过"
        else
            info "Patch monitor.js: 添加 didi_ 卡片路由..."
            sed -i.bak '/\"card\.action\.trigger\":/,/return await handleCardAction/ {
                /return await handleCardAction/i\
                    const action = data?.action?.value?.action;\
                    if (typeof action === "string" \&\& action.startsWith("didi_")) {\
                        const { handleDiDiCardAction } = await import("../tools/didi-ride/handler.js");\
                        return await handleDiDiCardAction(data, cfg, accountId);\
                    }
            }' "$MONITOR_FILE"
            rm -f "$MONITOR_FILE.bak"
            ok "monitor.js 路由已添加"
        fi
    else
        warn "monitor.js 不存在，跳过 patch（请手动添加卡片路由）"
    fi
}

# ═══════════════════════════════════════════════════════════
# [4/7] 配置飞书凭据
# ═══════════════════════════════════════════════════════════
configure_credentials() {
    echo ""
    echo "${BOLD}[4/7] 飞书凭据${NC}"
    echo ""

    if [ ! -f "$CONFIG" ]; then
        warn "openclaw.json 不存在，跳过"
        return 0
    fi

    local has_creds=$(_read_config has_credentials)
    if [ "$has_creds" = "yes" ]; then
        ok "飞书凭据: 已配置"
    else
        warn "飞书凭据未配置"
        echo ""

        if [ -t 0 ]; then
            echo "  是否现在配置飞书凭据？(y/n)"
            read -r answer
            if [[ "$answer" =~ ^[Yy] ]]; then
                echo ""
                echo -n "  飞书 App ID: "
                read -r app_id
                echo -n "  飞书 App Secret: "
                read -r app_secret

                if [ -n "$app_id" ] && [ -n "$app_secret" ]; then
                    python3 -c "
import json
with open('$CONFIG', 'r') as f: cfg = json.load(f)
feishu = cfg.setdefault('channels', {}).setdefault('feishu', {})
feishu['appId'] = '$app_id'
feishu['appSecret'] = '$app_secret'
feishu.setdefault('enabled', True)
feishu.setdefault('domain', 'feishu')
feishu.setdefault('connectionMode', 'websocket')
feishu.setdefault('streaming', True)
feishu.setdefault('blockStreaming', True)
feishu.setdefault('dmPolicy', 'open')
feishu.setdefault('allowFrom', ['*'])
with open('$CONFIG', 'w') as f: json.dump(cfg, f, indent=2, ensure_ascii=False)
" 2>/dev/null
                    ok "飞书凭据已写入配置"
                else
                    warn "输入为空，跳过"
                fi
            fi
        else
            echo "  请在 ~/.openclaw/openclaw.json 中配置:"
            echo ""
            echo "    \"channels\": {"
            echo "      \"feishu\": {"
            echo "        \"appId\": \"你的飞书应用 App ID\","
            echo "        \"appSecret\": \"你的飞书应用 App Secret\""
            echo "      }"
            echo "    }"
            echo ""
        fi
    fi
}

# ═══════════════════════════════════════════════════════════
# [5/7] 配置滴滴 MCP API Key
# ═══════════════════════════════════════════════════════════
configure_didi_key() {
    echo ""
    echo "${BOLD}[5/7] 滴滴 MCP API Key${NC}"
    echo ""

    if [ ! -f "$CONFIG" ]; then
        warn "openclaw.json 不存在，跳过"
        return 0
    fi

    local has_key=$(_read_config has_env "DIDI_MCP_KEY")
    if [ "$has_key" = "yes" ]; then
        local key_val=$(_read_config get_env "DIDI_MCP_KEY")
        ok "DIDI_MCP_KEY 已配置 (${key_val:0:8}...)"
    else
        warn "DIDI_MCP_KEY 未配置"
        echo ""
        echo "  申请地址: ${CYAN}https://mcp.didichuxing.com${NC}"
        echo ""

        if [ -t 0 ]; then
            echo -n "  请输入你的 DIDI_MCP_KEY（留空跳过）: "
            read -r didi_key

            if [ -n "$didi_key" ]; then
                python3 -c "
import json
with open('$CONFIG', 'r') as f: cfg = json.load(f)
cfg.setdefault('env', {})['DIDI_MCP_KEY'] = '$didi_key'
with open('$CONFIG', 'w') as f: json.dump(cfg, f, indent=2, ensure_ascii=False)
" 2>/dev/null
                ok "DIDI_MCP_KEY 已写入 openclaw.json"
            else
                warn "跳过，稍后可手动在 openclaw.json 的 env 中添加 DIDI_MCP_KEY"
            fi
        else
            echo "  请在 ~/.openclaw/openclaw.json 的 env 中添加:"
            echo ""
            echo "    \"env\": {"
            echo "      \"DIDI_MCP_KEY\": \"你的API Key\""
            echo "    }"
            echo ""
        fi
    fi

    echo ""
    info "默认使用沙箱模式（模拟数据，不产生真实订单）"
    info "切到正式环境: 编辑 src/client.js 将 DIDI_DEBUG_MODE 改为 false"
}

# ═══════════════════════════════════════════════════════════
# [6/7] 模型与超时配置
# ═══════════════════════════════════════════════════════════
configure_model() {
    echo ""
    echo "${BOLD}[6/7] 模型与超时配置${NC}"
    echo ""

    if [ ! -f "$CONFIG" ]; then
        warn "openclaw.json 不存在，跳过"
        return 0
    fi

    # 超时（打车流程较快，120s 足够）
    local timeout=$(_read_config timeout)
    if [ -n "$timeout" ] && [ "$timeout" -ge 120 ] 2>/dev/null; then
        ok "超时配置: ${timeout}s"
    else
        info "设置超时为 600s..."
        python3 -c "
import json
with open('$CONFIG', 'r') as f: cfg = json.load(f)
cfg.setdefault('agents', {}).setdefault('defaults', {})['timeoutSeconds'] = 600
with open('$CONFIG', 'w') as f: json.dump(cfg, f, indent=2, ensure_ascii=False)
" 2>/dev/null
        ok "超时已设置为 600s"
    fi

    # 模型推荐
    local current_model=$(_read_config current_model)
    echo ""
    if [ -n "$current_model" ]; then
        info "当前模型: $current_model"
    else
        info "当前模型: 未配置"
    fi

    local RECOMMENDED_MODELS=("claude-opus-4-6" "claude-sonnet-4-6")
    local model_ok=false
    for rm in "${RECOMMENDED_MODELS[@]}"; do
        if [[ "$current_model" == *"$rm"* ]]; then
            model_ok=true
            break
        fi
    done

    if $model_ok; then
        ok "模型能力足够"
    else
        warn "建议使用 claude-opus-4-6 或 claude-sonnet-4-6"
        echo ""
        echo "  ${DIM}打车技能需要较强的指令遵循能力。${NC}"
        echo "  ${DIM}修改: 编辑 ~/.openclaw/openclaw.json 中的 agents.defaults.model${NC}"
        echo ""
    fi
}

# ═══════════════════════════════════════════════════════════
# [7/7] 重启 Gateway
# ═══════════════════════════════════════════════════════════
restart_gateway() {
    echo ""
    echo "${BOLD}[7/7] 重启 Gateway${NC}"
    echo ""

    if ! command -v openclaw &>/dev/null; then
        warn "openclaw 未找到，请手动重启 gateway"
        return 0
    fi

    info "重启 gateway 使所有配置生效..."
    if openclaw gateway restart 2>&1 | tail -3; then
        ok "Gateway 已重启"
    else
        warn "重启失败，请手动执行: openclaw gateway restart"
    fi
}

# ═══════════════════════════════════════════════════════════
# 状态报告
# ═══════════════════════════════════════════════════════════
report() {
    echo ""
    echo "═══════════════════════════════════════════"
    echo ""
    ok "${BOLD}安装完成！${NC}"
    echo ""
    echo "  ${BOLD}使用方式：${NC}"
    echo "    在飞书中对龙虾说「帮我叫个车从A到B」→ 自动查价 + 交互卡片"
    echo "    在卡片上点按钮 → 叫车 / 刷新状态 / 取消订单"
    echo ""

    # 汇总待处理事项
    local todos=0
    if [ "$(_read_config has_credentials)" != "yes" ]; then
        echo "  ${YELLOW}⚠ 还需配置飞书凭据（appId + appSecret）${NC}"
        todos=$((todos+1))
    fi
    if [ "$(_read_config has_env DIDI_MCP_KEY)" != "yes" ]; then
        echo "  ${YELLOW}⚠ 还需配置 DIDI_MCP_KEY（https://mcp.didichuxing.com）${NC}"
        todos=$((todos+1))
    fi

    local current_model=$(_read_config current_model)
    local model_ok=false
    for rm in "claude-opus-4-6" "claude-sonnet-4-6"; do
        if [[ "$current_model" == *"$rm"* ]]; then
            model_ok=true
            break
        fi
    done
    if ! $model_ok; then
        echo "  ${YELLOW}⚠ 建议将模型切换为 claude-opus-4-6 或 claude-sonnet-4-6${NC}"
        todos=$((todos+1))
    fi

    if [ $todos -eq 0 ]; then
        echo "  ${GREEN}所有配置就绪，可以直接在飞书中使用！${NC}"
    fi
    echo ""

    echo "  ${DIM}更新技能: cd ~/.openclaw/skills/didi-ride && git pull${NC}"
    echo "  ${DIM}卸载技能: zsh ~/.openclaw/skills/didi-ride/uninstall.sh${NC}"
    echo "  ${DIM}问题反馈: https://github.com/Larkin0302/didi-ride-skill/issues${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
main() {
    echo ""
    echo "╔═══════════════════════════════════════════╗"
    echo "║   🦞 滴滴打车技能 — 一键安装器            ║"
    echo "╚═══════════════════════════════════════════╝"

    if ! command -v python3 &>/dev/null; then
        fail "python3 未安装"
        exit 1
    fi

    detect_mode
    info "安装模式: $MODE"

    deploy_skill            # 1. 部署技能文件
    install_plugin          # 2. 飞书插件自动安装/更新
    deploy_and_patch        # 3. 部署工具代码 + Patch 插件
    configure_credentials   # 4. 飞书凭据
    configure_didi_key      # 5. 滴滴 API Key
    configure_model         # 6. 模型与超时
    restart_gateway         # 7. 自动重启 gateway

    report
}

main "$@"
