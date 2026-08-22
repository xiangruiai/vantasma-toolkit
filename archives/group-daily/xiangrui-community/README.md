# 祥瑞和 Ta 的朋友们 · 群日报

这里是一群朋友认真聊天、彼此启发，也一起留下生活与实践痕迹的地方。

「祥瑞和 Ta 的朋友们」是祥瑞组织的个人 AI 朋友圈。群里有 AI 开发者、产品实践者，也有来自不同行业的一线从业者。大家聊真实业务问题、AI 产品、开发实战，也分享最近踩过的坑、刚跑通的方法和仍然想不明白的问题。

我们把每天值得留下来的讨论整理成群日报。它不是逐字聊天记录，也不是冷冰冰的会议纪要，而是当天群聊的一篇短篇报道。希望过一段时间再回头看，还能记得那天是谁提出了一个好问题，又是谁顺手递来了一块答案。

## 关于万涂幻象

[万涂幻象](https://www.xiangruiai.com/)是一个面向真实业务场景的企业 AI 落地实践社区。

我们从企业一线的真实问题出发，与行业从业者共同梳理流程、验证方案，并把可以公开、可以复用的经验整理成案例、方法和行业 Know-how。希望让懂业务的人与能实现的人更容易找到彼此，也让一次实践成为下一次落地更好的起点。

这个群是朋友们日常交流的个人空间，群日报则是这些交流留下来的公开社区记忆。这里的内容仅供阅读、学习和交流，不作为商业产品，不用于二次售卖。未经原发言者授权，请勿将群友观点和发言用于商业用途。

为了保护群友隐私，公开归档中的昵称已经脱敏，也不包含原始群聊、头像、成员名单、wxid、联系方式和内部配置。所有观点和发言仍归原发言者所有。

逐日阅读请进入 [`daily/`](daily/)，机器可读的完整目录见 [index.json](index.json)。

## 微信赞赏

群日报会继续免费公开。如果这些记录给你带来过一点启发，欢迎[请祥瑞喝杯咖啡](https://support.xiangruiai.com/?project=group-daily)，支持群日报的整理、归档与长期维护。赞赏完全自愿，不解锁任何权益，也不改变这份归档的非商业性质。

## 维护归档

以下命令只读取本地生产数据，输出公开脱敏副本：

```bash
python3 scripts/export_public_archive.py \
  --source "/path/to/xiangrui.me/src/data/daily" \
  --roster "/path/to/xiangrui.me/src/data/communityRoster.json" \
  --output . \
  --through YYYY-MM-DD
```

导出后必须校验：

```bash
python3 scripts/verify_archive.py .
```

## 文件说明

```text
.
├── README.md
├── index.json
├── daily/
│   └── YYYY-MM-DD.json
└── scripts/
    ├── export_public_archive.py
    └── verify_archive.py
```
