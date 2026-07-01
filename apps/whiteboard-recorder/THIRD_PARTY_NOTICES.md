# Third-Party Notices

祥瑞白板录制工具使用了一些开源项目作为基础能力，也参考了现有白板录制产品的工作流。我们会在这里记录来源、许可证和使用边界，方便使用者了解这个项目是如何构成的。

## Excalidraw

- Project: https://github.com/excalidraw/excalidraw
- Package: `@excalidraw/excalidraw`
- License: MIT
- Use: 白板编辑、场景编辑、素材库元素处理和绘图 UI 基础能力。
- Modification note: 本项目在 Excalidraw 外层加入了录制工作台、中文化菜单、素材库面板、摄像头浮窗、提词器、录制画幅和设置界面。

## mp4-muxer

- Project: https://github.com/Vanilagy/mp4-muxer
- Package: `mp4-muxer`
- License: MIT
- Use: 浏览器内录制结果的 MP4 封装。

## MediaPipe Tasks Vision

- Project: https://developers.google.com/mediapipe
- Package: `@mediapipe/tasks-vision`
- License: Apache-2.0
- Use: 摄像头分割和浏览器侧视觉能力实验。

## ffmpeg.wasm

- Project: https://github.com/ffmpegwasm/ffmpeg.wasm
- Packages: `@ffmpeg/ffmpeg`, `@ffmpeg/util`
- License: MIT
- Use: 浏览器侧媒体转换实验。

## Smart Teleprompter

- Project: https://github.com/Voumellis/smart-teleprompter
- Website: https://smartteleprompter.com/
- License: MIT
- Use: 提词器滚动、语音跟随、讲稿导入、快捷键、显示设置和本地持久化能力参考。
- Modification note: 已改造成 `src/components/TeleprompterPanel.tsx` 中的祥瑞白板提词器浮层，并接入录制工作台、中文界面和共享麦克风设置。

## Excalicord

- Product reference: https://www.excalicord.com/
- Related repository reviewed in this workspace: https://github.com/thinking-one-hour-everyday/excalicord
- Use: 白板录制产品方向、画幅录制、摄像头浮窗、提词器和幻灯片工作流给了本项目重要启发。
- Note: 当前项目会保留对 Excalicord 的感谢和来源说明。若未来继续复用或改写相关实现，会持续按实际代码来源补充许可证和修改记录。
