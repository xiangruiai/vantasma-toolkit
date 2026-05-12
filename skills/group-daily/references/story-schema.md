# story.json 数据结构

AI 在分析完聊天记录后，准备一份 story.json 文件喂给 `make_daily.py`。这是脚本和模型之间的契约。

## 完整结构

```json
{
  "group_name": "祥瑞和Ta的社区朋友们",
  "date": "2026-05-11",
  "time_range": "09:08 → 22:00",

  "lead_eyebrow": "Today's Story · 今日故事",
  "lead_title": "一天里，有人提问，\n有人答；有人输出，\n有人收。",
  "opening": "今天是个双峰日。上午十一点...（150-200 字开场叙述）",

  "timeline": [
    {
      "no": "01",
      "time": "09:20",
      "badge": "提问者",
      "cast": [
        {"name": "示例联系人A", "wxid": "wxid_example001"}
      ],
      "theme": "一个问题，点燃整个上午",
      "story": "示例联系人A抛了一个看似普通的问题...（150-250 字故事正文）",
      "quotes": [
        {"who": "示例联系人B", "text": "整理知识库的员工，不一定愿意沉下心整理..."},
        {"who": "Duke（杜傲）", "text": "贵的点在于每次都要全量检索。"},
        {"who": "示例联系人E", "text": "AI 这个东西，本质就是个工具，看你怎么用。", "source": "voice", "duration_s": 12.0}
      ],
      "output": "万涂幻象开源 wiki + 两篇公众号文章"
    }
  ],

  "highlights": [
    {
      "name": "示例联系人A",
      "wxid": "wxid_example001",
      "tag": "上午发问者",
      "desc": "一个问题点燃了整个上午的讨论。"
    }
  ],

  "sops": [
    {
      "title": "抖音 → 飞书妙记 → 多维表格沉淀",
      "author": "宋革辰",
      "time": "21:29",
      "steps": [
        "看到好抖音，复制链接",
        "敲击 iPhone 背面三次（提前设好快捷指令）",
        "..."
      ],
      "output": "每条视频形成视频链接加妙记链接双卡片"
    }
  ],

  "qas": [
    {
      "q": "搭企业内部知识库给新人培训用什么方案？",
      "asker": "示例联系人A",
      "answers": [
        {"who": "Essay 随笔", "text": "公司用飞书，自己用 Obsidian"},
        {"who": "李冬浩", "text": "知识问答贵，建议服务台加知识库组合"}
      ]
    }
  ],

  "stats": {
    "total_messages": 379,
    "unique_senders": 46,
    "total_chars": 6529,
    "new_members": 1
  },

  "footer_quote": {
    "text": "自己会，也要更多人会。爱分享，长智慧。",
    "attr": "宋革辰 21:32"
  }
}
```

## 字段说明

### 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `group_name` | ✓ | 群名 |
| `date` | ✓ | 日期 YYYY-MM-DD |
| `time_range` | ✓ | 时间跨度（如 "09:08 → 22:00"） |
| `lead_eyebrow` | | 主标题上方小字（默认 "Today's Story · 今日故事"） |
| `lead_title` | ✓ | 主标题，可用 `\n` 换行 |
| `opening` | ✓ | 开场叙述 100-200 字，首字会被自动做 drop cap |

### timeline 时间故事线（6-8 条）

| 字段 | 必填 | 说明 |
|---|---|---|
| `no` | ✓ | "01" - "08" 大编号 |
| `time` | ✓ | "HH:MM" |
| `badge` | ✓ | 角色徽章短语（"提问者" "架构师" "救火队员" "突破" 等） |
| `cast` | ✓ | 主角列表 `[{name, wxid}]`，1-4 人 |
| `theme` | ✓ | 一句话故事概括（大标题） |
| `story` | ✓ | 150-250 字叙述正文 |
| `quotes` | | 1-3 句金句引用 `[{who, text, source?, duration_s?}]`，`source: "voice"` 标记语音转写（渲染时显示「（语音 N 秒）」） |
| `output` | | 这一时刻产生了什么（产出物 / 决策 / 共识） |

### highlights 今日高光（6-8 张）

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✓ | 显示名 |
| `wxid` | | 用于取头像。没有就用首字 placeholder |
| `tag` | ✓ | 一句话角色定位（"救火队员" "概念原创者"） |
| `desc` | ✓ | 一句话描述今天的贡献 |

**选取标准**（不是发言量排名）：
- 不是「谁话最多」，是「谁在今天有戏」
- 想问 "今天没有这个人会怎样？" — 答案是「故事少一块」的人入选
- 提问者、答题者、输出者、新成员、概念原创者都可以入
- 「全员标签册」是坑，不要做

### sops 工作流 SOP（可选）

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` | ✓ | SOP 标题 |
| `author` | ✓ | 分享者显示名 |
| `time` | | 时间戳 |
| `steps` | ✓ | 步骤列表，3-10 步合适 |
| `output` | | 产出/收益描述 |

### qas Q&A 沉淀（可选）

| 字段 | 必填 | 说明 |
|---|---|---|
| `q` | ✓ | 问题 |
| `asker` | ✓ | 提问者 |
| `answers` | ✓ | 回答列表 `[{who, text}]`，1-5 个回答 |

### stats 底部数字

| 字段 | 必填 | 说明 |
|---|---|---|
| `total_messages` | ✓ | 总消息数 |
| `unique_senders` | ✓ | 发言人数 |
| `total_chars` | ✓ | 总字数（去 `[图片]` `[链接]` 等占位） |
| `new_members` | | 新入群人数 |

### footer_quote 底部金句（可选）

挑一句当天最有共鸣的话作为收尾。

## 节制原则

宁可少不要多：

- timeline 6 个就 6 个，凑 8 个反而稀释
- highlights 6 个就 6 个，46 个全员是反模式
- sops/qas 没有就不写，不要硬凑

## 准备 wxid 的两个时机

**写 story.json 时就带上 wxid**：先用 `lookup_members.py` 查映射，写进 cast 和 highlights。

**或者用 protagonists + wxids 平行数组**：脚本会自动归一化。
```json
{
  "protagonists": ["示例联系人A", "示例联系人B"],
  "wxids": ["wxid_example001", "wxid_example003"]
}
```
