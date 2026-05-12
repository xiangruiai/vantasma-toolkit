# 数据源说明

群日报需要从三处取数据：聊天记录、群成员、群成员头像。

## 一、聊天记录（wechat MCP）

工具：`mcp__wechat__get_chat_history`

参数：
- `chat_name`：群名（支持模糊匹配）
- `start_time` / `end_time`：YYYY-MM-DD HH:MM 格式
- `limit`：单次返回数量，默认 50，可设大（500-1000 都可以）
- `oldest_first`：True 表示从最早开始（推荐，方便按时间叙事）

返回的消息行格式：
```
[2026-05-11 09:20] 示例联系人A: 想问一下大家搭建企业的知识库用的什么方案呢？
[2026-05-11 09:21] me: obsidian可以实现
```

`me` 代表当前登录的微信用户（运行 skill 的本机用户）。其他消息按显示名（昵称或备注）展示，不带 wxid。

**注意**：图片消息、引用消息、链接消息会以 `[图片]` `[链接]` `[视频]` 等占位符出现。XML 内容（如卡片消息的 appmsg）会原样混在内容里，需要在叙事时忽略。

## 二、群成员（contact.db）

数据库：`$VCHAT_DATA_DIR/decrypted/contact/contact.db`（默认 `~/Projects/wechat-decrypt`，由 wechat-decrypt 项目生成的解密产物）

关键表：

```sql
-- 群本身（local_type=2 是群）
CREATE TABLE contact(
    id INTEGER PRIMARY KEY,
    username TEXT,         -- 群 wxid，如 45404041702@chatroom
    local_type INTEGER,    -- 2 = 群聊
    nick_name TEXT,        -- 群名
    remark TEXT,           -- 群备注
    head_img_md5 TEXT,
    ...
);

-- 成员关系
CREATE TABLE chatroom_member(
    room_id INTEGER,       -- 关联 contact.id
    member_id INTEGER,     -- 关联 contact.id
    ...
);
```

查群 ID：
```sql
SELECT id, username FROM contact
WHERE local_type=2 AND (nick_name=? OR remark=?);
```

查群成员（含显示名 → wxid 映射）：
```sql
SELECT c.username, c.nick_name, c.remark
FROM chatroom_member cm JOIN contact c ON cm.member_id = c.id
WHERE cm.room_id = ?;
```

封装在 `scripts/lookup_members.py` 里。直接调用即可：

```bash
python3 scripts/lookup_members.py \
    --group-name "祥瑞和Ta的社区朋友们" \
    --names "示例联系人A,示例联系人C,示例联系人D" \
    --out /tmp/members.json
```

## 三、群成员头像（head_image.db）

数据库：`$VCHAT_DATA_DIR/decrypted/head_image/head_image.db`（默认 `~/Projects/wechat-decrypt`）

表结构：
```sql
CREATE TABLE head_image(
    username TEXT PRIMARY KEY,  -- wxid
    md5 TEXT,
    image_buffer BLOB,           -- 头像二进制（JPEG 居多，2-7 KB）
    update_time INTEGER
);
```

封装在 `scripts/extract_avatars.py` 里。输入 `{wxid: 显示名}` 的 JSON，输出 `{显示名: data:image/jpeg;base64,...}` 的 JSON。

```bash
python3 scripts/extract_avatars.py \
    --names-map /tmp/members.json \
    --out /tmp/avatars.json
```

## 四、语音消息（v2.1 新增）

微信语音以 SILK 编码存储，`get_chat_history` 只看到 `[语音]` 占位符。要让语音进入日报，走以下链路：

### 4.1 列出语音

```
mcp__wechat__get_voice_messages chat_name="<群名>" limit=100
```

返回:
```
[2026-05-12 00:27] local_id=11239  18KB
[2026-04-26 04:55] local_id=7348  9KB
```

如果返回 `无语音消息`，跳过整个语音环节。

### 4.2 解码 SILK → WAV

```
mcp__wechat__decode_voice chat_name="<群名>" local_id=<N>
```

返回:
```
解码成功!
  文件: ~/Projects/wechat-decrypt/decoded_voices/<chatroom>_<YYYYMMDD>_<HHMMSS>_<N>.wav
  时长: 10.0秒
```

文件名编码了 chatroom username + 日期时间 + local_id，方便后续解析。

### 4.3 转写：两条路径

**A. MCP 内置（首选）**

```
mcp__wechat__transcribe_voice chat_name="<群名>" local_id=<N>
```

工具内部跑 decode + whisper + 写缓存 `voice_transcriptions.json`。需要 MCP server 装了 `openai-whisper` 并重启过才能用。

**B. 脚本 fallback（兜底）**

```bash
# 先 decode 所有需要的 local_id，wav 自动落到 decoded_voices/
# 然后批量转写
python3 ${CLAUDE_SKILL_DIR}/scripts/transcribe_voices.py \
    --wav-dir ~/Projects/wechat-decrypt/decoded_voices/ \
    --filter "<chatroom_id>" \
    --out /tmp/voices_<日期>_<群名>.json
```

脚本依赖 `openai-whisper`（系统装过即可，不依赖 MCP server）。缓存写到 `${CLAUDE_SKILL_DIR}/voice_cache.json`，按 wav 文件 mtime + size 签名，重复运行零成本。

### 4.4 输出 JSON 结构

```json
{
  "11239": {
    "time": "2026-05-12 00:27:49",
    "duration_s": 10.0,
    "text": "那还是不一样的\n没置顶的群讨就会永远的忘记..."
  }
}
```

AI 在 Step 3 写故事时，把语音转写当成「这个人的真实发言」用，引用时在 quote 里加 `source: "voice"` 字段（见 story-schema.md）。

### 4.5 常见坑

- **繁体输出**：whisper 中文模型默认偏繁体，转写出「沒置頂」「尊渡」这种。AI 引用时按上下文转成简体并修订错字。
- **短语音被跳过**：`--min-duration 3` 过滤掉 < 3 秒的，避免「嗯」「啊」浪费 token。需要全转改成 `--min-duration 0`。
- **模型下载**：首次跑 whisper 会下载约 145MB 的 base 模型权重。第一次慢，之后秒出。
- **群里没语音**：直接跳过整个 Step 1.5，不影响主流程。

## 五、典型工作流

```bash
# 1. 拉聊天记录（AI 调 MCP，自己处理消息文本）
# mcp__wechat__get_chat_history chat_name="XX群" start_time="2026-05-11 00:00" ...

# 1.5. 检查语音（如有，按 § 四 流程解码 + 转写）
# mcp__wechat__get_voice_messages chat_name="XX群" limit=100

# 2. AI 分析消息（含语音转写），提炼时间线 + 高光人物 + SOP + 金句
#    输出 story.json，语音引用加 source: "voice" 字段

# 3. 查群成员 wxid（仅查 story 里出现的人）
python3 scripts/lookup_members.py \
    --group-name "XX群" \
    --names "示例联系人A,示例联系人C,..." \
    --out /tmp/members.json

# 4. 把 wxid 写入 story.json 里的 cast.wxid 和 highlights.wxid 字段

# 5. 主编排（自动跑头像导出 + HTML + PNG）
python3 scripts/make_daily.py --story /tmp/story.json
```

## 五、备用路径

如果 wechat-decrypt 的解密产物路径变了，可以用环境变量或参数指定：

```bash
python3 scripts/extract_avatars.py \
    --db /your/path/head_image.db \
    --names-map /tmp/members.json \
    --out /tmp/avatars.json
```

如果某些群友的头像没解密到，`extract_avatars.py` 会在 stderr 列出 `✗ <name> (<wxid>): 头像未找到`。这种情况会自动 fallback 到首字 placeholder，不会让脚本挂掉。
