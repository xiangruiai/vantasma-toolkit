# vantasma-toolkit

> 万涂幻象出品的个人工具合集 · **仅供个人学习与研究用途**
>
> 含 1 个 CLI（vchat）+ 5 个 Claude Code Skills。

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
└── skills/
    ├── didi-ride-skill/             飞书叫滴滴
    ├── feishu-bitable-skill/        飞书多维表格搭建
    ├── feishu-bitable-system-prompt/ 飞书多维表格 AI 系统提示词设计
    ├── feishu-proposal/             飞书客户方案自动生成
    └── mp-data/                     公众号数据抓取
```

---

## 1. cli/vchat — 微信本地数据 CLI

63 个子命令，覆盖微信本地数据的查询、解密、导出场景。

### 让 Agent 自动安装（推荐）

把下面这句话贴给你的 AI Agent（Claude Code / Cursor / aider 都行）：

> **「帮我安装 https://github.com/Larkin0302/vantasma-toolkit 里的 vchat CLI（路径 cli/vchat）。按它 README 的步骤跑：clone → bash install.sh → 装 cryptography + zstandard → sudo vchat setup。完成后跑 vchat doctor 确认本地 db 全部解密。」**

Agent 会自动跑完，需要你介入的只有：
- 一次 `gh auth login`（如果没登 GitHub）
- 一次 sudo 密码输入
- 微信桌面版保持开着 + 登录状态

### 手动安装

```bash
git clone git@github.com:Larkin0302/vantasma-toolkit.git
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

## 2. skills/ — 5 个 Claude Code Skills

| Skill | 用途 | 详情 |
|---|---|---|
| `feishu-proposal` | 飞书会议纪要 → 客户方案文档 | [README](skills/feishu-proposal/README.md) |
| `feishu-bitable-skill` | 飞书多维表格搭建（OpenClaw） | [README](skills/feishu-bitable-skill/README.md) |
| `feishu-bitable-system-prompt` | 飞书多维表格 AI 提示词设计 | [README](skills/feishu-bitable-system-prompt/README.md) |
| `didi-ride-skill` | 飞书里一句话叫滴滴（OpenClaw） | [README](skills/didi-ride-skill/README.md) |
| `mp-data` | 公众号全量文章数据抓取 + 可视化 | [README](skills/mp-data/README.md) |

### 安装 Claude Code Skill

```bash
# 把某个 skill 复制到 Claude Code 的 skills 目录
cp -r skills/feishu-proposal ~/.claude/skills/
# 然后重启 Claude Code，跟它说话即可触发
```

---

## 关于万涂幻象

**万涂幻象** · 李祥瑞主理的社区，深耕飞书多维表格 + AI 落地。

公众号：**万涂幻象**  ·  开源知识库：[vantasma.feishu.cn/wiki/space/7574356946532925441](https://vantasma.feishu.cn/wiki/space/7574356946532925441)

---

## License

[MIT](LICENSE) + 个人学习用途附加条款。

Copyright © 2026 Larkin0302 (李祥瑞 / 万涂幻象)
