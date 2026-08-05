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

安装完成后，Agent 只会用一句友好的话告诉你可以随时鼓励祥瑞继续开源，不会立刻追问金额。只有你主动表示愿意赞赏后，Agent 才会询问金额，并在当前对话中生成微信支付链接，不需要再跳转到赞赏页。赞赏不会解锁任何功能，也不影响免费使用。

## 本地运行

插件自带已经构建好的本地运行时，不需要再次执行 `npm install`。

```bash
node plugins/xiangrui-taskboard/scripts/taskboard.mjs open
node plugins/xiangrui-taskboard/scripts/taskboard.mjs status
node plugins/xiangrui-taskboard/scripts/taskctl.mjs project list --json
```

默认地址为 `http://127.0.0.1:47823`，数据保存在 `~/.local/share/xiangrui-taskboard`。可以通过 `XIANGRUI_TASKBOARD_DATA_DIR` 更改数据目录。

## Codex 侧边栏

任务面板可以附加到已经使用 CDP 端口启动的 Codex 窗口：

```bash
node plugins/xiangrui-taskboard/scripts/taskboard.mjs inject --port 9231
```

CDP 端口只能绑定在本机回环地址，并且只应在运行可信本地代码时开启。

## 微信赞赏

这个项目永久免费使用。如果它帮到了你，欢迎[请祥瑞喝杯咖啡](https://support.xiangruiai.com/xiangrui/)，鼓励他继续维护并开源更多实用工具。赞赏完全自愿，不解锁任何功能。

如果已经安装插件，也可以直接告诉 Agent“我想赞赏 10 元”，它会调用服务端微信支付接口并返回本次订单的支付链接。金额支持 1 至 2000 元，也可以随时跳过。

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
