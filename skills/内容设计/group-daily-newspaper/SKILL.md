---
name: group-daily-newspaper
description: 群日报·人民日报式 A3 报纸（印刷可用），版数可变（2/4/6 版，一般偶数）。AI 先分析当天聊天 + 群内图片，决定今天适合几版，再为每版独立设计 layout：页眉页脚固定一致（左上角"第 N 版"按实际页码动态生成），中间内容由 AI 按当天具体情况决策（图嵌哪、跨几栏、配什么字、压缩什么）。严格 A3（297×420mm = 1123×1587px @96dpi），每版精确等高、零空白、零硬塞、不千篇一律、一页一版（page-break-inside: avoid + height: 1587px overflow hidden）。触发：用户说"做报纸版日报"、"印刷版日报"、"纸质版群日报"、"群报"、"做 N 版报纸"。
---

# Group Daily · Newspaper · A3 报纸版 v2.0（可变版数）

把群日报做成可印刷的 A3 报纸——**AI 主动分析当天素材后决定版数 + 排版**，像人民日报一样每天版面都不一样。

## 核心原则（v2.0 升级，必读）

这个 skill 不是"用固定模板填字"，而是"AI 每次跑都重新决定版数 + 设计 layout"。四条铁律：

### 0. 版数按当天故事量自适应（v2.0 新增）

- **故事少 / 节点少 → 2 版**（头版 + 高光附录）
- **常规一天（4-5 节点）→ 4 版**（头版 + 共建 + 副刊 + 高光附录）
- **丰富一天（6-9 节点）→ 6 版**（头版 + 共建 + 副刊 + 群体即兴 + 深夜专栏 + 高光附录）
- **特殊事件爆款 → 8 版**（最多）

**判定依据**：story.json 里 `timeline` 节点数。每版承载 1-2 个节点的精华最合适。
偶数版数为佳（印刷对折友好）。

### 1. 固定层 vs 灵活层

| 层 | 内容 | 是否每天变 |
|---|---|---|
| **固定层** | 报头（第 1 版）/ 简版页眉（第 2 版起，左上角"第 N 版"按实际页码动态）/ 页脚 page-foot | ❌ 严格一致，不动 |
| **灵活层** | 版数 + 每版中间的所有内容 | ✅ AI 每天独立决策 |

页眉页脚是"报纸品牌一致性"——读者一眼认出是「群日报」品牌。中间内容是"今日新闻"——每天不一样才有看头。

### 2. AI 先决定版数再分析后排版（必跑 5 步流程）

**禁止直接跑 render_newspaper.py**。每次必须按以下 5 步：

```
Step 0 → 决定版数：根据 story.json timeline 节点数（2/4/6/8）
Step 1 → AI 分析：看图 + 看上下文 + 决策
Step 2 → AI 写规划：layout-plan.json（page1..pageN）
Step 3 → render 按规划生成 HTML
Step 4 → AI 自检高度，每版必须 = 1587 px（用 height: 1587px + overflow: hidden 强制）
Step 5 → chrome --print-to-pdf 输出 A3，验证 Pages 数 == 版数
```

### 3. 设计目标四条同时满足

- **A3 严格等高**：每版 = 1587 px 精确（用 `height: 1587px; overflow: hidden;` 强制，不用 min-height）
- **一页一版**：PDF Pages 数必须 = 版数；超过说明内容溢出被拆页，回去删内容
- **零空白**：每版没有 > 50 px 的连续空白带
- **不千篇一律**：每版独立 layout，page_header 左上角"第 N 版"按 page_key 动态生成

任何一条不满足都不能交付。

## 工作流（必跑，按顺序）

### Step 0：前置依赖

```bash
ls /tmp/story_<日期>_<群名>.json    # group-daily skill 产出的 story.json
ls /tmp/avatars.json                # 头像 base64 映射
```

如果没有，先调 `group-daily` skill 生成。

### Step 1：导出群里图片

```bash
mkdir -p /tmp/<群名>_images/
vchat files "<群名>" -k image --export -o /tmp/<群名>_images/
```

vchat 会导出全部图，文件名格式 `YYYYMMDD_HHMMSS_<hash>.{png,jpg}` 自带时间戳。

### Step 2：AI 分析阶段（关键，不可跳过）

AI 必须做以下分析后，才能进入排版：

#### 2.1 浏览候选图

```bash
ls /tmp/<群名>_images/ | grep "^<YYYYMMDD>" | head -20
```

按时间戳筛选当天的图。对每张图 AI 用 Read 工具看一眼，判断：

| 图类型 | 处理建议 |
|---|---|
| **截屏对话** | 作为"现场直击"配 hero 主稿 |
| **海报/作品/教程** | 作为"今日产出物"区配图 |
| **人物 profile / 名片** | 作为"本版关键人物"配 hero |
| **二维码** | 作为"明日预告"实物证据 |
| **博物馆/旅行/生活照** | 作为"副刊"装饰图 |
| **表情包/小图标** | 跳过，不用 |
| **加载/空屏/无信息** | 跳过 |

**禁止**：把不匹配主题的图硬塞——「图文协调」比「填满」重要。

#### 2.2 为每张候选图找对应主题

```bash
grep -A 3 -B 3 "<图发送时间附近 ±10 分钟>" /tmp/chat_log_xxx.txt
```

读图的上下文消息，判断这张图对应 timeline 哪个故事节点 / 哪个版的主题。

#### 2.3 必跑 image probe（v2.2 新增）— 让 layout 按图本身比例排，不再硬塞

```bash
python3 ~/.claude/skills/group-daily-newspaper/scripts/image_probe.py \
   /tmp/<群名>_images/ --date YYYYMMDD --min-kb 20 > /tmp/image_probe.json
```

输出每张图的：
- `width / height / aspect / shape` (landscape/portrait/square)
- `kb`（过滤掉 <30KB 的极小图/表情）
- `suggested_layout.role` → `hero-figure / banner-image / person-card / qr / inline-narrow / decoration`
- `suggested_layout.max_width_px / display_height_px`（按 A3 1090 px 内容宽算好的）

**AI 必须按 probe 输出决策**——选哪张图、放哪个版、用多大显示尺寸。**禁止套用「banner 全 280px / hero 全 360px」这种硬模板**。

#### 2.4 整理候选图清单

为每张可用图记录：

```
图 1：/tmp/.../20260511_213357_xxx.png
  probe: 1920x1080 landscape, 824KB → role=banner-image, display 1090×614
  类型（AI 读完图判断）：终端截图（Claude 解密微信现场）
  上下文（grep ±10 分钟）：21:33 祥瑞「claude解密微信聊天记录成功了」
  匹配主题：第 1 版头条「微信解密 CLI 诞生之夜」
  建议位置：page1 aside.figure 主稿配图
  layout-plan 写法：
    "image": "file:///tmp/.../xxx.png",
    "img_style": "width:480px;height:270px;object-fit:cover;"
```

**figure/banner_image/person_card 都支持 img_style 字段**（v2.2），直接写 inline CSS 覆盖 CSS 默认值。这样实现"按图比例自由排"而不是"套模板"。

### Step 3：AI 写版面规划 layout-plan.json

**先决定版数**（看 story.json timeline 节点数）：

| story.json timeline 节点数 | 推荐版数 | 版面分配 |
|---|---|---|
| 2-3 节点 | **2 版** | page1（头版）+ page2（cast 模板：高光+SOP+附录） |
| 4-5 节点 | **4 版** | page1 + page2 共建 + page3 副刊 + page4 cast |
| 6-9 节点 | **6 版** | page1 + page2 共建 + page3 副刊 + page4 群体即兴 + page5 深夜专栏 + page6 cast |
| 10+ 节点 | **8 版**（极少） | 4-5 个深度版 + 1 个 cast 收尾 |

**plan 字段约定**：每个 `pageN` 必须声明 `template`（控制 renderer），可选值：

- `masthead`：头版（render_page_1）—— hero + aside figure + briefings + photo_strip + day_stats
- `communal`：共建/产出物版（render_page_2）—— person_card + hero + produced_list + timeline_strip + quote_wall
- `feature`：副刊/深度版（render_page_3）—— banner_image + hero + timeline_strip + letters + lingo
- `cast`：人物高光附录版（render_page_4）—— 8 高光 + SOP + QA + tomorrow + QR

**默认推断**（不写 template 字段时）：
- page1 → masthead
- page2/5/7 → communal
- page3/6 → feature
- page4/8 → cast

```json
{
  "masthead": { ... 报头共用元素 ... },
  "page1": {"template": "masthead", "hero": {...}, "aside": {...}, ...},
  "page2": {"template": "communal", "hero": {...}, "produced_list": [...], ...},
  "page3": {"template": "feature", "banner_image": {...}, "hero": {...}, ...},
  "page4": {"template": "feature", ...},
  "page5": {"template": "feature", ...},
  "page6": {"template": "cast", "tomorrow": {...}, ...}
}
```

**每版 layout 必须独立设计**——template 复用没问题但里面具体 figure 不能一样。

**page-banner-title 主+副标规则（v2.1 新增）**：

- 主标：`.page-banner-title` 默认 **46px**，大字气派
- 副标：用 `<span class="pbt-deck">` 包裹，**autosize_banner_title** 函数按字数自动注入字号：
  - ≤ 16 字 → 42px（接近主标，最大气）
  - 17-22 字 → 36px（仍大字单行）
  - 23-28 字 → 30px
  - 29-36 字 → 26px
  - 37+ 字 → 22px（最小但仍可读）
- 副标多段语义用 ` / ` 分隔（左右带空格）。CSS 已设 `word-break: keep-all`——wrap 会在空格处断，每段是完整词，**永远不会出现单字结尾行**。
- 写作约束：副标用 14-22 字最佳，能保证 42-36px 大字单行；超 28 字会被压到 30px 以下。

例：
```html
<!-- 14 字 → 42px 单行 -->
"theme_title_html": "今日主题<span class=\"pbt-deck\">上午话题 A / 晚上话题 B</span>"

<!-- 16 字 → 36px 单行（已经够大） -->
"theme_title_html": "今日热词<span class=\"pbt-deck\">主线一句 / 副线一句</span>"
```

详细 schema 见 `references/newspaper-schema.md`，模板库见 `references/layout-templates.md`。

### Step 4：渲染 + 强制 1587 + 自检

**v2.0 数据驱动**：render 接受 4 个参数，layout-plan.json 是 Step 3 写好的版面编排。

```bash
python3 ~/.claude/skills/group-daily-newspaper/scripts/render_newspaper.py \
  /tmp/story_<日期>_<群名>.json \
  /tmp/avatars.json \
  /tmp/layout-plan-<日期>-<群名>.json \
  ~/Desktop/<群名>日报_<日期>_报纸版.html
```

**Plan 起点**：
- 复制 `examples/layout-plan-template.json` 改名 `layout-plan-<日期>-<群名>.json`
- 字段说明见 `references/newspaper-schema.md`
- 完整参考样例（4 版）：`examples/layout-plan-template.json`（脱敏空白模板，复制改字段）

**必须强制 height: 1587px + overflow: hidden 防止内容溢出被 chrome 分页**：

```bash
# render 出 HTML 后，把 min-height 改成 height + overflow:hidden 强制定高
python3 -c "
p='~/Desktop/<群名>日报_<日期>_报纸版.html'
import os; p=os.path.expanduser(p)
s=open(p).read()
s=s.replace('min-height: 1587px;', 'height: 1587px; overflow: hidden;')
open(p,'w').write(s)
"

# 注入测量脚本（同时测每版高度 + 左上角版数）
cat >> ~/Desktop/<群名>日报_<日期>_报纸版.html <<'EOF'
<script>
window.addEventListener('load', () => {
  setTimeout(() => {
    const h = [...document.querySelectorAll('.page')].map(p => Math.round(p.scrollHeight));
    const n = [...document.querySelectorAll('.ph-num')].map(e => e.textContent);
    document.title = 'H:' + h.join(',') + ' N:' + n.join('|');
  }, 1500);
});
</script>
EOF
```

**自检三条**：
1. **scrollHeight ≤ 1592**（=1587+5）：超过说明强制截断，回 Step 3 砍内容
2. **左上角 ph-num** 必须依次显示「第 2 版」「第 3 版」...「第 N 版」（page1 没 ph-num，从 page2 起）
3. **chrome --print-to-pdf 后 Pages == 版数**（PDF 多页 = 内容溢出 = 失败）

### Step 5：PDF 输出

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --headless=new --disable-gpu --no-sandbox \
  --user-data-dir=/tmp/chrome-pdf-$(date +%s) \
  --virtual-time-budget=20000 --hide-scrollbars \
  --no-pdf-header-footer \
  --print-to-pdf=~/Desktop/<群名>日报_<日期>_报纸版.pdf \
  file://~/Desktop/<群名>日报_<日期>_报纸版.html

mdls -name kMDItemPageWidth -name kMDItemPageHeight ~/Desktop/*.pdf
# 必须看到 PageWidth=841.92 PageHeight=1191.12（A3 标准）
```

## 反例（这些做法直接被拒）

| 反例 | 为什么错 |
|---|---|
| 直接跑 render 不分析图 | 违反"先分析后排版"原则 |
| 不论故事多少都做 4 版 | v2.0 要求按故事量自适应 2/4/6/8 版 |
| 用 min-height: 1587px（默认 CSS） | chrome 分页阈值跟 A3 高度对不齐，超 4 px 就拆页。必须强制 height + overflow hidden |
| 加图后超 1587 不调整 | 破坏一页一版 |
| page-banner-title 副标用主标题字号 | 副标题字号 42px + letter-spacing 6px 会撑成 3 行。必须用 `<span class="pbt-deck">` 24px |
| page5/page6 不声明 template | render 会按默认推断，可能选错模板 |
| 图说编造数据/原话 | 违反 group-daily 红线 |
| 把跟主题不匹配的图硬塞 | "硬塞"是明令禁止的 |
| 历史 styles 标签（含藏量 100% / 藏师傅）当天没人说 | 违反 group-daily 红线 |

## Bundled Resources

### scripts/

| 脚本 | 作用 |
|---|---|
| `render_newspaper.py` | 把 story.json + layout-plan + 图 → 4 版 A3 HTML |

### references/

| 文件 | 作用 |
|---|---|
| `newspaper-design.md` | A3 设计硬约束（颜色/字号/线条/版面骨架） |
| `newspaper-schema.md` | story.json + layout-plan.json 字段定义 |
| `layout-templates.md` | layout 模板库——AI 选用的所有 figure 位置类型 |

### examples/

| 文件 | 作用 |
|---|---|
| `layout-plan-template.json` | **空白模板** · 跑新群时复制此文件改字段（含 4 版 + 全部字段定义） |
| `layout-plan-template.json` | **空白模板** · 跑新群时复制此文件改字段 |

## 为新群跑日报（v2.0 工作流摘要）

```bash
# 1) group-daily skill 先产出 story.json + avatars.json
# 2) 看 story.json timeline 节点数决定版数（2/4/6/8）
# 3) 复制 plan 模板，按版数加 pageN
cp ~/.claude/skills/group-daily-newspaper/examples/layout-plan-template.json \
   /tmp/layout-plan-<日期>-<群名>.json
# 每个 pageN 加 "template": "masthead/communal/feature/cast"

# 4) AI 按 Step 1-3 流程填 layout-plan.json
#    每版分配 1-2 个 timeline 节点，page-banner-title 副标用 <span class="pbt-deck">

# 5) 渲染 → 强制 height: 1587px overflow:hidden → 注入测量脚本
python3 ~/.claude/skills/group-daily-newspaper/scripts/render_newspaper.py \
  /tmp/story_<日期>_<群名>.json /tmp/avatars.json \
  /tmp/layout-plan-<日期>-<群名>.json \
  ~/Desktop/<群名>日报_<日期>_报纸版.html
# sed -i '' 's/min-height: 1587px;/height: 1587px; overflow: hidden;/' <html>

# 6) PDF 输出（chrome --print-to-pdf A3 portrait），验 Pages == 版数
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --headless=new --disable-gpu --no-sandbox \
  --user-data-dir=/tmp/cpdf-$(date +%s) --virtual-time-budget=20000 \
  --hide-scrollbars --no-pdf-header-footer \
  --print-to-pdf=~/Desktop/<群名>日报_<日期>_报纸版.pdf \
  file://~/Desktop/<群名>日报_<日期>_报纸版.html

pdfinfo ~/Desktop/*.pdf | grep -E "Title|Pages|Page size"
# 必须看到：H:1587,1587,... N:第 2 版|第 3 版|...  Pages: N（== 版数）  A3
```

## 失败模式

| 现象 | 根因 | 修法 |
|---|---|---|
| PDF Pages 数 > 版数 | 某版 scrollHeight > 1587 被 chrome 分页 | 删图说字数 / 缩 padding / 减 timeline 行；用 height: 1587 + overflow:hidden 兜底 |
| 某版被截掉一截内容 | 内容总和远超 1587，overflow hidden 截了 | 真减内容，不要硬塞 |
| 左上角"第 N 版"显示成"第 2 版"重复 | render_page_2/3/4 没传 page_key | 检查 render_newspaper.py renderer 调用是否传了 page_key 参数 |
| 副标题"评"字单独成行 | 没用 pbt-deck class，被主标题 42px 字号撑爆 | 副标改成 `<span class="pbt-deck">...</span>` |
| 4 版风格一样 | 复用同一 figure 类 | 每版强制选不同 layout 模板 |
| PDF 不是 A3 | @page size 失效 | 用 fresh chrome user-data-dir |
| 图说编造内容 | 没看上下文就写 | 回 Step 2，grep 图发送时间 ±10 分钟原话 |
