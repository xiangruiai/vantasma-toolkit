# group-activity-base

> 把一个微信群从建群到现在的完整历史，变成一个飞书多维表格：
> 谁活跃、谁潜水、谁什么时候进的群、谁被清退了、每天聊了多少 —— 外加一个仪表盘。

一个 Claude Code Skill。对着 AI 说一句“做 XX 群的活跃度表”，几分钟后得到：

```
XX群 · 群活跃度分析（飞书多维表格）
├── 成员活跃度          完整历史名册：每人发言数/活跃天数/进群时间/移出时间/活跃标签
│   └── 潜水名单视图     一眼看到谁从来没说过话
├── 发言记录汇总         全量消息明细（文本全文，按时间排序，可筛类型）
├── 每日消息趋势         按天消息数
└── 群活跃度仪表盘       9 个组件：4 指标卡 + 标签饼图 + 趋势线 + 词云 + 排行榜
```

## ✦ 它能回答什么问题

- 几百人的大群，**谁是那批从没说过话的**？（潜水名单视图直接给答案）
- 每个人**什么时候进的群**？谁邀请的、还是扫码进的？
- 上次批量清退是什么时候、**清了哪些人**？（移出时间列直接筛）
- 群的热度**在涨还是在凉**？（每日趋势 + 近 7 天活跃分布）
- 完整历史名册：**进过这个群的所有人**，包括进来没说一句话就走了的"隐形成员"

## ✦ 数据是怎么来的（重点，涉及隐私必读）

**所有数据都来自你自己电脑上、你自己微信账号的本地缓存。** 不碰服务器，不需要网络抓取，不涉及任何第三方数据服务。

- 聊天记录、群成员、系统消息（入群/移出通知）来自 macOS 微信 4.x 的本地 SQLCipher 数据库，由本仓库的 [`cli/vchat`](../../../cli/vchat/) 解密和查询
- 消息正文是 zstd 压缩的，脚本直接读解密库的原始字节解压（vchat 导出的 JSON 里压缩内容会被编码损坏，这是实测出来的坑）
- 分析结果写到**你自己的飞书租户**里的多维表格，通过官方 `lark-cli` 的 OpenAPI

**隐私边界（实测验证过的）**：
- 微信号（alias）只有你的好友才拿得到，非好友群成员微信服务端根本不下发 —— 这个 skill 不收集也收集不到
- 没发过言就退群的人，wxid 只能靠昵称反查你本地联系人缓存，**唯一命中才回填，重名不猜**
- 你自己的显示名通过环境变量 `GAB_SELF_NAME` 配置，不写死在任何文件里

**使用红线**：只分析你自己所在的群、数据只进你自己的飞书。把别人的群聊数据做成表格分发给无关人员，是对群友隐私的侵犯，也可能违反《个人信息保护法》。分享表格前把 wxid 列隐藏掉是基本礼貌。

## ✦ 安装

### 让 Agent 自动安装（推荐）

把这句话贴给你的 AI Agent（Claude Code / Cursor / aider 都行）：

> **帮我安装 https://github.com/xiangruiai/vantasma-toolkit 里的 group-activity-base skill（路径 skills/飞书办公/group-activity-base）。按它的 README：clone 仓库 → 跑该目录的 install.sh（缺 vchat 就用仓库 cli/vchat/install.sh 装，缺 lark-cli 就 npm i -g @larksuite/cli，每一步先问我同意）→ 确认微信是 4.x 版本 → 把 skill 目录拷到 ~/.claude/skills/ → 提醒我设置 GAB_SELF_NAME 环境变量和完成 lark-cli auth 授权。**

Agent 会自动跑完。需要你介入的只有：同意安装、一次 sudo 密码（vchat 解密）、lark-cli 的 OAuth 授权、还有告诉它你的显示名。

### 手动安装

三个依赖，缺一不可：

### 0. 先确认微信版本（重要）

vchat 依赖微信 macOS 客户端的本地数据库结构，**只支持微信 4.x**（实测 4.0 ~ 4.1.7）；3.x 及更早版本数据库结构完全不同，不适用。查看版本：

```bash
defaults read /Applications/WeChat.app/Contents/Info.plist CFBundleShortVersionString
```

微信升级后如果读不到新消息，重跑 `sudo vchat setup` 重新解密。详见 [`cli/vchat/README.md`](../../../cli/vchat/README.md) 的“微信版本兼容性”。

### 1. vchat（微信本地数据 CLI，本仓库自带）

```bash
cd cli/vchat && ./install.sh
# 跑通自检：
vchat ls        # 能列出最近会话就 OK
```

首次使用需要解密微信本地库，详细步骤（包括 SQLCipher key 提取原理、安全注意）见 [`cli/vchat/README.md`](../../../cli/vchat/README.md)。仅支持 macOS + 微信 4.x。

### 2. lark-cli（飞书官方 CLI）

```bash
npm i -g @larksuite/cli
lark-cli auth        # 按提示完成 OAuth 授权（需要一个飞书自建应用，见官方文档）
lark-cli doctor      # 自检：配置、认证、连通性
```

需要的权限 scope：多维表格读写（bitable）、云文档。授权走你自己的飞书账号，表格建在你自己的空间里。

### 3. Python 依赖 + 环境变量

```bash
pip3 install zstandard
export GAB_SELF_NAME="你的名字"   # 写进 ~/.zshrc 持久化
```

> 💡 **懒人路线**：直接跑本目录的 `./install.sh`，它会逐项检查依赖，缺什么会询问你是否自动安装（回车确认才装，不会擅自动手）。或者把这个 README 丢给 Claude Code，让 AI 征得你同意后代装。

### 4. 安装 Skill

把 `group-activity-base/` 目录整个拷到 Claude Code 的 skills 目录：

```bash
cp -r group-activity-base ~/.claude/skills/
```

重启 Claude Code，说“做 XX 群的活跃度表”即可触发。

## ✦ 用法

| 你说 | 它做 |
|---|---|
| “做 XX 群的活跃度表” | 从零建 Base：三张表 + 潜水视图 + 9 组件仪表盘，全量数据导入并自检 |
| “更新 XX 群的活跃度表” | 水位式增量：只追加上次之后的新消息，成员表只动有变化的行，旧数据一条不碰 |
| “XX 群谁没发言” | 直接读潜水名单视图给你答案 |

活跃标签阈值：核心活跃 ≥100 条 / 高活跃 ≥30 / 中活跃 ≥10 / 低活跃 ≥3 / 仅冒泡 1-2 / 潜水 0。想改就改 `scripts/extract_group_activity.py` 里的 `label_of`。

## ✦ 能力边界（诚实版）

| 能做到 | 做不到 |
|---|---|
| 完整历史名册（含零发言就退群的隐形成员） | 自行退群的时间（微信不发系统消息，只能推断存在过） |
| 精确到秒的进群时间（邀请/扫码/初始名单三来源） | 改过名又匹配不上的人的精确进群时间（有兜底近似） |
| 被清退的移出时间 | 非好友的微信号（微信隐私设计，服务端不下发） |
| 文本/引用回复全文 | 图片、语音内容（只有类型标签） |

## ✦ 已知坑（都帮你踩过了）

见 [references/base-schema.md](references/base-schema.md) 的“lark-cli 实战坑点”：13 条，包括 @file 只认相对路径、批次文件必须 3 位编号否则导入顺序乱掉、batch-update 对假 record_id 也返回成功、调用不存在的子命令静默失败等。每一条都是真实翻车记录。

## ✦ 免责声明

本 skill 仅供个人学习与研究。只在你自己拥有合法访问权的数据上使用；分析结果涉及群友个人信息，分发前请脱敏；一切使用后果由使用者自行承担。详见仓库根目录 README 的完整免责声明。

## License

MIT
