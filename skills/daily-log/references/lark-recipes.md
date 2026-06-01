# lark-cli 采集命令 + 文档模板 + 画图语法

> 全部命令在 lark-cli 1.0.41 真机实测通过。本机有 HTTPS 代理时，命令前加 `LARK_CLI_NO_PROXY=1`。
> 日期占位：`<D>` = `2026-06-01`（当天），`<NEXT>` = 次日 `2026-06-02`，`<ISO_START>` = `2026-06-01T00:00:00+08:00`，`<ISO_END>` = `2026-06-01T23:59:59+08:00`，`<YMD>` = `20260601`，`<ME>` = 本人 open_id（如 `ou_xxxxxxxxxxxxxxxxxxxxxxxx`）。
>
> **实测铁律（踩过的坑，别再踩）：**
> 1. 拉消息必须 `--page-all`，否则默认只回 20 条。
> 2. 单日 drive 查询 `--edited-until` 要写**次日** `<NEXT>`，写当天会变成零区间。
> 3. `@file` 只认当前目录相对路径，跨目录一律用 `cat <file> | ... --source -` 或 `--content -` 走 stdin。
> 4. 文档标题字段是 `title_highlighted`（顶层），不是 `result_meta.title`。
> 5. `task --created_at` 只认 ISO 日期，不认 `7d`。
> 6. `approval instances initiated` 返回不带时间戳，要逐条 `instances get` 补时间。
> 7. `--page-all` 在 chat-list / chat-messages-list 等会让输出变空或非 JSON；改用 `--page-size 20` 或缩小时间窗单页拉取。
> 8. 解析他人实名别用 `messages-search --sender`（会破坏 name enrich）；收集 open_id 后用 `contact +search-user --user-ids ... --as user`，实名在 `localized_name`。

## 一、全链路采集命令

### 1. 消息（im）能稳拿
```bash
# 本人当天全部发言（第一人称日志的主力，最准最全）
lark-cli im +messages-search --query "" --start "<ISO_START>" --end "<ISO_END>" --sender "<ME>" --page-all --page-limit 10
# @我的（被动卷入的工作）
lark-cli im +messages-search --query "" --start "<ISO_START>" --end "<ISO_END>" --is-at-me --page-all
# 全量（需要群上下文时才用，必加 --page-all，否则只回 20 条）
lark-cli im +messages-search --query "" --start "<ISO_START>" --end "<ISO_END>" --page-all --page-limit 15
```
返回 messages[]，每条 chat_name / chat_type / content / create_time / message_app_link / sender.id / mentions[].id。user 身份。
- **优先 `--sender <ME>` 直接拿本人发言**，比全量再筛准得多（实测全量 300 条里本人只占 72，靠 sender 一次拿全）。
- 私聊的 chat_name 为 null，按"私聊"处理。
- 群多时按"本人发言+被@"权重，别按总量截断。

### 2. 日程（calendar）能稳拿
```bash
lark-cli calendar +agenda --start "<D>" --end "<D>"
```
默认本人主日历。返回 title / start_time / end_time / attendees / location。`--end` 只给日期会自动取 23:59。

### 3. 视频会议 + 纪要（vc）能稳拿
```bash
lark-cli vc +search --participant-ids "<me>" --start "<D>" --end "<D>"      # 本人参与的已结束会议
lark-cli vc +notes --meeting-ids "<meeting_id>"                              # 对每个会取纪要/逐字稿/待办
```
只搜已结束会议。`<me>` 用本人 open_id 或 `me`。

### 4. 妙记（minutes）能稳拿
```bash
lark-cli minutes +search --owner-ids me --start "<D>" --end "<D>"
lark-cli minutes +search --participant-ids me --start "<D>" --end "<D>"
```
两次取并集去重。返回 display_info（含关键词、所有者、开始时间、时长）、app_link。再 `vc +notes --minute-tokens <token>` 取总结/待办/章节。

### 5. 文档/文件/wiki/表格 —— 统一走 drive +search（核心入口）能稳拿
```bash
lark-cli drive +search --query "" --edited-since "<D>" --edited-until "<NEXT>" --page-size 20   # 我编辑的(until 写次日!)
lark-cli drive +search --query "" --opened-since "<D>" --opened-until "<NEXT>" --page-size 20   # 我打开过的(含没改的)
lark-cli drive +search --query "" --commented-since "<D>" --commented-until "<NEXT>"            # 我评论的
```
返回 data.results[]，每条：`title_highlighted`（标题，去掉 `<em>` 标记）、entity_type、result_meta.{doc_types(DOCX/SHEET/BITABLE/WIKI)、owner_name、edit_user_name、create_time_iso、last_open_time_iso、url、token}。
- ⚠️ `--edited-until` 写当天 = 零区间，必须写**次日**。标题在 `title_highlighted`，不在 result_meta。
- `--mine` 限本人 owner；`--doc-types docx,sheet,bitable,wiki,file` 限类型。
- ⚠️ `my_edit_time`/`my_comment_time` 是小时级粒度，sub-hour 会 snap。
- ⚠️ `--opened-since` 窗口上限 90 天，查当天无影响。
- 拿到 token 后取内容：`docs +fetch --api-version v2 --doc <token>` / `sheets +read` / `base +record-list`。

### 6. 任务（task）能稳拿（注意坑）
```bash
lark-cli task +get-my-tasks --created_at "<D>"        # ⚠️ created_at 只认 ISO 日期，不认 7d 这种相对值
lark-cli task +get-my-tasks --complete                # 只看已完成
```
完成时间无服务端过滤，拿回来本地按 completed_at 筛当天。

### 7. 审批（approval）需验证（注意坑）
```bash
lark-cli approval instances initiated                 # 我发起的实例列表
lark-cli approval tasks query                          # 待办/已办审批任务
lark-cli approval instances get --instance-code <code> # ⚠️ initiated 返回不带时间戳，逐条 get 补 create_time 再按当天筛
```
initiated 返回 definition_name / initiator_name / instance_code / instance_status / summaries(审批内容键值)，无时间，必须 get 补。

### 8. OKR 能稳拿
```bash
lark-cli okr +cycle-list --user-id "<me>"             # 本人周期，可 --time-range "2026-06--2026-06"
lark-cli okr +cycle-detail --cycle-id "<id>"          # 周期内目标和KR
lark-cli okr +progress-list --target-id "<id>" --target-type objective   # 进展，按 modify_time 取当天
```
关键产出与决策挂 OKR 目标就靠这个。

### 9. 考勤（attendance）能稳拿
```bash
lark-cli attendance user_tasks query --check-date-from "<YMD>" --check-date-to "<YMD>" --employee-type "employee_no"
```
返回上班/下班打卡时间、结果（正常/迟到/早退）。user_ids 留空即查本人。给日志一个真实上下班骨架。

### 10. 邮件（mail）能稳拿
```bash
lark-cli mail +triage --filter '{"folder":"inbox","time_range":{"start_time":"<ISO_START>","end_time":"<ISO_END>"}}'
lark-cli mail +triage --filter '{"folder":"sent","time_range":{"start_time":"<ISO_START>","end_time":"<ISO_END>"}}'
```
收件箱 + 已发送各一次。`+message`/`+messages` 取正文。

### 人名解析（contact）—— 内部外部联系人都能查到实名 + 公司
```bash
# 把 open_id（含外部跨租户联系人）批量反查实名，必须 --as user 用本人身份
lark-cli contact +search-user --user-ids "ou_xxx,ou_yyy" --as user
```
返回 users[]，每个：`localized_name`（实名）、`department`（公司/部门）、`is_cross_tenant`（是否外部）、`p2p_chat_id`、`has_chatted`。
- ⚠️ **实名在 `localized_name`，不是 `name`**（name 对外部用户为 null，这是之前踩的大坑）。
- 默认 includes 外部用户，这是查到外部联系人实名 + 公司的唯一可靠路径。CLI 子命令也只有 `+search-user` 和 `+get-user`，查别人统一走 search-user。
- 私聊对方 open_id 怎么拿：`messages-search --chat-id <oc_xxx>` 返回里带 `chat_partner.open_id`，或会话消息里非本人的 `sender.id`。
- 流程：整理阶段把所有出现过的 open_id（消息 sender、@对象、任务负责人）收集去重，一次 search-user 批量解析成「实名（公司）」，再回填进日志。

## 二、结构化飞书文档（docs v2 DocxXML）

v2 用 `--content` 传 DocxXML（v1 才用 --markdown）。**跨目录必须走 stdin `--content -`**。XML 里 `<title>` 提供标题，无需再传 --title。

把 XML 写到文件（如 /tmp/doc.xml），然后：
```bash
cat /tmp/doc.xml | lark-cli docs +create --api-version v2 --content -
```
返回 `data.document.{document_id, url, new_blocks[]}`。**每个 `<whiteboard>` 标签都被建成空白画板**，对应一个 `new_blocks[].block_token`，画板内容在第三章单独写入。后续补段落用 `cat seg.xml | lark-cli docs +update --api-version v2 --doc <token> --mode append --content -`。

XML 骨架（结果与判断在前、明细在后；章节标题不带 emoji；whiteboard 一律 `type="blank"` 占位，按出现顺序对应 new_blocks）：
```xml
<title>收工日志 · 2026-05-26 周二 · 李祥瑞</title>
<callout emoji="🌅" background-color="light-blue"><p><b>今日一句话</b>：点出当天最重要的事，战略 / 决策优先冒头</p><p>N 场会 · M 篇产出 · K 条沟通 · …</p></callout>
<h1>今日全景</h1><whiteboard type="blank"></whiteboard>
<h1>一天怎么过的</h1><whiteboard type="blank"></whiteboard>
<h1>关键产出与决策</h1><ul><li><b>客户咨询 ｜ 张三（XX 公司）</b>：结果一句话，能量化就量化。计划兑现（昨日对照）也并到这里：昨天定的 N 件完成 M 件</li></ul>
<h1>今日数据</h1><whiteboard type="blank"></whiteboard><p><b>数据小结</b>：1 场会 + 1 妙记 ｜ 发言 N 条 ｜ 编辑 K 篇、查阅 J 篇</p>
<h1>今日洞察</h1><callout emoji="💡" background-color="light-yellow"><p>1. 从数据提炼的判断：重心转向 / 某条线索的价值 / 精力节奏规律</p><p>2. …（2-3 条，不只罗列）</p></callout>
<h1>事项明细</h1><table><thead><tr><th background-color="light-gray">事项</th><th background-color="light-gray">对接人</th><th background-color="light-gray">过程</th><th background-color="light-gray">进展/卡点</th></tr></thead><tbody><tr><td>xxx</td><td>张三（XX 公司）</td><td>来龙去脉、沟通、救火</td><td>完成度/卡在哪</td></tr></tbody></table>
<h1>卡点 · 待办 · 明日聚焦</h1><checkbox done="false">没做完的 xxx，卡在 yyy</checkbox><p><b>明日聚焦</b></p><ul><li>从待办提取（提不出不写）</li></ul>
<h1>数据来源</h1><p>本日志由飞书 CLI 自动聚合：消息、文档、日历、妙记、任务…对接人实名经飞书通讯录查得。⚠️ 某源失败在此注明。</p>
```
注意：**章节标题（h1）不带 emoji**；callout 高亮框的 emoji 属性（🌅💡）是组件图标，可留。常用块：`<callout emoji background-color>`、`<grid><column width-ratio>` 分栏、`<table>`、`<checkbox done>`、`<hr/>`、`<ul>/<ol>`。

归档：`drive` 移到固定文件夹 / `wiki` 建节点，命名含日期，累积成时间线。

## 三、画图语法（先占位，再写入）

**实测铁律：文档里的 whiteboard 必须先建成 `type="blank"` 占位，create 返回 block_token，再用 `whiteboard +update` 把 mermaid 灌进去。** 不能在 create 时直接嵌 mermaid（会被当空白板，内容丢失）。block_token 顺序 = XML 里 whiteboard 出现顺序。

```bash
# 1. create 后从 new_blocks[] 取每个 block_token（见第二章）

# 2. 思维导图：mermaid 写文件，stdin 灌进第 1 个画板
#   /tmp/mindmap.mmd:
#     mindmap
#       root((今日工作))
#         客户沟通
#           xxx
#         内容产出
#           xxx
cat /tmp/mindmap.mmd | lark-cli whiteboard +update --whiteboard-token "<block_token_1>" --input_format mermaid --source - --overwrite --as user

# 3. 完成度/精力饼图：灌进第 2 个画板
#   /tmp/pie.mmd:
#     pie title 今日精力分布
#         "社区答疑" : 40
#         "内容产出" : 25
cat /tmp/pie.mmd | lark-cli whiteboard +update --whiteboard-token "<block_token_2>" --input_format mermaid --source - --overwrite --as user

# 4. 一天时间线（复杂，走画板 DSL milestone，见 lark-whiteboard skill scenes/milestone.md 生成 JSON）
npx -y @larksuite/whiteboard-cli -i timeline.json --to openapi --format json \
  | lark-cli whiteboard +update --whiteboard-token "<block_token_3>" --source - --input_format raw --overwrite --as user

# 5. 导出预览图验证渲染（--output 也只认相对路径！）
lark-cli whiteboard +query --whiteboard-token "<block_token>" --output_as image --output ./preview.png
```

mermaid 节点文字避免裸 `()`（root 的 `root((标题))` 除外）和特殊字符，否则可能渲染异常。

## 四、行内交互组件（v9 工作枢纽，全部实测渲染通过）

让日志每个实体都能点，是把"文字日志"升级成"工作枢纽"的关键。都在 docs v2 XML 里写。

**@ 真人**（鼠标点上看资料、能触达；本人的活也 @ 本人）：
```xml
<cite type="user" user-id="ou_xxx"></cite>
```
空标签，飞书自动填 user-name。事项明细对接人列、沟通对象列、待办责任人、关键产出，凡是人名一律用它。实名仍取 `search-user` 的 `localized_name`；@ 渲染显示对方在飞书的账号名。搜不到的人保持文字。在 `<td>`、`<checkbox>`、`<li>` 里都能用，已验证。

**@ 文档 / 链接**：
```xml
<cite type="doc" doc-id="docx_token"></cite>        <!-- 文档卡片，仅 docx token 适用 -->
<a href="https://host/wiki/xxx">标题</a>            <!-- 普通超链接，wiki 和外部域名用这个，已验证可点 -->
<a type="url-preview" href="https://...">标题</a>    <!-- 链接预览卡 -->
```

**群聊入口**（点进去直达那个群）：
```xml
<a href="https://applink.feishu.cn/client/chat/open?openChatId=oc_xxx">群名</a>
```
群 chat_id 从消息的 `chat_id` 字段取。

**会议三链接**（会议与纪要板块）：`vc +notes --minute-tokens <token>` 返回 `note_doc_token`、`verbatim_doc_token`，拼成：
- 妙记原文 `https://host/minutes/<minute_token>`
- 智能纪要 `https://host/docx/<note_doc_token>`
- 文字记录 `https://host/docx/<verbatim_doc_token>`

**数字卡看板**（今日数据，比一行文字清爽）：
```xml
<grid>
<column width-ratio="0.25"><h3>1 场会议</h3><p>含 1 篇妙记</p></column>
<column width-ratio="0.25"><h3>72 条发言</h3><p>覆盖 16 会话</p></column>
<column width-ratio="0.25"><h3>22 篇文档</h3><p>编辑 3 查阅 19</p></column>
<column width-ratio="0.25"><h3>56 条沟通</h3><p>社区私聊与群</p></column>
</grid>
```

**文档价值分级**（文档与资料的「收到的分享」）：每篇判断用途 + 价值，加粗前缀分三级：
- `<b>值得沉淀</b>` 与本人业务同赛道、可复用
- `<b>可参考</b>` 有借鉴价值
- `<b>路过</b>` 通知/引导类，了解即可

不确定的 `docs +fetch --doc <token>` 取标题摘要核对，别堆链接不看内容。
