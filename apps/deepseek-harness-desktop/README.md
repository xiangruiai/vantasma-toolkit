# DeepSeek Harness Desktop

非官方 macOS 桌面壳安装包。图标为 DeepSeek 鲸鱼。本目录**只放安装包**，不放桌面壳源码。

不是 DeepSeek 官方客户端。DeepSeek Harness 本体见 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)。

## 下载

- 本目录：`DeepSeek-Harness-Desktop-1.0.0-macOS-Apple-Silicon.dmg`
- GitHub Release：https://github.com/xiangruiai/deepseek-harness-desktop/releases/tag/v1.0.0

## 安装

1. 先装 [Node.js 22+](https://nodejs.org)（目前只打了 Apple Silicon）。
2. 打开 DMG，把 `DeepSeek Harness.app` 拖进应用程序。
3. 若系统提示无法打开：Finder 里右键应用选打开；或执行 `xattr -cr "/Applications/DeepSeek Harness.app"`。
4. 首次启动会通过 `npx @deepseek-ai/dsh web` 拉起本地服务（`http://127.0.0.1:3080/`）。
5. 在界面里配置 API Key。

日志在 `~/Library/Logs/DeepSeekHarness/`。
