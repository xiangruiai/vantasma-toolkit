# Third-Party Notices

This product is being shaped as its own recording-first whiteboard app. It uses open-source projects as building blocks and keeps attribution separate from product branding.

The application is published from a codebase that started as a public Excalicord fork and has since been adapted into Xiangrui Whiteboard Recorder. When a third-party project has its own license, that license continues to apply. When a referenced project has no detected license, keep the reference explicit and review the code path before broad redistribution.

## Excalidraw

- Project: https://github.com/excalidraw/excalidraw
- Package: `@excalidraw/excalidraw`
- License: MIT
- Use: whiteboard editor, scene editing, library item handling, and drawing UI primitives.
- Modification note: this app wraps Excalidraw in a custom recording workspace and changes surrounding menus, recording controls, library browsing, localization, and settings surfaces.

## mp4-muxer

- Project: https://github.com/Vanilagy/mp4-muxer
- Package: `mp4-muxer`
- License: MIT
- Use: MP4 muxing for browser recording output.

## MediaPipe Tasks Vision

- Project: https://developers.google.com/mediapipe
- Package: `@mediapipe/tasks-vision`
- License: Apache-2.0
- Use: camera segmentation experiments and related browser-side vision features.

## ffmpeg.wasm

- Project: https://github.com/ffmpegwasm/ffmpeg.wasm
- Packages: `@ffmpeg/ffmpeg`, `@ffmpeg/util`
- License: MIT
- Use: optional browser-side media conversion experiments.

## ffmpeg-static

- Project: https://github.com/eugeneware/ffmpeg-static
- Package: `ffmpeg-static`
- License: GPL-3.0-or-later
- Use: local development dependency currently present in the project. Review before distributing a production build.

## Excalicord Reference

- Project reference: https://www.excalicord.com/
- Repository in this workspace: https://github.com/thinking-one-hour-everyday/excalicord
- License status: no license detected in the fork metadata at the time of review.
- Use policy: referenced for product research, workflow comparison, and experience inspiration. This codebase currently carries historical fork lineage, so this notice is intentionally kept visible until those portions are either replaced, relicensed with permission, or otherwise clarified.

## Smart Teleprompter

- Project: https://github.com/Voumellis/smart-teleprompter
- Website: https://smarttelepromter.com/
- License: MIT
- Use: teleprompter speech following, auto-scroll, script library, file import, shortcuts, display settings, and local persistence.
- Modification note: adapted into `src/components/TeleprompterPanel.tsx` as a scoped Xiangrui whiteboard overlay with local Chinese/English labels and integration with the recording workspace.
