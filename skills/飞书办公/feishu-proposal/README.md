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

从 toolkit 克隆后，把本 skill 目录复制到 Claude Code 的 skills 目录：

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cp -r vantasma-toolkit/skills/飞书办公/feishu-proposal ~/.claude/skills/
```

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

## 微信赞赏

这个项目永久免费使用。如果它帮到了你，欢迎[请祥瑞喝杯咖啡](https://pay.xiangruiai.com/?project=feishu-proposal)，鼓励他继续维护并开源更多实用工具。赞赏完全自愿，不解锁任何功能。

---

## 关于万涂幻象

**万涂幻象是一个面向真实业务场景的企业 AI 落地实践社区。**

从真实业务现场出发，我们连接一线业务实践者、能力贡献者和企业团队，共同发现问题、定义场景、验证方案、交付结果，并把有效经验沉淀为可复用的案例、方法和行业 Know-how。

- [社区与知识库](https://vantasma.feishu.cn/wiki/MC1nwBft0izODokXe4acHKjZnsh)
- [万涂幻象开源工具箱](https://github.com/xiangruiai/vantasma-toolkit)
- [公开工作台](https://www.xiangruiai.com)
- 联系：li@xiangruiai.com
