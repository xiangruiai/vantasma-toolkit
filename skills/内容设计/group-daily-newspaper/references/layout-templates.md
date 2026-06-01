# Layout 模板库

AI 在 Step 3 写 layout-plan.json 时，从这里选模板。

**核心原则**：每版必选不同模板，禁止 4 版用同一种。

## 一、固定层（不可改，4 版强制一致）

### F-1: 报头（第 1 版）

```html
<header class="masthead-row">
  <div class="mh-left">
    <h1 class="mh-name">{群名}日报</h1>
    <div class="mh-pinyin">PINYIN · DAILY</div>
    <div class="mh-tag">{推广链接}</div>
  </div>
  <div class="mh-box">
    <!-- 日期方框 -->
  </div>
  <div class="mh-right">
    <div class="mh-kicker">头版头条 · ...</div>
    <h2 class="mh-headline">{lead_title}</h2>
    <p class="mh-lead">{opening}</p>
  </div>
</header>
```

### F-2: 简版页眉（第 2-4 版）

```html
<header class="page-header">
  <div class="ph-left">第 N 版 · {主题}</div>
  <div class="ph-mid">{群名} 日报 · DAILY</div>
  <div class="ph-right">{日期} · VOL.</div>
</header>
```

### F-3: 页脚

```html
<footer class="page-foot">第 N 版 / 共 4 版 · {版名}</footer>
```

## 二、灵活层模板（每版独立选）

### L-1: hero-full（通栏 HERO 主稿）

适用：第 2、3 版主题深度报道。

```html
<article class="hero hero-full">
  <eyebrow / title / meta / cast />
  <div class="hero-body four-col">{合并 timeline 文字}</div>
  <quotes-box />
  <produced />
</article>
```

**不带图**。如果带图，换 L-2 或 L-3。

### L-2: hero-with-image-right（HERO 内嵌右图）

适用：当一张图直接对应该版头条主题（如人物 profile / 设备截图）。

```html
<article class="hero">
  <eyebrow / title / meta / cast />
  <div class="hero-with-image-grid">
    <div class="hwi-text">
      <div class="hero-body three-col">{文字}</div>
      <quotes-box />
    </div>
    <figure class="hwi-image">
      <img />
      <figcaption>{现场直击图说}</figcaption>
    </figure>
  </div>
  <produced />
</article>
```

**关键**：图占 1/4 宽度，文字 column-count 从 4 改 3 补齐宽度。

### L-3: hero-with-aside（HERO + 边栏）

第 1 版专用。HERO 跨 8 栏，aside 跨 4 栏。aside 内：briefings + editor-note + side-quote。

不放图。

### L-4: sub-grid-pair（2 副稿并排）

适用：第 2、3 版的 HERO 下方副稿区。

```html
<div class="grid-12 sub-grid">
  <div class="col-span-6">{副稿 1}</div>
  <div class="col-span-6">{副稿 2}</div>
</div>
```

### L-5: sub-grid-with-image（副稿 + 内嵌图）

L-4 的变体——其中一个副稿内右侧嵌入图（不另起 section）。

```html
<article class="sec-story sec-with-image">
  <sec-meta / sec-title />
  <div class="sec-image-grid">
    <p class="sec-body">{文字}</p>
    <figure class="sec-inline-image">
      <img />
      <figcaption>{短图说}</figcaption>
    </figure>
  </div>
  <quotes-box small />
</article>
```

### L-6: photo-strip-horizontal（横通栏头像合影）

适用：第 1 版 hero-row 下方放 8 高光人物头像。

```html
<section class="photo-strip">
  <div class="ps-banner">今日合影 · ...</div>
  <div class="ps-grid">
    <!-- 8 个 .ps-item，每个：头像 + 名字 + tag -->
  </div>
  <div class="ps-caption">{图说}</div>
</section>
```

### L-7: day-stats-strip（横通栏数字条）

适用：第 1 版底部放当天 6-8 个真实数据。

```html
<section class="day-stats">
  <div class="ds-banner">今日数字 · BY THE NUMBERS</div>
  <div class="ds-grid">
    <!-- 6-8 个 .ds-item，每个 .n 大字 + .l 标签 -->
  </div>
</section>
```

### L-8: quote-wall-grid（横通栏主理人语录）

适用：第 2、3 版底部放 4 句主理人当天原话。

```html
<section class="quote-wall">
  <div class="qw-banner">{主理人}当日语录 · ...</div>
  <div class="qw-grid">
    <!-- 4 个 .qw-item，每个 .t 原话 + cite 时间/场景 -->
  </div>
</section>
```

### L-9: produced-list（横通栏产出物）

适用：第 2 版的"今日产出物清单"。

```html
<section class="produced-list">
  <div class="pl-banner">今日产出物</div>
  <div class="grid-12 pl-grid">
    <!-- 3-4 个 .pl-item，每个编号 + 标题 + 简介 -->
  </div>
</section>
```

### L-10: letters-grid（横通栏读者来信）

适用：第 3 版放 3-4 条群友催更原话。

```html
<section class="letters">
  <div class="lt-banner">听友催更 · LETTERS</div>
  <div class="grid-12 lt-grid">
    <!-- 3 个 .lt-item，每个引语 + 来信人 + 时间 -->
  </div>
</section>
```

### L-11: lingo-grid（横通栏黑话词典）

适用：第 3 版放当天 6 个真实出现的群内词。

```html
<section class="lingo">
  <div class="lg-banner">今日黑话 · TODAY'S LINGO</div>
  <div class="lg-grid">
    <!-- 6 个 .lg-item，每个 .w 词 + .d 上下文解释 -->
  </div>
</section>
```

### L-12: highlights-portraits（8 高光人物 4×2）

适用：第 4 版主体。

```html
<section class="hl-grid">
  <!-- 8 个 .hl，每个头像 + 名字 + tag + desc -->
</section>
```

### L-13: appendix-grid（SOP + Q&A 并排）

适用：第 4 版。

```html
<div class="appendix-bar">附录 · APPENDIX</div>
<div class="grid-12 appendix-grid">
  <div class="col-span-6"><h3>可抄作业 · SOP</h3>{sop 列表}</div>
  <div class="col-span-6"><h3>群友答疑 · Q&A</h3>{qa 列表}</div>
</div>
```

### L-14: tomorrow-with-qr（明日预告 + 二维码）

适用：第 4 版底部。tomorrow 第二项替换为图（如群面基二维码）。

```html
<section class="tomorrow">
  <div class="tm-banner">下回分解 · COMING TOMORROW</div>
  <div class="grid-12 tm-grid">
    <div class="col-span-6 tm-item">{文字预告 1}</div>
    <div class="col-span-6 tm-item-qr">
      <img class="tm-qr" />
      <div class="tm-qr-cap">{二维码说明}</div>
    </div>
  </div>
</section>
```

### L-15: colophon（报尾，第 4 版底）

```html
<footer class="colophon">
  <div class="colophon-stats">5 数据</div>
  <div class="colophon-quote">{footer_quote}</div>
  <div class="colophon-meta">3 段元信息</div>
</footer>
```

## 三、4 版搭配建议（避免千篇一律）

每个版面应该从 L-1 ~ L-14 选 **3-5 个不同模板** 组合，且 4 版组合不同。

### 第 1 版搭配示例（如果有 1 张匹配的截屏图）

- L-3 hero-with-aside（HERO + 边栏 briefings/editor-note）
- L-2 hero-with-image-right（HERO 内嵌右图）—— 选用其中一个，不并存
- L-6 photo-strip-horizontal
- L-7 day-stats-strip

### 第 2 版搭配示例（如果有 1 张人物 profile 图）

- L-2 hero-with-image-right（HERO 主稿带 profile 图）
- L-4 sub-grid-pair（2 副稿不带图）
- L-9 produced-list
- L-8 quote-wall-grid

### 第 3 版搭配示例（如果有 1 张装饰图）

- L-1 hero-full（HERO 不带图）
- L-5 sub-grid-with-image（副稿其中一个内嵌图）
- L-10 letters-grid
- L-11 lingo-grid

### 第 4 版搭配示例（如果有 1 张二维码 / 现场图）

- L-12 highlights-portraits
- L-13 appendix-grid
- L-14 tomorrow-with-qr（带二维码图）
- L-15 colophon

## 四、CSS Class 全清单

实际 CSS 已在 `scripts/render_newspaper.py` 中定义。下面是 class 名清单，AI 写 HTML 时直接用：

| Class | 用途 |
|---|---|
| `.masthead-row` | 第 1 版三栏报头 |
| `.page-header` | 第 2-4 版页眉 |
| `.page-foot` | 4 版页脚（margin-top:auto 强制贴底） |
| `.headline` | 大字 lead title 区 |
| `.hero` / `.hero-full` | HERO 主稿 |
| `.hero-with-image-grid` | L-2 HERO 内右栏图 layout（新增） |
| `.sub-grid` / `.sec-story` | 副稿区 / 单个副稿 |
| `.sec-with-image` | L-5 副稿带图（新增） |
| `.photo-strip` | L-6 横通栏头像合影 |
| `.day-stats` | L-7 数据条 |
| `.quote-wall` | L-8 语录墙 |
| `.produced-list` | L-9 产出物 |
| `.letters` | L-10 来信 |
| `.lingo` | L-11 黑话 |
| `.hl-grid` | L-12 高光 |
| `.appendix-grid` | L-13 SOP+QA |
| `.tomorrow` | L-14 明日预告 |
| `.colophon` | L-15 报尾 |

## 五、高度预算表

每个模板的近似高度（px @ A3 96dpi）。AI 写 plan 时用来核算 1587。

| Layout | 近似高度 |
|---|---|
| L-1 hero-full | 600-700 |
| L-2 hero-with-image-right | 650-750 |
| L-3 hero-with-aside | 700-900（含 aside） |
| L-4 sub-grid-pair | 350-450 |
| L-5 sub-grid-with-image | 400-500 |
| L-6 photo-strip-horizontal | 180-220 |
| L-7 day-stats-strip | 120-150 |
| L-8 quote-wall-grid | 130-180 |
| L-9 produced-list | 140-180 |
| L-10 letters-grid | 130-170 |
| L-11 lingo-grid | 180-230 |
| L-12 highlights-portraits | 450-550 |
| L-13 appendix-grid | 350-450 |
| L-14 tomorrow-with-qr | 200-280 |
| L-15 colophon | 200-250 |
| 报头 masthead-row | 230-280 |
| 简版页眉 page-header | 35-45 |
| 页脚 page-foot | 30-40 |

AI 写 plan 时挑模板组合，总和 = 1587 ± 30。**超 30 必删模板或缩内容，不足 50 必加模板或加图填充**。
