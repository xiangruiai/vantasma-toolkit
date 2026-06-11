#!/usr/bin/env node
/* 逐帧录制 HTML 场景动画：暂停全部 CSS 动画，逐帧拨 currentTime 后截图，完全确定性。
   用法: node record_scene.js <html路径> <输出帧目录> <W> <H> <时长秒> [fps=30]
   输出: 帧目录/f_00001.png ... 由 render.py 用 ffmpeg 合成视频 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

(async () => {
  const [htmlPath, outDir, W, H, dur, fpsArg] = process.argv.slice(2);
  const fps = parseInt(fpsArg || '30', 10);
  const width = parseInt(W, 10), height = parseInt(H, 10);
  const totalFrames = Math.max(2, Math.round(parseFloat(dur) * fps));
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: [`--window-size=${width},${height}`, '--hide-scrollbars',
           '--force-device-scale-factor=1'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  // 页面默认底透明：媒体场景的"窗洞"框架需要 alpha 通道（不透明页面不受影响）
  const cdp0 = await page.createCDPSession();
  await cdp0.send('Emulation.setDefaultBackgroundColorOverride',
    { color: { r: 0, g: 0, b: 0, a: 0 } });
  await page.goto('file://' + path.resolve(htmlPath), { waitUntil: 'load' });
  // 等字体就绪，避免前几帧字体闪替
  await page.evaluate(() => document.fonts.ready);
  // 接管时间轴：CSS/WAAPI 动画归零暂停；GSAP 走 rAF 不在 getAnimations 里，单独接管全局时间线
  await page.evaluate(() => {
    document.getAnimations().forEach((a) => { a.pause(); a.currentTime = 0; });
    if (window.gsap && window.gsap.globalTimeline) {
      window.gsap.globalTimeline.pause();           // 停掉 rAF 驱动，改由我们逐帧 seek
      window.gsap.ticker.lagSmoothing(0);
    }
  });

  const client = await page.createCDPSession();
  const stepMs = 1000 / fps;
  for (let i = 0; i < totalFrames; i++) {
    await page.evaluate((t) => {
      document.getAnimations().forEach((a) => { a.currentTime = t; });
      // GSAP 确定性 seek：把全局时间线拨到 t 秒（含所有 tween/timeline/stagger）
      if (window.gsap && window.gsap.globalTimeline) {
        window.gsap.globalTimeline.totalTime(t / 1000);
      }
    }, i * stepMs);
    const shot = await client.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(outDir, `f_${String(i + 1).padStart(5, '0')}.png`),
      Buffer.from(shot.data, 'base64'));
  }
  await browser.close();
  console.log(`recorded ${totalFrames} frames @ ${fps}fps -> ${outDir}`);
})().catch((e) => { console.error(e); process.exit(1); });
