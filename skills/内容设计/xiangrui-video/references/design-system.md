# 万涂幻象视频设计语言（去 AI 味 SSOT，祥瑞 2026-06-11 定）

> 所有设计图（concept/demo/diagram/editorial）统一用这套，形成专属识别度。
> 核心目标：**杀掉 AI 味**——AI 味 = emoji 当图标 + 居中对称堆卡 + 千篇一律玻璃卡 + 荧光连线套路。
> 反面教材：VOL.06「你+军团」图（emoji+十字放射+玻璃卡），一眼 AI 生成。

## 三根支柱

### 1. 编辑排版骨架（场景类型 `editorial`，去 AI 味主场景）
像专业杂志版面，不是 AI 铺的卡：
- **左对齐**大标题（不居中），超大字号，含 `((accent))` 绿字高亮
- **英文眉头** kicker（等宽小字+大字距，如 `WHAT MAKES AN AGENT`）
- **超大编号** 01/02/03（粗黑大数字代替 emoji，首条绿色高亮）
- **细线分隔**的列表（border-top 1.5px），每条：编号 + 能力名 + 英文标签胶囊 + 一句描述
- **竖网格线**背景（设计细节）、右上角 idx_label 标注、**留白有意图**
- items 建议 3 条（4 条窗口偏挤）；元素带 `.in` 由 GSAP 接管错落入场

### 2. 手绘草图质感（Rough.js，`assets/vendor/rough.min.js`）
**对治 AI 味的核心武器**——玻璃卡太规整=AI 味，手绘线条的不规则=人味。
在 demo 场景的 demo_html 里放 `<svg>` + demo_js 里用：
```js
const rc = rough.svg(document.getElementById('rs'));
const svg = document.getElementById('rs');
// 手绘框（hachure 斜线填充）/ 手绘箭头 / 手绘圈注
svg.appendChild(rc.rectangle(x,y,w,h,{stroke:'#7ed8a8',roughness:2.2,strokeWidth:3.5,bowing:1.5,fillStyle:'hachure',fill:'rgba(34,166,103,0.06)'}));
svg.appendChild(rc.line(x1,y1,x2,y2,{stroke:'#22a667',roughness:2,strokeWidth:4}));
```
用途：流程图/关系图/对比/标注，全手绘风（替代规整玻璃卡 diagram）。静态生成，逐帧录制 OK，GSAP 可 animate 入场。

### 3. 开源图表矩阵
- **ECharts**（`assets/vendor/echarts.min.js`）：专业数据图（柱/折线/饼/雷达），
  数字可视化升级。**关掉 echarts 自身动画**（`animation:false`），入场交给 GSAP。
- **Mermaid**（待集成，异步渲染需等 `mermaid.run()` 完成再录制）：声明式流程图/时序图。
- **GSAP**：所有动效引擎，逐帧 seek 确定性。

## 设计常量（品牌一致）
- 配色：墨绿 `#22a667` / 亮绿 `#7ed8a8` / 粉莓 `#e84a6d` / 亮粉 `#ff8fae` / 深底 `#0c0d0c`
- 字体：阿里巴巴普惠 Heavy（正体大字，族名 'YSBTH'）+ 等宽 ui-monospace/Menlo（英文标注）
- accent：`((词))` = 绿字 + 粉莓笔刷下划线

## 去 AI 味禁区（硬规则）
- ❌ **禁 emoji 当图标**（🤖🎨 一眼廉价）→ 用编号/CSS 几何/Rough 手绘图形
- ❌ **禁居中对称堆卡**（十字放射/田字格玻璃卡）→ 编辑式不对称、有视觉重心
- ❌ **禁千篇一律玻璃卡**（同尺寸同圆角铺满）→ 大小/层级/强调差异化
- ❌ **禁招牌场景跨片复用**（对比卡/数字 demo 连套）→ 同意思换呈现
- ✅ 优先：编辑排版的层级感、手绘的人味、留白的呼吸、字体大小的强对比
