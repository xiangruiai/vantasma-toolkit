# Storyboard JSON Schema

render.py 与 tts.py 的输入契约。一个 scene = 一句完整 narration = 一个镜头。

## 顶层字段

```json
{
  "title": "片名（仅记录用）",
  "aspect": "portrait",        // portrait=1080x1920(默认) | landscape=1920x1080
  "show_title": ["1分钟看懂", "记忆的((Bug))"],  // 固定主题大字（每帧都在），((词))=翠绿强调+粉莓下划线
  "logo": "万涂幻象",           // 右下幽灵字水印，缺省取品牌配置 brand.logo
  "brand": {                    // 可选，单片覆盖品牌配置（全局默认在 ~/.config/xiangrui-video/config.json 的 brand 段）
    "name": "万涂幻象",          // 左上 logo 块
    "name_en": "VANTASMA",      // diagram 卡眉头 "<name_en> NOTES"
    "sig_tag": "VNT-2026",      // 左下 SIG.NN / <sig_tag> 标注
    "search_text": "李祥瑞",     // 结尾搜索框逐字打出的文字
    "search_hint": "全网搜索 · 同名账号",
    "host": "我是祥瑞"           // 结尾口播自介默认称呼
  },
  "vol": "VOL.01 · 记忆篇",     // 右上角期数标识（系列感），默认 VOL.01
  "tags": ["AI", "心理学", "科普"],  // 主题大字下方的领域标签胶囊，最多 4 个
  "fps": 25,                   // 可选，默认30。主力素材是25fps录屏(飞书/B站)时设25，避免重复帧卡顿
  "fade_out": 0.9,             // 可选，结尾渐隐秒数(画面淡黑+音频淡出)，默认0.9，设0关闭
  "transitions": true,         // 可选，场景间智能转场(xfade叠化/闪白)，默认开
  "bgm": "/abs/path/bgm.mp3",  // 默认配。fetch_bgm.py grab --mood <调性> 自动获取免版权曲
  "bgm_volume": 0.14,          // 渲染器自动 ducking（人声 sidechain 压 BGM）
  "scenes": [ ... ]
}
```

**v4 框架说明**：整片一个固定品牌框架（logo条/内容窗口/贴纸字幕条/show_title/做旧水印），
场景只换窗口内容。字幕条自动从 narration 切句生成，无需配置。`keywords` 字段已废弃（忽略）。

## scene 通用字段

| 字段 | 必填 | 说明 |
|------|------|------|
| type | ✅ | concept_card / whiteboard / broll / screenshot / impact_text / image_full / ending |
| narration | ✅ | 这个镜头的口播文本（TTS 朗读 + 自动切底部字幕）。可为空串=无声场景 |
| sfx | | impact / ding / whoosh / pop / tick，场景开头播放 |
| keywords | | 花字数组 `[{"text":"关键词","at":2.2,"dur":1.5}]`，at=场景内相对秒 |
| motion | | in(默认缓推) / out(缓拉) / up(上移，适合长图) |
| min_dur / dur | | 场景最短/指定时长秒（默认=口播时长+0.35s，最短1.6s） |
| source | | 左上角素材来源标注（broll 必填，如"素材来源：XX"） |
| transition | | 这个镜头**进场**的转场（镜头语言，按与上一镜头的叙事关系选）：`cut`硬切(默认多数用它,干净保节奏)/`dissolve`叠化(时间流逝)/`fadeblack`黑场(段落结束)/`fadewhite`闪白(转折冲击)/`slideup`/`wipeleft`(空间转换)/`zoomin`(聚焦)。不填按场景类型给克制默认 |
| transition_dur | | 转场时长秒，默认 0.3；`cut` 固定 0.06 |

## 各类型专属字段

### concept_card 开场概念卡（墨绿渐变 + 超大期数数字 + 大白标题）
```json
{"type": "concept_card", "narration": "...", "title": "曼德拉效应",
 "subtitle": "THE MANDELA EFFECT", "number": "01", "sfx": "impact"}
```
title=2-6 字主标题；subtitle=英文小标（自动加字距）；number=左上超大装饰数字（期数）。

### whiteboard 白板图解卡（白底点阵 + 白卡包图 + 大灰水印）
```json
{"type": "whiteboard", "narration": "...", "image": "/abs/path.png",
 "watermark": "记忆", "caption": "大脑 ≠ 硬盘",
 "keywords": [{"text": "自己脑补", "at": 2.2}], "sfx": "whoosh"}
```
watermark=2-4 字垫底大灰字；caption=粉桃胶囊里的一句结论（≤12 字）；image 用 seedream 自己生成的白底插画。

### diagram 自动图解卡（不需要图片素材，纯 JSON 生成）
```json
{"type": "diagram", "narration": "...", "watermark": "流程", "sfx": "whoosh",
 "diagram": {"kind": "flow", "title": "记忆的三步",
   "items": [{"t": "编码", "d": "看到的瞬间就开始失真"},
             {"t": "存储", "d": "睡一觉细节被改写"},
             {"t": "提取", "d": "每回忆一次就重写一次"}]}}
```
kind 三选一：
- `flow`：竖向步骤卡（绿色序号圆 + 粉莓箭头），items=[{t,d}] 3-4 步
- `compare`：左右对比卡（绿 vs 粉莓 + VS 圆），`"left":{"title","points":[]},"right":{...}` 每边 3-4 点
- `list`：要点卡，items=[{t,d}] 2-4 条
字数上限：t 2-4 字，d ≤ 14 字，points 每条 ≤ 10 字，超了会撑破卡片。

### broll 视频片段（⚠️ 素材纪律：仅官方发布素材/自己录屏/AI 生成视频，禁止搬运博主成片）
```json
{"type": "broll", "narration": "...", "video": "/abs/clip.mp4",
 "video_start": 0, "punch_in": true, "source": "素材来源：XX官方", "sfx": "tick"}
```
**fit**: cover(默认,填满窗口裁切,干净不突兀) | contain(完整缩放+模糊铺底,极少数必须看清整张内容才用)；video_start=从源片第几秒开始；片段比场景短会自动定格末帧；源音轨自动静音；右上角自动补品牌戳。

### screenshot 截图证据卡（白卡倾斜 + 粉莓荧光高亮，只用自己截的图）
```json
{"type": "screenshot", "narration": "...", "image": "/abs/shot.png",
 "highlight": [0.1, 0.35, 0.9, 0.6], "tilt": true, "sfx": "pop"}
```
highlight=[x0,y0,x1,y1] 相对坐标(0-1)。

### impact_text 全屏砸字（深底光斑背景 + 白字粉莓描边动画）
```json
{"type": "impact_text", "narration": "这记性，比你强多了。",
 "text": "比你强多了", "sfx": "ding"}
```
text ≤ 8 字；narration 同步说出这句话；text_color 可选覆盖文字色。

### editorial 编辑杂志式版面（去 AI 味主场景，见 design-system.md）
```json
{"type":"editorial","narration":"...","kicker":"WHAT MAKES AN AGENT",
 "title":"会((自己干活))的那种 AI","idx_label":"AGENT / 4 CORE",
 "items":[{"no":"01","cap":"会拆活","tag":"PLANNING","desc":"把大任务拆成小步骤"},
          {"no":"02","cap":"有记性","tag":"MEMORY","desc":"记得住上下文"},
          {"no":"03","cap":"会用工具","tag":"TOOLS","desc":"自己调搜索写代码"}]}
```
左对齐大标题+超大编号列表+细线分隔+竖网格，无 emoji 无玻璃卡。items 建议 3 条。GSAP 接管错落入场。

### demo 定制演示动画（每片现写，反千篇一律的核心）
```json
{"type": "demo", "narration": "...", "demo_bg": "paper|dark", "sfx": "whoosh",
 "demo_html": "<div>…窗口内 body 片段，元素带 id/class 供 GSAP 选中…</div>",
 "demo_css": "可选静态样式（GSAP 模式下样式多写 inline，动画交给 demo_js）",
 "demo_js": "GSAP 动画代码（优先用，比 CSS 强）：gsap.timeline()+from/to，elastic/back 弹性、stagger 错落、strokeDashoffset 描线。录制器自动逐帧 seek globalTimeline。gsap.min.js 自动引入"}
```
- 用途：概念可视化/过程演示/数字动效（如 tokenizer 剁字、扣费账单、计数器对比）
- **每片按内容从零写**，禁止复用往期 demo；只继承设计语言（见下）
- **设计语言 = Keynote 发布会风**（祥瑞 2026-06-10 三选一定稿）：
  深底 `linear-gradient(170deg,#101412,#0a0d0b)` + 翠绿/粉莓 radial 光晕；
  元素用玻璃卡 `backdrop-filter:blur(20px) + rgba(255,255,255,.07)底 + .16白边 +
  inset 0 1px 0 rgba(255,255,255,.12) 内高光 + 大圆角28px`；
  大字加同色 text-shadow 发光（如 `0 0 40px rgba(34,166,103,.8)`）；
  辅助色 #7ed8a8（亮绿）/#ff8fae（亮粉）；总结条用渐变玻璃胶囊；
  数据卡右下角标注实测来源（等宽小字）
- 写法约束：纯 CSS 动画（禁 JS/视频/GIF，逐帧录制只认 getAnimations）；
  元素用 animation-delay 编排出场节奏，与 narration 节拍对齐；
  **所有展示数据必须实测**（Step 7 事实校验一票否决）

### image_full 全屏图（Ken Burns）
```json
{"type": "image_full", "narration": "...", "image": "/abs/photo.jpg", "motion": "in"}
```

### ending 品牌结尾卡（VANTASMA + 万涂幻象 + 绿光互动框）
```json
{"type": "ending", "narration": "你怎么看？评论区聊聊。",
 "text": "评论区聊聊", "sfx": "pop"}
```
text 显示在绿光框内，HTML 渲染可用 emoji。

## 调用顺序

```bash
SKILL=~/.claude/skills/xiangrui-video
python3 $SKILL/scripts/tts.py --storyboard sb.json --workdir WORK     # 出 WORK/audio/manifest.json
python3 $SKILL/scripts/render.py --storyboard sb.json --workdir WORK # 出 WORK/final.mp4
```

render.py 发现 manifest 缺失会自动补跑 TTS。改了某句 narration 后删掉对应 `WORK/audio/scene_NNN.mp3` 重跑 tts.py 即可（其余句子不重合成——目前是全量重跑，量少无所谓）。
