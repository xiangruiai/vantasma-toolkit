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
- 移动端提示：手机访问时显示网页端使用提示，避免误以为需要安装 App。

## 本地运行

```bash
git clone https://github.com/xiangruiai/vantasma-toolkit.git
cd vantasma-toolkit/apps/whiteboard-recorder
npm install
npm run dev
```

开发服务器启动后，用电脑浏览器打开终端里显示的本地地址。摄像头、麦克风和录屏权限需要浏览器授权。

## 构建

```bash
npm run build
```

构建产物会输出到 `dist/`。

## 操作说明

操作说明见 [public/docs/operation-guide.md](./public/docs/operation-guide.md)，应用内的帮助入口也会展示同一套说明。

常用流程：

1. 在白板上整理讲解内容。
2. 添加或选择幻灯片画幅。
3. 打开摄像头和提词器。
4. 点击录制，选择画幅并开始录制。
5. 结束录制后导出视频。

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
