# 报纸版设计硬约束

来自早期实测 17 轮迭代踩坑记录。每条都是被用户当面 reject 过的反例修正成的硬规则。

## 1. 版面骨架

### 1.1 4 版严格等高（打印硬约束）

**每版必须严格 1400px**。打印 4 张报纸尺寸要一致，否则装订/折页乱套。

- `.page { min-height: 1400px }` 兜底
- 实测高度差 ≤ 5px 接受，> 10px 必须修

### 1.2 单版尺寸

- 宽：1200px
- 高：1400px
- padding：上下 16/20px，左右 24px
- 比例接近 A3 竖版（297×420mm 等比缩到 1200×1697）

### 1.3 page-foot 必须 margin-top: auto

否则页脚不贴底，每版位置不一致：

```css
.page-foot {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid #000;
}
```

## 2. 颜色

| 颜色 | 用途 | HEX |
|---|---|---|
| 底色 | 整张报纸背景 | `#fdfcf8`（接近白，略带米色暖意） |
| 主文字 | 正文 / 标题 | `#000` 或 `#222` |
| 报名红 | 第 1 版"<群名>日报"大字 + PRODUCED 边框 + 首字下沉 drop cap | `#c41e1e` 或 `#a02020` |
| 章节色（次要） | 部分 banner 色块 | 深蓝 `#1f2d4a` |
| 灰字 | 副信息 / cite / 注释 | `#555` |

**反例**：
- 米黄旧报纸底（#efe5c5）—— 不像现代日报，被 reject
- 加纸纹噪点 SVG / 折页痕迹 / 角落水印 —— 视觉太花，被 reject
- 多种装饰红（朱砂、暗红、玫红混用）—— 颜色不统一，被 reject

## 3. 字体

### 3.1 字体栈

```
报名（第 1 版巨字）：Noto Serif SC 900, Songti SC, STSong
标题（HERO / banner）：Noto Sans SC, PingFang SC, Heiti SC, Songti SC
正文：Noto Serif SC, Songti SC, STSong
英文 / 数字：Playfair Display, Old Standard TT
```

**反例**：
- 用 Ma Shan Zheng 楷书/手写体当报名 —— 不严肃，被 reject
- 报头巨字用 PingFang 现代黑体 —— 太"现代设计师"，被 reject

### 3.2 字号金字塔（严格）

| 位置 | 字号 | 备注 |
|---|---|---|
| 报名"<群名>日报" | 88px | 红色，第 1 版独有 |
| 头版头条 lead_title | ~32px | 跨多行 |
| 各版主题大标题 | 44px | 第 2-4 版顶部 banner |
| HERO 大稿标题 | 30px | HERO 主稿 |
| HERO deck（副题） | 18px | 斜体灰字 |
| 副稿标题 | 22px | sec-title |
| 各种 banner 标题 | 13-16px | 章节色块上的字 |
| 正文 | 11px | line-height 1.65-1.75 |
| 注释 / cite | 9.5-10.5px | 灰字 letter-spacing 1.5px |

**反例**：
- 字号扁平（标题 18 / 正文 13）—— 没层次感，被 reject
- 标题超大（lead_title 72px）—— 挤掉其他内容，被 reject

## 4. 线条

### 4.1 用线极简原则

总线条数 ≤ 30 条全报纸。多了"乱"。

| 线类型 | 允许位置 | 禁用位置 |
|---|---|---|
| **8px 粗黑实线** | 第 1 版报头顶部 | 其他全部 |
| **2px 实线** | 各章节大标题上下 / colophon 顶 | 一般段落 |
| **1px 实线** | 副稿之间 / 高光人物分隔 / 主要 banner 边 | — |
| **double 双线** | **禁用全部** | — |
| **dashed 虚线** | **禁用全部** | — |
| **3px+ 实线（非顶部）** | 禁用 | — |

**反例（17 轮迭代踩过的）**：
- 4px double 双线用了 10+ 处 —— 视觉过载，被 reject
- 1px dashed 段内分隔用了 7 处 —— 太花，被 reject

### 4.2 替代分隔方法

线删了之后，用以下方式做"视觉断点"：

1. **字号差**（标题 30px → 正文 11px 落差）
2. **字体差**（黑体标题 vs 宋体正文）
3. **颜色块**（深色 banner 黑底白字 / 朱砂底白字）
4. **留白**（段间 padding 14px）

**禁用替代**：装饰花纹 ◆ ◇ ✦ ❖ — 真人民日报零花纹，加了像微信公众号

## 5. 头版报头结构

人民日报式三栏 grid：

```
┌──────────┬─────────┬────────────────────┐
│  左报名  │ 中报眼  │ 右大字头条          │
│          │  方框   │ + 3-4 栏导语正文   │
└──────────┴─────────┴────────────────────┘
```

具体：

- **左**：80pt 红字报名 + 拼音 13px + slogan + KA21 链接（贴底）
- **中**：1px 黑框方框，内含 `2026 年 05 月 / 大字 15 / 周五 / 丙午年 / 出版方 / 刊号 / 代号 / 期号 / 今日 N 版` 等 10 行小字。**关键：方框 `align-self: start`，不被 grid stretch 拉伸**
- **右**：kicker 11px + 大字头条 32px + opening 走 4 栏 10.5px 多栏分栏

**反例**：
- 报头占整行通栏（巨字"<群名>日报"+ 报眼横排 + slogan 横排）—— 不像真日报，被 reject
- 中间方框被 grid stretch 拉到 200px 高，下面留空白 —— 被 reject

## 6. HERO 主稿结构

```
hero-eyebrow（10px 朱砂红 letter-spacing 5px）
hero-title（30px 黑体）+ deck（18px 斜体灰）
hero-meta（time + badge）
hero-cast（chip 头像 + 名字）
hero-body（4 栏 column-count）
quotes-box（朱砂红左竖线 + 引语列表）  ← flex:1 撑开剩余空间
produced（朱砂红上下边线 + 产出物 summary）
```

**关键 flex 规则**（让 quotes-box 自动撑开填空白）：

```css
.hero-row .hero {
  display: flex;
  flex-direction: column;
}
.hero-row .hero .quotes-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-around;
}
```

## 7. 副稿 sec-story 结构

类似 HERO 但更紧凑，单稿件占 6 栏（半幅）：

```css
.sec-story {
  display: flex;
  flex-direction: column;
}
.sec-story .quotes-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-around;
}
.sec-story .produced.small {
  margin-top: auto;
}
```

这套 flex 规则**专门用来吃 grid stretch 拉伸出来的空白**。grid 子项会被 stretch 到等高，但内部 block 流式不自动撑开。flex column + flex:1 让中间元素填满空白。

## 8. 每版底部"填空"专栏（关键）

每版总高 1400px。HERO + 副稿 + page-header 大约占 800-1100px，余下 300-600px 必须用以下专栏填，且**素材必须真实**：

### 8.1 第 1 版底部专栏

- **photo-strip 今日合影**（200-220px）：8 个高光人物头像 + 名字 + tag
- **day-stats 今日数字**（120-140px）：6-8 个真实数据，黑底白字 banner + grid

### 8.2 第 2 版底部专栏

- **produced-list 今日产出**（160-180px）：3 个编号产出物（深蓝色块 banner）
- **quote-wall 主理人当日语录**（180-200px）：4 句原话引语 + 时间/场景标签（深蓝 banner）

### 8.3 第 3 版底部专栏

- **letters 听友催更**（140-160px）：3 条群友催更原话 + 来信人 + 时间（朱砂红 banner）
- **lingo 今日黑话**（180-220px）：6 个当天聊天里**真实出现**的群内词（朱砂红 banner）

### 8.4 第 4 版底部专栏

- **appendix-bar + appendix-grid**（SOP 左 + Q&A 右，黑底 banner 横通栏）
- **tomorrow 下回分解**（150-180px）：2 条明日真实事件（深蓝 banner）
- **colophon 报尾**（数据 + 名言 + 三段 meta）

## 9. 空白处理（高度对齐 + 信息密度兼容）

用户最反复强调的两条相互矛盾的诉求：

1. 每版高度必须一致（打印需要）
2. 不要有空白

两者矛盾时，**用 flex:1 撑开中间内容** + **加专栏填底部** 同时解决。

详细处理流程：

1. 先测当前 4 版高度：用注入测量脚本（见 SKILL.md Step 5）
2. 找出最高的那版，作为基准（一般 1400px）
3. 比基准低的版面，往下加专栏内容（数字/语录/黑话/催更等）
4. 比基准高的版面，按以下顺序精简：
   - quote-wall / lingo padding 收紧
   - banner padding 减半
   - 字号 -0.5px
   - 实在不行删一条素材
5. 最后用 page-foot { margin-top: auto } 让页脚都贴底，统一视觉

## 10. 朱砂红 / PRODUCED 使用规则

朱砂红是稀缺资源，只在以下位置用：

1. 报名"<群名>日报"
2. 段落首字下沉 drop cap（::first-letter）
3. PRODUCED 上下边线（2px 实线）
4. 引语 box 左侧竖线（3px 实线）
5. hero-eyebrow 小字
6. story-no（01-09 编号大字）
7. cast-name / 副稿 cite 时间标签

**禁用位置**：banner 大色块（用深蓝或纯黑替代）、装饰花纹、段落正文、digest 表格

## 11. 验收清单

每次出报纸前必须 100% 满足：

- [ ] 4 版高度差 ≤ 5px
- [ ] page-foot 每版位置一致（都贴底）
- [ ] 没有 double 双线
- [ ] 没有 dashed 虚线
- [ ] 没有装饰花纹（◆◇✦❖）
- [ ] 所有数字 / 引语 / 黑话都能在 story.json 或聊天记录里找到出处
- [ ] 没有"含藏量 100%"类历史 styles 文件里的固化标签
- [ ] 头像 100% 加载（不允许首字 placeholder）
- [ ] 每版底部没有大块空白（> 80px）
