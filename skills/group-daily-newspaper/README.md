# group-daily-newspaper

> 把一个微信群一天（或一段时间）的对话，做成**可印刷的人民日报式 A3 报纸**——版数自适应（2/4/6/8 偶数版），每版精确等高，可彩打。

`group-daily` skill 的扩展版。`group-daily` 出杂志风长图，本 skill 把同一份 `story.json` 升级成报纸版 PDF。

![demo](docs/demo.jpg)

---

## ✦ 为什么做这个

`group-daily` 的杂志风长图适合发朋友圈，但有人想——

- 印出来当**实体周边**（巡演、生日报、年会纪念物）
- 排版上更像**人民日报 / 卫报 / Wall Street Journal** 这种正式纸媒
- 一份**可以裱起来挂墙上**的群文化档案

本 skill 解决：

- 严格 A3（297×420mm = 1123×1587px @96dpi）
- 版数按当天故事量自适应（节点少 2 版、常规 4 版、丰富 6 版）
- 每版精确等高 1587 px，强制一页一版
- 每版独立 layout，不千篇一律
- 主+副标自适应字号（按字数 22-42px 动态注入）
- 中文 `word-break: keep-all` + ` / ` 分隔保证 wrap 时每行结尾是完整词

---

## ✦ 安装

```bash
# 1) 先装 group-daily skill（本 skill 依赖它产出的 story.json + avatars.json）
git clone https://github.com/<user>/group-daily ~/.claude/skills/group-daily

# 2) 装本 skill
git clone https://github.com/<user>/group-daily-newspaper ~/.claude/skills/group-daily-newspaper
```

依赖：

- Chrome / Chromium（headless PDF 输出）
- Python 3.10+
- 由 `group-daily` skill 产出的 `story.json` + `avatars.json`

---

## ✦ 用法

```bash
# 1) 先跑 group-daily 出 story.json + avatars.json
#    详见 group-daily README

# 2) 复制空白 layout-plan 模板
cp ~/.claude/skills/group-daily-newspaper/examples/layout-plan-template.json \
   /tmp/layout-plan-<日期>-<群名>.json

# 3) AI 按当天故事量决定版数（2/4/6/8），填 plan 里的 pageN，每个加 template 字段：
#    masthead（page1）/ communal（共建版）/ feature（副刊版）/ cast（高光附录版）

# 4) 渲染 HTML
python3 ~/.claude/skills/group-daily-newspaper/scripts/render_newspaper.py \
   <story.json> <avatars.json> <layout-plan.json> <out.html>

# 5) 强制 height: 1587 + overflow:hidden 防 chrome 分页
sed -i '' 's/min-height: 1587px;/height: 1587px; overflow: hidden;/' <out.html>

# 6) PDF 输出（A3 portrait）
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --headless=new --disable-gpu --no-sandbox \
  --user-data-dir=/tmp/cpdf-$(date +%s) \
  --virtual-time-budget=20000 --hide-scrollbars \
  --no-pdf-header-footer \
  --print-to-pdf=<out.pdf> file://<out.html>

# 7) 验
pdfinfo <out.pdf> | grep -E "Pages|Page size"
# 必须看到 Pages == 版数，Page size: 841.92 x 1191.12 pts (A3)
```

---

## ✦ 4 种 template

| template | renderer | 适用版 | 主要 figure |
|---|---|---|---|
| `masthead` | render_page_1 | 第 1 版头版 | 报头 + hero + aside figure + briefings + photo_strip + day_stats |
| `communal` | render_page_2 | 共建版 / 产出物版 | person_card + hero + produced_list + timeline_strip + quote_wall |
| `feature` | render_page_3 | 副刊 / 群魂 / 深度版 | banner_image + hero + timeline_strip + letters + lingo |
| `cast` | render_page_4 | 人物高光附录版（推荐放最后） | 8 高光 + SOP + QA + tomorrow + QR |

---

## ✦ 隐私 & 安全

本 skill **完全本地运行**，不传任何数据到外部服务。

- `examples/` 只含**空白模板**，不含任何真实群对话/人名/wxid
- `.gitignore` 已配置：`layout-plan-2*.json` / `story_2*.json` / `*_images/` 全部禁止上传
- 渲染产物 `*-报纸版.{html,pdf}` 也在 .gitignore 中
- 真实群数据请存到 `$GROUP_DAILY_VAULT`（默认 `~/Documents/GroupDaily/`），它不在 skill 仓库里

**发 PR 前**自查：

```bash
grep -rn "wxid_\|@chatroom\|真群名\|真人名" .
```

---

## ✦ 设计来源

- 横向参考：人民日报、卫报、Wall Street Journal、Le Monde
- 纵向参考：Spotify Wrapped、网易云年报、Stripe Annual Letter

详细设计硬约束见 [`references/newspaper-design.md`](references/newspaper-design.md)。

---

## ✦ License

MIT

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
