---
name: gongzhonghao-typeset
description: 公众号排版技能。用 agent 写完公众号 markdown 后，一键排成可粘贴的公众号 HTML。带实时控制面板：品牌名 / 主题色 / 字号 / 行高 / 图片样式 / 屏幕吸色 / 图片吸色 / 剪贴板智能粘贴，全部所见即所得。最后 ClipboardItem 复制富文本到剪贴板，粘到 mp.weixin.qq.com 即可发布。适用于用户说「起公众号」、「公众号排版」、「把这篇排版」、「转公众号 HTML」、「排版公众号」时触发。
---

# 起公众号

用 agent 写完公众号文章后，一键排成**你品牌风**的公众号 HTML。

```
markdown（agent 写好的）
   ↓
[排版引擎：CSS 变量驱动 + 主题系统]
   ↓
[控制面板：实时自定义 / 多种吸色方式]
   ↓
ClipboardItem 复制富文本
   ↓
粘到 mp.weixin.qq.com
```

## 当前进度

🚧 **M1 雏形阶段** — 控制面板已通。

```bash
open templates/preview.html
```

浏览器里看：左边公众号文章预览，右边主题控制面板。拖控件 / 拖色卡 / 吸色 → 实时切换。调到满意点「复制公众号 HTML」→ 粘 mp.weixin.qq.com。

## 控制面板能力

| 类目 | 能调 |
|------|------|
| **品牌** | 品牌名 / 章节小戳 / 期号 |
| **配色** | 主色 / 高亮底色 / 辅助色 / 正文色（4 个大色卡） |
| **排版** | 正文字号 / 行高 / 章节大数字字号 |
| **图片** | 圆角 / 边框宽度 / 边框颜色 / 阴影强度 |

## 吸色三种方式

| 方式 | 兼容性 | 说明 |
|------|--------|------|
| 屏幕吸色 | 仅 Chrome / Edge | 浏览器原生 EyeDropper，鼠标变十字吸全屏任意位置 |
| 图片吸色 | 全浏览器 | 上传图片 → 鼠标移动显示 hex → 点击吸取 |
| 粘贴 hex / Cmd+V | 全浏览器 + 全工具 | 配合 macOS 数码测色计 / Sip / Figma 等，吸完 Cmd+V 自动识别应用 |

## 路线图

- [x] **M1 雏形**：控制面板 + CSS 变量驱动主题 + 三种吸色 + 一键复制（本次）
- [ ] **M1 完整**：移植 wechat-editorial 排版引擎成 `render.py`，吃 agent 写完的 markdown
- [ ] **M2 自然语言改 skill**：通过对话调整组件 / 加新组件 / 切预设主题（暗夜 / 杂志 / 极简）
- [ ] **M3 发布**：`install.sh` + README + 写公众号文章

## 用法（M1 完整后）

```bash
# agent 写完 md，丢路径给 skill 排版
python3 cli.py "/path/to/article.md"
# → 自动打开 /tmp/wx_preview.html，左预览右控制面板

# 切主题
python3 cli.py "..." --theme my_theme.json
```

## 触发

用户说：
- "起公众号"
- "排版一下"
- "把这篇做成公众号 HTML"
- "公众号排版"

## 跟 wechat-editorial 的区分

- `wechat-editorial`（祥瑞自用）：绑万涂幻象主题硬编码 + 含飞书 wiki 上传等完整工作流，专为祥瑞优化
- `gongzhonghao-typeset`（对外分享版）：通用主题 / 实时控制面板 / 多人可装可改，theme.json 配置即可换品牌风

## 设计哲学

**专注做排版差异化，不做链接抓取**。原因：
- agent 已经能写公众号文章（用 gongzhonghao-writer skill 或直接对话产出 md），抓取层是冗余复杂度
- 公众号文章抓取有反爬 + 平台政策变化，维护成本高
- 真正稀缺的是「写完后排成精致品牌风、可微调、一键复制」这层

排版层做四件事：
1. **反复验证的 9 条公众号 HTML 输出规范**（用 section/span 不用 ul/li，加粗用 span 不用 strong，图片 max-width:100%，等等）—— 这是 wechat-editorial 200+ 篇公众号反复踩坑沉淀
2. **CSS 变量驱动的主题系统**（一份 theme.json 切所有视觉）
3. **实时控制面板**（所见即所得，不用改 CSS 文件）
4. **三种吸色覆盖所有场景** + **ClipboardItem 富文本复制**（粘公众号编辑器直接生效）
