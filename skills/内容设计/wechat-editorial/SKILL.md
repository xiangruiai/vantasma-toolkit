---
name: wechat-editorial
description: 将 Markdown 或 Obsidian 文章转换为可复制到微信公众号编辑器的翠绿卡片风 HTML。支持 wikilink 图片、base64 内嵌、封面卡、章节头、三层重点标记、深色代码块、品牌尾卡和生成后合规校验。用户提到公众号排版、转公众号 HTML、粘贴到公众号、图文排版或 wechat editorial 时触发。
---

# 微信公众号排版

把已经写好的 Markdown 转成微信公众号可直接粘贴的 HTML。图片默认转成 base64，一键复制时跟随正文进入公众号编辑器。

## 硬边界

1. 默认模式必须有封面图。frontmatter 缺少 `封面图:` 时停止并提醒补图。
2. 合作稿或纯正文可显式使用 `--plain`，关闭封面和品牌尾卡。
3. 生成后必须运行内置合规校验，ERROR 清零才算完成。
4. 不在排版过程中改写文章事实、观点和结构。只允许按需补充排版标记。
5. 图片找不到时停止修正路径，不输出空图片占位。

## 基本用法

```bash
python3 md_to_editorial.py article.md --open
```

常用参数：

```bash
python3 md_to_editorial.py article.md \
  --out /tmp/wx_preview.html \
  --vault "/path/to/vault" \
  --image-root "/path/to/images" \
  --brand-name "你的品牌" \
  --tagline "你的品牌语" \
  --footer-card "/path/to/profile-card.png" \
  --footer-actions "/path/to/actions.gif" \
  --open
```

纯正文模式：

```bash
python3 md_to_editorial.py article.md --plain --open
```

## Frontmatter

```yaml
---
标题: 文章标题
副标题: 可选副标题
封面图: ./images/cover.png
创建时间: 2026-08-22
标签:
  - AI
  - 知识管理
固定尾卡: 是
---
```

图片解析顺序：绝对路径、文章所在目录、`--image-root`、`--vault` 全局搜索。

## 标记规则

- `## 标题`：极简大数字章节头
- `### 标题`：黄色下划线小节标题
- `>> 金句`：居中金句卡
- `⚠️ 内容`：黄色警告框
- `💡 内容`：绿色信息框
- `**文字**`：绿色加粗
- `==文字==`：黄色渐变高亮，全文建议不超过 5 处
- `++文字++`：浅绿下划线
- `~~文字~~`：灰底删除线标签
- `「按钮」`：浅灰胶囊
- `` `代码` ``：绿色行内代码
- `> 引用`：灰底虚线引用框
- 三反引号代码块：深色 Mac 窗口样式
- 文件名含 `全图`、`长图`、`scrollbox` 或 `longshot`：长图滚动容器

完整主题组件见：

- `references/theme-moyu-green.md`
- `references/common-components.md`

## 标记纪律

| 层级 | 用途 | 建议频率 |
|---|---|---|
| 锚点层 | 核心结论与金句，使用黄色高亮 | 全文不超过 5 处 |
| 标记层 | 关键词与关键数据，使用浅绿下划线 | 每段 1 至 3 个短语 |
| 容器层 | 引用、代码、提示和结构化信息 | 按需 |

一段内不超过两种高亮效果。绿色加粗只用于核心概念、品牌名和产品名。

## 微信兼容铁律

- 禁止在正文片段使用 `<div>`、`<ul>`、`<ol>`、`<li>`、`<strong>`。
- 禁止 class、id、外部 CSS、CSS 变量、grid、float 和绝对定位。
- 列表使用 `<section> + <span>`。
- 加粗使用内联样式 `<span>`。
- 普通图片使用 `max-width:100%;height:auto`，不要强制 `width:100%`。
- `<span leaf="">` 只包最里层裸文字，不能包住带样式的 span。
- 装饰性空元素内部使用 `<span leaf=""><br></span>`。

这些规则由 `validate_wx_html.py` 自动检查。

## 完成检查

1. 输出 HTML 已生成。
2. 校验结果为 0 ERROR。
3. 封面图、正文图片、GIF 和尾卡在浏览器中正常显示。
4. 点“复制到公众号”后，在公众号编辑器中抽查标题、重点样式、图片和代码块。
5. WARNING 逐条人工判断，不机械追求零警告。

## 品牌定制

默认附带万涂幻象的品牌尾卡，用于展示完整生产效果。其他账号使用时应替换品牌名、品牌语和尾卡资产，不要冒用万涂幻象身份。

需要重新生成同结构的 PNG + GIF 尾卡时，可安装 Pillow 后使用：

```bash
python3 gen_branded_footer.py /path/to/your-card-source.png
```

## 来源与许可

翠绿主题组件基于 `isjiamu/gzh-design-skill` 的 `theme-moyu-green` 改编。修改版与仓库整体遵循 AGPL-3.0-or-later，详见 `LICENSE` 和 `NOTICE`。
