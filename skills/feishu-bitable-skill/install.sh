#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════
# 飞书多维表格技能 — 一键安装器 v2
# ═══════════════════════════════════════════════════════════
#
# 两种安装方式：
#
#   方式 1 — 远程安装（推荐分享给他人）:
#     zsh <(curl -fsSL https://raw.githubusercontent.com/Larkin0302/feishu-bitable-skill/main/install.sh)
#
#   方式 2 — 本地安装（clone 后执行）:
#     git clone https://github.com/Larkin0302/feishu-bitable-skill ~/.openclaw/skills/feishu-bitable
#     zsh ~/.openclaw/skills/feishu-bitable/install.sh
#
set -euo pipefail

# ─── 捕获脚本路径（必须在函数定义之前）────────────────────
SCRIPT_PATH="${0:A}"
SCRIPT_DIR="${SCRIPT_PATH:h}"

# ─── 常量 ────────────────────────────────────────────────
SKILL_NAME="feishu-bitable"
SKILL_DST="$HOME/.openclaw/skills/$SKILL_NAME"
PLUGIN_SPEC="@larksuiteoapi/feishu-openclaw-plugin"
PLUGIN_ID="feishu-openclaw-plugin"
STOCK_PLUGIN_ID="feishu"
REPO_URL="${FEISHU_BITABLE_REPO:-https://github.com/Larkin0302/feishu-bitable-skill.git}"
CONFIG="$HOME/.openclaw/openclaw.json"
MIN_PLUGIN_VERSION="2026.3.0"

# ─── 颜色 ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
ok()   { echo "${GREEN}✓${NC} $1"; }
warn() { echo "${YELLOW}⚠${NC} $1"; }
fail() { echo "${RED}✗${NC} $1"; }
info() { echo "${CYAN}→${NC} $1"; }

# ─── 辅助：读/写 openclaw.json ───────────────────────────
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
elif q == 'current_model':
    print(cfg.get('agents', {}).get('defaults', {}).get('model', ''))
elif q == 'has_model':
    models = cfg.get('models', {}).get('providers', {})
    for prov in models.values():
        for m in prov.get('models', []):
            if m.get('id') == sys.argv[2]:
                print('yes'); sys.exit(0)
    print('no')
elif q == 'timeout':
    print(cfg.get('agents', {}).get('defaults', {}).get('timeoutSeconds', 0))
" "$@" 2>/dev/null
}

_version_ge() {
    # $1 >= $2 ?  (语义版本比较)
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
    if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/SKILL.md" ]; then
        SKILL_SRC="$SCRIPT_DIR"
        MODE="local"
    elif [ -f "$(pwd)/SKILL.md" ]; then
        SKILL_SRC="$(pwd)"
        MODE="local"
    else
        MODE="remote"
    fi
}

# ═══════════════════════════════════════════════════════════
# 步骤 1: 部署技能文件
# ═══════════════════════════════════════════════════════════
deploy_skill() {
    echo ""
    echo "${BOLD}[1/6] 部署 feishu-bitable 技能${NC}"
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
    for f in SKILL.md scripts/create_bitable_template.py scripts/feishu_common.py; do
        if [ ! -f "$SKILL_DST/$f" ]; then
            fail "缺少文件: $f"
            missing=1
        fi
    done
    [ $missing -eq 0 ] && ok "关键文件验证通过"
}

# ═══════════════════════════════════════════════════════════
# 步骤 2: 飞书官方插件（自动安装 / 自动更新）
# ═══════════════════════════════════════════════════════════
install_plugin() {
    echo ""
    echo "${BOLD}[2/6] 飞书官方插件${NC}"
    echo ""

    if ! command -v openclaw &>/dev/null; then
        fail "openclaw 未安装，跳过插件管理"
        warn "请先安装 OpenClaw: https://openclaw.com"
        return 0
    fi

    local installed=$(_read_config plugin_installed "$PLUGIN_ID")

    if [ "$installed" = "yes" ]; then
        # 已安装 → 检查版本是否需要更新
        local current_ver=$(_read_config plugin_version "$PLUGIN_ID")
        if [ -n "$current_ver" ]; then
            local is_ge=$(_version_ge "$current_ver" "$MIN_PLUGIN_VERSION")
            if [ "$is_ge" = "yes" ]; then
                ok "飞书官方插件已安装 (v$current_ver) — 版本满足要求"
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
        # 确保启用
        openclaw plugins enable "$PLUGIN_ID" &>/dev/null || true
    else
        # 未安装 → 自动安装
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
# 步骤 3: 配置工具策略（屏蔽 App 级创建）
# ═══════════════════════════════════════════════════════════
configure_tools() {
    echo ""
    echo "${BOLD}[3/6] 配置工具策略${NC}"
    echo ""

    if [ ! -f "$CONFIG" ]; then
        warn "openclaw.json 不存在，跳过"
        return 0
    fi

    python3 -c "
import json
with open('$CONFIG', 'r') as f: cfg = json.load(f)
deny = cfg.setdefault('tools', {}).setdefault('deny', [])
if 'feishu_bitable_app' not in deny:
    deny.append('feishu_bitable_app')
    with open('$CONFIG', 'w') as f: json.dump(cfg, f, indent=2, ensure_ascii=False)
    print('added')
else:
    print('exists')
" 2>/dev/null

    ok "已屏蔽 feishu_bitable_app 工具（防止 API 创建带默认字段）"
    info "保留: record / field / view / table（日常 CRUD 不受影响）"
}

# ═══════════════════════════════════════════════════════════
# 步骤 4: 模型与超时配置
# ═══════════════════════════════════════════════════════════
configure_model() {
    echo ""
    echo "${BOLD}[4/6] 模型与超时配置${NC}"
    echo ""

    if [ ! -f "$CONFIG" ]; then
        warn "openclaw.json 不存在，跳过"
        return 0
    fi

    # 检查超时配置
    local timeout=$(_read_config timeout)
    if [ -n "$timeout" ] && [ "$timeout" -ge 600 ] 2>/dev/null; then
        ok "超时配置: ${timeout}s — 满足要求（≥600s）"
    else
        info "设置超时为 3600s（搭建多维表格需要较长时间）..."
        python3 -c "
import json
with open('$CONFIG', 'r') as f: cfg = json.load(f)
cfg.setdefault('agents', {}).setdefault('defaults', {})['timeoutSeconds'] = 3600
with open('$CONFIG', 'w') as f: json.dump(cfg, f, indent=2, ensure_ascii=False)
" 2>/dev/null
        ok "超时已设置为 3600s"
    fi

    # 检查当前模型
    local current_model=$(_read_config current_model)
    echo ""
    if [ -n "$current_model" ]; then
        info "当前模型: $current_model"
    else
        info "当前模型: 未配置"
    fi

    # 推荐模型列表
    local RECOMMENDED_MODELS=("claude-opus-4-6" "claude-sonnet-4-6")
    local model_ok=false
    for rm in "${RECOMMENDED_MODELS[@]}"; do
        if [[ "$current_model" == *"$rm"* ]]; then
            model_ok=true
            break
        fi
    done

    if $model_ok; then
        ok "模型推荐: 当前模型能力足够，无需修改"
    else
        warn "模型建议: 推荐使用 claude-opus-4-6 或 claude-sonnet-4-6"
        echo ""
        echo "  ${DIM}当前模型: $current_model${NC}"
        echo "  ${DIM}此技能需要强指令遵循能力的模型才能严格按流程执行。${NC}"
        echo "  ${DIM}弱模型可能会：不按流程走、向用户提问而非直接搭建、截断配置文档。${NC}"
        echo ""
        echo "  修改方式: 编辑 ~/.openclaw/openclaw.json 中的 agents.defaults.model"
        echo ""
    fi
}

# ═══════════════════════════════════════════════════════════
# 步骤 5: Python 依赖 + 飞书凭据
# ═══════════════════════════════════════════════════════════
check_dependencies() {
    echo ""
    echo "${BOLD}[5/6] 依赖检查${NC}"
    echo ""

    # Python requests
    if python3 -c "import requests" 2>/dev/null; then
        ok "Python requests: 已安装"
    else
        info "安装 Python requests..."
        pip3 install requests 2>/dev/null && ok "requests 安装成功" || {
            warn "自动安装失败，请手动执行: pip3 install requests"
        }
    fi

    # 飞书凭据
    local has_creds=$(_read_config has_credentials)
    if [ "$has_creds" = "yes" ]; then
        ok "飞书凭据: 已配置"
    else
        warn "飞书凭据未配置"
        echo ""

        # 交互式引导（仅终端模式）
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
# 步骤 6: 重启 Gateway
# ═══════════════════════════════════════════════════════════
restart_gateway() {
    echo ""
    echo "${BOLD}[6/6] 重启 Gateway${NC}"
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
    echo "    在飞书中对 AI 说「搭建一个XX系统」→ 自动从零搭建多维表格"
    echo "    在飞书中对 AI 说「查记录」「导入数据」→ 日常 CRUD"
    echo ""

    # 汇总待处理事项
    local todos=0
    if [ "$(_read_config has_credentials)" != "yes" ]; then
        echo "  ${YELLOW}⚠ 还需配置飞书凭据${NC}"
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

    echo "  ${DIM}更新技能: cd ~/.openclaw/skills/feishu-bitable && git pull${NC}"
    echo "  ${DIM}问题反馈: https://github.com/Larkin0302/feishu-bitable-skill/issues${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
main() {
    echo ""
    echo "╔═══════════════════════════════════════════╗"
    echo "║   飞书多维表格技能 — 一键安装器 v2        ║"
    echo "╚═══════════════════════════════════════════╝"

    # 前置检查
    if ! command -v python3 &>/dev/null; then
        fail "python3 未安装"
        exit 1
    fi

    detect_mode
    info "安装模式: $MODE"

    deploy_skill         # 1. 部署技能文件
    install_plugin       # 2. 插件自动安装/更新
    configure_tools      # 3. 工具策略
    configure_model      # 4. 模型与超时
    check_dependencies   # 5. Python 依赖 + 凭据
    restart_gateway      # 6. 自动重启 gateway

    report
}

main "$@"
