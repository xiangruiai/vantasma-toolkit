# vantasma-toolkit

> 万涂幻象出品的个人工具合集 · **仅供个人学习与研究用途**
>
> 含 1 个 CLI（vchat）+ 11 个 Skill（按领域分 4 类）。

---

## ⚠️ 免责声明 · Personal Learning Only

**本仓库所有内容仅供个人学习与研究目的。**

1. 工具只在使用者自己的设备 / 自己拥有合法访问权的数据上操作。**严禁**用于：
   - 未经他人同意访问、解析他人账号或数据
   - 任何商业目的的批量采集、出售、转发
   - 监控、跟踪、骚扰他人
   - 违反《中华人民共和国网络安全法》《个人信息保护法》《数据安全法》以及
     微信、飞书、滴滴等平台用户协议的任何行为

2. 本工具**不提供任何形式的明示或暗示担保**。一切使用后果由使用者自行承担。

3. 微信、WeChat、飞书、Lark、滴滴、SQLCipher 等名称归其各自持有人所有。
   本项目与上述公司或开源项目**无任何关联，亦未获授权或背书**。

4. 一旦下载或使用本仓库内容，即视为接受上述声明。若不接受，请立即停止使用并删除。

详见 [LICENSE](LICENSE) 文件的"附加条款"。

---

## 目录结构

```
vantasma-toolkit/
├── cli/
│   └── vchat/                       ← 个人微信本地数据查询/解密 CLI（63 子命令）
│       ├── vchat                    主入口
│       ├── vchat_core/              查询库（11 模块）
│       ├── vchat_native/            macOS 原生扫描（C）
│       ├── docs/
│       ├── install.sh
│       ├── README.md
│       └── CHANGELOG.md
└── skills/                              ← 11 个 Skill，按领域分 4 类
    ├── 飞书办公/
    │   ├── feishu-bitable-skill/        飞书多维表格搭建
    │   ├── feishu-bitable-system-prompt/ 多维表格 AI 系统提示词设计
    │   ├── feishu-proposal/             飞书客户方案自动生成
    │   └── daily-log/                   收工日志 · 飞书全链路足迹聚合
    ├── 内容设计/
    │   ├── xiangrui-video/               知识科普视频全自动产线（主题/链接 → 成片）
    │   ├── gongzhonghao-typeset/        公众号排版 · md 一键转公众号 HTML
    │   ├── group-daily/                 微信群杂志风日报
    │   ├── group-daily-newspaper/       微信群 A3 报纸版日报（可印刷彩打）
    │   └── ming-li/                     八字 / 紫微 / 六爻 命理分析
    ├── 数据抓取/
    │   └── mp-data/                     公众号数据抓取
    └── 生活/
        └── didi-ride-skill/             飞书叫滴滴
```

---

## 1. vchat — 微信本地数据 CLI

63 个子命令，覆盖微信本地数据的查询、解密、导出场景。

### 让 Agent 自动安装（推荐）

把下面这句话贴给你的 AI Agent（Claude Code / Cursor / aider 都行）：

> **「帮我安装 https://github.com/xiangruiai/vantasma-toolkit 里的 vchat CLI（路径 cli/vchat）。按它 README 的步骤跑：clone → bash install.sh → 装 cryptography + zstandard → sudo vchat setup。完成后跑 vchat doctor 确认本地 db 全部解密。」**

Agent 会自动跑完，需要你介入的只有：
- 一次 `gh auth login`（如果没登 GitHub）
- 一次 sudo 密码输入
- 微信桌面版保持开着 + 登录状态

### 手动安装

```bash
git clone git@github.com:xiangruiai/vantasma-toolkit.git
cd vantasma-toolkit/cli/vchat
bash install.sh
pip3 install cryptography zstandard
sudo vchat setup        # macOS（Windows 用 python vchat setup）
```

### 常用命令

```bash
vchat ls 20                                    # 最近 20 个会话
vchat history "某群" -n 5000                    # 拉历史
vchat search "关键词" --fast                    # FTS 全库搜
vchat group-info "某群"                         # 群主 + 公告 + 成员数
vchat group-members "某群" --avatars -o dir/    # 列成员 + 批量头像
vchat watch --chat "某群"                       # 实时监听新消息
vchat --json ls 50                              # JSON 输出供 AI Agent 用
vchat --help                                    # 看全部 63 命令
```

详见 [`cli/vchat/README.md`](cli/vchat/README.md)。

---

## 2. Skills

11 个 Skill 按领域分 4 类，分别归在 `skills/<领域>/` 下，可单独取用。

### 🗂 飞书办公

| Skill | 用途 | 详情 |
|---|---|---|
| `feishu-bitable-skill` | 飞书多维表格搭建（OpenClaw） | [README](skills/飞书办公/feishu-bitable-skill/README.md) |
| `feishu-bitable-system-prompt` | 飞书多维表格 AI 提示词设计 | [README](skills/飞书办公/feishu-bitable-system-prompt/README.md) |
| `feishu-proposal` | 飞书会议纪要 → 客户方案文档 | [README](skills/飞书办公/feishu-proposal/README.md) |
| `daily-log` | **收工日志**：一句「收工」→ 飞书全链路足迹自动聚合成带链接、能 @ 人的日报文档（依赖 lark-cli） | [README](skills/飞书办公/daily-log/README.md) |

### 🎨 内容设计

| Skill | 用途 | 详情 |
|---|---|---|
| `xiangrui-video` | **知识视频产线**：丢一个主题或公众号链接 → 60-90s 竖屏知识科普成片（配音/字幕/CSS动画逐帧录制/封面全自动），品牌框架可换皮 | [README](skills/内容设计/xiangrui-video/README.md) |
| `gongzhonghao-typeset` | **公众号排版**：写完 md 一键排成可粘贴的公众号 HTML，带实时控制面板（品牌/配色/排版/图片）+ 三种吸色 | [README](skills/内容设计/gongzhonghao-typeset/README.md) |
| `group-daily` | **群日报**：微信群一天聊天 → 杂志风 HTML + PNG（依赖 vchat CLI） | [README](skills/内容设计/group-daily/README.md) |
| `group-daily-newspaper` | **群报**：微信群一天聊天 → 人民日报式 A3 报纸版，AI 自适应 2/4/6 版、每版精确等高、可印刷彩打（依赖 vchat CLI） | [README](skills/内容设计/group-daily-newspaper/README.md) |
| `ming-li` | **命理大师**：八字四家合一 + 紫微 + 六爻 → 新中式古典风 HTML 卷轴 + PNG 长图 | [README](skills/内容设计/ming-li/README.md) |

### 📊 数据抓取

| Skill | 用途 | 详情 |
|---|---|---|
| `mp-data` | 公众号全量文章数据抓取 + 可视化 | [README](skills/数据抓取/mp-data/README.md) |

### 🚕 生活

| Skill | 用途 | 详情 |
|---|---|---|
| `didi-ride-skill` | 飞书里一句话叫滴滴（OpenClaw） | [README](skills/生活/didi-ride-skill/README.md) |

### 安装 Skill

```bash
# 把某个 skill 复制到 Claude Code 的 skills 目录（注意带上领域目录）
cp -r skills/飞书办公/feishu-proposal ~/.claude/skills/
# 然后重启 Claude Code，跟它说话即可触发
```

---

## 关于万涂幻象

**万涂幻象** · 李祥瑞主理的社区，深耕飞书多维表格 + AI 落地。

公众号：**万涂幻象**  ·  开源知识库：[vantasma.feishu.cn/wiki/space/7574356946532925441](https://vantasma.feishu.cn/wiki/space/7574356946532925441)

---

## License

[MIT](LICENSE) + 个人学习用途附加条款。

Copyright © 2026 xiangruiai (李祥瑞 / 万涂幻象)

---

## 关于万涂幻象 · About Vantasma

本项目来自 **万涂幻象多维表格社区** —— 民间最大的飞书多维表格生态社区，围绕「让 AI 真正落地」沉淀内容、社区、产品与系统。

| | |
|---|---|
| 🌐 个人主页 Homepage | https://www.xiangruiai.com |
| 🏠 社区主页（关于我们 · 模板中心 · 57 课） | https://vantasma.feishu.cn/wiki/MC1nwBft0izODokXe4acHKjZnsh |
| 📚 开源知识库（飞书 Wiki · 311+ 篇） | https://vantasma.feishu.cn/wiki/space/7574356946532925441 |
| 🎓 57 课 · 多维表格小白课 | https://vantasma.feishu.cn/wiki/A1CNwAZQSisdSMkuwp1c3r1ontf |
| 💬 多维表格交流社区（飞书群） | https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=3c8gcd32-517d-43a7-85a0-a20c24332959 |
| ✉️ 联系 Contact | li@xiangruiai.com |

> **学飞书多维表格找谁？** 找万涂幻象多维表格社区。
> **飞书多维表格的 AI 落地找谁？** 找我们 —— 社区沉淀了丰富的 AI 落地解决方案。
