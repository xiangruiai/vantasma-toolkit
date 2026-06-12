# 素材与研究：全网搜索（穷尽式）+ 标注来源

> **第〇原则·素材丰富度（最高优先级，祥瑞 2026-06-11 定）**：每个项目素材尽可能完整、越丰富越好。
> 逐句配画面（字幕讲什么画面给什么，列举多项配多画面快切）；媒体场景多 shot 轮换（2-4个）；
> 从源材料穷尽式多截取贴切片段（抽帧建候选网格确认）；真实画面占比要够，别让设计场景太多显单薄。
>
> 四条原则：① 知识内容必须全网搜到"搜不动为止"，信息密度是片子的命；
> ② **能用视频绝不用图**：media shot 先找视频，没有才退图片；60-90 秒片 ≥7 个素材位；
> ③ 外部素材都标来源，下载后必 Read 验证；
> ④ **教程/博主成片画面禁用**（2026-06-10 祥瑞定）：UP主做的教学PPT/信息图/录屏演示
>   是别人的创作成果，即使标来源也不用。可用的外部素材：新闻/纪录片画面、
>   官方发布物料、原始截图证物（如 ChatGPT 对话截图）、AI 生成、
>   **通用背景/氛围视频**（风景/粒子/科技抽象/城市空镜这类 B-roll，可用，标来源）。
>   **演示类画面一律自制**：用 demo 场景现写 HTML 动画（比录屏更干净且完全原创）。
> ⑤ **图片素材静置呈现**：媒体 shot 里的图片只做淡入，不加缩放推拉
>   （zoompan 像素抖动，祥瑞否决"晃动放大"效果）；动效感靠视频素材和 HTML 动画提供。

## 0. 研究环节（决定信息密度，比素材更重要）

- 标准动作：调 **deep-research skill** 对主题做穷尽式研究（多路检索+事实核验），不满足于一两次 WebSearch
- 产出要求：3 个以上"反常识信息点" + 关键数据/年份/人物 + 至少一个具体故事（脱口秀的"具体化"原料）
- Vault-first：`ov find "主题"` 先看库里已有认知
- 事实不确定的不写进口播稿

## 1. 全网图片（人物/事件/新闻/产品图）→ fetch_image.py

```bash
SKILL=~/.claude/skills/xiangrui-video
python3 $SKILL/scripts/fetch_image.py search "关键词" --limit 8     # 看候选（尺寸/标题/URL）
python3 $SKILL/scripts/fetch_image.py grab "关键词" --out WORK/assets/x.jpg --index 2
```
- DDG 搜索结果顺序会变，**grab 下来后必须 Read 看图确认内容**，不对就换 index 或换词
- 用进 scene 时标 `"source": "素材来源：网络"`（知道具体出处就写具体的，如"图源：纽约时报"）
- 优先选分辨率 ≥ 800px 的横图（窗口是横向裁切）

## 2. 图解卡 → HTML diagram 场景（首选：有逐步出现的动效感，祥瑞 2026-06-10 最终定）

步骤/过程 → `kind: flow`；对比 → `kind: compare`；要点 → `kind: list`。
HTML 卡的价值在**入场动效**（条目一步一步出现），生图是死图。版式持续打磨。

### 备选：seedream 简笔画卡（静态，HTML 版式不满意或额度允许时）

seedream 生成**简笔画手绘涂鸦风**卡片，做成 media 场景单 shot（自动缓推）。
Prompt 模板（实测文字零错误）：

```
简笔画手绘涂鸦风信息图，竖版，米白色纸张背景带细腻纸纹，
顶部翠绿色小字眉头「<英文眉头>」，黑色马克笔手写感特粗大标题「<标题>」，
<内容描述：步骤用手绘圆圈包数字01/02/03+标题+小字+相关简笔画涂鸦图标，
 对比用左右两栏简笔画主体+绿/粉马克笔高亮标题+手绘对勾叉号短句+中间黑圆圈VS>，
步骤间手绘波浪箭头连接，翠绿色(#22a667)和粉莓色(#e84a6d)马克笔随手高亮关键词，
黑色简洁线条，可爱治愈涂鸦感，留白充足，除指定文字外不要任何其他文字
```
- 尺寸 `--size 1920x2080`（贴合竖屏窗口比例）；生成后 Read 验证文字无误再用
- 每条小字 ≤ 12 字、条目 ≤ 4 个，文字多了会出错
- scene 写法：`{"type":"media","narration":"...","sfx":"whoosh","shots":[{"media":"image","src":"<卡片路径>"}]}`
- HTML diagram 场景仍可用（生图额度不足时的兜底）

## 3. 插画/概念图 → seedream 自己生成

```bash
python3 ~/.claude/skills/seedream-image/scripts/gen_image.py \
  --prompt "极简扁平风格插画，[主体]，纯白色背景，居中构图，主色调翠绿色(#22a667)点缀粉色，无文字" \
  --output WORK/assets/xxx.png --size 1920x1920
```

## 4. 截图证据 → web-access / 本机截图

官网、文档、新闻页、数据面板：web-access skill（CDP）开页面截图，标 source。

## 5. 视频 B-roll → fetch_broll.py

- 官方物料（发布会/官方宣传片）、新闻片段：B 站搜下载，scene 标 `"source": "素材来源：XX/网络"`
- 自己录屏：QuickTime / `screencapture -v`
- AI 生成：`dreamina text2video`
- 单源引用控制在 ≤10s；避免把其他博主的"整段成片解说"搬进来（素材片段 OK，搬解说不 OK）

## 6. BGM（可选）

```bash
python3 -m yt_dlp --proxy http://127.0.0.1:7897 -x --audio-format mp3 \
  "ytsearch1:NCS no copyright funk upbeat" -o WORK/assets/bgm.mp3
```

## 通用纪律

- 每个素材落地后 Read/抽帧确认，禁止盲用
- 外部素材必有 source 字段（渲染器会打角标）
- 对外发布前过一遍：来源标注齐不齐、引用片段长不长

## 品牌 logo 徽章（口播点名软件/大厂时，祥瑞 2026-06-12 定）

口播点名具体产品/公司（Claude、Codex、豆包、Cursor…）时，**logo 跟名字同时出现**当认知锚点：

```bash
python3 $SKILL/scripts/fetch_logo.py claude --out assets/logos/claude.svg          # Simple Icons 首选
python3 $SKILL/scripts/fetch_logo.py doubao --domain doubao.com --out assets/logos/doubao.png  # 国产兜底 favicon
python3 $SKILL/scripts/fetch_logo.py openai --color ffffff --out assets/logos/o_w.svg  # 深底单色化
```

**协调规范**：
- logo 不改色不变形（深底可整体单色化白色），统一装进**白底圆角方章**（52-64px，logo 居中占 ~70%），
  像 App 图标排排坐——原色在白章里互不打架，白章在深底玻璃卡里是统一语言
- 点名才出现，不点名不出现，禁止满屏 logo 乱飞
- scene 标 `source: "logo:各品牌官方(科普合理使用)"`；不变形不暗示官方背书
- logo 是身份标识不算"素材复用"红线，assets/logos/ 可跨片缓存
