---
name: chaping-video
description: 万涂幻象品牌知识科普视频自动生成。固定品牌框架（墨绿做旧底+内容窗口+贴纸字幕条+固定主题大字，WaytoAGI式骨架万涂幻象皮肤），文案学脱口秀（铺垫-包袱-干货-callback），信息密度对齐差评君。研究主题→脱口秀口播稿→分镜→自制图解（diagram自动生成/seedream生图）→TTS→逐帧动画渲染成片。当祥瑞说"做个视频"、"把 XX 做成视频"、"讲解视频"、"科普视频"、"我想了解 XX 帮我做成视频"时触发。
---

# 万涂幻象知识视频生成（节奏对齐差评君）

## 第一原则：具体情况具体分析，禁止模板化（祥瑞 2026-06-10 定）

固定的只有两样：**品牌框架**（黑底格子/窗口/字幕/进度条/标签）和**留存五规则**。
其余一切都是每片现做的创作决策：
- **叙事形态先行**：研究完先回答"这片该怎么讲"——故事驱动？现场演示驱动？数据冲击驱动？
  对比悬疑驱动？（记忆篇=故事，Token篇=演示，下一片必须再换）形态决定场景编排，不是反过来
- **场景组合不复制**：类型、数量、顺序、节拍按题材定；连续两片结构雷同 = 返工
- **演示动画现写**：demo 场景的 HTML 每片从零创作
- **文案的梗和包袱来自当片题材**（梗调研），不搬运上一片的句式

把任意主题做成口播科普视频：信息密度和节奏学差评君，**视觉是万涂幻象自己的品牌体系**（与公众号同源：翠绿主色/粉莓点缀/点阵白卡/墨绿渐变，一眼认出是我们的）。默认竖屏 1080x1920，说"横屏"切 1920x1080。
产出：成片 MP4 + 口播稿 + storyboard JSON，全部落在工作目录。

**素材红线：禁止使用其他博主/UP 主成片画面。图解用 diagram 自动生成，插画用 seedream 自己生成，详见 asset-sourcing。**

## 工作流（7 步，顺序执行）

### Step 0: 确认需求（开工必问，不许默认）
- **输入三种模式**：① 一个主题（"讲讲 Token"）② **一个链接**（文章转视频）③ 一段现成素材
- **每片必问用户**（AskUserQuestion 一次问完）：期数 `vol`（如 VOL.04）、主题大字 `show_title`
  （给 2-3 个候选让用户选）、标签 `tags`；时长/画幅有偏好也一并确认
- 工作目录：`~/Projects/chaping-videos/<日期>-<主题slug>/`，建 `assets/` 子目录

**链接模式专属流程**（祥瑞 2026-06-10 定）：
1. 抓正文：公众号 → `opencli weixin download --url <url>`（第一选择，绕反爬）；
   普通网页 → defuddle skill；飞书 docx/wiki → lark-doc skill
2. 文中图片下载到 assets/ 并 Read 验证，可用作素材（标 `source: "图源：原文"`），
   但**视频素材仍然优先**（fetch_broll 按文章主题另搜）；文中的图表/数据图
   **不截图搬运，用 demo HTML 按原数据重制**（更美观且原创）
3. 文章只是底稿不是全部：仍走 Step 1 穷尽研究补事实+梗调研，数据照常实测核验
4. 改写纪律：观点转述成脱口秀口播（改写 ≥70%，原创度纪律），文章作者/出处在
   相关场景标 source，结尾口播可带一句"原文来自 XX"

### Step 1: 穷尽式研究（信息密度的来源，不能省）
- 调 **deep-research skill** 对主题做全网穷尽搜索（多路检索 + 事实核验），搜到"搜不动为止"
- 产出门槛：≥3 个反常识信息点 + 关键数据/年份/人物 + 至少一个具体故事（脱口秀"具体化"的原料）
- **梗调研（必做）**：搜"主题 + 梗/段子/名场面/热议"，挖这个话题圈子里自带的梗
  （如曼德拉效应圈的"皮卡丘尾巴颜色"、Token 圈的"一句废话烧掉五毛钱"）。
  主题自带梗 > 通用梗：有圈层认同感，观众会去评论区接梗。产出 2-3 个，
  用法两种：写进口播当包袱素材 / 搜对应梗图当表情包弹出（scene.memes）
- Vault-first：`ov find "主题"` 先看库里已有认知；不确定的事实不进稿

### Step 2: 写口播稿
**先读 [references/style-guide.md](references/style-guide.md)**（文案结构/节奏数据/场景配比）。
- 钩子 → 概念锚点 → 讲解（翻译官话术）→ 吐槽/反转 → 结论 + 互动
- 竖屏 60-90 秒 ≈ 350-550 字，一句话 = 一个镜头 = 一个 scene
- 写完通读一遍：有没有不口语的书面腔、有没有超过 25 字的长句

### Step 3: 设计 storyboard（反千篇一律，这是创作不是填表）
**按 [references/storyboard-schema.md](references/storyboard-schema.md) 写 sb.json**。
- **框架是死的，编排是活的**：固定的只有品牌框架和留存五规则；叙事结构、场景类型组合、
  节拍必须按题材重新设计。连续两片结构雷同 = 失败（记忆篇是故事驱动，Token 篇是演示驱动，下一片再换打法）
- **demo 场景每片现写**：`demo` 类型 = 窗口里放一段为本片内容从零写的 HTML 动画
  （概念可视化/过程演示/数字动效），禁止复用往期的 demo HTML，只继承品牌色和确定性 CSS 写法
- 场景类型配比参考 style-guide 第二、三节，但配比是参考不是配方
- 每个 scene 先把 image/video 字段留好路径（下一步去填实）

### Step 4: 收集素材（全网开放 + 标注来源）
**按 [references/asset-sourcing.md](references/asset-sourcing.md) 决策树执行**：
- 全网图片 → `scripts/fetch_image.py`（人物/事件/新闻图都能用，scene 标 `source: "素材来源：网络"`）
- 图解 → diagram 场景零素材；插画 → seedream；截图 → web-access；broll → fetch_broll.py
- 每个素材拿到后**Read 确认内容**再填进 sb.json，禁止盲用；外部素材必填 source（渲染器自动打角标）
- 不搬其他博主的整段成片解说；素材片段引用单源 ≤10s

### Step 5: TTS 配音
```bash
SKILL=~/.claude/skills/chaping-video
python3 $SKILL/scripts/tts.py --storyboard sb.json --workdir .
```
- 后端自动选择：火山豆包（配置了 appid/token 时）→ edge-tts（免费兜底，自动走 127.0.0.1:7897 代理）
- 看 manifest 时长合理即可（一句 20 字 ≈ 4-6s）

### Step 6: 渲染成片
```bash
python3 $SKILL/scripts/render.py --storyboard sb.json --workdir . --out final.mp4
```

### Step 7: 自检（必做，不跳过）
0. **事实校验（一票否决）**：演示动画和口播里出现的每一个数据必须实测或有来源——
   token 切分用 tiktoken 现场跑（`python3 -c "import tiktoken; ..."`，演示卡标注"实测"），
   价格/年份/数字对研究报告来源核对。编造一个数据 = 整片作废（2026-06-10 Token篇教训：
   切分和编号最初是编的，被祥瑞当场质疑）
1. `ffprobe` 看总时长、视频音频双流存在
2. **抽每个场景中点帧 Read 看效果**：文字有没有溢出、图有没有糊/裁坏、高亮位置对不对
3. `volumedetect` 看 max_volume 在 -1~-6dB 区间
4. 有问题改 sb.json 对应 scene 重跑 render.py（TTS 没改就不用重跑）
5. 全部通过才报告"完成"，附成片路径 + 时长 + 场景数

## 首次安装（开源用户从这里开始）

```bash
bash scripts/setup.sh            # 体检：列出缺什么、怎么装
bash scripts/setup.sh --install  # 一键安装全部必备依赖
```

必备：ffmpeg-full、Node + puppeteer-core/ws、Chrome、edge-tts、openai-whisper、tiktoken
（音效和标题字体已随 skill 附带）。全 ✅ 即可出片。

**品牌换皮**：编辑 `~/.config/chaping-video/config.json` 的 `brand` 段——
左上 logo（name）、右下水印（logo）、签名后缀（sig_tag）、结尾搜索框文案
（search_text / search_hint / host）全部在此替换，模板零改动。

**可选增强与兜底**（缺了照样出片）：
| 能力 | 配置 | 缺省兜底 |
|---|---|---|
| 火山播客 TTS（最佳音质） | env/钥匙串 VOLC_PODCAST_APPID/TOKEN | edge-tts 免费男声 |
| opencli（公众号链接抓取最稳） | `npm i -g @jackwener/opencli` + 浏览器扩展 | WebFetch / defuddle skill |
| seedream 生图（插画/底图） | 火山方舟 API key | 纯 CSS 设计，不依赖生图 |
| B站素材/全网搜图 | 无需配置（fetch_broll.py / fetch_image.py 纯内置） | — |

## 一次性配置（已就绪/可升级）

| 项 | 状态 |
|----|------|
| ffmpeg | 固定用 `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`（PATH 里的精简版没有 subtitles/drawtext 滤镜，**别用**） |
| edge-tts | 已装，挂 127.0.0.1:7897 代理可用 |
| 火山豆包 TTS（音质升级，推荐开通） | console.volcengine.com/speech → 语音合成大模型 → appid+access_token 填入 `~/.config/chaping-video/config.json` 的 tts.volc，之后自动优先使用 |
| 音效库 | `assets/sfx/` 已生成（impact/ding/whoosh/pop/tick），缺了跑 `scripts/make_sfx.py` |
| 字体 | 系统 PingFang SC + Baoli SC，无需安装 |

## 脚本速查

| 脚本 | 用途 |
|------|------|
| `scripts/tts.py` | 逐句配音出 manifest；`--check` 看后端状态；`--text/--out` 单句测试 |
| `scripts/render.py` | storyboard → 成片（HTML 品牌静帧+zoompan 运动+ASS 动态字幕+SFX/BGM 混音） |
| `scripts/html_still.py` | 品牌场景卡合成（HTML→无头 Chrome 截图）；单跑出全类型样张 |
| `scripts/fetch_broll.py` | B 站素材 search/download（内置绕 412 路径，CDN 拒 ffmpeg 直连所以先整段下载再裁） |
| `scripts/make_sfx.py` | 重新生成音效库 |

## 改进路线（2026-06-10 社区调研，按 ROI 排序，未实现的逐步做）

- ✅ 已做：自动封面（钩子帧）、来源水印体系、时长由音频驱动（编辑鲁棒）、多 shot 素材轮换
- 待做：BGM 自动 ducking（sidechaincompress，加 BGM 时实装）；Pexels/Pixabay 多源素材 API（免费 key，丰富 B-roll）；逐词卡拉 OK 字幕（TTS 时间轴已有句级，词级需对齐器）；多平台安全区模板（16:9/1:1 适配）
- 避雷（写死）：内部时间全用秒 float 不用帧号；字幕按语速预留 10% 缓冲；水印矢量生成

## 已知坑

- ending text / 任何 ASS 文本不要放 emoji（渲染不出）
- B 站搜索 API 偶发风控，重试或换关键词；彻底失效用 `python3 -m yt_dlp` 兜底
- 渲染中途报错先看 stderr 里的 filter_complex，最常见是素材路径不存在
- temp/ 目录保留中间产物方便排查，确认成片 OK 后可删
