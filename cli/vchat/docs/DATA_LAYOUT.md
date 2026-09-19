# vchat 期望的数据目录布局

> vchat 不做解密，只做查询。任何能输出 sqlite db 的解密工具产物都能喂进来，
> 关键是把目录布局摆成下面这个样子。

## 数据根目录

由环境变量决定，按下列优先级查找：

1. `$VCHAT_DATA_DIR`（推荐显式设）
2. `$WECHAT_DECRYPT_PATH`（旧名兼容）
3. `~/.vchat/data`（如存在则用）
4. `~/Projects/wechat-decrypt`（旧默认值兼容）

下文里用 `$DATA_DIR` 指代这个根目录。

## 目录结构

```
$DATA_DIR/
├── decrypted/                  # ← vchat 真正读的就是这一层
│   ├── contact/
│   │   └── contact.db          # 必需 · 联系人 + 群成员
│   ├── session/
│   │   └── session.db          # 必需 · 最近会话索引
│   ├── message/
│   │   ├── message_0.db        # 必需 · 消息分片 0（一定存在）
│   │   ├── message_1.db        # 可选 · 消息分片 1（如果聊天多就有）
│   │   ├── message_N.db        # 可选 · 更多分片
│   │   └── media_0.db          # 可选 · 媒体/语音元数据
│   ├── head_image/
│   │   └── head_image.db       # 可选 · 头像（avatar 子命令需要）
│   ├── favorite/
│   │   └── favorite.db         # 可选 · 收藏夹
│   └── sns/
│       └── sns.db              # 可选 · 朋友圈
├── decoded_voices/             # vchat voice transcribe 自动生成
├── voice_transcriptions.json   # 转写缓存（自动写）
└── config.json                 # 可选 · 朋友圈图片解密需要（image_aes_key 等）
```

## 验证

```bash
vchat doctor
```

会列出每个 db 是否到位，以及缺失的影响。

## 从各解密工具产物迁移

### 从 `ylytdeng/wechat-decrypt`

它的产物默认就长上面那个样子，**不用改**。直接：

```bash
export VCHAT_DATA_DIR=~/Projects/wechat-decrypt
```

### 从 `PyWxDump`

PyWxDump 默认导出格式不同（单一 `MSG.db` / `MicroMsg.db`），需要做一次目录映射：

```bash
mkdir -p ~/.vchat/data/decrypted/{contact,session,message,head_image,favorite,sns}

# 联系人
cp /your/pywxdump/output/MicroMsg.db  ~/.vchat/data/decrypted/contact/contact.db
# 消息（PyWxDump 的 MSG.db 对应 message_0.db）
cp /your/pywxdump/output/MSG.db       ~/.vchat/data/decrypted/message/message_0.db
# 媒体
cp /your/pywxdump/output/MediaMSG.db  ~/.vchat/data/decrypted/message/media_0.db
# 头像
cp /your/pywxdump/output/MicroMsg.db  ~/.vchat/data/decrypted/head_image/head_image.db

# 跑 doctor 看缺什么
vchat doctor
```

> ⚠️ 不同版本的 PyWxDump 表结构可能跟 vchat 期望的有差异（比如字段名）。
> 如果 `vchat ls` 返回不正常，issue 我们一起补适配。

### 从 `WeChatMsg / 留痕`

类似 PyWxDump，先按上面的布局放，再跑 `vchat doctor` 看缺什么。

## 自定义路径

如果不想用默认路径，显式设：

```bash
export VCHAT_DATA_DIR=/Volumes/External/wechat-backup-2026Q2
# 然后期望下面这个目录存在：
# /Volumes/External/wechat-backup-2026Q2/decrypted/...
```

写到 `~/.zshrc` / `~/.bash_profile` 持久化。

## 多账号

vchat 一次只看一个数据目录。多账号的话起多个目录，用 shell 函数切：

```bash
# ~/.zshrc
vchat-main()  { VCHAT_DATA_DIR=~/.vchat/main  vchat "$@"; }
vchat-alt()   { VCHAT_DATA_DIR=~/.vchat/alt   vchat "$@"; }
```

## 数据安全提醒

- `decrypted/` 下全是明文聊天记录，**别上传 GitHub / iCloud**
- 项目自带 `.gitignore` 已忽略 `*.db` / `decrypted/` / 转写缓存
- 真要备份就压缩加密一份放冷存储
