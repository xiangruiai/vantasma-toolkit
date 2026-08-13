# 本机能力地图 Skill

一个只读的 Agent Skill，用来扫描本机已经安装的 Agent Skills、CLI、MCP servers 和 Codex plugins，并生成“场景 → 首选能力”的能力地图。

它解决的不是“再装更多工具”，而是让 Agent 先知道这台电脑已经具备什么能力，再按场景选择路线。

## 能做什么

- 扫描 Codex、Claude Code 和共享目录中的 `SKILL.md`
- 合并软链接造成的重复 Skill，同时保留可见位置
- 扫描 `PATH` 中的常用 CLI
- 只输出 MCP server 和 plugin 名称，不输出配置值
- 生成 Markdown 和 JSON 两份能力地图
- 用可编辑规则建立“场景 → 首选能力 → 备选”的反向索引
- 明确区分：已发现、已探测、已认证、已验证

## 安装

### Codex

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cp -R vantasma-toolkit/skills/Agent能力/discover-local-capabilities ~/.codex/skills/
```

### Claude Code

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cp -R vantasma-toolkit/skills/Agent能力/discover-local-capabilities ~/.claude/skills/
```

也可以安装到项目级 `.agents/skills/`、`.codex/skills/` 或 `.claude/skills/`。

## 使用

直接对 Agent 说：

```text
扫描一下这台电脑有哪些 Skill、CLI、MCP 和插件，生成本机能力地图。
```

也可以直接运行脚本：

```bash
python3 skills/Agent能力/discover-local-capabilities/scripts/scan_capabilities.py \
  --project "$PWD" \
  --output-dir .capability-map
```

输出：

```text
.capability-map/
├── capability-map.md
└── capability-map.json
```

需要版本信息时显式添加 `--probe-versions`。默认不执行任何发现到的工具。

## 安全边界

- 不读取 `.env`、token、密钥或命令历史
- 不输出 MCP 配置值，只记录 server 名称
- 不安装、更新、授权、调用或删除发现到的工具
- 默认不执行版本探测
- 报告中的家目录会显示为 `~`
- “已发现”不等于“已认证”或“已验证”

## 自定义路由

编辑 [`references/routing-rules.json`](references/routing-rules.json)，把你自己的首选工具按顺序写进每个场景。扫描结果只提供证据，路线优先级仍应通过真实任务持续验证。

## License

遵循本仓库根目录的 [LICENSE](../../../LICENSE)。
