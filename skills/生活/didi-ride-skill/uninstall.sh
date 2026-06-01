#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════
# 🦞 didi-ride-skill — 卸载器
# ═══════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
ok()   { echo "${GREEN}✓${NC} $1"; }
warn() { echo "${YELLOW}⚠${NC} $1"; }
fail() { echo "${RED}✗${NC} $1"; }
info() { echo "${CYAN}→${NC} $1"; }

PLUGIN_DIR="$HOME/.openclaw/extensions/feishu-openclaw-plugin"
TOOL_DIR="$PLUGIN_DIR/src/tools/didi-ride"
SKILL_DIR="$HOME/.openclaw/skills/didi-ride"

echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║   🦞 滴滴打车技能 — 卸载器                ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# ─── [1/4] 移除工具代码 ──────────────────────────────────
echo "${BOLD}[1/4] 移除工具代码${NC}"
echo ""

if [ -d "$TOOL_DIR" ]; then
    rm -rf "$TOOL_DIR"
    ok "已删除 $TOOL_DIR"
else
    info "工具目录不存在，跳过"
fi

# ─── [2/4] 移除技能文件 ──────────────────────────────────
echo ""
echo "${BOLD}[2/4] 移除技能文件${NC}"
echo ""

if [ -d "$SKILL_DIR" ]; then
    rm -rf "$SKILL_DIR"
    ok "已删除 $SKILL_DIR"
else
    info "技能目录不存在，跳过"
fi

# ─── [3/4] 清理插件 Patch ────────────────────────────────
echo ""
echo "${BOLD}[3/4] 清理插件 Patch${NC}"
echo ""

INDEX_FILE="$PLUGIN_DIR/index.js"
MONITOR_FILE="$PLUGIN_DIR/src/channel/monitor.js"

if [ -f "$INDEX_FILE" ]; then
    info "清理 index.js..."
    sed -i.bak '/import.*didi-ride\/register\.js/d' "$INDEX_FILE"
    sed -i.bak '/registerDiDiRideTool(api)/d' "$INDEX_FILE"
    sed -i.bak '/Register DiDi ride tool/d' "$INDEX_FILE"
    rm -f "$INDEX_FILE.bak"
    ok "index.js 已清理"
else
    info "index.js 不存在，跳过"
fi

if [ -f "$MONITOR_FILE" ]; then
    info "清理 monitor.js..."
    # 移除 didi_ 相关块（if 开始到闭合 }）
    python3 -c "
import re
with open('$MONITOR_FILE', 'r') as f:
    content = f.read()
# Remove the didi_ block (4 lines: if check + import + call + closing brace)
pattern = r'\s*if \(typeof action === \"string\" && action\.startsWith\(\"didi_\"\)\) \{\n.*?handleDiDiCardAction.*?\n.*?return await handleDiDiCardAction.*?\n\s*\}\n'
content = re.sub(pattern, '', content)
# Also try simpler pattern
pattern2 = r'[ \t]*const action = data\?\.action\?\.value\?\.action;\n[ \t]*if \(typeof action.*?startsWith\(\"didi_\"\).*?\{[^}]*\}\n'
content = re.sub(pattern2, '', content)
with open('$MONITOR_FILE', 'w') as f:
    f.write(content)
" 2>/dev/null && ok "monitor.js 已清理" || {
    # Fallback to sed
    sed -i.bak '/action\.startsWith("didi_")/,+3d' "$MONITOR_FILE"
    rm -f "$MONITOR_FILE.bak"
    ok "monitor.js 已清理 (sed fallback)"
}
else
    info "monitor.js 不存在，跳过"
fi

# ─── [4/4] 重启 Gateway ──────────────────────────────────
echo ""
echo "${BOLD}[4/4] 重启 Gateway${NC}"
echo ""

if command -v openclaw &>/dev/null; then
    info "重启 gateway..."
    if openclaw gateway restart 2>&1 | tail -3; then
        ok "Gateway 已重启"
    else
        warn "重启失败，请手动执行: openclaw gateway restart"
    fi
else
    warn "openclaw 未找到，请手动重启 gateway"
fi

# ─── 完成 ────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo ""
ok "${BOLD}卸载完成！${NC}"
echo ""
echo "  ${DIM}DIDI_MCP_KEY 保留在 openclaw.json 中，如需删除请手动编辑${NC}"
echo "  ${DIM}飞书官方插件未卸载（其他技能可能在用）${NC}"
echo ""
