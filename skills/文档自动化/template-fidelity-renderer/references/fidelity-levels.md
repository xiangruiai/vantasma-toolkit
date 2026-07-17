# Fidelity Levels

## L1 强保真

输入是可编辑 DOCX，模板里有明确占位符，字段没有被拆进多个 run，机器人环境有模板所需字体或已提供授权字体。

承诺：
- 复制模板作为底稿
- 只替换字段内容
- 保留样式、字体表、编号、设置、页眉页脚
- 输出 DOCX/PDF 和验证报告

适用工具：
- `render_pipeline.py`
- `render_docx.py`
- `prepare_fonts.py`
- `verify_fidelity.py`

## L2 半自动保真

输入是可编辑 DOCX，但没有占位符，只有示例文本或人工说明。

流程：
- 先分析模板结构
- 识别可能替换的示例文本
- 用 `draft_spec.py` 生成保守 spec 草案、TODO 数据脚手架和 warnings
- 输出字段映射建议
- 让用户确认后进行 literal replacement 或改造模板
- 如果是公开学校论文模板，先确认 `placeholders`、`content_controls`、书签和示例文本。没有 tag/alias 的页脚页码内容控件不算可填字段。

风险：
- 示例文本可能跨 run，替换后容易破坏局部样式
- 内容长度超出模板区域时需要人工决策
- 真实论文模板常是格式样张，不是数据模板。只能替换明确示例文本，或先改造成带占位符/spec/reference DOCX 的可填模板。

适用工具：
- `render_pipeline.py`
- `render_pipeline.py --draft-spec`
- `analyze_template.py`
- `fill_by_spec.py`
- `prepare_fonts.py`
- `verify_fidelity.py`

典型能力：
- 用 `paraId`、`text_anchor`、`bookmark`、`content_control` 定位段落字段
- 用 `table_loops` 克隆表格示例行生成报价明细、付款节点、论文附表等重复结构

## L3 视觉仿排

输入是 PDF、截图或图片，没有可编辑 DOCX。

承诺：
- 只能尽量相似
- 不能保证 Word 内部样式、字体表、编号体系一致
- 更适合生成最终 PDF，不适合交付可编辑 DOCX
