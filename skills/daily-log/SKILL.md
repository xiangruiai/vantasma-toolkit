---
name: daily-log
label: 收工日志
description: 当用户说"收工""今天干了啥""复盘一下今天""工作日志""这周做了啥"时触发。用 lark-cli 把用户当天在飞书的全链路足迹（消息、日程、会议妙记、文档、任务、审批、OKR、考勤、邮件）挖出来，按第一人称整理去重、解析对接人实名与公司，生成一份带可点链接和真 @ 的结构化飞书文档：速览数字卡、工作全景思维导图、一天时间线、关键产出与决策、会议与纪要三链接、沟通闭环、文档与资料价值分级、事项明细、待办、明日聚焦，按日期归档并与昨日计划做兑现对照。区别于手填日报：一键从真实活动数据自动聚合，每个人名真 @、每个会议文档群聊都能点开直达，不靠回忆、不表演。
---

# 收工日志 · 飞书全链路工作枢纽

把用户当天在飞书的所有工作痕迹自动聚合，整理成一份**既体面到能发给上级、又诚实到能留给自己复盘**的结构化飞书文档。它不是一堆文字，是一个带链接和真 @ 的工作枢纽：会议点纪要、文档点直达、人名点 @、群聊点进群。

## 一、定位（先读这条，它决定后面每一个取舍）

一份完整的个人工作日志，**结果与判断在前，过程与明细在后**。一份就够，既能发上级、又能自己复盘，靠同一份从飞书自动聚合的真实数据，不写两遍，不贴"给谁看"标签。

**四条铁律：**

1. **第一人称。** 只记本人亲手做的、参与决策的、@本人或需本人跟进的。群里路过、与本人无关的，不进日志。
2. **挖全。** 当天本人在飞书碰过的东西，能挖的全挖（见 Step 1）。
3. **真实不表演。** 不确定标"待确认"，挖不到标边界，绝不编造。人称用中性客观陈述，不用"你"，给上级看也不别扭。
4. **实体全部可点。** 每个人名用真 @（`<cite type="user">`），每个会议挂纪要链接，每篇文档可点直达，每个群聊给入口链接。日志里的实体都能一键跳转，不留死文本。

## 二、环境前置

- 用 `lark-cli`。开始前先 `lark-cli doctor`，确认 `"ok": true`。
- 本机有 HTTPS 代理时，命令前加 `LARK_CLI_NO_PROXY=1`。
- 采集命令 `Risk: read`，只读安全。
- 逐域命令、XML 模板、@人/群链接/数字卡语法、踩过的坑，全在 [references/lark-recipes.md](references/lark-recipes.md)。分类规则见 [references/classification.md](references/classification.md)。

## 三、执行流程

### Step 0：确定日期范围

当天 `YYYY-MM-DDT00:00:00+08:00` 至 `T23:59:59+08:00`。00:00–05:00 说"收工"取昨日；05:00 后取当日；用户指定日期以指定为准；周报放宽到一周。

### Step 1：全链路采集

三档：能稳拿必采，需验证尽量采，拿不到跳过并在数据来源注明。完整命令和坑见 references/lark-recipes.md。

| 源 | 命令要点 |
|---|---|
| 消息 | `im +messages-search --query "" --start --end`，必加 `--page-all`。**别用 --sender 过滤**（会破坏 name enrich），全量拉回本地按 sender.id 筛 |
| 日程 | `calendar +agenda --start --end` |
| 会议+纪要 | `vc +search --participant-ids <me>`，再 `vc +notes --minute-tokens <token>` 取 `note_doc_token`（智能纪要）、`verbatim_doc_token`（文字记录）、章节总结 |
| 妙记 | `minutes +search --owner-ids me` 和 `--participant-ids me`，并集去重，拿 app_link |
| 文档/文件/wiki/表格 | 统一走 `drive +search`：`--edited-since`/`--opened-since`/`--commented-since`，`--edited-until` 写次日；返回 `title_highlighted` 标题、`result_meta.url` 链接 |
| 任务 | `task +get-my-tasks --created_at <ISO日期>` |
| OKR | `okr +cycle-list` + `+progress-list` |
| 考勤 | `attendance user_tasks query --check-date-from/to <yyyyMMdd>` |
| 邮件 | `mail +triage --filter '{folder,time_range}'` |
| 群链接 | 从消息拿目标群 chat_id，拼 `https://applink.feishu.cn/client/chat/open?openChatId=oc_xxx` |

采集纪律：群聊按"本人发言+被@"排序不按总量；日程优先有妙记/总结的不按时长；私聊设上限。

### Step 2：整理（第一人称 + 解析对接人 + 文档价值 + 沟通闭环 + 去重 + 兑现）

1. **第一人称过滤**：剔除与本人无关的内容。
2. **解析对接人**：收集所有 open_id（含本人）去重，一次 `contact +search-user --user-ids <csv> --as user` 批量查。实名取 `localized_name`（不是 name），外部联系人带 `department` 公司名。私聊对方从 `messages-search --chat-id` 的 `chat_partner` 取。**每个解析到的人都准备好 open_id，写文档时用真 @。** 搜不到实名的标文字。
3. **文档价值判断**：对收到分享、查阅的文档，判断用途和价值，分「值得沉淀 / 可参考 / 路过」三级，说明每篇是干什么的、对本人有没有用。不确定的 `docs +fetch` 取标题摘要核对。
4. **沟通闭环分析**：@我的回了没、我@的对方回了没、私聊看最后一句是谁说的判断"球在谁手里"，分「待我跟进 / 等对方反馈 / 已闭环」。具体写清是什么事，不笼统。
5. **相关性排序 + 按事项分类 + 跨源去重**：主来源优先级 妙记/会议总结 > 群聊 > 私聊 > 文档痕迹。
6. **计划兑现对照**：读昨天归档的"明日聚焦"对今天。首次无数据则跳过。

### Step 3：生成结构化飞书文档

`cat doc.xml | lark-cli docs +create --api-version v2 --content -`（v2 用 --content，跨目录走 stdin）。从 `new_blocks[]` 拿画板 token 供 Step 4。完整 XML 模板见 references/lark-recipes.md。

**章节顺序（章节标题不带 emoji；人名一律真 @；实体一律可点）：**

1. **标题** `收工日志 · YYYY-MM-DD 周X · 姓名`
2. **速览** callout：今日一句话（战略/决策优先冒头）+ 数字条
3. **今日全景** 思维导图画板
4. **一天怎么过的** 时间线画板
5. **关键产出与决策** 结果导向，对接人用 `<cite type="user" user-id="ou_xxx">` 真 @ 加公司名，对齐 OKR
6. **会议与纪要** 每场会挂三个链接：妙记原文、智能纪要、文字记录
7. **今日数据** 饼图画板 + grid 四栏数字卡（大数字加小注解）
8. **今日洞察** callout：2-3 条判断，关联线索价值、重心转向、节奏规律
9. **沟通待跟进** 表格：状态 / 具体事项 / 对象。对象 @人 或给群链接，球在谁手里一眼清
10. **文档与资料** 全部可点：今日产出编辑、查阅参考（带用途）、收到分享（按值得沉淀/可参考/路过分级）、我分享出去
11. **事项明细** 表格：事项 / 对接人（真 @ 加公司）/ 过程 / 进展卡点。**本人的活 @ 本人自己**
12. **待办与明日聚焦** 待办 `<checkbox>` 带责任人真 @（本人事 @本人）、状态、时间；明日聚焦有序列表
13. **数据来源** 中文标注来源，注明实名经通讯录查得

后续补段落用 `docs +update --mode append --content -`。

### Step 4：配图（三张画板）

**铁律：whiteboard 先 `type="blank"` 占位，create 后拿 block_token，再 `cat x.mmd | whiteboard +update --whiteboard-token <bt> --input_format mermaid --source - --overwrite --as user` 写入。** block_token 顺序 = XML whiteboard 出现顺序。

1. 工作分类思维导图（mermaid mindmap，最重要分支放最前）
2. 一天时间线（mermaid timeline，分段挂关键事件带对接人）
3. 精力分布饼图（mermaid pie）

### Step 5：归档 + 状态闭环

文档按日期归档到固定云文档文件夹或知识库节点，一天一篇，累积成时间线。记下"明日聚焦"供明天 Step 2.6 对照。这一步把 skill 从一次性纪要变成可追踪的工作记忆系统。

## 四、异常处理

| 场景 | 处理 |
|------|------|
| 当天无活动 | 告知"今天没检测到飞书活动记录" |
| 某源失败 | 跳过，用其他源继续，数据来源注明"⚠️ X 源获取失败" |
| 某群超 200 条 | 只提取与本人相关及含工作关键词的消息 |
| 妙记/文档无法访问 | 标"有此纪要但无法读取"，不编造 |
| 对接人搜不到实名 | search-user 返回空（不在通讯录），保持文字名，不 @ |
| 群链接拿不到 chat_id | 退回文字群名 |

## 五、注意事项

1. 时间严格按 Step 0，只取目标日。
2. 不确定标"待确认"，不编造。
3. 用户已授权访问本人全部会话；日志只记与本人工作相关的。
4. 输出精炼克制，结果在前过程在后。人称中性客观，不用"你"。
5. 有明确卡点才写问题；能从未完成项提取才写计划，不泛推断。
6. **人名一律真 @**：`<cite type="user" user-id="ou_xxx">`，本人的活也 @ 本人自己。实名取 `localized_name`。
7. **实体一律可点**：会议挂纪要链接、文档给直达链接或 `<cite type="doc">` 卡片、群聊给 applink 入口。
8. **文档要判断价值和用途**，不是堆链接。客户、合作方等关键对接人才解析公司，路人不必。
9. 不做全网情报挖掘，对接人信息停在飞书能拿的「实名 + 公司」层。
