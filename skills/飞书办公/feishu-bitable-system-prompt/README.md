# feishu-bitable-system-prompt

把模糊业务需求整理成高质量飞书多维表格 AI 系统提示词的 skill。

这个仓库里的核心 skill 名叫 `feishu-bitable-prompt-designer`。它不直接搭系统，而是先追问业务逻辑，再输出一版可直接丢给飞书多维表格 AI 专家模式的系统提示词。

## 适用场景

- 只有一句模糊需求，比如“帮我搭个 CRM”“做个训练营运营系统”
- 想让 agent 先理清业务逻辑，再喂给飞书多维表格 AI
- 想减少飞书 AI 的猜测、补问和跑偏

## 核心能力

- 判断需求清晰度，而不是上来就直接收口
- 按缺口追问 `目标、角色、对象、关系、规则、流程、权限`
- 复杂系统准备收口前，会先确认还有没有想补充的
- 最终输出两部分：
  - `业务逻辑摘要`
  - `飞书多维表格 AI 系统提示词`

## 仓库结构

```text
.
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    └── system-prompt-template.md
```

## 使用方式

在支持 skills 的 agent 环境里，把这个 skill 安装到本地技能目录后触发。

常见触发词：

- `系统提示词`
- `/系统提示词`
- `模糊需求`
- `先梳理业务逻辑`
- `帮我整理成飞书系统提示词`

典型输入：

```text
/系统提示词 帮我搭一个训练营运营管理系统，我们团队内部要用，能把从报名到结营这整个过程都管起来，尽量实用一点。
```

预期行为：

1. agent 不直接搭建
2. agent 先追问最关键的业务逻辑缺口
3. agent 收口前确认是否还有补充
4. agent 输出最终可复制的系统提示词

## 配套文件

- [SKILL.md](./SKILL.md)：主技能说明
- [references/system-prompt-template.md](./references/system-prompt-template.md)：通用提示词骨架
- [agents/openai.yaml](./agents/openai.yaml)：agent 调用元数据

## 说明

这个 skill 更适合配合飞书多维表格 AI 的 `专家模式` 使用。

如果你的需求已经非常结构化，字段、公式、流程、权限都写清楚了，那就不一定需要它，直接喂给飞书 AI 往往更快。

---

## 微信赞赏

这个项目永久免费使用。如果它帮到了你，欢迎[请祥瑞喝杯咖啡](https://pay.xiangruiai.com/?project=feishu-bitable-prompt-designer)，鼓励他继续维护并开源更多实用工具。赞赏完全自愿，不解锁任何功能。

---

## 关于万涂幻象

**北京万涂幻象科技有限公司**：以自研的 Agent 上下文与主体连续性技术为底座，在上面跑着企业 AI 落地、课程与培训、品牌宣传三条业务。技术不空转，每一次业务交付都是对底座的一次真实验证。

- [公司业务最新介绍（飞书）](https://waytoagi.feishu.cn/wiki/EAJkw9JcviTt3UkjoyXcKkLzn1W)
- [万涂幻象开源工具箱](https://github.com/xiangruiai/vantasma-toolkit)
- 联系：li@xiangruiai.com
