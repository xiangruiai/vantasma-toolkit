# gongzhonghao-typeset

公众号排版 Claude Code skill。**用 agent 写完 markdown 后，一键排成可粘贴的公众号 HTML**。

带实时控制面板：左侧公众号文章预览，右侧拖控件调主题 品牌名 / 主题色 / 字号 / 行高 / 图片样式，所见即所得，一键复制富文本粘贴到 `mp.weixin.qq.com`。

## 特性

- **实时控制面板**：CSS 变量驱动，拖色卡 / 调字号 / 改品牌名，左侧文章实时跟着切
- **三种吸色**：浏览器 EyeDropper Chrome / Edge+ 上传图片吸色 全浏览器+ Cmd+V 粘贴 hex 配合 macOS 数码测色计 / Sip / Figma 任意工具
- **主题系统**：一份 `theme.json` 切换所有视觉，可保存为不同品牌的预设
- **ClipboardItem 富文本复制**：`getComputedStyle` flatten CSS 变量到 inline style，粘公众号编辑器直接生效
- **9 条公众号 HTML 输出规范**：200+ 篇公众号反复粘贴验证沉淀 用 section/span 不用 ul/li，加粗用 span 不用 strong，图片 max-width:100%，块级元素剥 width，根标签用 section 等
- **零依赖**：纯 Python 标准库 + 浏览器原生 API，无 pip 包

## 安装

作为 Claude Code skill 安装：

```bash
git clone https://github.com/<your>/gongzhonghao-typeset.git \
  ~/.claude/skills/gongzhonghao-typeset
```

也可以直接当 CLI 工具用，跟 Claude Code 解耦。

## 用法

```bash
# 默认：panel 模式 + 浏览器自动打开
python3 scripts/cli.py article.md

# 自定义主题
python3 scripts/cli.py article.md --theme my-theme.json

# 覆盖期号
python3 scripts/cli.py article.md --vol 188

# 裸模式（无控制面板，wechat-editorial 风格单文件）
python3 scripts/cli.py article.md --no-panel

# 不自动打开浏览器
python3 scripts/cli.py article.md --no-open
```

## 主题自定义

复制 `theme.json` 改成你的品牌：

```json
{
  "brand": {
    "name": "你的品牌",
    "magazine_suffix": "MAGAZINE",
    "chapter_stamp": "你的品牌 ─",
    "issue_prefix": "VOL.",
    "issue_number": 1,
    "case_prefix": "CASE",
    "feature_label": "ISSUE FEATURE"
  },
  "colors": {
    "main": "#22a667",
    "soft": "#a3d97d",
    "highlight_pink": "#ffe5ec",
    "text": "#3a3a3a"
  },
  "typography": {
    "body_font_size_px": 15,
    "body_line_height": 1.85,
    "chapter_number_size_px": 58,
    "h3_size_px": 17
  }
}
```

跑 `cli.py article.md --theme your-theme.json` 即可。

## Markdown 约定

支持的语法 用 `demo.md` 跑一遍看完整演示：

| 标记 | 渲染效果 |
|------|---------|
| `**1. 标题**` | 章节卡：大灰数字 + 品牌小戳 + 标题 + CASE 副标 |
| `## 标题` | 大数字章节头 "写在最后" 走居中短横款 |
| `### 标题` | 左侧主色竖条 + 17px 粗体 |
| `**粗体**` | 深黑加粗 用 span 不用 strong，避免公众号强插换行 |
| `==高亮==` | 粉桃 mark 高亮 |
| `` `code` `` | 翠绿胶囊 inline code |
| `按钮` | 浅灰胶囊 |
| `- 列表项` | 主色圆点 用 section+span，避免公众号拆行 |
| `1. 有序项` | 主色双位编号 |
| `> 引用` | 白卡 + 灰点 多行用 br join 保留节奏 |
| ` ```代码块``` ` | 白卡 + 灰点 + 等宽 |
| `\| 表格 \|` | 主色表头 + 斑马纹 |
| `![alt](url)` 或 `![[wiki]]` | 圆角 + 主色边框 + 投影 + caption |
| 文件名含全图/长图 | 自动 scrollbox 超长 PNG 不挤死阅读 |
| `---` | 两端渐隐分割线 |

Frontmatter 用**中文 key**：

```yaml
---
标题: 文章标题
副标题: 副标题钩子
创建时间: 2026.05.19
标签:
  - 标签1
  - 标签2
---
```

## 工作流

```
agent 写完 markdown
     ↓
python3 cli.py article.md
     ↓
浏览器打开预览页 + 控制面板
     ↓
拖色卡 / 调字号 / 改品牌名（实时切换）
     ↓
点「复制公众号 HTML」
     ↓
粘 mp.weixin.qq.com
     ↓
发布
```

## 致谢

排版引擎核心规范沉淀自一个长期维护的公众号排版工具，本 skill 基于它的9 条输出规范做了通用化改造 参数化主题 + 控制面板 + 多平台吸色 + CSS 变量驱动。

## License

MIT

---

**万涂幻象出品** · 作者 **祥瑞** · 个人网站 [www.xiangruiai.com](https://www.xiangruiai.com)
