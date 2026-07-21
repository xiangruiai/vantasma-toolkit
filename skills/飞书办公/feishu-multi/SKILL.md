---
name: feishu-multi
description: macOS 原生飞书双开工具。通过复制官网版飞书、隔离 Bundle ID 与 LarkShell 数据目录、恢复 Hardened Runtime 并逐层重签名，创建可同时登录第二个账号的独立飞书客户端。用户要求“飞书双开”“再开一个飞书”“同时打开两个飞书”“修复或重建飞书双开”“检查飞书双开状态”或“退出第二个飞书”时使用；不得用 Lark 或网页版替代。
---

# 飞书原生双开

在 macOS 上创建并维护一个独立的原生飞书副本。副本拥有不同的 Bundle ID 和用户数据目录，可以和官网版飞书同时运行、分别登录账号。

## 运行入口

使用随 Skill 提供的脚本：

```bash
bash "<skill目录>/scripts/feishu-multi.sh" <命令>
```

根据用户意图选择命令：

| 用户意图 | 命令 | 行为 |
|---|---|---|
| 双开飞书、再开一个飞书 | `auto` | 检查副本，必要时重建，然后启动两个原生客户端 |
| 只安装副本，暂不启动 | `setup` | 创建并签名副本 |
| 启动已有副本 | `start` | 启动原飞书和副本 |
| 飞书更新后修复、重建 | `rebuild` | 归档旧副本，按当前官网版重建并启动 |
| 检查是否正常 | `status` | 显示版本、PID、签名和数据目录 |
| 退出第二个飞书 | `stop` | 只退出副本，不影响原飞书 |

正常请求优先运行：

```bash
bash "<skill目录>/scripts/feishu-multi.sh" auto
```

如官网版飞书不在默认位置，显式指定：

```bash
bash "<skill目录>/scripts/feishu-multi.sh" auto --source-app "/自定义路径/Lark.app"
```

## 执行流程

1. 若副本可能已经存在，先运行 `status` 获取当前状态。
2. 普通双开请求运行 `auto`，不要手工复制 App 或自行拼接签名命令。
3. 脚本完成后，再运行 `status`，确认原飞书和副本都有独立 PID，且副本签名为“通过”。
4. 向用户报告副本路径、运行状态和独立数据目录。首次打开后的账号登录由用户在飞书界面完成。
5. 官网版飞书升级后，如果副本版本落后，运行 `rebuild`。

## 默认位置

- 官网版飞书：优先查找 `/Applications/Lark.app`，也兼容 `Feishu.app`、`飞书.app` 和用户应用目录。
- 双开副本：优先安装到 `/Applications/飞书双开.app`；无写权限时使用 `~/Applications/飞书双开.app`。
- 独立数据目录：`~/Library/Application Support/LarkDual2`。
- 旧副本归档：`~/Applications/Feishu Multi Backups/`。

可以用 `--dest-dir`、`--app-name` 和对应的 `FEISHU_MULTI_*` 环境变量覆盖默认值。运行 `--help` 查看完整参数。

## 前提与安全边界

- 仅支持 macOS。
- 需要已安装飞书官网版客户端，当前支持的源 Bundle ID 为 `com.electron.lark`。这只是飞书官网版在 macOS 包内使用的技术标识，不代表国际版 Lark。
- 只使用 macOS 自带工具，不安装第三方依赖，不需要另装双开器。
- 不修改官网版飞书，不删除聊天数据。重建时先完整构建并验签新副本，再归档旧副本。
- 不删除 `LarkDual2` 数据目录，重建副本后原有第二账号登录态应继续复用。
- 不使用 `rm -rf`、不绕过脚本的源 App 校验、不把 Lark 或网页版当作替代结果。
- 若新版飞书内部结构变化，脚本应在替换旧副本前失败。保留完整报错并说明当前版本暂不兼容，不要盲目修改二进制。

## 故障排查

先运行：

```bash
bash "<skill目录>/scripts/feishu-multi.sh" status
```

- “未找到官方飞书客户端”：先确认官网版已安装，或使用 `--source-app` 指定真实路径。
- “不支持的源 App Bundle ID”：不要继续补丁，确认选中的是中国版飞书官网客户端。
- “副本签名失败”或启动后立即退出：运行 `rebuild` 并保留终端输出；必要时检查 `~/Library/Logs/DiagnosticReports/`。
- `/Applications` 不可写：脚本会自动回退到 `~/Applications`，也可通过 `--dest-dir` 指定可写目录。

任何修复都必须保持“两个原生飞书客户端、两套独立登录态”这一结果。
