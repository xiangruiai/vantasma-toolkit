# knowledge-system-maintainer

给 Codex、Claude Code 或其他支持 Agent Skills 的 AI 装上一套知识系统健康审计方法。它来自 AI 知识管理训练营 Week4 Day2“系统健康审计”和 Day3“受控自我进化”，但不依赖讲师电脑、私有脚本、固定 Vault 结构或 Obsidian 插件。

## 它解决什么问题

普通“知识库体检”容易退化成文件计数，再把旧文件、孤岛笔记和缺标签机械判成问题。这个 Skill 固定检查六个真实能力：

- 找得到：真实问题能否找到权威答案
- 读得懂：人和 Agent 能否判断来源、状态和含义
- 用得上：能力能否被正确选择、执行和验证
- 接得住：新对话或新 Agent 能否继续当前工作
- 救得回：重要内容能否从独立副本或版本记录恢复
- 管得动：规则、债务、安全边界和维护成本是否可控

默认只读。自动扫描只提供信号，红黄绿和 P0 到 P3 必须有实际证据与人的判断。

## 安装

### Codex

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo xiangruiai/vantasma-toolkit \
  --path 'skills/知识管理/knowledge-system-maintainer'
```

安装后开启新任务，让 Codex 重新发现 Skill。

### Claude Code

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cp -R 'vantasma-toolkit/skills/知识管理/knowledge-system-maintainer' ~/.claude/skills/
```

安装后重启 Claude Code。

## 使用

只读审计：

```text
请对这个知识系统做一次只读健康审计。先列出当前能用和不能确认的能力，不要修改文件。
```

受控改进：

```text
请从这份健康报告中选择一个可复现问题，预览最小系统改造和回滚方法。没有我的确认不要修改。
```

Skill 安装失败时，仍可直接使用 `references/` 中的操作卡和 `assets/` 中的报告模板完成实战。

## 输出

- Available / Not observed / Provided 三类能力清单
- 六维红黄绿总览，未检查项保持灰色
- 自动信号与人工判断分栏
- 带证据、优先级、下一动作和完成标志的问题卡
- 只针对一个已确认问题的修复预览、同例复测和回滚记录

## 边界

- 默认只读。
- 不依赖讲师电脑上的私有脚本或绝对路径。
- 不自动删除、移动、批量改标签或重写链接。
- 不把孤岛、旧文件或低频 Skill 自动判为问题。
- 自我进化必须有人确认、同例复测并能回滚。

## 验证报告

```bash
python3 scripts/health_report_check.py path/to/健康审计报告.md
```

这个脚本只验证报告结构和安全约束，不会读取报告以外的文件，也不会修改任何内容。脚本通过不代表结论真实，证据仍需人工核对。

## License

MIT。见 [LICENSE](LICENSE)。

## 微信赞赏

这个项目永久免费使用。如果它帮到了你，欢迎[请祥瑞喝杯咖啡](https://pay.xiangruiai.com/?project=knowledge-system-maintainer)，鼓励他继续维护并开源更多实用工具。赞赏完全自愿，不解锁任何功能。

## 关于万涂幻象

万涂幻象是一个面向真实业务场景的企业 AI 落地实践社区。

- [社区与知识库](https://vantasma.feishu.cn/wiki/MC1nwBft0izODokXe4acHKjZnsh)
- [万涂幻象开源工具箱](https://github.com/xiangruiai/vantasma-toolkit)
- [公开工作台](https://www.xiangruiai.com)
- 联系：li@xiangruiai.com
