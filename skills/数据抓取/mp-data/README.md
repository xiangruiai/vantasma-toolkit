# 公众号数据 — Skill

抓取微信公众号全量文章数据，生成包含互动率、阅读分布、内容类型分析等深度洞察的可视化 HTML 报告。

支持任意公众号，只需微信扫码登录对应后台即可。

## 安装

把下面这句话复制粘贴到 Claude Code 里，它会自动完成所有安装：

> 帮我安装公众号数据分析 skill：从 https://github.com/Larkin0302/mp-data clone 下来，安装 playwright 和 chromium 依赖

<details>
<summary>或者手动安装</summary>

```bash
git clone https://github.com/Larkin0302/mp-data.git
pip install playwright && playwright install chromium
```
</details>

## 使用

在 Claude Code 中：

```
/公众号数据                    # 全量抓取 + HTML 分析报告
/公众号数据 --quick            # 用已有数据直接生成报告
```

首次运行会弹出浏览器窗口，用微信扫码登录公众号后台。登录态自动保存，后续无需重复扫码。

## 报告内容

- **KPI 概览**：总篇数、总阅读、篇均阅读、中位数、互动率
- **阅读量分布**：直方图 + 统计特征 均值/中位数/标准差/P90
- **趋势图表**：月度阅读、发文量、互动率趋势、内容类型对比
- **数据表格**：TOP 20 文章 按阅读量/互动率、月度汇总、高潜力文章

## 工作原理

1. 通过 Playwright 驱动 Chromium 浏览器
2. 打开 mp.weixin.qq.com 公众号后台
3. 自动检测登录态，未登录则等待扫码
4. 逐页抓取"发表记录"页面的文章数据
5. 生成带图表的 HTML 分析报告

## 文件结构

```
├── SKILL.md              # Claude Code skill 定义
├── scripts/
│   ├── extract.js        # 浏览器端 DOM 数据提取
│   ├── scrape.py         # Playwright 驱动的全量抓取
│   └── report_html.py    # HTML 可视化报告生成
```

---

**万涂幻象出品** · 作者 **祥瑞** · 个人网站 [www.xiangruiai.com](https://www.xiangruiai.com)
