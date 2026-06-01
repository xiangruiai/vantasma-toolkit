# feishu-proposal

基于[飞书 CLI](https://github.com/larksuite/cli) 的客户方案自动生成 Skill。

从一场飞书会议的智能纪要 + 文字记录出发，自动生成结构化的客户方案文档，并写到飞书。

## 效果

输入：一场客户沟通会议 飞书自动生成的智能纪要 + 文字记录

输出：一份可直接发给客户的方案文档，包含项目背景、痛点分析、业务流程图、解决方案、数据模型设计等，流程图自动渲染为飞书画板。

[查看示例方案](references/example_education.md) 少儿美术培训机构教务系统

## 安装

### 前置条件

- [lark-cli](https://github.com/larksuite/cli)：`npm install -g @larksuite/cli`
- 已完成飞书认证：`lark-cli auth login`
- Claude Code 或其他支持 Skill 的 AI Agent

### 安装 Skill

将本仓库克隆到 Claude Code 的 skills 目录：

```bash
git clone https://github.com/Larkin0302/feishu-proposal.git ~/.claude/skills/feishu-proposal
```

或者手动复制 `SKILL.md` 和 `assets/` 目录到 `~/.claude/skills/feishu-proposal/`。

## 使用

在 Claude Code 中直接说：

```
帮我把上次跟客户沟通的会议纪要写成方案
```

或者给出具体链接：

```
根据这两份飞书文档写一份客户方案：
智能纪要：https://xxx.feishu.cn/docx/xxx
文字记录：https://xxx.feishu.cn/docx/xxx
```

AI 会自动：
1. 拉取会议纪要和文字记录
2. 提炼会议要点，引用客户原话
3. 按模板生成方案 流程图自动转飞书画板
4. 写到飞书文档，返回链接

## 方案结构

| 章节 | 内容 |
|------|------|
| 一、项目背景 | 客户概况 + 现有系统 |
| 二、核心痛点与需求 | 痛点清单 + 功能诉求 |
| 三、业务流程梳理 | mermaid 流程图 自动转飞书画板 |
| 四、解决方案总览 | 按业务模块分节说明 |
| 五、合作模式 | 搭建周期 / 培训 / 后续支持 |
| 六、字段级数据模型 | 每张表的字段设计 + ER 关系图 |
| 七、待确认事项 | 会议中未拍板的事项 |

章节可根据实际需求增减 如添加报价章节。

## 自定义

- 修改 `assets/template.md` 可调整方案模板结构
- 在 `references/` 目录下添加行业案例作为参考
- SKILL.md 中的规则可根据自己的业务习惯调整

## 相关项目

- [lark-cli](https://github.com/larksuite/cli) — 飞书官方 CLI 工具
- [飞书 CLI 创作者大赛](https://waytoagi.feishu.cn/wiki/R4S3w8wTTie04nkYiL6c8rxon4d)

## License

MIT

---

**万涂幻象出品** · 作者 **祥瑞** · 个人网站 [www.xiangruiai.com](https://www.xiangruiai.com)
