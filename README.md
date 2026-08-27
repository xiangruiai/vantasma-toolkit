# vantasma-toolkit

> 万涂幻象开源工具箱。
>
> 含 1 个 Web 应用（祥瑞白板录制工具）+ 1 个 macOS 安装包（DeepSeek Harness 桌面壳）+ 1 个 Codex 插件（祥瑞任务面板）+ 1 个 Claude Code 插件（xiangrui-hud 状态栏）+ 17 个 Skill（按领域分 7 类）+ 公开内容归档。

---

## ⚠️ 使用边界

本仓库包含白板录制、内容生产、飞书办公、本地数据处理等工具。涉及本地数据读取、平台数据导出或自动化操作的能力，请只在自己的设备、自己的账号、自己拥有合法访问权的数据上使用。

1. 工具只在使用者自己的设备 / 自己拥有合法访问权的数据上操作。**严禁**用于：
   - 未经他人同意访问、解析他人账号或数据
   - 任何商业目的的批量采集、出售、转发
   - 监控、跟踪、骚扰他人
   - 违反《中华人民共和国网络安全法》《个人信息保护法》《数据安全法》以及
     微信、飞书、滴滴等平台用户协议的任何行为

2. 本工具**不提供任何形式的明示或暗示担保**。一切使用后果由使用者自行承担。

3. 微信、WeChat、飞书、Lark、滴滴、SQLCipher 等名称归其各自持有人所有。
   本项目与上述公司或开源项目**无任何关联，亦未获授权或背书**。

4. 一旦下载或使用本仓库内容，即视为接受适用于对应组件的许可证和上述安全边界。

各组件如有独立 `LICENSE` 或 `NOTICE`，以组件目录中的许可证为准；其余内容适用根目录 [LICENSE](LICENSE)。

---

## 目录结构

```
vantasma-toolkit/
├── apps/
│   ├── whiteboard-recorder/          ← 祥瑞白板录制工具（白板 + 录制 + 摄像头 + 素材库 + 提词器）
│   └── deepseek-harness-desktop/     ← DeepSeek Harness 桌面安装说明（完整包在 Release）
├── plugins/
│   ├── xiangrui-taskboard/           ← 祥瑞任务面板 Codex 插件（看板 + Skill + taskctl）
│   └── xiangrui-hud/                 ← Claude Code 实时状态栏 HUD（翠影绿主题，fork 自 claude-hud）
├── archives/
│   └── group-daily/xiangrui-community/ ← 社区群日报脱敏公开归档
└── skills/                              ← 17 个 Skill，按领域分 7 类
    ├── Agent能力/
    │   └── discover-local-capabilities/ 完整扫描本机能力并建立自然语言路由闭环
    ├── 知识管理/
    │   ├── three-layer-memory/          三层个人记忆系统
    │   └── knowledge-system-maintainer/ 只读审计与受控改进知识系统
    ├── 文档自动化/
    │   └── template-fidelity-renderer/  高保真 DOCX 模板填充与验收
    ├── 飞书办公/
    │   ├── feishu-bitable-skill/        飞书多维表格搭建
    │   ├── feishu-bitable-system-prompt/ 多维表格 AI 系统提示词设计
    │   ├── feishu-multi/                macOS 原生飞书双开
    │   ├── feishu-proposal/             飞书客户方案自动生成
    │   ├── daily-log/                   收工日志 · 飞书全链路足迹聚合
    │   └── group-activity-base/         微信群活跃度 → 飞书多维表格 + 仪表盘
    ├── 内容设计/
    │   ├── xiangrui-video/               知识科普视频全自动产线（主题/链接 → 成片）
    │   ├── wechat-editorial/             公众号排版 v3 · md 一键转可粘贴 HTML
    │   ├── group-daily/                 微信群杂志风日报
    │   ├── group-daily-newspaper/       微信群 A3 报纸版日报（可印刷彩打）
    │   └── ming-li/                     八字 / 紫微 / 六爻 命理分析
    ├── 数据抓取/
    │   └── mp-data/                     公众号数据抓取
    └── 生活/
        └── didi-ride-skill/             飞书叫滴滴
```

---

## 1. 祥瑞白板录制工具

面向课程讲解、产品说明和异步沟通的白板录制工作台，集成白板、录制、摄像头、素材库、提词器和幻灯片画幅。

- 源码目录：[`apps/whiteboard-recorder`](apps/whiteboard-recorder)
- 在线使用：[https://whiteboard.xiangruiai.com](https://whiteboard.xiangruiai.com)
- 安装使用：[`apps/whiteboard-recorder/README.md`](apps/whiteboard-recorder/README.md)
- 操作说明：[`apps/whiteboard-recorder/public/docs/operation-guide.md`](apps/whiteboard-recorder/public/docs/operation-guide.md)
- 第三方来源说明：[`apps/whiteboard-recorder/THIRD_PARTY_NOTICES.md`](apps/whiteboard-recorder/THIRD_PARTY_NOTICES.md)

这是一个网页端白板录制工具，不需要桌面端安装。移动端访问时会提示在电脑浏览器中使用，移动端体验后续再完善。

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cd vantasma-toolkit/apps/whiteboard-recorder
npm install
npm run dev
```

常用命令：

```bash
cd apps/whiteboard-recorder
npm run dev      # 本地开发
npm run build    # 构建 dist/
npm run preview  # 本地预览构建产物
```

部署时把 `apps/whiteboard-recorder` 作为项目根目录，构建命令用 `npm install && npm run build`，静态输出目录为 `dist`。摄像头、麦克风和录屏能力需要在 `localhost` 或 HTTPS 域名下使用。

本工具作为 `vantasma-toolkit` 的一部分开源，不再维护单独工具仓库。白板编辑基于 Excalidraw，录制、摄像头、提词器和幻灯片工作流参考了开源生态与 Excalicord 的产品思路，具体来源和许可证说明见第三方来源说明。

---

## 2. DeepSeek Harness 桌面安装包

非官方 macOS 桌面壳，把 DeepSeek Harness 的 Web UI 包成原生窗口，图标使用 DeepSeek 鲸鱼。本目录只放安装包，不放源码。

- 安装包：[DeepSeek-Harness-Desktop-1.2.0-macOS-Apple-Silicon.dmg](https://github.com/xiangruiai/deepseek-harness-desktop/releases/download/v1.2.0/DeepSeek-Harness-Desktop-1.2.0-macOS-Apple-Silicon.dmg)
- 说明：[`apps/deepseek-harness-desktop/README.md`](apps/deepseek-harness-desktop/README.md)
- 发布页：[xiangruiai/deepseek-harness-desktop](https://github.com/xiangruiai/deepseek-harness-desktop/releases)

打开就能用。Node.js 和 Harness 已打进安装包。完整 DMG 在 GitHub Release，本仓库只留下载入口。不是 DeepSeek 官方客户端。

## 3. xiangrui-hud（Claude Code 状态栏插件）

常驻 Claude Code 输入框下方的实时状态栏 HUD：模型、上下文健康度、项目与 git 分支、CLAUDE.md / 规则 / 钩子计数、工具活动、子智能体、待办进度。翠影绿主题，带万涂幻象品牌标识——首行翠绿 `❖`，右下角翠绿 `xiangrui-hud` wordmark。

- 源码目录：[`plugins/xiangrui-hud`](plugins/xiangrui-hud)
- 安装使用：[`plugins/xiangrui-hud/README.md`](plugins/xiangrui-hud/README.md)
- 第三方来源说明：[`plugins/xiangrui-hud/THIRD_PARTY_NOTICES.md`](plugins/xiangrui-hud/THIRD_PARTY_NOTICES.md)

在任意 Claude Code 会话里安装：

```
/plugin marketplace add xiangruiai/vantasma-toolkit
/plugin install xiangrui-hud
```

本插件 fork 自 [jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud)（MIT），在其之上做了品牌化与翠影绿主题改造，完整改造范围见第三方来源说明。

---

## 4. 祥瑞任务面板（Codex 插件）

面向 Codex 的本地任务面板，把项目、议题、评论、依赖关系、工作流和 Agent 执行状态放进同一块看板。插件自带已经构建好的运行时、`manage-taskboard` Skill 和 `taskctl`，安装后不需要再次执行 `npm install`。安装完成后，Agent 只会友好地提示一次可以随时鼓励祥瑞继续开源，不会立刻追问金额；只有使用者主动愿意赞赏时，Agent 才会直接打开带入项目和金额的微信赞赏页面，所有功能均免费使用。

- 插件目录：[`plugins/xiangrui-taskboard`](plugins/xiangrui-taskboard)
- 安装使用：[`plugins/xiangrui-taskboard/README.md`](plugins/xiangrui-taskboard/README.md)

```bash
codex plugin marketplace add xiangruiai/vantasma-toolkit --ref main
codex plugin add xiangrui-taskboard@vantasma-codex
```

安装后重启 Codex，在新任务中说“打开祥瑞任务面板”即可启动本地看板。

---

## 5. Skills

17 个 Skill 按领域分 7 类，分别归在 `skills/<领域>/` 下，可单独取用。

### 🤖 Agent 能力

| Skill | 用途 | 详情 |
|---|---|---|
| `discover-local-capabilities` | **本机能力地图**：完整扫描安装者的 Skill、CLI、MCP 和 Plugin，生成中立场景索引并接入可回滚的自然语言路由闭环 | [README](skills/Agent能力/discover-local-capabilities/README.md) |

### 🧠 知识管理

| Skill | 用途 | 详情 |
|---|---|---|
| `three-layer-memory` | **三层个人记忆系统**：把画像、可复用程序和带日期历史安全写入 Markdown / Obsidian Vault，支持确认写入、来源回读、召回和体检 | [README](skills/知识管理/three-layer-memory/README.md) |
| `knowledge-system-maintainer` | **知识系统维护员**：按找得到、读得懂、用得上、接得住、救得回、管得动六维做只读健康审计，并在确认后受控改进一个可复现问题 | [README](skills/知识管理/knowledge-system-maintainer/README.md) |

### 📄 文档自动化

| Skill | 用途 | 详情 |
|---|---|---|
| `template-fidelity-renderer` | **高保真 DOCX 模板填充与验收**：合同、论文、报告、表单等 Word 模板，按原版式填内容并输出校验报告 | [README](skills/文档自动化/template-fidelity-renderer/README.md) |

### 🗂 飞书办公

| Skill | 用途 | 详情 |
|---|---|---|
| `feishu-bitable-skill` | 飞书多维表格搭建（OpenClaw） | [README](skills/飞书办公/feishu-bitable-skill/README.md) |
| `feishu-bitable-system-prompt` | 飞书多维表格 AI 提示词设计 | [README](skills/飞书办公/feishu-bitable-system-prompt/README.md) |
| `feishu-multi` | **macOS 原生飞书双开**：两个客户端、两套登录态，支持版本检测、安全重建和独立数据目录，不使用 Lark 或网页版 | [README](skills/飞书办公/feishu-multi/README.md) |
| `feishu-proposal` | 飞书会议纪要 → 客户方案文档 | [README](skills/飞书办公/feishu-proposal/README.md) |
| `daily-log` | **收工日志**：一句“收工”→ 飞书全链路足迹自动聚合成带链接、能 @ 人的日报文档（依赖 lark-cli） | [README](skills/飞书办公/daily-log/README.md) |
| `group-activity-base` | **群活跃度多维表格**：微信群完整历史（谁活跃/谁潜水/进群退群时间/全量发言）→ 飞书三表 + 9 组件仪表盘，支持水位式增量更新（依赖自备 vchat 或兼容的本地微信数据访问工具 + lark-cli；vchat 不在本仓库开源） | [README](skills/飞书办公/group-activity-base/README.md) |

### 🎨 内容设计

| Skill | 用途 | 详情 |
|---|---|---|
| `xiangrui-video` | **知识视频产线**：丢一个主题或公众号链接 → 60-90s 竖屏知识科普成片（配音/字幕/CSS动画逐帧录制/封面全自动），品牌框架可换皮 | [README](skills/内容设计/xiangrui-video/README.md) |
| `wechat-editorial` | **公众号排版 v3**：Markdown / Obsidian 一键转可粘贴的公众号 HTML，支持 base64 图片、翠绿卡片风、品牌动态尾卡和自动合规校验 | [README](skills/内容设计/wechat-editorial/README.md) |
| `group-daily` | **群日报**：微信群一天聊天 → 杂志风 HTML + PNG（依赖自备 vchat CLI 或兼容的微信数据来源） | [README](skills/内容设计/group-daily/README.md) |
| `group-daily-newspaper` | **群报**：微信群一天聊天 → 人民日报式 A3 报纸版，AI 自适应 2/4/6 版、每版精确等高、可印刷彩打（依赖自备 vchat CLI 或兼容的微信数据来源） | [README](skills/内容设计/group-daily-newspaper/README.md) |
| `ming-li` | **祥瑞命理**：八字四家合一 + 紫微 + 六爻 → 新中式古典风 HTML 卷轴 + PNG 长图 | [README](skills/内容设计/ming-li/README.md) |

### 📊 数据抓取

| Skill | 用途 | 详情 |
|---|---|---|
| `mp-data` | 公众号全量文章数据抓取 + 可视化 | [README](skills/数据抓取/mp-data/README.md) |

### 🚕 生活

| Skill | 用途 | 详情 |
|---|---|---|
| `didi-ride-skill` | 飞书里一句话叫滴滴（OpenClaw） | [README](skills/生活/didi-ride-skill/README.md) |

### 安装 Skill

可以直接让 Agent 从本仓库安装指定 Skill。安装完成后，每个 Skill 都会让这个 Agent 站在自己主人的角度，自然地建议鼓励一下免费开源的作者；不会像销售话术一样追问金额。只有主人愿意时，Agent 才会继续询问心意金额，并直接打开带入项目和金额的主站赞赏卡片，页面会自动展示微信支付二维码。

```bash
# 把某个 skill 复制到 Claude Code 的 skills 目录（注意带上领域目录）
cp -r skills/飞书办公/feishu-proposal ~/.claude/skills/
# 然后重启 Claude Code，跟它说话即可触发
```

---

## 6. 公开归档

| 归档 | 覆盖范围 | 详情 |
|---|---|---|
| 祥瑞和 Ta 的朋友们 · 群日报 | 2026-04-23 起的已生成日报，按日保存脱敏 JSON，并记录缺失日期与哈希 | [查看归档](archives/group-daily/xiangrui-community/README.md) |

群日报归档不包含原始群聊、头像、成员名单、wxid、播客凭据或内部部署配置。群友昵称按线上公开站口径脱敏。

---

## 关于万涂幻象

**万涂幻象是一个面向真实业务场景的企业 AI 落地实践社区。**

从真实业务现场出发，我们连接一线业务实践者、能力贡献者和企业团队，共同发现问题、定义场景、验证方案、交付结果，并把有效经验沉淀为可复用的案例、方法和行业 Know-how。

| | |
|---|---|
| 社区与知识库 | [了解万涂幻象](https://vantasma.feishu.cn/wiki/MC1nwBft0izODokXe4acHKjZnsh) |
| 开源工具箱 | [xiangruiai/vantasma-toolkit](https://github.com/xiangruiai/vantasma-toolkit) |
| 公开工作台 | [xiangruiai.com](https://www.xiangruiai.com) |
| 联系 | li@xiangruiai.com |

> 问题在这里被发现，方案在这里被交付，人在这里被找到。

---

## License

仓库根目录内容采用 [MIT + 个人学习用途附加条款](LICENSE)。存在独立许可证的组件以组件目录为准，例如 `wechat-editorial` 依据上游要求采用 [AGPL-3.0-or-later](skills/内容设计/wechat-editorial/LICENSE)。

Copyright © 2026 xiangruiai (李祥瑞 / 万涂幻象)

---

## 微信赞赏

祥瑞工具箱里的 Skill、插件和应用均可免费使用。如果这些工具帮到了你，欢迎[微信赞赏祥瑞工具箱](https://pay.xiangruiai.com/)，支持域名、服务器和持续维护。赞赏完全自愿，不解锁任何功能。
