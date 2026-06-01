# Newspaper Schema · v1.2

## 两份 JSON 输入

| 文件 | 来源 | 角色 |
|---|---|---|
| `story.json` | group-daily skill 产出 | 当天事实数据（timeline / highlights / sops / qas / stats / footer_quote） |
| `layout-plan.json` | 本 skill AI 在 Step 3 写 | 版面编排（masthead / 4 版每版的 banner / 图说 / 专栏内容） |

**职责分离**：story.json = "发生了什么"，layout-plan.json = "怎么排版面"。同一份 story 可以配多种 plan 试错。

## render 调用

```bash
python3 scripts/render_newspaper.py \
  /tmp/story_<日期>_<群名>.json \
  /tmp/avatars.json \
  /tmp/layout-plan-<日期>-<群名>.json \
  ~/Desktop/<群名>日报_<日期>_报纸版.html
```

## layout-plan.json 顶层结构

```
{
  "masthead": {...},     # 报头 · 4 版固定一致
  "page1": {...},        # 第 1 版 · 头版
  "page2": {...},        # 第 2 版 · 共建/主题
  "page3": {...},        # 第 3 版 · 副刊
  "page4": {...}         # 第 4 版 · 人物 + 附录
}
```

## masthead 字段

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `name_top` | str | "<群名>" | 报名第 1 行（中文） |
| `name_bot` | str | "日报" | 报名第 2 行 |
| `pinyin` | str | "DENGXIABAI · DAILY" | 拼音/英文 |
| `slogan_en` | str | "A NEWSPAPER FOR ONE WECHAT GROUP" | 英文 slogan |
| `slogan_cn_html` | str(html) | "群 魂 · 共 建 · 共 学&lt;br&gt;灯 下 白 群 当 日 实 录" | 中文 slogan，可含 `<br>` |
| `promo_tag` | str | "KA21 工具导航 · ka21.org/zh/tutorials" | 推广链接 |
| `lunar` | str | "丙午年三月三十" | 农历 |
| `publisher` | str | "<群名>群出版" | 出版方 |
| `cn_no` | str | "CN 11-0515" | 仿 CN 号（按日期编） |
| `issue_code` | str | "代号 1-1" | 仿邮政代号 |
| `issue_no` | str | "第 0515 期" | 期号 |
| `total_pages` | str | "今日 4 版" | 版数 |
| `footer_brand` | str | "灯 下 白 日 报 · DENGXIABAI DAILY" | 简版页眉中部品牌 |

## page1（头版）字段

| 路径 | 类型 | 说明 |
|---|---|---|
| `name` | str | 简版页眉左侧（如 "头 版 要 闻"） |
| `foot` | str | 页脚（"第 1 版 / 共 4 版 · ..."） |
| `lead_kicker` | str | 报头右侧 kicker 小标题 |
| `hero.eyebrow` | str | 朱砂红小字 "EXCLUSIVE REPORT" |
| `hero.title_html` | html | 主标题（可含 `<br>` + `<span class="deck">副标题</span>`） |
| `hero.time` | str | 时间区间 |
| `hero.badge` | str | badge 标签 |
| `hero.timeline_indices` | int[] | 从 story.timeline 取哪些索引合并 |
| `hero.story_break_html` | str | 多 timeline 之间的分隔条文字 |
| `hero.quotes_pick` | [int,int][] | 从 timeline[i].quotes[j] 挑引语 |
| `hero.produced_html` | html | PRODUCED 区文字 |
| `aside.figure` | obj | 顶部图位 `{image, alt, eyebrow, text, credit}` |
| `aside.side_banner` | str | 边讯 banner 文字 |
| `aside.briefings` | [{time,title,desc}] | 3 条边讯小新闻 |
| `aside.side_quote` | {text_html, attr} | 底部金句墙 |
| `photo_strip.banner` | str | 8 头像合影 banner |
| `photo_strip.caption` | str | 合影图说 |
| `day_stats.banner` | str | 数字 strip banner |
| `day_stats.items` | [{n,l}] | 8 个数字 + 标签 |

## page2（共建·人物卡）字段

| 路径 | 类型 | 说明 |
|---|---|---|
| `name` / `foot` / `theme_title_html` / `theme_en` | str | 同 page1 |
| `person_card.image` | str | 人物海报图 file:// 路径 |
| `person_card.alt` | str | 图描述 |
| `person_card.eyebrow` | str | "本 版 关 键 人 物 · KEY PERSON" |
| `person_card.quote_block_title` | str | 录音笔标题（含时间） |
| `person_card.quote_block_lines` | [[time, quote]] | 3-5 条人物原话 |
| `person_card.caption_html` | html | 图说 + 人物简介 |
| `hero.*` | 同 page1 hero | 右 8 栏 HERO 主稿 |
| `hero.cast_pick_indices` | int[] (可选) | 限制 cast 取哪些 timeline |
| `hero.cast_pick_extra_t8_filter_name` | str (可选) | 从第 N 个 timeline 只挑这个名字的人 |
| `produced_list.banner` | str | 产出物 banner |
| `produced_list.items` | [{no,title,desc}] | 3 个产出物 |
| `timeline_strip.banner` | str | mini-strip banner |
| `timeline_strip.items` | [{time,text,who}] | 6 个时间点 |
| `quote_wall.banner` | str | 金句墙 banner |
| `quote_wall.items` | [{t,cite}] | 8 句群成员金句（4×2 grid） |

## page3（副刊·横图 banner）字段

| 路径 | 类型 | 说明 |
|---|---|---|
| `name` / `foot` / `theme_title_html` / `theme_en` | str | 同上 |
| `banner_image` | obj | 顶部横图 `{image, alt, eyebrow, title, text, credit}` |
| `hero.*` | 同 page1 hero | 通栏 4 栏文字 HERO（无图） |
| `timeline_strip.*` | 同 page2 | 6 时间点（如复读传递链） |
| `letters.banner` | str | 听友催更 banner |
| `letters.items` | [{text,from}] | 3 条群友催更原话 |
| `lingo.banner` | str | 黑话 banner |
| `lingo.items` | [{w,d}] | 6 个当天真实出现的群内词 |

## page4（人物·附录）字段

| 路径 | 类型 | 说明 |
|---|---|---|
| `name` / `foot` / `theme_title_html` / `theme_en` | str | 同上 |
| `appendix_banner` | str | 黑底 banner |
| `sop_title` | str | SOP 列标题（"可 抄 作 业 · 实 操 SOP"） |
| `qa_title` | str | Q&A 列标题 |
| `tomorrow.banner` | str | 下回分解 banner |
| `tomorrow.items` | [{tag,title,desc}] | 4 条预告（左 8 栏） |
| `tomorrow.qr` | obj | 右 4 栏二维码 `{image, alt, title_html, desc}` |

注：page4 的 `highlights` / `sops` / `qas` / `colophon stats` 自动从 `story.json` 读，**不需要在 plan 写**。

## 自动读 story.json 的字段（不需在 plan 写）

- `story.lead_title` → 报头大字头条（自动 `\n` → `<br>`）
- `story.opening` → 报头右侧 4 栏 opening
- `story.timeline[i]` → 通过 plan 的 `timeline_indices` / `quotes_pick` / `cast_pick_indices` 引用
- `story.highlights[:8]` → P1 photo-strip + P4 hl-grid
- `story.sops` → P4 appendix 左
- `story.qas` → P4 appendix 右
- `story.stats` → P4 colophon stats
- `story.footer_quote` → P4 colophon quote
- `story.group_name` + `story.date` + `story.time_range` → P4 colophon meta + 各页 page-header

## 关键约束（与 SKILL.md 一致）

1. **A3 严格 1123×1587**：4 版高度差 ≤ 5px
2. **每版充实零空白**：没有 > 50px 连续空白带
3. **4 版独立 layout**：page1 = hero-with-aside；page2 = person-card-column；page3 = banner-image-top；page4 = highlights + appendix + tomorrow-with-qr
4. **内容真实**：图说 / 引语 / 时间点 / 黑话 / 数据都能在 story.json 或聊天记录里找到出处，禁编造
5. **填空白用真实内容**：不靠 padding 撑空白，靠 timeline_strip / quote_wall / tomorrow.items 等横通栏专栏填补

## 渲染失败排错

| 现象 | 根因 | 修法 |
|---|---|---|
| KeyError: 'masthead' | plan.json 缺顶层字段 | 复制 `examples/layout-plan-template.json` 重写 |
| 某版超 1587 | 该版 plan 内容总和过多 | 缩 timeline_strip items / 缩 lingo items / 缩 desc 字数 |
| 某版 < 1582 留空白 | plan 内容不够 | 加 briefings / timeline_strip / qw items 条数；或加专栏 |
| 图 404 不显示 | `image` 路径错或文件已删 | 确认 `file://` 路径绝对 + 文件存在 |
| 头像首字 placeholder | wxid 错或 avatars.json 缺 | 用 `vchat group-members --avatars` 重导 |
| `cast_pick_extra_t8_filter_name` 不生效 | 该 timeline cast 里没匹配名字 | 检查 story.json 对应 timeline 的 cast 数组 |
