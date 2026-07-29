# Third-Party Notices

xiangrui-hud 不是从零编写的项目，而是在开源项目 **claude-hud** 之上 fork 改造而来。我们在这里如实记录来源、许可证和改造范围，方便使用者了解这个插件是如何构成的。

## claude-hud（本项目的上游基础）

- Project: https://github.com/jarrodwatts/claude-hud
- Author: Jarrod Watts
- Base version: 0.0.12
- License: MIT
- Use: 提供了整套 Claude Code 状态栏 HUD 的核心能力——stdin 解析、上下文健康度计算、autocompact 缓冲估算、工具/子智能体/待办渲染、用量配额、git 状态、多语言、宽度自适应换行和配置系统。xiangrui-hud 的绝大部分逻辑来自这里。
- Modification note: 万涂幻象在其之上做了品牌化与主题化改造，主要包括：
  - 加入万涂幻象品牌标识——首行翠绿 `❖` 前缀 + 右下角翠绿 `xiangrui-hud` wordmark（`src/render/index.ts`、`src/render/colors.ts`），可通过 `display.brand` 关闭。
  - 新增品牌翠绿 `#22a667` 配色常量与 `brand()` 上色函数。
  - 将插件标识、配置目录名、DEBUG 命名空间、日志前缀、初始化文案从 `claude-hud` 改为 `xiangrui-hud`。
  - 重写 `package.json`、`.claude-plugin/plugin.json`、README 等品牌与市场清单，并接入 `xiangruiai/vantasma-toolkit` 工具箱的插件市场。

上游的 MIT 版权声明已完整保留在本目录 [`LICENSE`](LICENSE) 中，与万涂幻象的 fork 版权声明并列。

## 商标声明

Claude、Claude Code 名称归 Anthropic 所有。本项目与 Anthropic、与 claude-hud 原作者均无隶属关系，亦未获授权或背书。
