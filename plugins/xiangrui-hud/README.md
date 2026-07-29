# xiangrui-hud

> 万涂幻象 · Claude Code 实时状态栏 HUD（翠影绿主题）。

常驻在 Claude Code 输入框下方，一眼看清当前会话状态：模型、上下文健康度、项目与 git 分支、加载的 CLAUDE.md / 规则 / 钩子数量、工具活动、子智能体、待办进度。带万涂幻象品牌标识——首行翠绿 `❖`，右下角翠绿 `xiangrui-hud` wordmark。

```
❖ [Opus 4.8 (1M context)] │ xiangrui.me git:(main*)
上下文 ██░░░░░░░░ 12%
1 CLAUDE.md │ 3 规则 │ 5 钩子              xiangrui-hud
```

本项目 fork 自 [jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud)（MIT），在其之上做了品牌化与翠影绿主题改造。完整来源与改造范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 安装

在任意 Claude Code 会话里执行：

```
/plugin marketplace add xiangruiai/vantasma-toolkit
/plugin install xiangrui-hud
```

装好后按提示重启 Claude Code（macOS 上状态栏可能需要重启才显示）。

> Linux 用户若安装时报 `EXDEV: cross-device link not permitted`，先设置临时目录再启动：
> `mkdir -p ~/.cache/tmp && TMPDIR=~/.cache/tmp claude`

## 配置

配置文件位于 `~/.claude/plugins/xiangrui-hud/config.json`，不存在时用内置默认值。常用项：

| 键 | 默认 | 说明 |
|----|------|------|
| `display.brand` | `true` | 是否显示万涂幻象品牌标识（`❖` 前缀 + wordmark） |
| `language` | `en` | 界面语言，可设 `zh` 切中文标签 |
| `lineLayout` | `expanded` | `expanded`（多行）/ `compact`（单行） |
| `display.showConfigCounts` | `false` | 显示 CLAUDE.md / 规则 / 钩子计数 |
| `colors.*` | 见下 | 各元素配色，支持预设名 / 0-255 / `#rrggbb` |

品牌翠绿为 `#22a667`。想让整体更贴翠影绿，可把 `colors.context`、`colors.project` 也设成 `"#22a667"`。

想关掉品牌标识：

```json
{ "display": { "brand": false } }
```

## 从源码构建

```bash
cd plugins/xiangrui-hud
npm install
npm run build      # tsc → dist/
npm test           # 运行测试
npm run test:stdin # 用示例 stdin 打印一次状态栏
```

## 许可

MIT。版权归 Jarrod Watts（上游原作者）与 xiangruiai（李祥瑞 / 万涂幻象）共同所有，见 [LICENSE](LICENSE)。

Claude、Claude Code 名称归 Anthropic 所有，本项目与其无隶属关系。
