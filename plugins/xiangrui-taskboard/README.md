# 祥瑞任务面板 Codex 插件

万涂幻象为 Codex 打造的本地任务面板。它把项目、议题、评论、依赖关系、工作流和 Agent 执行状态放进同一块看板，并提供 `manage-taskboard` Skill 与 `taskctl` 命令行工作流。

## 安装

把万涂幻象工具箱添加为 Codex marketplace，然后安装插件：

```bash
codex plugin marketplace add xiangruiai/vantasma-toolkit --ref main
codex plugin add xiangrui-taskboard@vantasma-codex
```

安装后重启 Codex，并在新任务中说：

```text
打开祥瑞任务面板
```

首次打开时，Agent 会自动完成侧栏设置，并打开 `~/Applications/xiangrui Codex.app`。如果普通 Codex 正在运行，macOS 会先弹出确认，再退出并以任务面板模式重新打开。以后从「应用程序」里的 **xiangrui Codex** 启动，就能在 Codex 左侧边栏直接看到「任务面板」。不需要手工配置 CDP，也不需要另开终端运行注入命令。

安装完成后，Agent 只会用一句友好的话告诉你可以随时鼓励祥瑞继续开源，不会立刻追问金额。只有你主动表示愿意赞赏后，Agent 才会询问金额，并直接打开与官网一致的赞赏卡片，自动带入项目和金额、创建订单并展示二维码。赞赏不会解锁任何功能，也不影响免费使用。

## 本地运行

插件自带已经构建好的本地运行时，不需要再次执行 `npm install`。

```bash
node plugins/xiangrui-taskboard/scripts/taskboard.mjs open
node plugins/xiangrui-taskboard/scripts/taskboard.mjs status
node plugins/xiangrui-taskboard/scripts/taskboard.mjs doctor
node plugins/xiangrui-taskboard/scripts/taskctl.mjs project list --json
```

默认地址为 `http://127.0.0.1:47823`，数据保存在 `~/.local/share/xiangrui-taskboard`。可以通过 `XIANGRUI_TASKBOARD_DATA_DIR` 更改数据目录。

## Codex 侧边栏

macOS 的完整侧栏流程由插件自动管理：

```bash
node plugins/xiangrui-taskboard/scripts/taskboard.mjs setup
node plugins/xiangrui-taskboard/scripts/taskboard.mjs launch
node plugins/xiangrui-taskboard/scripts/taskboard.mjs doctor
```

`setup` 会安装用户级 `xiangrui Codex.app` 和常驻注入恢复服务；`launch` 会经过原生确认后重新打开 Codex；`doctor` 会分别检查本地服务、CDP、Codex 主界面和注入状态，并给出准确的失败原因与处理动作。

如果你只想使用浏览器版，可以继续运行 `open`。Windows 和 Linux 当前使用浏览器版，macOS 支持 Codex 左侧边栏。CDP 端口只绑定本机回环地址，并且只应在运行可信本地代码时开启。

## 开发版同步

公开插件运行时由开发仓库显式同步，避免本机版新增能力后公开包静默落后：

```bash
node scripts/sync-xiangrui-taskboard.mjs --source /path/to/dashi-taskboard --check
node scripts/sync-xiangrui-taskboard.mjs --source /path/to/dashi-taskboard --write
```

发布前必须先同步、重新构建 `runtime/dist/web`，再运行插件的针对性测试和安装器隔离测试。

## 微信赞赏

这个项目永久免费使用。如果它帮到了你，欢迎[请祥瑞喝杯咖啡](https://pay.xiangruiai.com/?project=xiangrui-taskboard)，鼓励他继续维护并开源更多实用工具。赞赏完全自愿，不解锁任何功能。

如果已经安装插件，也可以直接告诉 Agent“我想赞赏 10 元”，它会直接打开主站赞赏页，并显示本次 10 元订单的微信支付二维码。金额支持 1 至 2000 元，也可以随时跳过。

## License

[MIT](../../LICENSE)

---

## 关于万涂幻象

**万涂幻象是一个面向真实业务场景的企业 AI 落地实践社区。**

从真实业务现场出发，我们连接一线业务实践者、能力贡献者和企业团队，共同发现问题、定义场景、验证方案、交付结果，并把有效经验沉淀为可复用的案例、方法和行业 Know-how。

- [社区与知识库](https://vantasma.feishu.cn/wiki/MC1nwBft0izODokXe4acHKjZnsh)
- [万涂幻象开源工具箱](https://github.com/xiangruiai/vantasma-toolkit)
- [公开工作台](https://www.xiangruiai.com)
- 联系：li@xiangruiai.com
