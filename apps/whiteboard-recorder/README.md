# 祥瑞白板录制工具

> 万涂幻象出品的白板录制工作台，面向课程讲解、产品说明、异步沟通和视觉化演示。

祥瑞白板录制工具是一套录制优先的白板应用。它把白板、摄像头、素材库、提词器、幻灯片画幅和视频导出整合在一起，目标是让讲解型内容可以更简单、稳定、好看地完成。

当前网页版基于 React + Vite 构建，白板编辑能力使用 `@excalidraw/excalidraw`。我们在它之上做了自己的录制工作台、中文化菜单、素材库面板、摄像头浮窗、录制画幅、提词器、快捷键和导出体验。

本项目作为 `xiangruiai/vantasma-toolkit` 工具箱的一部分开源，源码目录为 `apps/whiteboard-recorder`。

## 在线地址

计划绑定到：

```text
https://whiteboard.xiangruiai.com
```

现有个人主页仍然保留在：

```text
https://www.xiangruiai.com
```

域名绑定和部署步骤见 [DEPLOYMENT.md](./DEPLOYMENT.md)。

## 功能

- 白板绘制与素材库
- 白板录屏与 MP4 导出
- 摄像头浮窗，支持位置、尺寸和形状调整
- 录制画幅选择，支持 16:9、4:3、3:4、9:16、1:1 和自定义
- 幻灯片式画幅管理
- 提词器浮层
- 中英文界面切换
- 深色、浅色和跟随系统主题

## 开发

```bash
cd apps/whiteboard-recorder
npm install
npm run dev
```

## 构建

```bash
cd apps/whiteboard-recorder
npm run build
```

## 部署

推荐部署到 Cloudflare Pages：

```text
Build command: npm ci && npm run build
Build output directory: dist
Root directory: apps/whiteboard-recorder
```

本项目带有 Cloudflare Pages Functions，用于移动端发送桌面打开链接。上线时需要在 Cloudflare Pages 里配置：

```text
RESEND_API_KEY
```

本地也可以在子目录里直接部署：

```bash
cd apps/whiteboard-recorder
npm run deploy:cloudflare
```

`public/_redirects` 已处理 SPA 回退，`public/_headers` 已加入基础安全与媒体权限策略。

## 开源说明

本项目公开源码，并尊重所使用开源项目的许可证。第三方来源、许可证和使用边界记录在 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。

特别说明：

- Excalidraw 是 MIT License，本项目使用它作为白板编辑内核，并保留来源说明。
- mp4-muxer、ffmpeg.wasm、MediaPipe、Mermaid、Vega 等项目按各自许可证使用。
- Excalicord 对白板录制体验的探索给了我们产品方向上的启发。当前仓库从公开 fork 演化而来，发布时会持续保留来源说明，并逐步把产品实现收敛成祥瑞白板自己的系统。

## 操作说明

基础使用说明见 [public/docs/operation-guide.md](./public/docs/operation-guide.md)，应用内“关于”面板也会提供入口。

## 关于万涂幻象

**万涂幻象** 是李祥瑞主理的飞书多维表格 + AI 落地社区，长期沉淀多维表格教程、模板、知识库、AI 工作流和业务自动化实践。

| | |
|---|---|
| 个人主页 | https://www.xiangruiai.com |
| 开源工具箱 | https://github.com/xiangruiai/vantasma-toolkit/tree/main/apps/whiteboard-recorder |
| 开源知识库 | https://vantasma.feishu.cn/wiki/space/7574356946532925441 |
| 联系邮箱 | li@xiangruiai.com |

## License

[MIT](./LICENSE) for original code authored for Xiangrui Whiteboard Recorder, with third-party components governed by their own licenses and notices.
