# vchat CLI · 优先路径

如果运行机器上装了 `vchat` CLI（通常在 `~/.local/bin/vchat`），它是微信本地数据查询/导出的一站式工具。它内部走的是 wechat-decrypt 项目的 venv，独立于系统 Python 和 MCP server，**更稳定也更快**。

skill 里所有微信数据访问优先走 vchat CLI，MCP 工具作为兜底。如果 `vchat` 不在 PATH 中，自动降级到 MCP + 本 skill 自带脚本。

**注意**：`vchat` CLI 和 `wechat-decrypt` 项目目前是作者私有项目，未公开发布。本 skill 文档保留对它们的引用是为了在作者本机以及未来开源后能直接复用。没有这两个的用户，**只能走 MCP 路径**，详见 `data-sources.md`。

## 一、能力对照表

| 任务 | 首选（vchat CLI） | 备选（MCP / 脚本） |
|---|---|---|
| 拉聊天记录 | `vchat history "<群名>" -n N --asc` | `mcp__wechat__get_chat_history` |
| 找联系人 | `vchat contacts "<显示名>"` | `mcp__wechat__get_contacts` |
| 查群成员 wxid 映射 | （vchat 暂不支持群成员列表）| `lookup_members.py` |
| 列语音 | `vchat voice-ls "<群名>" -n N` | `mcp__wechat__get_voice_messages` |
| 转写语音 | `vchat voice-transcribe "<群名>" --local-id N` | `mcp__wechat__transcribe_voice` / `transcribe_voices.py` |
| 导出头像 | `vchat avatar "<名/wxid>" -o <dir>` | `extract_avatars.py`（sqlite blob） |
| 数据洞察 | `vchat stats-overview / top-contacts / top-groups` | （无） |
| 全量导出 | `vchat export "<群名>" --md -o <path>` | （无） |
| 数据库新鲜度 | `vchat info` | （无） |

## 二、最常用的 5 个命令

### 1. 拉群历史（首选用法，避免 MCP 爆 token）

```bash
vchat history "<群名>" -n 5000 --asc > /tmp/chat_log_<日期>_<群名>.txt
```

- `-n` 控制条数，5000 条已覆盖大多数群史场景
- `--asc` 旧到新，故事按时间叙事
- 直接写文件，AI 用 Read 分块读，不会爆 context
- **典型场景**：做某群 20 天群史时，MCP `get_chat_history` 拉 5000 条会返回 240KB+，触发自动落盘；vchat 直接落盘没有这个问题

### 2. 列语音 + 转写

```bash
# 看群里有几条语音
vchat voice-ls "<群名>" -n 100

# 转写单条
vchat voice-transcribe "<群名>" --local-id <N>
```

输出格式：
```
[2026-05-12 00:27] (zh)
那还是不一样的没置顶的群讨就会永远的忘记...
```

**优势**：用 vchat 项目自己的 venv 跑 whisper（已装 `openai-whisper` + `silk-python`），不依赖系统 Python，不需要重启 MCP server。

**批量**：vchat 不支持单命令批量转写，AI 用 shell 循环或多次调用即可：
```bash
for ID in 11239 7348 344 343 335; do
  vchat voice-transcribe "<群名>" --local-id $ID
done > /tmp/voices_<日期>_<群名>.txt
```

### 3. 找单人 wxid

```bash
vchat contacts "示例联系人A"
# 输出: wxid_example001  昵称: 示例联系人A
```

注意：这是「全局好友/联系人搜索」，**不限定某个群**。一个昵称可能对应多个人，要看清楚。
查群成员 wxid 映射（带群范围限定）仍用 `lookup_members.py`。

### 4. 导出头像

```bash
# 单个
vchat avatar "李祥瑞" -o /tmp/avatars
# 输出: /tmp/avatars/李祥瑞_wxid_example002.jpg

# 批量（不推荐，7000+ 个）
vchat avatar --all -o /tmp/all_avatars
```

文件名格式 `<显示名>_<wxid>.jpg`，可直接用 wxid 反查或显示名匹配。

skill 现有的 `extract_avatars.py` 是 sqlite 直读 + base64 内嵌 HTML，更适合 skill 编排（不写中间文件）。如果只需要拿头像看看，用 vchat 更方便。

### 5. 数据洞察

```bash
vchat stats-overview
# 消息总数: 224,736 / 聊天对象数: 757 / 时间跨度: 2026-03-04 至 2026-05-12

vchat stats-top-groups -n 10    # 最活跃的群
vchat stats-top-contacts -n 10  # 最活跃的私聊
vchat stats-monthly             # 月活跃度
vchat stats-hourly              # 小时活跃度

vchat voice-stats               # 语音密度排行（决定值不值得转写）
```

`vchat voice-stats` 在 Step 1.5 之前先看一眼很有价值：决定这个群有没有语音要转。

## 三、何时仍用 MCP / 脚本

- **AI 想看消息内容做即时判断**（不是落盘）→ MCP `get_chat_history` 直接返回（小量）
- **生成 HTML 时要 base64 头像内嵌**→ `extract_avatars.py`（一次性 sqlite 拿全部 wxid 的 blob，比循环 vchat 快）
- **查群成员 wxid 映射** → `lookup_members.py`（vchat 暂不支持）
- **vchat 不可用**（卸载、路径变了）→ 全部回落 MCP

## 四、新鲜度自检

vchat 内部依赖解密后的数据库，定期需要 `sudo wxrefresh` 重解密。`vchat info` 输出会显示「上次 sudo wxrefresh: 距今 X.Yh」。

- 0-6h：放心用
- 6-24h：可能漏掉最近 N 小时的消息
- > 24h：建议先跑 `sudo wxrefresh` 再继续

skill 不强制检查新鲜度（AI 跑命令时 vchat 会在 stderr 提示），但做「今天的日报」如果数据库太旧会丢消息。
