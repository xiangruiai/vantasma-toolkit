# HTML 报告模板（专业命理咨询输出）· v2.4

> 韦千里 8 步 + 古今夹叙 + 13 类赛道 + 通俗化双层 + 新中式古典视觉
> 同时支持 **PNG 长图导出**（用于发群、朋友圈、分享）

---

## ⚡ v2.4 视觉硬规范（务必遵守）

### 字体
- 主体：**Kaiti SC / STKaiti / Songti SC**（楷宋）
- 干支与术语：Songti SC（衬线感强）
- ❌ 禁用：Cormorant Garamond / Inter / Noto Serif（v2.2 教训）
- ❌ 禁用：所有英文标题（如"MING LI · BAZI ANALYSIS"）

### 配色
| 名称 | 用途 | 值 |
|---|---|---|
| 宣纸米黄底 | 整体背景 | `#ede4cd` |
| 墨主 | 正文 | `#1f1b16` |
| 墨次 | 副文 | `#3b342a` / `#5d544a` |
| 墨淡 | 注释 | `#8a8170` / `#a39884` |
| 朱砂 | 关键词 / 印章 | `#8e2e22` |
| 古铜 | 装饰线 / 角花 | `#8a6f47` |

### 线条
- **禁用硬实线 `border 1px solid`**（用户反馈"突兀"）
- 横线一律用 **两端淡入淡出的渐变线**：
  ```css
  background: linear-gradient(to right, transparent 0%, var(--bronze) 30%, var(--bronze) 70%, transparent 100%) top / 100% 1px no-repeat;
  ```
- 总诀匾额用 **四角角花**（L 形），不用贯穿横线
- 章节内子目用 **朱砂小菱形 + 渐变引线**，不用左侧竖线
- "通俗说"卡用 **朱砂印章式标签 + 浅色块**，不用左侧竖线

### 章节结构（韦千里 8 步）
1. 卷之一 · 看强弱
2. 卷之二 · 定格局
3. 卷之三 · 取用神
4. 卷之四 · 论喜忌
5. 卷之五 · 查岁运
6. 卷之六 · 推六亲
7. 卷之七 · 评性情
8. 卷之八 · 断事业（含 13 类赛道表 + 总诀心法）

外加：
- **卷首 + 共情开场**（在第一章前）
- **术语简注 + 共情结语**（在第八章后，无线包围）
- **印章落款**（卷末）

### 通俗化双层
- 行内浅注：`<span class="gloss">（一句话通俗解释）</span>` 用 `--ink-gloss` 浅灰小字
- 卷末术语简注：30+ 名词 `<dl>` 速查
- ⚠️ 不要正文 + "通俗说"卡 + 简注三层重复——选其一

### 月份用单字
12 月编号用农历月份单字：**正、二、三、四、五、六、七、八、九、十、冬、腊**
- ❌ 不用"壹贰叁..."（"十一""十二"会撑破格子）
- ❌ 不用"1月2月..."（不古典）

## 一、何时输出 HTML

### 触发条件

- 用户明确说"出 HTML 报告 / 详细报告 / 完整报告 / 我要可视化"
- 推命完成后 AI 主动询问："是否需要生成 HTML 详细报告？"
- 长期咨询 / 深度推命场景（≥ 30 分钟咨询的最终输出）

### 不触发

- 快速咨询（一句话问答）→ Markdown 即可
- 单一事件占卜（六爻）→ Markdown 简报即可

## 二、报告 9 章结构（ISAR 8 章 + 命造卡片）

| # | 章节 | 内容来源 |
|---|---|---|
| 0 | **命造卡片** | 生辰 + 真太阳时 + 四柱 / 命盘 |
| 1 | **性格画像** | 日主 + 月支 + 用神 + 心理学语言（references/05）|
| 2 | **优势与才能** | 喜用神 + 吉神煞 + 紫微吉星 |
| 3 | **生命议题** | 忌神 + 凶神煞 + 紫微煞星 |
| 4 | **成长模式** | 格局 + 大运转换 |
| 5 | **当前阶段意义** | 当前大运 + 流年主题 |
| 6 | **危机与机会时期** | 应期算法（references/90）|
| 7 | **时机与决策建议** | 短/中/长期 时间窗口 |
| 8 | **综合行动建议** | 行动化语言，不只描述 |

## 三、HTML 完整模板

### 3.1 文件结构

```
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{姓名}} 命理综合分析报告</title>
  <style>{{CSS}}</style>
</head>
<body>
  <header><!-- 标题 + disclaimer --></header>
  <main>
    <section id="chart-card"><!-- 0. 命造卡片 --></section>
    <section id="personality"><!-- 1. 性格画像 --></section>
    <section id="strengths"><!-- 2. 优势与才能 --></section>
    <section id="issues"><!-- 3. 生命议题 --></section>
    <section id="growth"><!-- 4. 成长模式 --></section>
    <section id="current"><!-- 5. 当前阶段 --></section>
    <section id="cycles"><!-- 6. 危机与机会 --></section>
    <section id="timing"><!-- 7. 时机决策 --></section>
    <section id="action"><!-- 8. 综合建议 --></section>
  </main>
  <footer><!-- disclaimer + 生成时间 --></footer>
</body>
</html>
```

### 3.2 CSS 设计原则

```css
/* 配色：清爽现代，避免"算命摊"红黄黑 */
:root {
  --bg: #ffffff;
  --text: #1a1a1a;
  --text-muted: #6b6b6b;
  --primary: #2d5f3f;          /* 深绿（木）*/
  --accent: #c4a76b;            /* 暖金（土）*/
  --danger: #b85450;            /* 暗红（火忌神）*/
  --info: #4a6fa5;              /* 海蓝（水）*/
  --neutral: #e8e8e8;           /* 灰白 */

  /* 五行配色 */
  --wood: #5fa874;
  --fire: #d6605c;
  --earth: #c4a76b;
  --metal: #a0a0a0;
  --water: #5b8bb0;
}

body {
  font-family: -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.7;
  max-width: 800px;
  margin: 0 auto;
  padding: 40px 24px;
}

h1 { font-size: 28px; font-weight: 600; letter-spacing: 0.5px; }
h2 { font-size: 20px; border-left: 4px solid var(--primary); padding-left: 12px; margin-top: 40px; }
h3 { font-size: 16px; color: var(--primary); margin-top: 24px; }

/* 命造卡片 */
.chart-card {
  background: linear-gradient(135deg, #fafaf7 0%, #f0ede4 100%);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 32px;
}

/* 四柱表格 */
.bazi-table {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 16px 0;
}
.bazi-pillar {
  text-align: center;
  padding: 16px 8px;
  border-radius: 8px;
  background: #fafafa;
  border: 1px solid var(--neutral);
}
.bazi-pillar .gan { font-size: 24px; font-weight: 600; }
.bazi-pillar .zhi { font-size: 24px; font-weight: 600; margin-top: 4px; }
.bazi-pillar .label { font-size: 12px; color: var(--text-muted); margin-bottom: 8px; }
.bazi-pillar .ten-god { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

/* 五行配色干支 */
.wuxing-木 { color: var(--wood); }
.wuxing-火 { color: var(--fire); }
.wuxing-土 { color: var(--earth); }
.wuxing-金 { color: var(--metal); }
.wuxing-水 { color: var(--water); }

/* 大运时间线 */
.timeline {
  display: flex;
  overflow-x: auto;
  gap: 8px;
  padding: 16px 0;
}
.timeline-item {
  min-width: 100px;
  padding: 12px 8px;
  border-radius: 8px;
  text-align: center;
  background: #fafafa;
  border-top: 3px solid var(--accent);
}
.timeline-item.current {
  background: linear-gradient(135deg, #fff9e6 0%, #fff4d4 100%);
  border-top-color: var(--danger);
  font-weight: 600;
}
.timeline-item .age { font-size: 11px; color: var(--text-muted); }
.timeline-item .pillar { font-size: 18px; margin: 4px 0; }
.timeline-item .theme { font-size: 11px; color: var(--text-muted); }

/* 神煞徽章 */
.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}
.badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 13px;
  background: #f0f0f0;
  border: 1px solid var(--neutral);
}
.badge.good { background: #e8f4ed; border-color: #b5d8c4; color: var(--primary); }
.badge.warn { background: #fdf4e3; border-color: #e8d4a5; color: #8a6d20; }
.badge.bad { background: #fde8e7; border-color: #e8b5b3; color: var(--danger); }

/* 五行雷达图（用 CSS 简单实现 / 或 SVG）*/
.wuxing-radar {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  margin: 16px 0;
}
.wuxing-bar {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.wuxing-bar .bar {
  width: 24px;
  background: var(--primary);
  border-radius: 4px 4px 0 0;
  transition: height 0.3s;
}
.wuxing-bar .label { font-size: 12px; margin-top: 4px; }

/* 流年月份热力图 */
.year-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 4px;
  margin: 12px 0;
}
.month-cell {
  aspect-ratio: 1;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  border: 1px solid var(--neutral);
}
.month-cell.吉 { background: #e8f4ed; }
.month-cell.平 { background: #fafafa; }
.month-cell.凶 { background: #fde8e7; }
.month-cell.动 { background: #fdf4e3; }

/* Disclaimer */
.disclaimer {
  background: #f9f9f9;
  border-left: 4px solid var(--info);
  padding: 16px 20px;
  margin: 24px 0;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
}

/* 行动建议卡 */
.action-card {
  background: #fafafa;
  border-radius: 8px;
  padding: 16px 20px;
  margin: 12px 0;
  border-left: 4px solid var(--primary);
}
.action-card .label {
  display: inline-block;
  font-size: 11px;
  background: var(--primary);
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
  margin-bottom: 8px;
}

/* 打印友好 */
@media print {
  body { max-width: none; padding: 20px; }
  section { page-break-inside: avoid; }
  .timeline { overflow: visible; flex-wrap: wrap; }
}
```

### 3.3 章节内容生成模板

**Section 0 · 命造卡片**：

```html
<section id="chart-card">
  <div class="chart-card">
    <h1>{{姓名}} 命理综合分析</h1>
    <p class="meta">{{公历}} | 农历 {{农历}} | {{出生地}}</p>
    <p class="meta">真太阳时校正：{{校正分钟}}</p>

    <h3>四柱八字</h3>
    <div class="bazi-table">
      <div class="bazi-pillar">
        <div class="label">年柱</div>
        <div class="gan wuxing-{{年干五行}}">{{年干}}</div>
        <div class="zhi wuxing-{{年支五行}}">{{年支}}</div>
        <div class="ten-god">{{年柱十神}}</div>
      </div>
      <div class="bazi-pillar">
        <div class="label">月柱</div>
        <div class="gan wuxing-{{月干五行}}">{{月干}}</div>
        <div class="zhi wuxing-{{月支五行}}">{{月支}}</div>
        <div class="ten-god">{{月柱十神}}</div>
      </div>
      <div class="bazi-pillar">
        <div class="label">日柱（我）</div>
        <div class="gan wuxing-{{日干五行}}">{{日干}}</div>
        <div class="zhi wuxing-{{日支五行}}">{{日支}}</div>
        <div class="ten-god">日主</div>
      </div>
      <div class="bazi-pillar">
        <div class="label">时柱</div>
        <div class="gan wuxing-{{时干五行}}">{{时干}}</div>
        <div class="zhi wuxing-{{时支五行}}">{{时支}}</div>
        <div class="ten-god">{{时柱十神}}</div>
      </div>
    </div>

    <h3>五行强弱</h3>
    <div class="wuxing-radar">
      <div class="wuxing-bar"><div class="bar" style="height: {{木%}}px"></div><div class="label">木</div></div>
      <div class="wuxing-bar"><div class="bar" style="height: {{火%}}px"></div><div class="label">火</div></div>
      <div class="wuxing-bar"><div class="bar" style="height: {{土%}}px"></div><div class="label">土</div></div>
      <div class="wuxing-bar"><div class="bar" style="height: {{金%}}px"></div><div class="label">金</div></div>
      <div class="wuxing-bar"><div class="bar" style="height: {{水%}}px"></div><div class="label">水</div></div>
    </div>

    <h3>核心结构</h3>
    <div class="badges">
      <span class="badge">{{格局名}}</span>
      <span class="badge good">用神：{{用神}}</span>
      <span class="badge bad">忌神：{{忌神}}</span>
    </div>
  </div>

  <div class="disclaimer">
    <strong>免责声明</strong><br>
    本报告基于中国传统命理学（八字 / 紫微 / 六爻）方法论，是关于"潜力倾向"的结构分析，<strong>不是宿命预测</strong>。命理是工具，不是命令。你的选择决定结构的表达方式。
  </div>
</section>
```

**Section 1 · 性格画像**：

按 `references/05-心理学包装语言库.md` 模板：

```html
<section id="personality">
  <h2>1. 你的性格画像</h2>

  <h3>核心特质</h3>
  <p>{{一句话定位，基于日主 + 月支 + 用神}}</p>
  <p>例：你是一个"内省 + 独立"型的人——善于深度思考，但需要主动启动行动。</p>

  <h3>认知风格</h3>
  <p>{{基于印 / 食伤 / 财关系}}</p>

  <h3>情感模式</h3>
  <p>{{基于日支 / 桃花 / 比劫}}</p>

  <h3>行动倾向</h3>
  <p>{{基于官杀 / 食伤 / 比劫}}</p>
</section>
```

**Section 2 · 优势与才能**：

```html
<section id="strengths">
  <h2>2. 你的优势与才能</h2>

  <div class="badges">
    <span class="badge good">{{贵人神煞}}</span>
    <span class="badge good">{{文昌学堂}}</span>
    <span class="badge good">{{驿马 / 华盖}}</span>
  </div>

  <ul>
    <li><strong>优势 1</strong>：{{描述}}</li>
    <li><strong>优势 2</strong>：{{描述}}</li>
    <li><strong>优势 3</strong>：{{描述}}</li>
  </ul>

  <h3>适合方向</h3>
  <p>{{基于喜用神 + 格局推职业方向}}</p>
</section>
```

**Section 3 · 生命议题**：

```html
<section id="issues">
  <h2>3. 你需要修的生命课题</h2>

  <div class="badges">
    <span class="badge warn">{{忌神}}</span>
    <span class="badge bad">{{凶神煞}}</span>
  </div>

  <ul>
    <li><strong>议题 1</strong>：{{描述}}<br>
        <em>建议</em>：{{行动化建议}}</li>
    <li><strong>议题 2</strong>：{{描述}}<br>
        <em>建议</em>：{{行动化建议}}</li>
  </ul>
</section>
```

**Section 4 · 成长模式**：

```html
<section id="growth">
  <h2>4. 你的成长模式</h2>
  <p>{{基于格局 + 用神位置 → 成长曲线描述}}</p>
  <p>例：你的成长属于"晚熟型"——前 40 年偏积累，39 岁后才会真正启动。</p>
</section>
```

**Section 5 · 当前阶段意义**：

```html
<section id="current">
  <h2>5. 你当前阶段的意义</h2>

  <div class="action-card">
    <span class="label">当前大运</span>
    <h3>{{大运干支}}（{{起年}}-{{止年}}岁）</h3>
    <p>{{主题描述 + 心理学包装}}</p>
  </div>

  <div class="action-card">
    <span class="label">今年流年</span>
    <h3>{{流年干支}}</h3>
    <p>{{今年主题}}</p>
  </div>
</section>
```

**Section 6 · 大运时间线（可视化重点）**：

```html
<section id="cycles">
  <h2>6. 你的人生时间线（大运 + 关键节点）</h2>

  <div class="timeline">
    <div class="timeline-item">
      <div class="age">9-18 岁</div>
      <div class="pillar">{{干支}}</div>
      <div class="theme">童年期</div>
    </div>
    <div class="timeline-item current">
      <div class="age">19-28 岁</div>
      <div class="pillar">{{干支}}</div>
      <div class="theme">{{主题}}</div>
    </div>
    <!-- ... 后续大运 -->
  </div>

  <h3>本年 12 月气运图</h3>
  <div class="year-grid">
    <div class="month-cell 平">1月</div>
    <div class="month-cell 平">2月</div>
    <!-- ... 按吉/平/凶/动配色 -->
  </div>
</section>
```

**Section 7 · 时机与决策**：

```html
<section id="timing">
  <h2>7. 时机与决策建议</h2>

  <div class="action-card">
    <span class="label">短期窗口（今年）</span>
    <p>{{今年最佳行动月份 + 内容}}</p>
  </div>

  <div class="action-card">
    <span class="label">中期窗口（3-5 年）</span>
    <p>{{下一个大运转换 + 准备建议}}</p>
  </div>

  <div class="action-card">
    <span class="label">长期窗口（10+ 年）</span>
    <p>{{命局真正启动 / 大成期 + 现在该做什么准备}}</p>
  </div>
</section>
```

**Section 8 · 综合行动建议**：

```html
<section id="action">
  <h2>8. 综合行动建议</h2>

  <h3>核心心法</h3>
  <ol>
    <li>{{基于格局的根本建议}}</li>
    <li>{{基于用神的发力方向}}</li>
    <li>{{基于忌神的规避建议}}</li>
  </ol>

  <h3>具体动作</h3>
  <ul>
    <li>{{下一步具体可执行动作}}</li>
    <li>{{下一步具体可执行动作}}</li>
  </ul>

  <div class="disclaimer">
    <strong>记住</strong>：命理结构是镜子，照见的是你的潜力空间。你怎么选择、怎么行动，决定结构如何被表达。<br>
    任何健康议题请咨询医生 / 法律议题请咨询律师 / 心理困扰请咨询心理咨询师。
  </div>
</section>

<footer>
  <p>生成于 {{日期}} | by ming-li skill (Claude Code)</p>
</footer>
```

## 四、生成流程

### Step 1 · 数据准备

完成 `references/10-八字推演.md` 8 步推演 → 拿到所有数据。

### Step 2 · 心理学包装

对照 `references/05-心理学包装语言库.md`，把推演结果翻译成现代心理学语言。

### Step 3 · 伦理审查

对照 `references/04-伦理代码.md` 12 红线，确保无违规。

### Step 4 · 填充模板

按本文件 9 章模板填充。

### Step 5 · 输出

两种方式：
- **直接输出 HTML 字符串**（用户直接复制）
- **保存到 vault**：`Vault 50.个人/命理报告-{{姓名}}-{{日期}}.html`

### Step 6 · 用户预览

如果是示例命主，建议保存到 vault 后：
```bash
open "/path/to/report.html"
```
浏览器打开预览。

## 五、可视化简化方案（无 JS）

为了不依赖 JS 库，所有图表用**纯 CSS + SVG inline**：

- 五行雷达 → CSS `flex` + `height` 渐进
- 大运时间线 → CSS `flex` 横向
- 流年热力图 → CSS `grid` + 颜色 class
- 命盘 → SVG inline（紫微 12 宫圆形）

如果用户要更复杂可视化（如紫微圆形命盘），可以用 SVG 内嵌。

## 六、对照传统输出的优势

| 维度 | 传统命理报告 | ming-li HTML 报告 |
|---|---|---|
| **结构** | 散文式 | **模块化 9 章** |
| **可视化** | 仅命盘图 | **5 种图表（四柱+雷达+时间线+热力图+徽章）** |
| **语言** | 古文 / 半古 | **现代心理学语言** |
| **建议** | 抽象 | **行动化** |
| **伦理** | 模糊 | **顶部 + 底部 disclaimer** |
| **打印** | 不友好 | **A4 打印 ready** |
| **配色** | 红黄黑 | **清爽现代 + 五行配色** |

## 七、HTML 输出示例（最简版）

调用本模板时，AI 生成完整 HTML 字符串，保存为 `.html` 文件。

保存路径：`Vault 20.领域/命理学/命理报告-{{姓名}}-{{YYYY-MM-DD}}.html`

打开方式：`open <path>` 即可。

---

## 八、PNG 长图导出（v2.4 新增）

### 触发场景

用户说：
- "出 PNG / 出图 / 长图"
- "导出图片"
- "做成图发朋友圈 / 发群"
- "可不可以保存图片"

### 用法

```bash
python3 ~/.claude/skills/ming-li/scripts/html_to_png.py \
  --html "<HTML 绝对路径>" \
  --out  "/Users/lixiangrui/Desktop/命理报告-{{姓名}}-{{日期}}.png" \
  --width 820 \
  --height 16000
```

参数说明：
- `--width`：建议 820（与 HTML 容器 680 + 余量匹配）；想要更宽用 900
- `--height`：截图高度上限。脚本会用 Pillow **自适应裁底空白**，所以填大没关系（默认 18000）
- **PNG 默认保存在桌面**（`~/Desktop/命理报告-{{姓名}}-{{日期}}.png`），便于直接发图、收藏。HTML 留在 vault，PNG 上桌面。

### 实现原理

1. **Chrome headless 截图**（无桌面 GUI，背景跑）
2. **Pillow 检测底部主色，自动裁掉空白**
3. **保存为优化 PNG**（无损）

### 依赖

- Chrome / Chromium / Edge（任一即可）
- Python3 + Pillow

如缺 Pillow：
```bash
pip3 install Pillow --break-system-packages
```

### 实测尺寸参考（示例八字报告）

- width 820 → 实际高度 10488 px → 2.7 MB
- 适合朋友圈 / 微信群发图 / 保存收藏

### 双输出（HTML + PNG）

完整咨询流程默认两个都出，**分别落在不同位置**：

```
HTML → Vault 20.领域/命理学/命理报告-{{姓名}}-{{日期}}.html
PNG  → ~/Desktop/命理报告-{{姓名}}-{{日期}}.png
```

`.html` 留在 vault 给精读、打印、长期归档。
`.png` 落到桌面，方便随手发群、朋友圈、AirDrop 给别人。

## 八、版本演进

- **v1.0**（当前）：CSS-only，单 HTML 文件
- **v2.0**（计划）：内嵌 SVG 紫微命盘
- **v3.0**（计划）：交互式（hover 显示详情）
- **v4.0**（计划）：PDF 导出 + 在线分享链接
