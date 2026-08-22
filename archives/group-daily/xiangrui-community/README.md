# 祥瑞和 Ta 的朋友们 · 群日报公开归档

这里保存万涂幻象社区群公开群日报的脱敏副本。归档来自已经公开展示在 [xiangruiai.com](https://www.xiangruiai.com/) 的日报内容，不是微信群原始聊天记录。

## 当前覆盖

- 首份日报：2026-04-23
- 最新已生成日报：2026-08-21
- 已归档：115 份
- 历史缺失：2026-04-24、04-25、04-26、04-27、04-28、05-03
- 2026-08-22 日报尚未生成，因此不补造内容

机器可读的完整清单、统计和文件哈希见 [index.json](index.json)。逐日报告位于 [`daily/`](daily/)。

## 隐私边界

- 李祥瑞、祥瑞、万涂幻象保留公开名称
- 其他多字符昵称只保留第一个有效字符，其余替换为星号
- 自动隐藏中国大陆手机号、邮箱、wxid 和 chatroom id
- 删除头像、成员 ID、用户 ID 等私有字段
- 不归档头像、原始群聊、成员名单、播客凭据和内部部署配置

日报中的群友观点和发言归原发言者所有。本归档仅保存公开日报的脱敏编排版本，不代表授予第三方对群友原始发言的再许可。

## 更新归档

以下命令只读取本地生产数据，输出公开脱敏副本：

```bash
python3 scripts/export_public_archive.py \
  --source "/path/to/xiangrui.me/src/data/daily" \
  --roster "/path/to/xiangrui.me/src/data/communityRoster.json" \
  --output . \
  --through YYYY-MM-DD
```

导出后必须校验：

```bash
python3 scripts/verify_archive.py .
```

## 文件说明

```text
.
├── README.md
├── index.json
├── daily/
│   └── YYYY-MM-DD.json
└── scripts/
    ├── export_public_archive.py
    └── verify_archive.py
```
