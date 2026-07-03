---
name: group-activity-base
description: 微信群活跃度多维表格技能。把指定微信群从建群到现在的聊天记录（vchat CLI + 本地解密库 zstd 解压）分析成飞书多维表格：成员活跃度（发言数/活跃标签/进群时间/移出时间/潜水名单）+ 发言记录全文 + 每日消息趋势 + 仪表盘。支持为新群从零创建，以及对已建 Base 做水位式增量更新。当用户说"做 XX 群的活跃度表"、"群活跃度多维表格"、"更新活跃度表"、"谁没发言/潜水名单"、"活跃度仪表盘"时触发。
---

# 群活跃度多维表格

## 概览

一条流水线：`vchat` 导出 + `~/.vchat/data/decrypted/message/*.db` 原始 zstd 内容 → `scripts/extract_group_activity.py` 全量分析 → `lark-cli` 写入飞书 Base（三张表 + 仪表盘）。

**先读 [references/base-schema.md](references/base-schema.md)**：字段 schema、仪表盘规范、lark-cli 实战坑点（相对路径 @file、--yes 规则、批量更新语义、select 选项 not_found 等，都是实测踩过的）。

**前置依赖**（安装见 README.md）：
- `vchat`（本仓库 `cli/vchat/`）：微信本地数据解密与查询，需先跑通 `vchat ls`
- `lark-cli`（`npm i -g @larksuite/cli`）：飞书 CLI，需先完成 `lark-cli auth` 授权
- Python `zstandard`：`pip3 install zstandard`
- 环境变量 `GAB_SELF_NAME`：你自己的显示名（vchat 导出里本人是 "me"，用它替换）

**本地登记表**：每建一个群的 Base，把 base_token / table_id / dashboard_id 记到本地私有文件（如 `~/.config/group-activity-base/groups.md`），**不要提交进任何公开仓库**。下次增量更新直接查登记表拿 ID。

## 模式一：为群从零创建（主场景："做 XX 群的活跃度表"）

1. `python3 scripts/extract_group_activity.py "<群名>"`，读输出的 summary.json 核对计数
2. `lark-cli base +base-create --name "<群名> · 群活跃度分析" --table-name "成员活跃度" --fields '<schema 见 references>'`
3. `+table-create` 建「发言记录汇总」和「每日消息趋势」。发言记录汇总的「类型」select **选项必须一次配全**：先统计本群 msg_batch 里实际出现的类型，缺的选项加进字段 JSON（缺选项整批报 800030005）
4. cd 到脚本输出目录（`--json @file` 只认相对路径），逐批 `+record-batch-create` 导入三张表，串行执行，1254291 冲突等 2 秒重试
5. 建「潜水名单（零发言）」筛选视图：`+view-create --json '{"name":"潜水名单（零发言）","type":"grid"}'` + `+view-set-filter`（tuple 格式：`[["活跃标签","intersects",["潜水（零发言）"]],["在群状态","intersects",["在群"]]]`）
6. 默认视图改名：每张表的「Grid View」用 `+view-rename --name <表名>` 改成和表同名；发言记录汇总的视图加时间升序 `+view-set-sort --json '{"sort_config":[{"field":"时间","desc":false}]}'`
7. 按 references 的「仪表盘规范（9 组件）」串行创建 + `+dashboard-arrange`。排行榜的 ranking 类型是 UI 专属（API 建不了），用降序 bar 等价替代，报告里提醒用户可在 UI 手动换
8. **自检（必做）**：分页数出三张表行数对 summary.json，`+dashboard-block-get-data` 核对指标卡数值
9. 把新 Base 的 token / table ids 记进本地登记表

## 模式二：水位式增量更新

**铁律：绝不重写已入库的旧数据。** 发言记录汇总是 append-only：唯一基准是表内「时间」列的最大值（水位），只把水位之后的新消息追加进去，旧消息一条不动。

1. **取水位**：`+record-list --field-id 时间 --sort-json '[{"field":"时间","desc":true}]' --limit 1`
2. **提取**：`python3 scripts/extract_group_activity.py "<群名>" --since "<水位时间>"`（activity/daily 全量重算，msg_batch 只出新增）
3. **成员表最小化更新**：拉现有记录和 activity.csv 逐行 diff，**只动有变化的行**（水位后发过言的人 + 近7天窗口滑动影响的人）逐条 `+record-upsert`；新成员 `+record-batch-create`；退群的只改在群状态不删行。注意单条 upsert 约 1s，>100 条分段跑
4. **发言记录追加**：逐批导入新增 msg_batch
5. **每日趋势**：删掉最新一天旧行（可能是半天数据），按 daily.csv 补写缺失日期
6. **自检**：行数对 summary，抽查 1-2 人发言数

已建 Base 的仪表盘和视图可能被用户手动调整过（换组件类型、改布局、改名），增量更新**只动数据不动结构**：不要 arrange、不要增删组件、不要改视图。

## 活跃标签阈值

核心活跃 ≥100 / 高活跃 ≥30 / 中活跃 ≥10 / 低活跃 ≥3 / 仅冒泡 1-2 / 潜水 0（改动需同步已有表）

## 数据能力边界（提前给用户预期）

- **完整历史名册**：成员表 = 现存成员 + 发过言的退群者 + 隐形退群成员（进过群但零发言就走的人，从入群/移出系统消息重建）。被管理员移出的有「移出时间」；自行退群微信不发系统消息，只能推断存在
- **进群时间**：来自入群系统消息（邀请 + 扫码 + 建群初始名单）。入群时昵称 ≠ 当前昵称，模糊匹配失败时兜底（有初始名单用建群时间，否则用首次发言近似）
- **隐形成员的 wxid**：用昵称反查本地联系人库，唯一命中才回填，重名不猜，查无留空——空值是诚实状态
- **微信号（alias）拿不到**：微信只给好友同步微信号，非好友群成员服务端不下发，不要加这列
- 发言内容截断 1800 字符；图片/表情/视频等媒体消息只有类型标签
- 数据新鲜度取决于 vchat 解密缓存；陈旧先刷新（见 vchat 文档）
