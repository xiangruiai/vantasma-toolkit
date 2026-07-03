# 字段 schema + 仪表盘规范 + lark-cli 实战坑点

> 全部来自数百人真实大群实测，不是文档抄的。

## 表一：成员活跃度

```json
[{"type":"text","name":"昵称"},{"type":"text","name":"wxid"},
 {"type":"number","name":"总发言数","style":{"type":"plain","precision":0}},
 {"type":"number","name":"文本消息数","style":{"type":"plain","precision":0}},
 {"type":"number","name":"活跃天数","style":{"type":"plain","precision":0}},
 {"type":"number","name":"近7天发言数","style":{"type":"plain","precision":0}},
 {"type":"datetime","name":"首次发言","style":{"format":"yyyy-MM-dd HH:mm"}},
 {"type":"datetime","name":"最近发言","style":{"format":"yyyy-MM-dd HH:mm"}},
 {"type":"datetime","name":"进群时间","style":{"format":"yyyy-MM-dd HH:mm"}},
 {"type":"datetime","name":"移出时间","style":{"format":"yyyy-MM-dd HH:mm"},"description":"被清退出群的时间（来自系统消息）；空=在群或自行退群"},
 {"type":"select","name":"活跃标签","multiple":false,"options":[
   {"name":"核心活跃","hue":"Red","lightness":"Light"},{"name":"高活跃","hue":"Orange","lightness":"Light"},
   {"name":"中活跃","hue":"Yellow","lightness":"Light"},{"name":"低活跃","hue":"Blue","lightness":"Lighter"},
   {"name":"仅冒泡","hue":"Gray","lightness":"Lighter"},{"name":"潜水（零发言）","hue":"Purple","lightness":"Lighter"}]},
 {"type":"select","name":"在群状态","multiple":false,"options":[
   {"name":"在群","hue":"Green","lightness":"Light"},{"name":"已退群","hue":"Gray","lightness":"Lighter"}]}]
```

## 表二：发言记录汇总

类型选项按你的群实际出现的补齐（脚本跑完统计 msg_batch 里的类型集合再建表）：

```json
[{"type":"datetime","name":"时间","style":{"format":"yyyy-MM-dd HH:mm"}},
 {"type":"text","name":"发言人"},{"type":"text","name":"wxid"},
 {"type":"select","name":"类型","multiple":false,"options":[
   {"name":"文本","hue":"Blue","lightness":"Light"},{"name":"引用回复","hue":"Wathet","lightness":"Light"},
   {"name":"图片","hue":"Green","lightness":"Lighter"},{"name":"表情","hue":"Yellow","lightness":"Lighter"},
   {"name":"链接分享","hue":"Purple","lightness":"Lighter"},{"name":"视频号","hue":"Carmine","lightness":"Lighter"},
   {"name":"视频","hue":"Orange","lightness":"Lighter"},{"name":"合并转发","hue":"Turquoise","lightness":"Lighter"},
   {"name":"文件","hue":"Gray","lightness":"Light"},{"name":"视频号直播","hue":"Carmine","lightness":"Light"},
   {"name":"视频分享","hue":"Orange","lightness":"Light"},{"name":"位置","hue":"Lime","lightness":"Lighter"},
   {"name":"动图","hue":"Yellow","lightness":"Light"},{"name":"接龙","hue":"Green","lightness":"Light"},
   {"name":"名片","hue":"Gray","lightness":"Lighter"},{"name":"红包","hue":"Red","lightness":"Light"},
   {"name":"转账","hue":"Red","lightness":"Lighter"},{"name":"群公告","hue":"Red","lightness":"Lighter"},
   {"name":"笔记","hue":"Wathet","lightness":"Lighter"},{"name":"音乐","hue":"Purple","lightness":"Light"},
   {"name":"语音","hue":"Lime","lightness":"Light"},{"name":"视频号名片","hue":"Carmine","lightness":"Lighter"},
   {"name":"小程序","hue":"Blue","lightness":"Lighter"}]},
 {"type":"text","name":"内容"}]
```

## 表三：每日消息趋势

```json
[{"type":"datetime","name":"日期","style":{"format":"yyyy-MM-dd"}},
 {"type":"number","name":"消息数","style":{"type":"plain","precision":0}}]
```

## 仪表盘规范（9 组件，串行创建）

| # | type | 名称 | data_config 要点 |
|---|---|---|---|
| 1 | statistics | 群成员总数 | count_all + filter 在群状态=在群 |
| 2 | statistics | 总发言数（建群至今） | SUM 总发言数 |
| 3 | statistics | 发过言的人数 | count_all + filter 总发言数>0 |
| 4 | statistics | 潜水（零发言）人数 | count_all + filter 活跃标签=潜水 且 在群 |
| 5 | pie | 活跃标签分布（在群成员） | count_all, group_by 活跃标签 value desc, filter 在群 |
| 6 | line | 每日消息趋势 | SUM 消息数, group_by 日期 group asc（数据源：每日消息趋势表） |
| 7 | column | 近7天活跃发言分布 | SUM 近7天发言数, group_by 昵称 value desc, filter ≥5 |
| 8 | wordCloud | 发言关键词云图 | `{"table_name":"发言记录汇总","count_all":true,"group_by":[{"field_name":"内容","mode":"integrated"}]}`（不要传 sort，CLI 校验 sort 必须带 order） |
| 9 | bar | 发言排行榜 | SUM 总发言数, group_by 昵称 value desc, filter 总发言数>0 |

- 组件 9 的理想形态是「排行榜（ranking）」类型，但 **ranking 无法经 API 创建**（CLI 白名单和 v3 blocks endpoint 都拒收），只能建完后在 UI 手动换。bar 降序在数据上完全等价
- 布局（位置/大小）没有 API：创建完 `+dashboard-arrange` 一次智能排版，精调靠 UI
- `+dashboard-create` 偶发报 800008006 内部错误但**其实已创建成功**：先 `+dashboard-list` 确认再决定重试，否则会撞名报错

## lark-cli 实战坑点

1. `--json @file` 的文件路径**必须是相对路径**（先 cd 到批次目录），绝对路径报 "invalid JSON file path"
2. `+record-batch-update` / `+record-upsert` **没有** `--yes`；`+table-delete` / `+field-delete` **必须带** `--yes`
3. `+record-batch-update` 是同值批量：一份 patch 应用到整个 record_id_list。逐行不同值 → 按值分组再逐组调用（进群时间这类高度重复的值分组后调用次数骤降）
4. `+record-search --json` 是 `{"keyword":"...","search_fields":[...]}` 形态；tuple filter 走 `+record-list --filter-json '{"logic":"and","conditions":[["字段","==","值"]]}'`
5. `+view-create` 用 `--json '{"name":"x","type":"grid"}'`，没有 `--name` flag；视图改名是 `+view-rename --name`
6. **调用不存在的子命令不报错**（回落到 help 且 exit 0），看起来像成功实际没执行——任何"改完"都要用对应 get/list 复核
7. select 写入未知选项整批报 800030005，不会自动加选项；建表时选项配全，后补用 `+field-update` 全量提交 options + `--yes`
8. `+record-list` 计数：`--limit 200 --offset N` 翻到最后一页看 `Meta: count=`
9. `+record-upsert` 单条约 1s，>100 条注意 shell 超时，分段或后台跑
10. 数字字段空值转 null；datetime 用 `"YYYY-MM-DD HH:mm:ss"` 字符串
11. 消息批次文件用 **3 位编号**（msg_batch_000），两位编号时第 100+ 批字典序插到 10/11 之间，导入顺序乱掉，表格底部看起来"缺最新数据"。视图加时间排序兜底
12. `+record-batch-update` 对不存在的 record_id 也返回 ok:true（服务端不校验），成功返回≠真写进去，抽查复核才算数
13. 批量写入单批最多 200 行；连续写同一表串行执行，1254291 冲突等 2 秒重试

## 微信数据侧的关键事实

- vchat 导出 JSON 里 zstd 压缩内容已被 UTF-8 replace 损坏，**消息内容必须回解密库原始 BLOB 取**（`~/.vchat/data/decrypted/message/*.db` 的 `Msg_<md5(chatroom_id)>` 表，zstd magic `28 B5 2F FD`）
- 本人消息 sender_name 是 "me" → 用 `GAB_SELF_NAME` 环境变量的名字替换
- 群本身（chatroom id 作 sender）和 local_type=10000 系统消息不算发言
- 入群事件三来源：①首条邀请通知 XML「群聊参与人还有」=建群初始名单 ②`"A"邀请"B"加入了群聊` ③`"X"通过扫描"Y"分享的二维码加入群聊`（社区群扫码占比可能近半，漏了会缺一大片进群时间）
- 移出事件：`你将"X"移出了群聊` / `"A"将"B"移出了群聊`；批量清退会共享同一秒时间戳
- 有的成员微信昵称本身是空的，表里用「(无昵称)」占位
