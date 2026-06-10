# chaping-video

> 丢一个主题、或者一个公众号链接进去，约 25 分钟出一条 60-90 秒的竖屏知识科普视频。
> 配音、字幕、动画、音效、封面，全自动。

一个 Skill。信息密度和节奏对齐差评君，文案学脱口秀（铺垫-包袱-干货-callback），视觉是一套苹果 Keynote 玻璃风的固定品牌框架。默认品牌是「万涂幻象」，所有品牌元素可一个配置文件换皮。

---

## ✦ 它出来的片子长什么样

固定品牌框架（每一帧都在）：左上 logo 块 + 右上期数 VOL.NN + 顶部进度条 + HUD 角括号 + 玻璃片名横幅（兼封面）+ 底部无框字幕 + 右下幽灵水印。框架是死的，窗口里的内容每片现做：

- **demo 场景**：为本片内容从零写的 CSS 动画（概念可视化 / 过程演示 / 数字动效），一步一步出现，不是 PPT 轮播
- **media 场景**：透明窗洞合成，视频素材垫底、框架盖顶，来源角标永远浮在素材上
- **结尾标配**：评论钩 + 玻璃搜索框（逐字打出品牌搜索词 + 闪烁光标）

三条参考成片形态：故事驱动（记忆篇）/ 现场演示驱动（Token 篇）/ 新闻速报（Fable 5 篇）。skill 的第一原则是**反模板化**：连续两片结构雷同 = 返工。

---

## ✦ 管线架构

```
storyboard JSON ──► TTS 配音（火山播客音色 / edge-tts 兜底）
       │
       ▼
每场景一页 CSS 动画 HTML ──► 无头 Chrome 逐帧录制
       │                    （getAnimations 全暂停后逐帧拨 currentTime，完全确定性）
       ▼
whisper 词级对齐字幕（逗号切句、顿号不切、英文单词不拦腰砍）
       │
       ▼
ffmpeg 拼装 + 音效 + 自动封面（钩子帧）──► final.mp4
```

硬规则（写在 SKILL.md 里，每条都是踩坑换来的）：

- **事实校验一票否决**：演示动画和口播里的每个数据必须实测或有来源，编造一个数 = 整片作废
- **素材红线**：禁用其他博主的成片画面（即使标来源）；可用 = 新闻纪录片 / 官方物料 / 原始截图证物 / AI 生成 / 通用氛围 B-roll；外部素材必标来源
- **图片素材静置 + 淡入**，禁 zoompan 晃动放大；动效感靠视频素材和 HTML 动画

---

## ✦ 安装

```bash
# 放进 skills 目录（以 Claude Code 为例）
cp -r chaping-video ~/.claude/skills/

# 体检 + 一键装依赖
bash ~/.claude/skills/chaping-video/scripts/setup.sh --install
```

必备依赖：ffmpeg（含 libass 的完整版）、Node + puppeteer-core/ws、Chrome、edge-tts、openai-whisper、tiktoken。音效和标题字体已随 skill 附带。

然后对 agent 说「做个视频，讲讲 XX」或者丢一个文章链接即可。

---

## ✦ 品牌换皮

默认出片是万涂幻象的牌子。想换成你自己的，建一个 `~/.config/chaping-video/config.json`：

```json
{
  "brand": {
    "name": "你的品牌",
    "name_en": "YOURBRAND",
    "logo": "你的品牌",
    "sig_tag": "YB-2026",
    "search_text": "你的账号名",
    "search_hint": "全网搜索 · 同名账号",
    "host": "我是XX"
  }
}
```

左上 logo、右下水印、签名标注、结尾搜索框，全部跟着换，模板零改动。单片覆盖可在 storyboard JSON 里写 `brand` 字段。

---

## ✦ 可选增强（缺了照样出片）

| 能力 | 配置 | 缺省兜底 |
|---|---|---|
| 火山播客 TTS（最佳音质） | 环境变量 `VOLC_PODCAST_APPID` / `VOLC_PODCAST_TOKEN` | edge-tts 免费男声 |
| opencli（公众号链接抓取） | `npm i -g @jackwener/opencli` | WebFetch 直抓 |
| seedream 生图（插画/底图） | 火山方舟 API key | 纯 CSS 设计 |
| B 站素材 / 全网搜图 | 无需配置（脚本内置） | — |

---

## ✦ 字体版权

- 阿里巴巴普惠体 Heavy：阿里巴巴免费商用授权
- 优设标题黑：免费商用授权

均允许再分发，随 skill 附带方便开箱即用。

---

## ✦ 免责声明

仅供个人学习与研究。视频中引用的外部素材请遵守对应平台规则并标注来源；TTS、生图等云服务凭证自行申请、自行保管（skill 不落盘任何明文凭证）。详见仓库根目录免责声明。

MIT License.
