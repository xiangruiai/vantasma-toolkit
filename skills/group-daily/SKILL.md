---
name: group-daily
description: |
  群日报技能。把指定微信群一天（或指定时间段）的聊天记录，做成杂志风的日报
  HTML + PNG 长图：含报头、主标题与开场叙述、6-8 段时间故事线（带真实头像）、
  6-8 张今日高光人物卡、可抄作业的 SOP 与 Q&A，以及底部数据条。
  本技能内嵌的设计准则来自《群日报形态横纵分析报告》（QFD 质量屋打分
  + Spotify Wrapped/网易云年报/Stripe Letter 等横向对比），明确摒弃
  「智能纪要」范式，走「故事化年报」路线。
  当用户说"做群日报"、"群日报"、"给 XX 群做日报"、"XX 群今天聊了什么做个日报"、
  "整理一下今天 XX 群"时触发。
---

# Group Daily · 群日报

## 用途

把一个微信群一天的对话，转化成可消费、可传播、可沉淀的杂志风内容产品。
不是会议纪要，是一篇短篇报道。

## 何时使用

用户说以下话时主动触发：

- 「做群日报」「给 XX 群做日报」「XX 群今天聊了什么做个日报」
- 「整理一下今天 XX 群的对话」
- 「XX 群昨天聊了啥，做个总结」
- 「再来一份群日报」（继续之前的群）

如果用户只说「做日报」没指明群，主动追问群名。

## 输入

- **群名**（必填）：微信群的显示名
- **日期/时间段**（可选）：默认今天 00:00 → 现在；用户也可以指定 "昨天" "2026-05-11" "近三天" 等

## 输出

- `~/Desktop/群日报_<群名>_<日期>.html`（杂志风 HTML，浏览器看）
- `~/Desktop/群日报_<群名>_<日期>.png`（900px 宽长图 PNG，发群发朋友圈）
- 生成后自动 open 两个文件
- 同时归档 story.json 到 `$GROUP_DAILY_VAULT/<日期>_<群名>.json`（默认 `~/Documents/GroupDaily/`）

## 工作流（按顺序执行）

> v2.3（2026-05-13）新增 **Step 0 强制刷新解密**——每次跑日报先无条件 `sudo -n wxrefresh`，根治"拿不到今天最新消息"的问题。下面 Step 1 之前必看。

### 工具优先级：CLI 优先，MCP 兜底（v2.2 新增）

如果运行机器上装了 `vchat` CLI（见 README），skill 里所有微信数据访问**优先走 vchat CLI**，MCP 工具作为兜底。完整对照见 `references/vchat-cli.md`。

| 任务 | 首选 | 备选 |
|---|---|---|
| 拉聊天记录 | `vchat history "<群名>" -n N --asc > /tmp/log.txt` | `mcp__wechat__get_chat_history` |
| 列语音 | `vchat voice-ls "<群名>"` | `mcp__wechat__get_voice_messages` |
| 转写语音 | `vchat voice-transcribe "<群名>" --local-id N` | `mcp__wechat__transcribe_voice` |
| 找单人 wxid | `vchat contacts "<显示名>"` | `mcp__wechat__get_contacts` |
| 数据洞察 | `vchat stats-overview / voice stats` | （无） |

**为什么 CLI 优先**：
- 拉大量历史不爆 token（直接落盘，AI Read 分块）
- 语音转写零依赖（vchat 自带 venv 装好 whisper + silk）
- 不需要重启 MCP server

### Step 0：强制刷新解密（必跑）

群日报必须基于"刚解密"的最新数据。每次触发 skill 都先无条件刷一次：

```bash
sudo -n wxrefresh
```

- 已配 NOPASSWD 时 AI 直接跑不要密码，2-5 秒返回（NOPASSWD 配置见 `references/wxrefresh-setup.md`）
- 内部调 `vchat decrypt` 全量重解所有加密 db
- 跑完核对 stamp：

  ```bash
  STAMP="$HOME/.cache/wxrefresh.stamp"
  test -f "$STAMP" && python3 -c "
  import os, time
  t = int(open(os.path.expanduser('~/.cache/wxrefresh.stamp')).read())
  print('stamp:', time.strftime('%F %T', time.localtime(t)),
        '·', int(time.time() - t), '秒前')"
  ```

  距今 > 30 秒说明刷新没跑成，**禁止继续**，先排错。

- 失败模式：
  - `WeChat 主进程没在跑` → 让用户打开微信再回来
  - `sudo: a password is required` → NOPASSWD 配置丢失或未装，按 `references/wxrefresh-setup.md` 重装
  - vchat 报 PermissionError → 数据目录被 root 拿了，wxrefresh 末尾的 chown 没生效，手动 `sudo chown -R $(whoami):staff ~/.vchat/data`

**不要跳过**：vchat 的 mtime-cache 自动追新有延迟，可能漏最近 1-5 分钟的消息；强制 decrypt 才能 100% 保证拿到今天最新。

### Step 1：拉聊天记录

**首选**（避免 MCP 爆 token）：

```bash
vchat history "<群名>" -n 5000 --asc > /tmp/chat_log_<日期>_<群名>.txt
```

- `-n` 视范围调整（一天 1000 足够，20 天群史用 5000-10000）
- `--asc` 旧到新方便叙事
- AI 用 Read 工具分块读这个文件
- **vchat 模糊匹配**：群名匹配到的实际群可能跟你输的不一样。看 `chat_log` 第一行的「XXX 的消息记录」确认实际匹中的群名，不一致就用更精确的名字重拉。

**兜底**：MCP `get_chat_history`（小量场景下也快），返回直接看就好。

### Step 1.5：语音转写（如有）

v2.1 新增、v2.2 改首选路径。微信语音消息以 SILK 编码存储，需要解码再转写才能进入日报。

**首选：vchat CLI（v2.2）**

```bash
# 1. 看群里有几条语音（顺手看下值不值得转）
vchat voice-ls "<群名>" -n 100

# 2. 看不见语音就跳过整个 Step 1.5
# 看到语音列表，对每条调:
vchat voice-transcribe "<群名>" --local-id <N>
```

输出格式：
```
[2026-05-12 00:27] (zh)
那还是不一样的没置顶的群讨就会永远的忘记...
```

可以用 shell 循环批量：

```bash
for ID in 11239 7348 344 343 335; do
  echo "=== local_id=$ID ==="
  vchat voice-transcribe "<群名>" --local-id $ID
done > /tmp/voices_<日期>_<群名>.txt
```

**节制**：

- 优先转写时长 ≥ 5 秒的（短的「嗯」「OK」忽略）
- 当天语音 > 30 条时挑核心人物的
- whisper 中文输出常是繁体，AI 引用时按上下文转简体并修订错字

**兜底路径**：

1. MCP `mcp__wechat__transcribe_voice` — server 没装 whisper / 没重启时不可用
2. `scripts/transcribe_voices.py` — 走 `decode_voice` 拿 wav + 系统 whisper CLI（功能完整、但依赖系统 whisper 安装）

写故事时把语音转写当成「真实发言」用，在 quote 里加 `source: "voice"` 和 `duration_s` 字段（见 `references/story-schema.md`），渲染时会显示 🎙 角标。

详细见 `references/vchat-cli.md` 和 `references/data-sources.md` § 四。

### Step 2：基础统计

写一个临时 Python 脚本统计或在脑内算：
- 总消息数 `total_messages`
- 发言人数 `unique_senders`
- 总字数（去除 `[图片]` `[链接]` 等占位）`total_chars`
- 新成员数（看 `[系统]` 消息含 "邀请...加入" 的）

### Step 2.5：加载群风格指纹

这是 v2 的核心升级。**只沉淀群文化，人物画像不沉淀，每次临时分析**。

在动笔写故事前先看「这个群历史上怎么写」：

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/context_helper.py check-style \
    --group-name "<群名>"
```

- 如果 `exists: true`，用 Read 工具加载这份 `styles/<群名>.md`。把里面的一句话定位、文化标签、典型徽章库、内部黑话、禁忌作为写故事的硬约束。
- 如果 `exists: false`，跳过加载（首次跑某群），后续 Step 7.5 会生成 v1 风格。

人物气质由 AI 当天读聊天记录临时判断，不预加载档案（避免给人贴长期标签）。

详细资产结构见 `references/group-style.md`。

### Step 3：阅读并提炼故事

通读聊天记录，按 `references/writing-style.md` 和 `references/design-principles.md` 的要求提炼：

- **opening**：100-200 字开场叙述，一句话钩子 + 故事概括
- **lead_title**：可换行的主标题，凝结今天的核心
- **timeline**：6-8 个时间故事节点，每个含 no/time/badge/cast/theme/story/quotes/output
- **highlights**：6-8 张高光人物（不是发言量排名，是「今天没他故事就少一块」的人）
- **sops**：可抄作业的工作流（如有，从聊天记录里提炼出步骤）
- **qas**：被多人回答的有价值问题（如有）
- **footer_quote**：当天最有共鸣的一句话作为收尾

**节制原则**：宁可少不要多。timeline 6 个就 6 个，highlights 6 个就 6 个，硬凑会稀释故事浓度。

详细字段定义见 `references/story-schema.md`。

### Step 4：查群成员 wxid

为了能加载真实头像，需要拿到群成员的 wxid。

**v2.0 推荐路径**（一行拿全部成员 + 直接 JSON）：

```bash
vchat --json group-members "<群名>" > /tmp/members.json
```

输出格式：
```json
{
  "group": "...", "username": "<...@chatroom>", "member_count": 447,
  "members": [{"username": "wxid_xxx", "nick_name": "...", "remark": "..."}, ...]
}
```

读这个 JSON 后在 cast/highlights 里按显示名匹配 wxid。

**老路径（兼容）**：

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lookup_members.py \
    --group-name "<群名>" \
    --names "示例联系人A,示例联系人C,示例联系人D,..." \
    --out /tmp/members.json
```

把 `names` 参数填入 story 中 cast 和 highlights 里出现的所有人物（不重复）。

**v2.0 加分项**：如果要顺便把头像批量导出落盘（不只是渲染时 base64），加 `--avatars`：

```bash
vchat group-members "<群名>" --avatars -o /tmp/<群名>_avatars/
```

### Step 5：把 wxid 写入 story

**推荐（v2.4）**：写完 story.json 后跑 `resolve_story_wxids.py` 一键批量注入：

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/resolve_story_wxids.py \
    --story /tmp/story_<日期>_<群名>.json \
    --group "<群名>"
```

脚本会：
1. 扫 story 收集所有 cast/highlights 的 name（去重）
2. 三档匹配群成员（nick 完全相等 → remark 完全相等 → 子串包含）
3. 群里找不到的 → 全库 `vchat contacts` 兜底搜
4. 找全 → 退出码 0；缺人 → 退出码 2 + stderr 列出哪些名字没解析

**老路径（手动）**：从 `/tmp/members.json` 按显示名匹配，手动填进 `cast[].wxid` 和 `highlights[].wxid`。容易漏人（漏了静默 fallback 到首字 placeholder），不推荐。

### Step 6：写 story.json + 事实核查

#### 6a. 写

用 Write 工具把完整的 story.json 写到 `/tmp/story_<日期>_<群名>.json`。

#### 6b. 跑事实核查（v2.4 必跑）

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/verify_story.py \
    --story /tmp/story_<日期>_<群名>.json \
    --chat /tmp/chat_log_<日期>_<群名>.txt
```

脚本会逐条 quote 核对原文：
- **A. quote 文字** 能否在原文找到（按 12 字片段子串匹配，容忍 `/` 分隔的多句拼写）
- **B. sender** 是否匹配（容忍后缀括号、emoji；自动处理 `me` ↔ `me 真名` 别名）
- **C. 时间** 是否在该 timeline 节点的 `time` 范围内（支持跨日 `次日`）
- **D. cast** 列表里的人是否在 time 范围内有真实发言

退出码：
- `0` 全过；`1` 有跨节警告（quote 时间不在节点范围内）；`2` 有错位（sender 错位 / quote 找不到）

**非 0 必修**：根据 stderr 改 story.json，再跑一次直到 0。这步是 skill v2.4 的硬约束，跳过 = skill 反模式。

### Step 7：跑主编排

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/make_daily.py \
    --story /tmp/story_<日期>_<群名>.json \
    --out-dir ~/Desktop
```

脚本自动：
1. 从 story 收集所有 wxid，调 extract_avatars.py 导出头像
2. 用模板 + 头像渲染 HTML
3. 用 Chrome headless 截 PNG 长图
4. 自适应裁底
5. 自动 open HTML + PNG

### Step 7.5：更新群风格指纹

写完故事后顺手把今天的群文化观察沉淀进 styles。**只更新群风格，不沉淀任何人物档案**。

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/context_helper.py path \
    --style "<群名>"
```

- 已存在：用 Edit 推进 `last_updated`、追加 `sample_dates`、`sample_count + 1`。如果今天出现了新的内部黑话、新的徽章类型、新的禁忌观察，加入对应小节。
- 不存在：用 Write 生成 v1，按 `references/group-style.md` 的模板填。frontmatter 里 `created` 和 `last_updated` 都填今天，`sample_dates` 填 `[今天]`，`sample_count` 填 1。

**节制原则**：

- styles 的「主流话题」「内部黑话」按重要度精选，不堆砌
- 不要在 styles 里点名固化「X 是 Y 角色」，最多写「这个群通常有 X / Y / Z 几类角色」

### Step 8：归档

```bash
VAULT="${GROUP_DAILY_VAULT:-$HOME/Documents/GroupDaily}"
mkdir -p "$VAULT"
cp /tmp/story_<日期>_<群名>.json "$VAULT/<日期>_<群名>.json"
```

story.json 是最珍贵的资产（比 HTML/PNG 更值钱），归档后可以追溯每天的群叙事。styles 在 Step 7.5 已经更新。

## 设计准则（必读）

加载并遵循 `references/design-principles.md`。核心要点：

1. **时间故事线是骨架**（QFD 矩阵打分 200，最高）
2. **砍掉冗余**：24h 曲线 / 话题分布 / TOP N 排行 / 全员标签册 / Dashboard 都是反模式
3. **杂志风去 AI 化**：衬线字体 + 米黄底 + 朱砂红 + 大编号 + 留白
4. **干货默认 details open**：保证 PNG 截图能看到完整内容
5. **每节点固定结构**：时间 / 角色徽章 / 主题 / CAST 头像 / 故事正文 / 1-3 句金句 / 产出物

## 写作风格（必读）

加载并遵循 `references/writing-style.md`。核心要点：

- 写短篇报道，不写会议总结
- 拒绝 AI 套话和破折号
- 节奏感：长短句交错
- 故事正文 150-250 字一段
- 金句原汁原味（不改造）
- 角色徽章要有性格（提问者 / 救火队员 / 概念原创者）

## 数据源说明

加载并遵循 `references/data-sources.md`。关键路径：

- 聊天记录：`vchat history` CLI（首选）或 `mcp__wechat__get_chat_history`（兜底）
- 群成员：`$VCHAT_DATA_DIR/decrypted/contact/contact.db`（默认 `~/.vchat/data`）
- 头像：`$VCHAT_DATA_DIR/decrypted/head_image/head_image.db`

依赖：Chrome（或 Chromium）+ Pillow。一次性安装见 `install.sh`，自检用 `scripts/check_env.py`。

## Bundled Resources

### 外部依赖（不在 skill 里，但 skill 调用）

| 工具 | 路径 | 作用 |
|---|---|---|
| `wxrefresh` | `~/.local/bin/wxrefresh`（用户自装，包内不分发）| Step 0 强制刷新解密。内部调 `vchat decrypt`。NOPASSWD 配置见 `references/wxrefresh-setup.md` |
| `vchat` | `~/.local/bin/vchat` → `~/Projects/vantasma-toolkit/cli/vchat/vchat` | 微信本地数据查询、解密、导出 |

### scripts/

| 脚本 | 作用 |
|---|---|
| `lookup_members.py` | 根据群名 + 成员显示名列表，查显示名 → wxid 映射 |
| `extract_avatars.py` | 从 head_image.db 导出指定 wxid 的头像为 base64 JSON |
| `render_html.py` | 把 story.json + avatars.json 渲染为杂志风 HTML |
| `html_to_png.py` | 用 Chrome headless 把 HTML 截成长图 PNG，自适应裁底 |
| `make_daily.py` | 主编排（吃 story.json，依次跑上面几个） |
| `context_helper.py` | 群风格指纹的目录助手（v2 新增），检查 style 是否存在、给出文件路径 |
| `transcribe_voices.py` | 微信语音批量转写（v2.1 新增），用 openai-whisper 跑 base 模型，含 wav 签名缓存 |
| `resolve_story_wxids.py` | v2.4 新增。吃 story.json + 群名，自动批量解析 cast/highlights 全部人物的 wxid 并注入，缺人 stderr 报错 |
| `verify_story.py` | v2.4 新增。吃 story.json + chat_target.txt，逐条 quote 核对 sender/文字/时间，错位列报告并非 0 退出 |

### references/

| 文件 | 作用 |
|---|---|
| `design-principles.md` | 来自横纵分析报告的硬约束（什么该做、什么不该做） |
| `story-schema.md` | story.json 完整字段定义和示例 |
| `writing-style.md` | 故事化叙事的写作风格指引（去 AI 化的具体做法） |
| `data-sources.md` | wechat MCP / contact.db / head_image.db 的使用说明 |
| `group-style.md` | v2 新增。群风格指纹的结构定义和写作约定（仅群文化沉淀，不沉淀人物） |
| `vchat-cli.md` | v2.2 新增。vchat CLI 命令速查 + CLI 优先 / MCP 兜底原则 |

### assets/

| 文件 | 作用 |
|---|---|
| `template.html` | 杂志风 HTML 模板（含 `{{TITLE}}` `{{TIMELINE}}` 等占位符） |

## 失败模式与排错

| 现象 | 原因 | 修法 |
|---|---|---|
| 头像全是首字 placeholder | head_image.db 路径错或 wxid 拼错 | 看 `extract_avatars.py` stderr 提示 |
| PNG 底部一大片空白 | 自适应裁底没识别背景色 | 模板里背景色是否被改成奇怪值 |
| 找不到群 | 群名跟 nick_name / remark 不一致 | `lookup_members.py` 会列出候选群 |
| Chrome 找不到 | 没装 Chrome | 装 Chrome / Chromium |
| 故事写得像 AI | 没遵循 writing-style.md | 重写，砍掉 AI 套话 + 加节奏感 |
| 生成挂在 extract_avatars | 数据目录变了 | 设 `VCHAT_DATA_DIR` 或重跑 `sudo vchat setup` |
