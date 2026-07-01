# 祥瑞白板录制工具

> 一个面向课程讲解、产品说明和异步沟通的网页端白板录制工具。

祥瑞白板录制工具把白板、摄像头、录制画幅、幻灯片、素材库和提词器放在同一个工作台里。它适合用来录制讲解视频、产品演示、课程片段、异步说明和知识卡片式内容。

本项目是 `xiangruiai/vantasma-toolkit` 的一部分，源码目录为 `apps/whiteboard-recorder`。

## 功能

- 白板绘制：基于 Excalidraw，支持手绘风图形、文字、图片、画框和素材库。
- 录制画幅：支持 16:9、4:3、3:4、9:16、1:1 和自定义画幅。
- 幻灯片：按录制画幅组织白板内容，录制时可在幻灯片之间切换。
- 摄像头：支持摄像头浮窗、位置调整、尺寸调整、圆形和方形显示。
- 提词器：支持讲稿、逐词高亮、轻量模式和语音跟随。
- 素材库：内置个人素材库和公共素材库入口，可把素材添加到白板。
- 主题与语言：支持浅色、深色、跟随系统，以及中文 / English 切换。
- 导出：在浏览器内完成录制并导出视频文件。
- 移动端提示：手机访问时显示网页端使用提示，避免误以为需要安装客户端。

## 环境要求

- Node.js 20 或更高版本。
- npm 10 或更高版本。
- 推荐使用最新版 Chrome 或 Edge。录制、摄像头和麦克风能力依赖浏览器权限。
- 本地开发可使用 `localhost`。线上部署需要 HTTPS，否则浏览器可能拒绝摄像头、麦克风或录屏权限。

## 安装

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cd vantasma-toolkit/apps/whiteboard-recorder
npm install
```

## 本地使用

启动开发服务器：

```bash
npm run dev
```

开发服务器启动后，用电脑浏览器打开终端里显示的地址。第一次使用摄像头、麦克风或录屏时，浏览器会弹出权限确认，需要允许。

基础使用流程：

1. 在白板上整理讲解内容，可以画图、插入文字、导入图片或添加素材库元素。
2. 点击右侧幻灯片按钮，添加录制画幅。
3. 打开摄像头，根据需要调整位置、大小和圆形 / 方形。
4. 打开提词器，把讲稿粘贴进去，按需要开启逐词高亮或语音跟随。
5. 点击录制，选择 16:9、4:3、3:4、9:16、1:1 或自定义画幅。
6. 开始录制，讲解完成后停止录制并导出视频。

更详细的图文说明见 [public/docs/operation-guide.md](./public/docs/operation-guide.md)。

## 构建

```bash
npm run build
```

构建产物会输出到 `dist/`。

本地预览构建产物：

```bash
npm run preview
```

## 自行部署

这是纯前端网页端工具，构建后可以部署到任意支持静态网站的服务。

通用配置：

```text
项目根目录：apps/whiteboard-recorder
安装命令：npm install
构建命令：npm run build
输出目录：dist
```

部署到线上域名后，请确认页面通过 HTTPS 访问。浏览器的摄像头、麦克风和录屏能力通常只在 `localhost` 或 HTTPS 页面中可用。

如果使用子路径部署，例如 `https://example.com/tools/whiteboard/`，需要同步调整 Vite 的 `base` 配置，否则静态资源路径可能不正确。默认配置适合部署在域名根路径。

## 常见问题

### 手机能不能用？

手机访问会显示移动端提示页。当前主要面向电脑浏览器使用，移动端体验还在开发中。

### 为什么摄像头、麦克风或录屏打不开？

请确认页面运行在 `localhost` 或 HTTPS 下，并且浏览器已经允许摄像头、麦克风和屏幕录制权限。macOS 还需要在系统设置里允许浏览器访问摄像头、麦克风和屏幕录制。

### 录制导出失败怎么办？

优先使用最新版 Chrome 或 Edge，并确认录制画幅宽高是偶数。H.264 编码通常要求偶数尺寸，应用会尽量自动修正，但自定义尺寸时仍建议使用偶数。

## 开源与致谢

本项目公开源码，并尊重所使用开源项目的许可证。完整第三方来源、许可证和修改说明见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。

特别感谢：

- [Excalidraw](https://github.com/excalidraw/excalidraw)：提供优秀的开源白板编辑能力。
- [mp4-muxer](https://github.com/Vanilagy/mp4-muxer)：用于浏览器内 MP4 封装。
- [MediaPipe Tasks Vision](https://developers.google.com/mediapipe)：用于浏览器侧视觉能力实验。
- [smart-teleprompter](https://github.com/Voumellis/smart-teleprompter)：为提词器能力提供参考和基础。
- [Excalicord](https://www.excalicord.com/)：对白板录制、画幅、摄像头和提词器工作流给了很重要的启发。

## 许可证

本项目中由祥瑞白板录制工具新增的代码使用 [MIT License](./LICENSE)。第三方组件按各自许可证使用。
