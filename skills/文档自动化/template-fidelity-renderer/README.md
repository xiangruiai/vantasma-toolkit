# template-fidelity-renderer

高保真 DOCX 模板填充与验收 Skill。

它适合合同、报价单、项目申报书、报告、课程论文、毕业论文等需要“沿用原 Word 模板，只替换内容”的场景。

## 能做什么

- 复制原始 DOCX 模板，在副本里替换字段
- 支持占位符、段落锚点、书签、内容控件、表格循环、图片替换等路线
- 输出渲染报告，记录哪些字段被填充、哪些字段没命中
- 校验字体、页眉页脚、编号、样式、PDF 导出和可选视觉 diff
- 对缺字体、分页漂移、字段残留、模板结构变化给出明确报告

## 快速使用

```bash
python3 scripts/render_pipeline.py \
  --template TEMPLATE.docx \
  --data DATA.json \
  --output OUT.docx \
  --pdf \
  --compare-template-pdf
```

如果模板里没有明确占位符，可以先生成草案 spec：

```bash
python3 scripts/render_pipeline.py \
  --template TEMPLATE.docx \
  --data DATA.json \
  --output OUT.docx \
  --draft-spec
```

## 使用边界

这个 Skill 的目标是尽可能保留原模板格式，但不承诺所有输入都能 100% 自动完成。缺字体、复杂域代码、目录刷新、页面溢出、PDF 视觉差异，都必须通过报告和人工预览确认。

详细流程见 [SKILL.md](SKILL.md)。

---

## 微信赞赏

这个项目永久免费使用。如果它帮到了你，欢迎[请祥瑞喝杯咖啡](https://pay.xiangruiai.com/?project=template-fidelity-renderer)，鼓励他继续维护并开源更多实用工具。赞赏完全自愿，不解锁任何功能。

---

## 关于万涂幻象

**北京万涂幻象科技有限公司**：以自研的 Agent 上下文与主体连续性技术为底座，在上面跑着企业 AI 落地、课程与培训、品牌宣传三条业务。技术不空转，每一次业务交付都是对底座的一次真实验证。

- [公司业务最新介绍（飞书）](https://waytoagi.feishu.cn/wiki/EAJkw9JcviTt3UkjoyXcKkLzn1W)
- [万涂幻象开源工具箱](https://github.com/xiangruiai/vantasma-toolkit)
- 联系：li@xiangruiai.com
