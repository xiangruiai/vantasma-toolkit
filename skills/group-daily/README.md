# group-daily

> 把一个微信群一段时间的对话，做成杂志风的「故事化群报」HTML + PNG 长图。
> 不是会议纪要，是一篇短篇报道。

一个 Claude Code Skill，用 Spotify Wrapped / 网易云年报那种「故事化年报」的范式，给你的微信群每天/每周/每月做一份能截图发朋友圈的杂志风内容产品。

---

## ✦ 为什么做这个

市面上的「微信群智能纪要」工具有一个共同的问题：**信息保存了，但价值传不出去**。

把一群人聊了一天的内容压成一份 bullet-point 清单，技术上是「智能化」了，但读起来像会议纪要——没人想转发，也没人想保存。

故事化年报这种产品形态（Spotify Wrapped、网易云年报、Stripe Annual Letter）告诉我们另一条路：

> 数据是起点，故事是终点。<br>
> 可分享性是一切的前置条件。<br>
> 不同的用户群需要不同的格式。

这个 skill 是把这套思路套在「群日报」这个新场景上的一次实践。设计依据基于《群日报形态横纵分析报告》——做了 QFD 质量屋打分 + Spotify Wrapped / 网易云年报 / Stripe Letter / 飞书智能纪要 等横向对比。

跑出来的样子（部分截图）：

```
┌──────────────────────────────────────┐
│ 群日报                  Vol. 2026.05.11 │
│                                       │
│ 二十天，                              │
│ 从一条「1」                           │
│ 到 Claude 解密微信。                  │
│                                       │
│ 「这群早在 3 月 23 日就开了，第一条… │
│ ─────────────────────────────────────│
│                                       │
│  01    ── 09:20 ─────────────         │
│                                       │
│  提问者                               │
│                                       │
│  一个问题，                           │
│  点燃整个上午                         │
│                                       │
│  CAST · [示例联系人A头像]                  │
│                                       │
│  「示例联系人A抛了一个看似普通的问题……」  │
│                                       │
│  「整理知识库的员工，不一定愿意…」   │
│                              — 示例联系人B  │
│                                       │
│  PRODUCED · 万涂幻象开源 wiki + …    │
└──────────────────────────────────────┘
```

---

## ✦ 微信数据是怎么来的（重点）

这是这个项目最特别也最敏感的部分，单独写一节。

### 1. 数据在哪里

macOS 桌面版微信 4.x 把消息、联系人、群成员、头像、语音、图片这些数据全部存在本地，路径在：

```
~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/
├── <wxid>_<random>/                  # 当前登录用户
│   ├── msg/                          # 消息附件
│   ├── db_storage/
│   │   ├── message/message_N.db      # 聊天记录（SQLCipher 加密）
│   │   ├── contact/contact.db        # 联系人/群成员（SQLCipher 加密）
│   │   ├── head_image/head_image.db  # 头像（SQLCipher 加密）
│   │   └── ...
│   └── temp/head_image/              # 头像缓存（明文 jpg，但文件名是 hash）
└── all_users/
    └── head_imgs/                    # 全局头像（明文 jpg）
```

iOS / Android 不在范围内，本 skill 仅支持 macOS。

### 2. 为什么要"解密"

微信用 SQLCipher 给上面这些 db 文件加了密，直接拿 `sqlite3 contact.db` 会报 `file is not a database`。要正常读取，需要：

1. **拿到解密 key**：从运行中的微信进程内存里找到（每个登录用户的 key 不同）
2. **用 key 解密整库**：把加密的 db 解成普通的 SQLite db（落到一个新目录）
3. **读取解密后的库**：之后就是标准 SQL 操作

这一步社区有几个成熟方案：

| 方案 | 平台 | 状态 | 备注 |
|---|---|---|---|
| [PyWxDump](https://github.com/xaoyaoo/PyWxDump) | macOS / Windows | 开源 | 老牌方案，覆盖广 |
| [WeChatMsg / 留痕](https://github.com/LC044/WeChatMsg) | Windows 主 | 开源 | 桌面客户端 + 导出 |
| [wxhelper](https://github.com/ttttupup/wxhelper) | Windows | 开源 | DLL 注入路线 |
| [wechat-dump-rs](https://github.com/0xlane/wechat-dump-rs) | macOS / Windows | 开源 | Rust 重写版 |
| `wechat-decrypt`（本作者私有项目）| macOS | **未公开** | 集成了 `vchat` CLI + `mcp_server` |

本 skill 默认依赖最后一个（`wechat-decrypt`），因为开发它的作者就是 skill 的作者。**如果你没有这个项目，按下面"无 wechat-decrypt 怎么办"的指引走 PyWxDump 等替代方案，效果一致**。

### 3. 三条数据访问路径

skill 实际跑的时候，按以下优先级使用：

```
[A] vchat CLI (推荐)
       ↓ 失败/没装
[B] wechat MCP server
       ↓ 失败/没装
[C] 直接读 sqlite 解密产物
```

**A. `vchat` CLI（推荐路径，最稳）**

`vchat` 是 `wechat-decrypt` 项目里附带的命令行工具，封装了一站式微信本地数据访问能力。skill 主要用它的这几个命令：

```bash
vchat history "<群名>" -n 5000 --asc > log.txt   # 拉聊天记录
vchat voice-ls "<群名>"                           # 列语音
vchat voice-transcribe "<群名>" --local-id N      # 转写单条
vchat contacts "<显示名>"                         # 找单人 wxid
vchat avatar "<名/wxid>" -o <dir>                # 导出头像
vchat stats-overview / voice stats                # 数据洞察
```

优点：自带 venv 装好 `openai-whisper` + `silk-python`，零外部依赖；拉大量历史直接落盘不爆 token。

**B. `wechat` MCP server（兜底）**

如果运行机器配置了 wechat MCP server（Claude Code MCP 集成），skill 可以调用 MCP 工具替代 CLI：

```
mcp__wechat__get_chat_history
mcp__wechat__get_voice_messages
mcp__wechat__decode_voice
mcp__wechat__transcribe_voice
mcp__wechat__get_contacts
mcp__wechat__decode_image
```

这套 MCP 工具源自 `wechat-decrypt` 项目里的 `mcp_server.py`。开源后会公开仓库和注册方法。

**C. 直接读 sqlite（fallback 的 fallback）**

skill 自带的 `lookup_members.py` 和 `extract_avatars.py` 会直接读解密后的 `contact.db` 和 `head_image.db`。表结构见 `references/data-sources.md`。

只要你的解密产物路径符合下面这个结构（通过 `VCHAT_DATA_DIR` 环境变量指定根目录），脚本就能跑：

```
$VCHAT_DATA_DIR/
└── decrypted/
    ├── contact/contact.db
    └── head_image/head_image.db
```

如果你用 PyWxDump 之类的替代方案，把解密产物 link 到这个路径即可。

### 4. 无 wechat-decrypt 怎么办

如果你没有作者的 `wechat-decrypt` 项目（目前未公开），仍然可以让 skill 跑起来，按以下步骤：

```bash
# 1. 装一个开源解密工具（推荐 PyWxDump，覆盖 macOS）
git clone https://github.com/xaoyaoo/PyWxDump.git
cd PyWxDump && pip install -e .

# 2. 跑解密，拿到 contact.db / head_image.db
#    （具体命令看 PyWxDump 的 README）

# 3. 把解密产物放到 skill 期待的路径
mkdir -p ~/wechat-decrypted/decrypted/{contact,head_image}
cp <PyWxDump 输出>/contact.db ~/wechat-decrypted/decrypted/contact/
cp <PyWxDump 输出>/head_image.db ~/wechat-decrypted/decrypted/head_image/

# 4. 告诉 skill 这个路径
export VCHAT_DATA_DIR=~/wechat-decrypted
```

此时 `lookup_members.py` 和 `extract_avatars.py` 能跑；`vchat history` 和 `vchat voice-transcribe` 不可用，但 skill 会自动降级到 MCP 兜底路径（前提是你装了 wechat MCP server）。

### 5. 隐私承诺

- 这个 skill **不上传任何数据到任何服务器**，所有处理都在本地
- skill 仓库本身**不包含**任何聊天记录、头像、群名、个人信息
- 作者自己用过的 styles / story.json 历史档案存在 Vault 里，**不在 skill 仓库**，不会随 git push 出去
- whisper 语音转写也是**本地模型**（base 模型约 145MB，首次自动下载到 `~/.cache/whisper/`）
- 用作者私有的 `vchat` CLI 时，所有命令都是只读访问本地 sqlite

把这个 skill 分享 / 开源给别人时，对方下载到的是工作流脚本和模板，**接触不到分享者的任何微信数据**。每个用户跑起来读的是自己机器上的微信。

### 6. 合规提示

- 这个 skill 只读取**当前登录用户自己**的微信本地数据
- 不要用它读取不属于你的微信账号的数据
- 商业用途请评估当地隐私法规

---

## ✦ 安装

### 1. 装 skill

```bash
git clone https://github.com/<owner>/group-daily.git ~/.claude/skills/group-daily
# 或下载 release tarball 解压到 ~/.claude/skills/group-daily/
```

### 2. 一键装依赖 + 自检

```bash
bash ~/.claude/skills/group-daily/install.sh
```

脚本会：

- 装 Python 依赖（Pillow、openai-whisper、silk-python）
- 跑 6 项环境自检（macOS、Python 包、vchat、wechat-decrypt 路径、Chrome、环境变量）
- 给每个缺失项打印修复建议

### 3. 配环境变量（可选）

```bash
# 群日报数据根目录（styles + story.json 归档存放处）
# 默认: ~/Documents/GroupDaily
export GROUP_DAILY_VAULT=~/Documents/GroupDaily

# wechat-decrypt（或其他解密工具）的根目录
# 默认: ~/Projects/wechat-decrypt
export VCHAT_DATA_DIR=~/Projects/wechat-decrypt
```

写到 `~/.zshrc` 或 `~/.bash_profile` 持久化。

---

## ✦ 使用

在 Claude Code 里说：

> 给「XX 群」做个群日报

或：

> XX 群今天聊了什么，做个日报

skill 自动触发，按 8 步流程跑：

| Step | 干什么 |
|---|---|
| 1 | 拉聊天记录（`vchat history -n N --asc` 落盘，或 MCP 兜底） |
| 1.5 | 检查语音 + 批量转写（如有） |
| 2 | 基础统计（消息数、发言人、字数） |
| 2.5 | 加载群风格指纹（已沉淀过的群） |
| 3 | 阅读消息提炼故事（6-8 段时间故事线 + 高光人物 + SOP + Q&A） |
| 4 | 查群成员 wxid |
| 5 | 写 story.json |
| 6 | 跑 make_daily.py 生成 HTML + PNG 长图 |
| 7.5 | 更新群风格指纹 |
| 8 | 归档 story.json 到 `$GROUP_DAILY_VAULT/<日期>_<群名>.json` |

输出在 `~/Desktop/`，自动打开 HTML 和 PNG。

---

## ✦ 设计哲学

详见 `references/design-principles.md`：

1. **时间故事线是骨架**（QFD 矩阵打分 200，所有特征里最高）
2. **砍掉冗余**：24h 曲线 / 话题分布 / TOP N 排行 / 全员标签册 / Dashboard 都是反模式
3. **杂志风去 AI 化**：衬线字体 + 米黄底 + 朱砂红 + 大编号 + 留白
4. **干货默认 details open**：保证 PNG 截图能看到完整内容
5. **只沉淀群文化，不沉淀人物档案**：群文化稳定（黑话/调性），人物动态（每次临时分析）

---

## ✦ 目录结构

```
group-daily/
├── README.md                     ← 本文件
├── LICENSE                       ← MIT
├── SKILL.md                      ← Claude Code skill 主入口（8 步工作流）
├── install.sh                    ← 一键装依赖 + 自检
├── .gitignore
├── scripts/
│   ├── check_env.py             ← 环境自检（6 项）
│   ├── lookup_members.py        ← 查群成员 wxid 映射
│   ├── extract_avatars.py       ← 导出头像为 base64
│   ├── transcribe_voices.py     ← 批量转写语音（系统 whisper CLI 兜底）
│   ├── render_html.py           ← 渲染杂志风 HTML
│   ├── html_to_png.py           ← HTML → PNG 长图（Chrome headless + Pillow 裁底）
│   ├── make_daily.py            ← 主编排
│   └── context_helper.py        ← 群风格指纹目录助手
├── references/
│   ├── design-principles.md     ← QFD 设计准则
│   ├── writing-style.md         ← 故事化写作风格
│   ├── story-schema.md          ← story.json 字段定义
│   ├── data-sources.md          ← 微信数据源说明
│   ├── group-style.md           ← 群风格指纹结构
│   └── vchat-cli.md            ← vchat CLI 速查
└── assets/
    └── template.html            ← 杂志风 HTML 模板
```

---

## ✦ 路线图

- [x] v1：发言量/时段 dashboard 版（已弃，「太 AI 味」）
- [x] v2：杂志风时间故事线 + 真实头像
- [x] v2.1：语音消息接入
- [x] v2.2：CLI 优先，MCP 兜底
- [x] v2.3：路径环境变量化，可分享版
- [ ] v3：模板可换肤（杂志风之外的极简风/科技风）
- [ ] v3：跨群「群史专辑」一键生成
- [ ] v3：群风格指纹的演化追踪（每次更新生成 diff）
- [ ] 等待 `wechat-decrypt` 开源后补充安装指引

---

## ✦ 致谢

- 设计方法论：赤尾洋二 1972 年提出的 QFD（质量屋）
- 写作风格参考：Spotify Wrapped、网易云年度报告、Stripe Annual Letter、Stratechery（Ben Thompson）
- 字体回退链：macOS 自带的 Songti SC / STSong（无网络也能显示衬线效果）
- 语音转写：OpenAI Whisper（base 模型）
- SILK 解码：[silk-python](https://github.com/CarlGao4/silk-python)
- 启发：横纵分析法（融合 Saussure 历时-共时 + 社会科学 longitudinal-cross-sectional + 商学院案例研究）

---

## ✦ License

MIT。见 `LICENSE`。

---

## ✦ FAQ

**Q：为什么不支持 Windows / Linux？**
A：微信桌面数据库的路径、解密 key 提取方式、whisper / silk-python 在不同平台的安装方式都不一样。当前作者只用 macOS，没有跨平台测试条件。欢迎 PR。

**Q：能不能给企业微信 / 钉钉 / 飞书做？**
A：飞书有官方 OpenAPI，技术上可行但风格完全不同。本项目专注微信群这种「非结构化口语对话」场景。

**Q：转写出来的语音是繁体？**
A：whisper 中文模型默认偏繁体输出。skill 的 writing-style 里写了：AI 引用语音转写时按上下文转简体并修订错字。

**Q：群里太多，怎么知道哪个值得做日报？**
A：跑 `vchat stats-top-groups -n 20` 看最活跃的群。也可以跑 `vchat voice-stats` 看哪些群语音密度高。

**Q：能不能不在 Claude Code 里跑，用脚本一次性出图？**
A：当前的「故事提炼」环节强依赖 LLM 来读消息、写叙事。如果想完全脚本化，可以接 Claude API 或本地 LLM，但需要改 make_daily.py 增加 LLM 调用。这是 v4 的方向。
