# three-layer-memory · 三层记忆

> 给 Codex、Claude Code 或其他支持 Agent Skills 的 AI 装上一套可检查、可召回、不会静默覆盖的个人长期记忆系统。

这个 Skill 把长期记忆分成三个入口：

- 画像记忆：稳定身份、偏好、长期目标和不常变化的事实
- 程序记忆：可以反复复用的做法、工作流、判断规则和经验
- 历史记忆：带日期、事件或来源的工作记录

它不会把聊天记录全部塞进长期记忆。写入前先预览，只有用户明确确认才落盘；密码、API Key、Access Token、验证码和私钥会被拦截。

## ✦ 能做什么

- 在 Obsidian 或纯 Markdown Vault 中初始化三层记忆入口
- 已有 `user.md`、`memory.md`、`AGENTS.md` 时不覆盖原内容
- 画像、程序、历史三类内容确认后分别写入
- 按关键词召回，并返回准确来源文件和行号
- 检查缺失入口、重复内容、疑似秘密和 Claude 入口是否连通
- 同时支持 Codex 与 Claude Code

## ✦ 环境要求

- Python 3
- 一个 Obsidian Vault，或包含 `00.系统` 与知识顶层目录的 Markdown Vault
- Codex、Claude Code 或其他支持 Agent Skills 的工具

## ✦ 让 Agent 自动安装

把下面这句话直接发给 Agent：

> **请安装 https://github.com/xiangruiai/vantasma-toolkit/tree/main/skills/知识管理/three-layer-memory 里的 three-layer-memory Skill，安装到当前 Agent 的 skills 目录；安装后打开当前 Vault 根目录并初始化三层记忆系统，完成记忆体检后告诉我结果。**

## ✦ 手动安装

### Codex

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo xiangruiai/vantasma-toolkit \
  --path 'skills/知识管理/three-layer-memory'
```

安装后开启新对话，让 Codex 重新发现 Skill。

### Claude Code

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cp -R 'vantasma-toolkit/skills/知识管理/three-layer-memory' ~/.claude/skills/
```

安装后重启 Claude Code。

也可以在解压后的 Skill 目录外运行：

```bash
python3 three-layer-memory/scripts/install.py --target both
```

安装器遇到已有同名 Skill 会跳过，不会覆盖。

## ✦ 使用

安装完成后，在准确的 Vault 根目录打开 Agent，然后说：

```text
$three-layer-memory 初始化我的三层记忆系统
```

日常主要使用四句话：

```text
记住：……
确认记住：……
回忆：……
记忆体检
```

Skill 负责文件、路径、格式和检查，人负责判断什么值得记、应该放在哪一层。

## ✦ 默认文件

初始化会按需创建或补充：

| 用途 | 默认位置 |
|---|---|
| 画像记忆 | `00.系统/agent/user.md` |
| 程序记忆 | `00.系统/agent/memory.md` |
| 历史入口 | `50.个人/对话日志/README.md` |
| Agent 协议 | `AGENTS.md` |
| Claude 入口 | `CLAUDE.md` |

## ✦ 安全边界

- 初始化默认支持 dry-run，先展示将发生什么
- 所有真实记忆写入都要求明确确认
- 不覆盖已有文件
- 拒绝密码、密钥、Token、验证码和私钥
- 不自动删除重复、过期或冲突记忆，只在体检中报告
- 不把未经确认的推断当成用户事实

## License

MIT。见 [LICENSE](LICENSE)。

---

## 微信赞赏

这个项目永久免费使用。如果它帮到了你，欢迎[请祥瑞喝杯咖啡](https://pay.xiangruiai.com/?project=three-layer-memory)，鼓励他继续维护并开源更多实用工具。赞赏完全自愿，不解锁任何功能。

---

## 关于万涂幻象

**万涂幻象是一个面向真实业务场景的企业 AI 落地实践社区。**

从真实业务现场出发，我们连接一线业务实践者、能力贡献者和企业团队，共同发现问题、定义场景、验证方案、交付结果，并把有效经验沉淀为可复用的案例、方法和行业 Know-how。

- [社区与知识库](https://vantasma.feishu.cn/wiki/MC1nwBft0izODokXe4acHKjZnsh)
- [万涂幻象开源工具箱](https://github.com/xiangruiai/vantasma-toolkit)
- [公开工作台](https://www.xiangruiai.com)
- 联系：li@xiangruiai.com
