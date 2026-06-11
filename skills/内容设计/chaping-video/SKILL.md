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
  （给 2-3 个候选让用户选）、标签 `tags`、要不要 BGM；时长/画幅有偏好也一并确认
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
- **时长完全由"讲清楚需要多长"决定，不预设任何档位（祥瑞 2026-06-11 重申）**：
  禁止"概念 1 分钟、复杂 2-3 分钟"这种档位思维——那也是死板。该问的是：把这个内容真正讲明白、讲到位，
  需要几个必讲的点、每个点要铺垫多少？时长是这个判断的自然结果。1 分钟讲不清一个概念就别硬压成 1 分钟，
  该 3 分钟讲透就 3 分钟；30 秒能说清就别拖。红线只有一条：不注水，每句有信息增量。
- 钩子 → 概念锚点 → 讲解（翻译官话术）→ 吐槽/反转 → 结论 + 互动
- **镜头语言（祥瑞 2026-06-11 定，反对"一句一镜"的机械模板）**：
  - **一句话可以多镜头**：一句口播讲一个过程、列举多项、或有视觉转折时，拆成多个镜头（蒙太奇）——
    media 场景多 shot、或一句话拆成连续几个 scene。别死守"一句=一镜"
  - **转场按叙事关系选，不千篇一律**（scene 填 `transition` 字段）：
    并列/递进（同主题继续）→ `cut` 硬切（最常用，干净保节奏，**大部分切换都该硬切**）；
    时间流逝/柔和关联 → `dissolve`；转折反转（"但是"/打脸）→ `fadewhite` 闪白；
    段落结束/情绪沉淀 → `fadeblack` 黑场；空间转换/并列对比 → `slideup`/`wipeleft`；聚焦强调 → `zoomin`。
    **滥用花转场显廉价**——克制，多用硬切，关键转折才上特殊转场
- 写完通读一遍：有没有不口语的书面腔、有没有超过 25 字的长句

### Step 3: 设计 storyboard（反千篇一律，这是创作不是填表）
**按 [references/storyboard-schema.md](references/storyboard-schema.md) 写 sb.json**。
- **框架是死的，编排是活的**：固定的只有品牌框架和留存五规则；叙事结构、场景类型组合、
  节拍必须按题材重新设计。连续两片结构雷同 = 失败（记忆篇是故事驱动，Token 篇是演示驱动，下一片再换打法）
- **HTML 框内排布纪律（祥瑞 2026-06-11 定）**：demo/concept/diagram/screenshot 这些 HTML 设计场景，
  内容必须在内容窗口框（content_rect）范围内排布好——该显示的完整显示、不溢出窗口、不被白边框遮挡，
  元素间距/字号按框的大小适配。媒体视频素材保持 cover 填满（默认），不做完整展示+模糊铺底。
- **demo 场景每片现写**：`demo` 类型 = 窗口里放一段为本片内容从零写的 HTML 动画
  （概念可视化/过程演示/数字动效），禁止复用往期的 demo HTML，只继承品牌色和确定性 CSS 写法
- 场景类型配比参考 style-guide 第二、三节，但配比是参考不是配方
- **招牌场景不跨片复用（祥瑞 2026-06-11 定，反模板硬规则）**：对比卡(diagram compare)、
  数字滚动 demo、某种 impact 句式这类"顺手就能套"的场景，写分镜时先回顾最近 2-3 片用过什么——
  连续片子套同一个招牌场景 = 模板化 = 返工。VOL.04/05/06 连着套对比卡就是反面教材。
  同一个意思有很多种呈现：对比可以用对比卡，也可以用工位网格熄灭、数据冲击、反转 demo、媒体画面+旁白。换着来
- 每个 scene 先把 image/video 字段留好路径（下一步去填实）

### Step 4: 收集素材（全网开放 + 标注来源）
**素材丰富度铁律（祥瑞 2026-06-11 定，最高优先级）**：每个视频项目都要把素材做到
**尽可能完整、越丰富越好**——这是观感的命门。具体要求：
- **配图必须和内容相符，地点尤其严（祥瑞 2026-06-11 定）**：说苏州就不能配郑州，说北京中关村
  就不能配随便一个城市天际线——张冠李戴比没画面更糟。真实地点/机构画面找不到合规素材时，
  改用文字/数据/地图示意把地点写准（如数据卡写明"苏州工业园"），不强行配不符的通用画面。
  通用氛围(城市/科技/人物剪影)只能用在不指向具体地点的泛叙述里。
- **逐句配画面**：口播稿每一句讲的内容，画面上要有对应的真实素材或设计呈现，
  字幕说 A 画面就给 A，禁止"字幕在讲、画面对不上"。一句列举多项（"论文、数据、会议纪要"）
  就配多个画面快切，一项一个镜头
- **媒体场景多 shot**：能多给画面就多给，单个场景 2-4 个 shot 轮换比一个 shot 干到底丰富得多；
  从源素材（妙记/视频/网页）里穷尽式多截取贴切片段，宁多勿少
- **链接/素材模式**：把源材料里所有能用的画面（视频片段、图表、截图、案例图）都挖出来备选，
  抽帧建候选网格逐一确认内容，再按字幕匹配编排
- **纯设计场景适度**：concept_card/impact_text/diagram 这类无真实画面的设计场景是叙事节奏需要，
  但占比别太高——真实画面太少会显得"素材单薄"，设计场景之间多穿插真实素材
- 自检：渲染后逐场景抽帧，确认每句字幕都有匹配画面；对不上 = 返工补素材

**按 [references/asset-sourcing.md](references/asset-sourcing.md) 决策树执行**：
- 全网图片 → `scripts/fetch_image.py`（人物/事件/新闻图都能用，scene 标 `source: "素材来源：网络"`）
- 图解 → diagram 场景零素材；插画 → seedream；截图 → web-access；broll → fetch_broll.py
- 每个素材拿到后**Read 确认内容**再填进 sb.json，禁止盲用；外部素材必填 source（渲染器自动打角标）
- 不搬其他博主的整段成片解说；素材片段引用单源 ≤10s
- **BGM（可选，Step 0 问用户要不要）**：要的话按当片调性选 mood（tech/upbeat/suspense/chill/epic/funny/news，
  `fetch_bgm.py list` 看表），跑 `fetch_bgm.py grab --mood X --out assets/bgm.mp3 --duration <片长>`，
  sb.json 填 `bgm` + `bgm_volume`（默认 0.14）。渲染器自动 ducking：说话时 BGM 让位，停顿浮上来。
  调性判定来自 Step 1 研究：同类爆款视频惯用什么 BGM 风格就选对应 mood。
  **发布提示**：站外免版权曲保成片完整；发抖音/视频号时若站内曲库有热门同风格音乐，
  在平台编辑器替换更好（热门音乐自带流量加成且零版权风险）

### Step 5: TTS 配音
```bash
SKILL=~/.claude/skills/chaping-video
python3 $SKILL/scripts/tts.py --storyboard sb.json --workdir .
```
- 后端自动选择：火山豆包（配置了 appid/token 时）→ edge-tts（免费兜底，自动走 127.0.0.1:7897 代理）
- 看 manifest 时长合理即可（一句 20 字 ≈ 4-6s）

### 自实现效果库（剪映式效果用 ffmpeg/CSS 自造，全自动出片，祥瑞 2026-06-11 定）

剪映的特效画面是剪映引擎专属渲染的，CLI 化只能写特效名进草稿、画面搬不进 ffmpeg。
所以方向是**用我们自己的 ffmpeg/CSS 实现剪映式效果**，剪映只当"参考图鉴"。
排版保真（HTML 品牌画面不动），效果是叠加的增强。已实现/规划：
- ✅ **场景智能转场**（render.py，`sb["transitions"]` 默认开）：xfade 自实现叠化/闪白/黑场，
  按场景语义匹配（impact_text=闪白、concept_card=黑场叠、其余=自然叠化），不为配而配；
  转场缩短时间轴后自动重算 SFX 对齐
- ✅ **GSAP 动画引擎**（2026-06-11 接入，jheaven 级动效）：`assets/vendor/gsap.min.js` 已附带，
  record_scene.js 已支持逐帧捕获 GSAP（`gsap.globalTimeline.totalTime(t)` seek，rAF 驱动不走 WAAPI）。
  **demo 场景动画优先用 GSAP** 而非 CSS keyframes：timeline 精确编排出场序列、elastic/back/expo
  专业缓动（真弹性物理回弹，CSS 做不出）、stagger 错落出场一行搞定、数字滚动、SplitText 文字逐字。
  HTML 里 `<script src="file://.../assets/vendor/gsap.min.js"></script>` 引入即可。
  写 GSAP 代码参考已装的 gsap-core / gsap-timeline / gsap-plugins skill（官方知识，按需加载）
- 规划：画面特效（震动/缩放/故障/聚焦）、钩子大字砸场、数字滚动用 GSAP 重做

### Step 6: 渲染成片
```bash
python3 $SKILL/scripts/render.py --storyboard sb.json --workdir . --out final.mp4
```

**可选：导出剪映草稿精修**（祥瑞说"导进剪映/用剪映改"时）：
```bash
# 三轨成品版（场景成片段+配音+字幕，快速）
python3 $SKILL/scripts/export_jianying.py --storyboard sb.json --workdir .
# 全分层可编辑版（推荐，祥瑞 2026-06-11 定）：背景/素材/字幕/logo/期数/标题各独立成轨
python3 $SKILL/scripts/export_jianying.py --storyboard sb.json --workdir . --layered
```
**分层模式 6 轨**：HTML 设计场景渲染成「无文字纯背景」(bare 模式)，媒体场景用真实素材逐 shot 拆开，
字幕/logo/期数/标题全部剪映原生文字轨可直接改。取舍：剪映原生文字做不出 HTML 的玻璃发光/
accent 高亮/普惠 Heavy 正体，换来彻底可编辑 + 充分用剪映素材特效。设计哲学：HTML 出剪映做不出的
设计资产，剪映做素材组装+精修，不是互相取代。三轨成品版保真但不可改文字，按需选。
限制：依赖 render.py 的 temp/ 中间产物（出过片才能导）；剪映保存后草稿转加密，
CLI 单向生成不能回读；macOS 剪映无自动导出接口，导出手动点。
**铁律**（都是踩坑换来的，导出器已全部内化）：
① 生成前必退剪映（运行态覆盖草稿目录会损坏草稿，脚本自动退）；
② 主文件名必须 `draft_info.json`（剪映 10.6 找这个，pyJianYingDraft 只写 draft_content.json，脚本自动补）；
③ 素材必须复制进草稿目录 materials/（剪映是沙盒应用，无权访问 ~/Projects，否则"暂无访问权限"，脚本自动复制改路径）；
④ 补 cover 缩略图 + 修 meta tm_duration（否则草稿箱不显示/判损坏）；
⑤ 默认纯三轨，转场/动画是 `--effects` 实验开关；⑥ 生成后手动开剪映。
**关于解密**：剪映 10.6 保存后的草稿是真 AES 加密（base64 解码后熵 7.999），解密要逆向剪映二进制+密钥绑设备，不现实也不必要——我们是生成明文草稿，剪映能读（保存时才加密），单向导出。

### Step 7: 自检（必做，不跳过）
0. **事实校验（一票否决）**：演示动画和口播里出现的每一个数据必须实测或有来源——
   token 切分用 tiktoken 现场跑（`python3 -c "import tiktoken; ..."`，演示卡标注"实测"），
   价格/年份/数字对研究报告来源核对。编造一个数据 = 整片作废（2026-06-10 Token篇教训：
   切分和编号最初是编的，被祥瑞当场质疑）
1. `ffprobe` 看总时长、视频音频双流存在
2. **抽每个场景中点帧 Read 看效果**：文字有没有溢出、图有没有糊/裁坏、高亮位置对不对；**配图与口播是否对得上**(尤其地点：说A配的就得是A，不符=返工)；
   **装饰元素纪律**（祥瑞 2026-06-11 定）：短横/分隔线/下划线/角标这些装饰，必须与文字保持
   明确间距、不重合——游离的 absolute 定位最容易压字，优先用 flex gap 把装饰挂在文字下方固定间距
3. `volumedetect` 看 max_volume 在 -1~-6dB 区间
3.5 **静默检查（祥瑞 2026-06-10 定）**：`silencedetect=n=-45dB:d=1.0` 必须 0 命中——
   任何 >1s 的无声段=返工。病根通常是 min_dur 硬拉时长但口播没跟上：
   要么补口播填满（首选，信息密度↑），要么收短 min_dur；
   钩子停留等设计性静默也压在 1s 以内
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
| `scripts/fetch_bgm.py` | 按调性 mood 自动找免版权 BGM（yt_dlp，`list` 看 mood 表） |
| `scripts/make_sfx.py` | 重新生成音效库 |
| `scripts/export_jianying.py` | 工程导出为剪映草稿（场景视频/TTS音频/字幕三轨对齐，剪映里精修+手动导出） |

## 改进路线（2026-06-10 社区调研，按 ROI 排序，未实现的逐步做）

- ✅ 已做：自动封面（钩子帧）、来源水印体系、时长由音频驱动（编辑鲁棒）、多 shot 素材轮换、
  BGM 自动匹配+ducking（fetch_bgm.py + sidechaincompress）、竖屏手机安全区布局
  （信息元素避开顶部 ~150px/底部 ~330px 平台 UI 遮挡，装饰元素留遮挡区填构图）
- 待做：Pexels/Pixabay 多源素材 API（免费 key，丰富 B-roll）；逐词卡拉 OK 字幕（TTS 时间轴已有句级，词级需对齐器）；1:1 画幅适配
- 避雷（写死）：内部时间全用秒 float 不用帧号；字幕按语速预留 10% 缓冲；水印矢量生成

## 已知坑

- ending text / 任何 ASS 文本不要放 emoji（渲染不出）
- B 站搜索 API 偶发风控，重试或换关键词；彻底失效用 `python3 -m yt_dlp` 兜底
- 渲染中途报错先看 stderr 里的 filter_complex，最常见是素材路径不存在
- temp/ 目录保留中间产物方便排查，确认成片 OK 后可删
