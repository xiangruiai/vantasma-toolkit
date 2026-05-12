---
name: feishu-bitable-prompt-designer
description: Turn a fuzzy business requirement into a high-quality Feishu Bitable AI system prompt by asking clarifying questions first instead of building immediately. Use when the user says `系统提示词`, `/系统提示词`, `模糊需求`, `先梳理业务逻辑`, `先别搭建`, `帮我整理成飞书系统提示词`, or wants an agent like 龙虾 to ask the right questions and then output a prompt for Feishu Bitable AI expert mode. Do not use for direct system building.
---

# Feishu Bitable Prompt Designer

## Overview

这个 skill 不是替用户直接搭系统。

这个 skill 的职责，是先把模糊业务需求梳理成结构化业务逻辑，再输出一版可直接丢给飞书多维表格 AI 的高质量系统提示词。

如果用户明确说了 `系统提示词` 或 `/系统提示词`，要把这理解为：

`先别搭建，先把模糊需求整理成系统提示词`

不要把它路由成直接搭建任务。

核心原则：

1. 先理清业务，再写提示词
2. 先补角色、对象、关系、规则，再提“要什么页面”
3. 提示词的目标不是写得花，而是让飞书 AI 少猜、少补、少跑偏
4. 如果用户最初只给了一句模糊需求，第一轮只能收集业务概览，不能直接收口

## When To Use

在下面这些场景使用：

- 用户想让飞书多维表格 AI 搭系统，但在正式搭建前需要先把模糊需求整理成系统提示词
- 用户只会说“搭个 CRM / 进销存 / 报名系统”，但讲不清业务逻辑
- 用户想用龙虾、OpenClaw、Claude、Codex 之类的 agent 先帮忙梳理需求
- 用户要喂给飞书多维表格 AI 默认模式或专家模式一版更完整的 prompt

不要在这些场景使用：

- 用户已经给出完整字段、公式、角色、流程、权限定义
- 用户要的是直接落地搭建，而不是先产出 prompt
- 用户要的是文章、课程、文案，而不是系统提示词

## Output Goal

最终交付 2 份内容：

1. `业务逻辑摘要`
2. `飞书多维表格 AI 系统提示词`

如果信息不足，不要直接硬写 prompt。先进入追问环节。

## Workflow

### First rule: do not force rounds, follow the gaps

Complex systems often need more than one round, but do not mechanically force a fixed number of rounds.

The right behavior is:

1. identify the biggest remaining gaps
2. ask only the 1 to 3 most useful follow-up questions
3. when the answer feels mostly sufficient, do not output the final prompt immediately
4. first summarize the likely remaining risk gaps and ask whether the user wants to add anything

The goal is:

- do not close while clear gaps still exist
- do not keep asking low-value questions just to satisfy a rigid process

### Step 1: 判断需求清晰度

先快速判断用户当前属于哪一类：

- `模糊需求`
  例：搭个客户管理系统、做个报名系统、搞个进销存
- `半结构化需求`
  例：已经说了几张表、几个角色，但规则还没讲透
- `结构化需求`
  例：字段、公式、流程、权限都写得差不多了

判断标准看 8 个维度：

1. 目标
2. 使用角色
3. 核心对象
4. 对象关系
5. 关键字段
6. 计算规则
7. 流程触发
8. 权限边界

缺 3 个以上，视为模糊需求。

### Step 2: 用业务八问法追问

如果需求还不够清楚，用下面这 8 类问题补逻辑。

每次优先追问最关键的缺口，不要一口气抛太多理论解释。

#### 1. 目标

- 这个系统最主要解决什么问题
- 这次先做到什么程度就算够用
- 哪些暂时不做

#### 2. 角色

- 谁会用这个系统
- 谁录入
- 谁处理
- 谁审批
- 谁看报表

#### 3. 核心对象

- 系统里最重要的几类数据是什么
- 每一类数据是否值得单独成表

#### 4. 对象关系

- 一个客户能不能有多个订单
- 一个学员能不能报多门课
- 一个商品能不能在多个仓库里有库存

如果出现多对多关系，主动提醒需要中间表。

#### 5. 关键字段

- 每张表至少要记录哪些字段
- 哪些字段是文本，哪些字段应该是人员、日期、单选、关联、数字、货币

#### 6. 计算规则

- 有哪些字段不是手填，而是算出来的
- 统计口径是什么
- 异常条件怎么定义

#### 7. 流程和触发

- 什么事件发生后要提醒谁
- 什么情况要自动流转
- 什么条件下要升级、审批、告警

#### 8. 权限

- 谁能看全部
- 谁只能看本人或本组
- 哪些字段敏感

### Step 2.1: prioritize the biggest gaps

If the user started with one fuzzy sentence, the first round will often cover:

1. business type / core pain point
2. roles
3. core data objects

But that is only a common starting pattern, not a rigid script.

After the user replies, first decide which category is most missing:

- object relationships
- exception flows
- rule definitions
- permission boundaries
- metrics / automation triggers

Then ask only the most valuable 1 to 3 questions.

For training / enrollment / cohort systems, the highest-value follow-ups are usually:

1. how learners relate to cohorts, classes, and courses, including延期 / 转班 / 重读
2. how exception flows work, such as退款 / 延期 / 转班 / 请假 / 补课 / 补交作业
3. how graduation rules, risk alerts, permissions, and key metrics are defined

### Step 2.5: 完整度闸门

准备输出最终提示词前，先静默检查下面 10 项是不是已经被明确回答：

1. 系统类型和核心痛点
2. 角色与职责
3. 核心对象
4. 对象关系
5. 主流程阶段
6. 异常流程
7. 关键规则或计算口径
8. 权限边界或敏感字段
9. 关键视图或仪表盘指标
10. 自动化、提醒、审批触发

只要命中下面任一条，就继续追问，不得输出最终提示词：

- 上面 10 项里缺 2 项以上
- 还没问到对象关系
- 还没问到异常流程
- 还没问到规则口径
- 还没问到权限边界
- 用户最初只有一句模糊需求
- 需求里出现 `全流程`、`从报名到结营`、`运营管理`、`训练营`、`CRM`、`ERP`、`进销存`、`报名系统` 这类复杂生命周期信号

对培训、训练营、报名类系统，至少确认这些后才能收口：

- 学员和期次、班级、课程之间怎么对应
- 缴费、退款、延期、转班怎么处理
- 签到、作业、考试、结营规则怎么判定
- 不同角色各能看什么、改什么
- 至少一类统计指标或提醒触发

如果还存在明显缺口，要直接告诉用户：

`我还有几块关键逻辑没问透，先继续确认，不急着出最终提示词。`

### Step 2.6: forbidden phrases

While clear gaps still exist, do not say:

- `你直接按这 3 条回我即可，我下一条就给你完整系统提示词`
- `这版信息已经足够`
- `下面给你成品`
- `我直接帮你整理最终提示词`

If you say any of these while important gaps remain, you are closing too early.

### Step 3: 自动补隐含逻辑

用户没提，但如果场景里天然带这些逻辑，要主动补出来并确认：

| 场景 | 常见隐含逻辑 |
|------|-------------|
| CRM | 跟进提醒、商机阶段、负责人分配、成交漏斗 |
| 进销存 | 入库、出库、库存计算、预警、审批 |
| 培训机构 | 学员选课中间表、签到、缴费、课前提醒、未签到告警 |
| 项目管理 | 截止日期提醒、延期判断、责任人、项目视图、管理驾驶舱 |
| 报名/表单 | 表单入口、状态流转、统计看板、提醒通知 |

不要擅自当成既定事实。应输出成“建议补充项”让用户确认。

### Step 4: 把需求压成系统设计骨架

当信息足够后，先整理出这份骨架，再写 prompt：

```markdown
## 系统目标

## 使用角色

## 核心数据表

## 表间关系

## 关键字段与字段类型

## 关键公式/计算规则

## 需要的视图

## 需要的仪表盘

## 需要的工作流

## 权限设计

## 验收标准
```

### Step 4.5: summarize the gaps, then ask whether to add anything

Even if the information feels mostly sufficient, do not output the final prompt immediately.

First do two things:

1. summarize what you believe is already clear
2. point out 1 to 3 remaining risk areas that may still need clarification

Then ask naturally:

`我这边已经能整理最终系统提示词了。目前我理解的重点是 A、B、C，不过像 X、Y 这几块如果你还有特殊规则，也可以现在补充。你看看还有没有想加的；如果没有，我就按这版整理。`

Only output the final prompt when:

1. the user clearly says “没有了 / 就这样 / 可以整理了”
2. or the user adds the last details and explicitly agrees to close

If the user has not clearly agreed to close, stay in clarification mode.

### Step 5: 输出飞书多维表格 AI 提示词

提示词必须满足这些要求：

1. 明确系统目标和边界
2. 明确角色及职责
3. 明确核心对象和表结构
4. 明确一对多、多对多关系
5. 明确计算规则和触发规则
6. 明确需要的视图、仪表盘、工作流、权限
7. 明确示例数据要求
8. 明确验收标准

不要只写：

- 帮我搭个系统
- 做得专业点
- 好看点
- 你按理解补全

这种写法会让飞书 AI 猜太多。

## Output Format

默认按下面格式输出：

### 一、业务逻辑摘要

用简洁中文总结：

- 系统目标
- 角色
- 对象
- 关系
- 规则
- 流程
- 权限

### 二、飞书多维表格 AI 系统提示词

输出一版可以直接复制的完整 prompt。

如果场景复杂，默认建议用户使用 `专家模式`。

## Prompt Construction Rules

写最终提示词时，遵守这些规则：

1. 先写业务目标，再写结构
2. 少用“模块”这种空词，多写“谁做什么”
3. 少写“优化一下”，多写规则
4. 关系一定显式写出来
5. 计算逻辑尽量写成可验证口径
6. 如果信息不足，允许在提示词末尾让飞书 AI 最多追问 3 个关键问题

额外约束：

- 不要只问一轮业务概览就提前收口
- 生命周期长、角色多、流程复杂的系统，默认至少做两轮以上追问

## References

需要模板时，读取：

- [系统提示词模板](references/system-prompt-template.md)
