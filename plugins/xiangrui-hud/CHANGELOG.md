# Changelog

本文件只记录 xiangrui-hud fork 之后的变更。上游 claude-hud 的历史见 https://github.com/jarrodwatts/claude-hud 。

## 0.1.0

首个 xiangrui-hud 版本，fork 自 claude-hud 0.0.12（MIT，作者 Jarrod Watts）。

改造内容：

- 新增万涂幻象品牌标识：首行翠绿 `❖` 前缀 + 右下角翠绿 `xiangrui-hud` wordmark，品牌翠绿为 `#22a667`（`src/render/index.ts`、`src/render/colors.ts`）。
- 新增配置项 `display.brand`（默认 `true`），可一键关闭品牌标识。
- 将插件标识、配置目录名（`~/.claude/plugins/xiangrui-hud/`）、DEBUG 命名空间、日志前缀、初始化文案、setup/configure 命令从 `claude-hud` 全量改为 `xiangrui-hud`。
- 重写 `package.json`、`.claude-plugin/plugin.json`、README；接入 `xiangruiai/vantasma-toolkit` 工具箱插件市场（仓库根 `.claude-plugin/marketplace.json`）。
- 新增 `THIRD_PARTY_NOTICES.md`、双版权 `LICENSE`（Jarrod Watts + xiangruiai）、`tests/brand.test.js`。
