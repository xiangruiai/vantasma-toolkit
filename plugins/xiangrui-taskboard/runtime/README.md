# 祥瑞任务面板运行时

这是 `xiangrui-taskboard` Codex 插件内置的开源运行时源码。插件已携带 `dist/web` 生产构建，普通安装不需要执行 `npm install`。

本地开发：

```bash
npm install
npm run dev
```

生产验证：

```bash
npm run check
```

macOS 上需要把任务面板嵌入单独的 Codex 窗口时，可以运行：

```bash
./scripts/xiangrui-codex
```

该入口使用本机回环 CDP 端口，并带上 `--disable-features=LocalNetworkAccessChecks`。只应在运行可信本地代码时开启 CDP。
