---
name: 公众号数据
description: 抓取微信公众号全量文章数据并生成可视化 HTML 分析报告（支持任意公众号，需登录对应后台）
trigger: /公众号数据
---

# 公众号数据 Skill

抓取 mp.weixin.qq.com 发表记录页的全量文章数据，生成包含互动率、阅读分布、内容类型 ROI 等深度分析的可视化 HTML 报告。支持任意公众号，只需在 Chrome 中登录对应后台即可。

## 前置条件

```bash
pip install playwright && playwright install chromium
```

首次运行会弹出浏览器窗口，用微信扫码登录公众号后台。登录态自动保存在 `~/.mp-data-browser/`，后续无需重复扫码。

## 使用方式

```
/公众号数据                          # 全量抓取 + HTML 分析报告
/公众号数据 --quick                  # 只跑分析（用已有 /tmp/mp_all_publish_data.json）
/公众号数据 --content                # 抓取文章正文内容
/公众号数据 --content --top 20       # 只抓阅读量前20篇的正文
```

## 执行流程

### Step 1: 检查是否需要抓取

- `--quick` 模式：跳到 Step 5，直接用已有数据生成报告
- 默认模式：先检查/完成登录，再全量抓取

### Step 2: 登录公众号后台

脚本自动处理登录流程：

```bash
python3 ~/.claude/skills/mp-data/scripts/scrape.py
```

1. 打开 mp.weixin.qq.com，检测是否已有登录态
2. 如果已登录：自动提取 token，显示当前公众号名称
3. 如果未登录：Chrome 会显示扫码页面，提示用户用微信扫码
4. 等待扫码完成（最长 3 分钟），自动提取 token

**无需手动复制 token**，脚本从页面 URL 自动提取。

### Step 3: 获取总页数

在发表记录页执行 JS 提取总文章数：

```javascript
var total = document.querySelector('.weui-desktop-pagination__num') || 
            document.querySelector('[class*=total]');
total ? total.innerText : 'unknown';
```

计算总页数 = Math.ceil(总数 / 10)

### Step 4: 逐页抓取

对每一页（begin=0, 10, 20, ...）：
1. `opencli browser open` 导航到对应页
2. 等待 4 秒加载
3. `opencli browser eval` 执行提取脚本 `scripts/extract.js`
4. 解析 JSON 结果，追加到文章列表

抓取完成后保存到 `/tmp/mp_all_publish_data.json`。

### Step 5: 生成 HTML 分析报告

```bash
python3 ~/.claude/skills/mp-data/scripts/report_html.py /tmp/mp_report.html
open /tmp/mp_report.html
```

报告内容包括：

**顶部 KPI**：总篇数、总阅读、篇均阅读、中位数阅读、赞阅比、在看阅比、分享率、综合互动率

**阅读量分布特征**：均值/中位数/标准差/变异系数/四分位数/P90 头部线/前 20% 贡献度 + 阅读量直方图

**4 个趋势图表**：
- 月度总阅读（柱状图）
- 篇均 vs 中位数 / 发文量（折线+柱状复合图）
- 月度互动率趋势（赞阅比/在看率/分享率/综合互动率四线）
- 内容类型篇均阅读（横向柱状图）

**5 个数据表格**：
- TOP 20 文章（按阅读量）：含赞阅比、在看率、分享率、互动率
- TOP 20 文章（按互动率）：发现读者真正认可的内容
- 月度汇总：含中位数、各互动比率
- 内容类型深度分析：各类型的互动行为差异和阅读占比
- 高分享率文章（>15%，阅读>100）
- 高潜力文章（高互动低阅读，值得二次推广）

**底部指标说明**：每个指标的含义和公众号典型参考值

### Step 6: 获取文章内容（--content 模式）

通过 CDP 浏览器打开每篇文章 URL，提取正文文本。

```bash
# 单篇
python3 ~/.claude/skills/mp-data/scripts/fetch_content.py "文章URL"

# 批量（用已有数据）
python3 ~/.claude/skills/mp-data/scripts/fetch_content.py --batch /tmp/mp_all_publish_data.json

# 只取阅读量前20篇
python3 ~/.claude/skills/mp-data/scripts/fetch_content.py --batch /tmp/mp_all_publish_data.json --top 20
```

前置条件：CDP Proxy 已启动（`localhost:3456`）。

提取内容包括：标题、作者、发布时间、正文文本、图片URL列表、字数统计。
输出保存到 `/tmp/mp_articles_content.json`。

### Step 7: 数据存储

- JSON 数据 → `/tmp/mp_all_publish_data.json`（全量，供后续分析复用）
- HTML 报告 → `/tmp/mp_report.html`（浏览器直接打开）
- 文章内容 → `/tmp/mp_articles_content.json`（正文提取结果）
- 如需归档到 Vault → `{VAULT}/10.项目/公众号/6.数据复盘/` 下

## 故障排除

- **扫码超时**：重新运行，Chrome 会再次显示扫码页面
- **token 失效**：关闭 Chrome 中已打开的 mp.weixin.qq.com 页面，重新运行让脚本自动获取新 token
- **opencli 不可用**：确认 `opencli browser` 命令可正常执行

## 文件结构

```
scripts/
├── extract.js       # 浏览器端 DOM 提取脚本（含文章 URL 抓取）
├── scrape.py        # 全量翻页抓取脚本
├── report_html.py   # HTML 可视化报告生成器
└── fetch_content.py # 文章正文内容提取（CDP 浏览器）
```
