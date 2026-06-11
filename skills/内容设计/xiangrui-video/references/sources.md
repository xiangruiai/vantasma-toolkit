# 信源（xiangrui-video 研究信源 · 开源可引用，祥瑞 2026-06-11 定）

> AI / 科技类主题做研究时**必用**，按优先级取最新最准的事实。
> 时效性强的事实（"X 元年是哪年"、当前最火的产品、最新数据）**必须用实时信源核实**，
> 禁止把训练数据或普通搜索的一句话当现状——AI 领域半年就大变样。
> 反面教材：2026-06 把"2026 是 Agent 元年"当真（实际 2025 才是，2026 是 Agent 落地年）。

## 优先级与用法

### 1. aihot — AI HOT 实时资讯（首选）
- **来源**：https://aihot.virxact.com （公开匿名可访，无需 token）
- **安装**：`curl -fsSL https://aihot.virxact.com/aihot-skill/install.sh | bash`
  （或装好的 aihot skill 直接用）
- **用法**：每天精选 + 关键词搜，比训练数据和普通搜索都新。调 API 必带浏览器 UA：
  ```bash
  UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
  # 最近精选热点
  curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=selected&take=30"
  # 关键词搜（覆盖全池，找具体产品/公司最准）
  curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?q=Claude%20Code&take=6"
  ```
- **适用**：核实"现在最火的 AI 产品/模型/Agent 是什么"、最新发布、当前热点。
  实测能查到 Claude Code、Codex、OpenClaw(龙虾)、各厂新模型等普通搜索滞后的内容。

### 2. WaytoAGI — 开源知识库（深度信源）
- **来源**：https://waytoagi.feishu.cn/wiki/ （飞书 wiki 开源知识库）
- **用法（飞书 CLI，祥瑞 2026-06-11 指）**：space token `7226178700923011075`，用 `lark-wiki` skill
  列节点 + `lark-doc` skill 读文档内容（`lark-cli` 原子命令）。先列 space 节点找相关主题，再读对应节点。
- **适用**：AI 工具/概念的体系化知识、教程、深度梳理。aihot 给"最新动态"，WaytoAGI 给"系统认知"。

### 3. deep-research / WebSearch（补充）
- aihot 和 WaytoAGI 没覆盖到的，再用 deep-research skill 或 WebSearch 多角度补全。
- WebSearch 找冷门产品/代号很有用（如"龙虾"= OpenClaw 就是 WebSearch 查到的）。

## 引用规范
- 视频里用到的事实/数据，相关场景标 `source`（如"素材来源：网络"、"数据来源：xx"）。
- 开源用户用本 skill 时，这两个信源开箱即用：aihot 一行安装，WaytoAGI 公开可读。
- 信源出处务必备注（本文件即出处说明），不掠人之美。
