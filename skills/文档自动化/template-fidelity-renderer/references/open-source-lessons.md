# Open Source Lessons

本 skill 吸收这些开源项目的设计思想，但不直接复制实现。

## eigenpal/docx-template-skill

Repository: https://github.com/eigenpal/docx-template-skill

可吸收点：
- 从多个已填好的 DOCX 中比较“变化字段”和“不变模板”。
- 识别变量、表格行循环、段落块循环和条件段。
- 字段命名要稳定，循环字段用复数。
- 替换文本时尽量只修改命中的 `w:t`，保留其他 run 的样式。
- 对跨 run 命中的文本要有专门测试，防止破坏 bold/italic/color/font size。

对我们的启发：
- 增加“反推模板模式”：当祥瑞给 2 份同类已填合同/表单/论文封面时，先比较差异，再建议占位符和循环结构。
- 对每个替换算法写最小 XML 级测试，验证样式没有被改。

## hey-yulee/spec-driven-docx-template-fill

Repository: https://github.com/hey-yulee/spec-driven-docx-template-fill

可吸收点：
- 用 `template_spec.json` 描述模板如何填写，而不是每次靠自然语言临场发挥。
- 支持多种 locator：`paraId`、`text_anchor`、`bookmark`、`content_control`、`xpath`。
- 区分 `template_source` 和 `reference_source`。空模板负责输出骨架，参考样张负责长文本段落数量、缩进、行距、run 样式。
- 分离 analyze、fill、verify 三阶段，并输出 render report。
- 必填字段缺失、locator 找不到、渲染文本不匹配都应报错。

对我们的启发：
- 在 `{{字段}}` 之外，增加 spec 驱动填充模式。
- 分析报告要输出段落 inventory，包含 index、paraId、textId、styleId 和文本摘要。
- 长正文优先从参考样张克隆段落样式，不凭 AI 自己排版。

## alonrbar/easy-template-x

Repository: https://github.com/alonrbar/easy-template-x

可吸收点：
- 插件化处理 text、loop、image、link、chart、rawXml。
- 文本替换支持多行，用 `w:br` 放在原 run 中，保留 run 样式。
- 插入链接时复制原 run 的属性，避免新内容样式漂移。
- raw XML 插入必须区分替换 text node 还是整段 paragraph。

对我们的启发：
- 第一版先做 text 和 paragraph spec，再加 table loop、已有图片替换，后续补 link、chart、raw XML 插件。
- 多行文本不要直接塞进一个 `w:t`，应按模式选择 line breaks 或 paragraphs。

## 2026-07-16 GitHub 再对照

参考项目：
- https://github.com/elapouya/python-docx-template
- https://github.com/open-xml-templating/docxtemplater
- https://github.com/Sayi/poi-tl
- https://github.com/plutext/docx4j
- https://github.com/antonmihaylov/OpenXmlTemplates

共同模式：
- 成熟 DOCX 模板引擎都假设模板里有显式机器锚点，如 Jinja/tag、占位符、内容控件、custom XML 或 OpenDoPE 绑定。
- 这些项目的强项是“模板已结构化之后的稳定渲染”，不是从普通学校格式样张里自动猜字段。
- content controls/customXml 比普通可见文本更适合做严肃模板 API，因为 tag/alias/binding 可与数据字段稳定对应。

对我们的启发：
- `--auto-content-controls` 只能在内容控件有 tag/alias 且能匹配数据字段时自动启用；无 tag/alias 的页码控件不能当字段。
- 公开高校论文 DOCX 模板如果没有占位符和 tag/alias 内容控件，应归为 L2，先生成字段映射或改造模板，不承诺 100% 自动字段识别。
- 我们自己的差异化仍是验收层：字体计划、PDF 字体检查、字段局部格式签名、invariant parts、视觉 diff 和明确 warning。

## 真实高校模板前向测试

2026-07-16 抽取公开高校 DOCX 模板做前向测试：
- 北京大学本科毕业论文模板：无占位符、无内容控件，但有 `[此处键入中文标题]`、`[此处键入摘要]` 等明确示例文本。`render_docx.py --strict` 的 literal replacement 可全部命中，`text_format_checks.preserved=true`，`verify_fidelity.py` 能确认核心格式未漂移，同时如实报告本机缺 `Calibri`、`Cambria`。
- 南开大学生命科学学院本科毕业论文模板：无占位符，有 3 个内容控件，但都在页脚页码类区域且无 tag/alias，不能作为业务字段自动匹配。

内化规则：
- 真实学校模板先按“格式样张”评估，不默认按“可填数据模板”评估。
- 有明确示例文本时可做 literal replacement，但必须开 strict 并输出 render/verify report。
- 没有机器锚点的长正文、章节、图表、参考文献，应要求 reference DOCX 或先改造模板。

## 设计取舍

- 这些项目都证明：高保真 DOCX 生成不是“AI 看图仿排”，而是“模板结构化 + XML 级操作 + 验证报告”。
- 我们的差异化是补上字体依赖、PDF 字体覆盖、页数变化和视觉验收。开源项目大多不把字体和 PDF 结果作为第一等级门槛。

## 已内化到当前 skill 的能力

- `render_pipeline.py`：把 analyze、font plan、render、verify 串成一条可复用流水线，减少人工漏检；同时生成 `<stem>.pipeline.json`、`<stem>.pipeline.md`、`<stem>.delivery.json` 和 `<stem>.delivery.md`，让交付时可以快速看到状态、决策建议、artifact 路径、缺字体、失败检查、字段刷新证据和 post-refresh drift；支持 `--auto-content-controls` 从内容控件 `spec_candidate` 和数据字段 tag/alias 自动生成临时 spec，也支持 `--draft-spec` 从单份 DOCX 格式样张生成保守草案并在没有显式 spec 或可用内容控件 spec 时自动走 `fill_by_spec.py` 渲染；自动把 render report 交给 verifier 做字段局部格式签名验收。
- `check_delivery.py`：把 pipeline JSON 转成交付硬门禁，输出 `ready` / `needs_review` / `blocked`、blockers、warnings 和 artifact 路径。它默认阻断缺字体、验证失败、输出缺失、未替换占位符、render 错误、field-refreshed sidecar 验证失败和 post-refresh core drift；也支持要求真实字段刷新、PDF 和视觉 diff。
- `package_delivery.py`：把 pipeline JSON 对应的 DOCX/PDF/报告汇总成带 `manifest.json` 的 ZIP 交付包。默认拒绝 blocked delivery gate；显式 `--include-blocked` 时只做 evidence package，并把 blockers/warnings 写进 manifest。
- `request_field_update.py` + `render_pipeline.py --request-field-update`：对目录、页码、交叉引用、日期等 Word 字段，只设置 `word/settings.xml` 里的 `w:updateFields=true` 并写报告，请求 Word 打开时刷新；它不是字段计算引擎，最终仍需 Word/LibreOffice 更新后再做 PDF/视觉验收。
- `refresh_fields.py` + `render_pipeline.py --refresh-fields`：把字段刷新升级成可审计 sidecar。能使用 Microsoft Word AppleScript、LibreOffice CLI 重存或 LibreOffice UNO 时，尝试更新 fields/indexes 并另存 `<stem>.field-refreshed.docx` / PDF；后端不可用时退回 request-only，但报告里的 `actual_field_results_refresh=false` 会阻止误判为已刷新。`post_refresh_drift` 会直接列出外部引擎重存前后被改动的 DOCX parts，特别标出 styles/fontTable/numbering/theme 等核心保真风险。pipeline 会继续为刷新后的 sidecar 生成 `<stem>.field-refreshed.verify.json`，避免只验主输出却交付重存后的文件。
- `run_field_refresh_live_check.py`：用最小 `PAGE` 字段 fixture 验证本机后端是否真的能把过期字段结果刷新掉。它让“本机能不能实机刷新字段”变成可重复测试，而不是靠安装印象判断。
- `infer_template.py`：从多份已填 DOCX 中比较 body 段落、页眉页脚/脚注尾注段落和表格行差异，输出字段、`text_part_fields`、整段条件块、明显可选表格行条件块、表格循环、占位符模板和 spec 草案。
- `draft_spec.py`：从单份 DOCX 格式样张生成保守 L2 草案，只把明确占位符、完整段落示例文本、带 tag/alias 的内容控件提升为 spec 字段；完整段落示例文本默认写 `replacement_mode: "literal_text"`，交给 `fill_by_spec.py` 做跨 text node 保结构替换；checkbox 内容控件默认写 `replacement_mode: "checkbox"`；嵌入式示例文本进入 literal replacement 候选并写 warnings，避免把普通格式样张误判成完整数据模板。
- `analyze_template.py`：输出段落 inventory、`paraId`、表格摘要、字体表、关键 OOXML 部件 hash，以及跨正文/页眉/页脚/脚注/尾注的内容控件 inventory 和可直接转 L2 spec 的 `spec_candidate`。
- `prepare_fonts.py`：先做字体可用性和候选字体报告，只有显式 `--install` 才复制本地授权字体。
- `render_docx.py`：L1 占位符替换，支持单 run 和跨 run token，只改命中文本节点，保留模板 zip 结构；render report 写 `text_format_checks`，对被改 text part 清空文本后比较格式结构 hash。
- `fill_by_spec.py`：L2 spec 填充，支持 `paraId`、`text_anchor`、`bookmark`、`content_control`、`image_index`、`image_alt_text`、跨 text part 的 `part` 定位、分节页眉页脚 part 定位、分节页眉页脚继承上一节默认阻断、内容控件文本填充并保留 SDT wrapper/tag/alias、checkbox 内容控件勾选状态和显示符号填充、跨 run token、literal 字段 `literal_text_replace` 跨 text node 保结构替换、已有 hyperlink 替换、新 hyperlink 插入、`reference_block` 段落级样式克隆、缺失样式定义合并、直接编号定义迁移、缺失样式内部编号迁移、外部超链接关系迁移、内嵌图片关系/媒体迁移、脚注/尾注/批注迁移、修订/域代码复杂结构门禁报告、`conditional_blocks`、顶层/嵌套 `table_loops` 和 `image_fields`；普通文本字段写 `format_check`，对比字段前后 `pPr/rPr/sdtPr` 签名；表格循环写行/单元格级 `format_check`，对比模板行与每条插入行的 `trPr/tcPr/pPr/rPr` 签名。
- `verify_fidelity.py`：检查 invariant parts、未替换 token、内容控件 wrapper/tag/alias 是否保留、render report 里的普通文本字段和表格循环 `tracked_text_format_preserved`、缺字体、PDF 导出、PDF 字体嵌入、PDF 是否真正覆盖模板字体，以及可选 PDF 单页/多页视觉 diff。视觉 diff 支持页眉、页脚、页码和自定义动态区域白名单，并输出 mask 图；有 render report 或 field-update report 依据的 reference style/numbering/settings change 可通过 pipeline 自动白名单对应 OOXML part。
- `run_regression_tests.py`：用自动生成的 DOCX fixture 回归页眉页脚文本结构保真、字段局部格式签名保真与负例失败、表格循环行/单元格格式签名保真与负例失败、分节页眉页脚定位、分节页眉页脚继承门禁、内容控件文本填充、内容控件 checkbox 填充、单模板草案生成和 pipeline 自动草案渲染、pipeline Markdown 交付摘要、delivery gate ready/needs_review/blocked 门禁、delivery ZIP 打包与 blocked gate 拒绝、字段刷新请求、字段刷新 sidecar request-only 边界、自动内容控件 pipeline、验证保留检查、跨 run 占位符、spec 顶层表格循环、spec 嵌套表格循环、spec 页眉页脚字段、spec 图片替换、spec 条件块、已有 hyperlink 替换、新 hyperlink 插入、reference block 段落样式克隆、缺失样式定义合并、直接编号定义迁移、缺失样式内部编号迁移、外部超链接关系迁移、内嵌图片关系/媒体迁移、脚注/尾注/批注迁移、修订/域代码复杂结构门禁、反推模板 text part 字段、反推条件段、反推条件表格行和视觉忽略配置，防止后续脚本改动破坏已有能力。

## 2026-07-17 内容控件再内化

GitHub 对照结论：
- 没找到比 `eigenpal/docx-template-skill` 更接近“机器人 skill”的完整开源实现；多数成熟项目是模板引擎，不负责 agent workflow。
- `OpenXmlTemplates` 这类项目更值得吸收的是方法论：把 Word 内容控件当稳定 API，靠结构化字段绑定，而不是让 AI 猜视觉位置。
- 合同和表单里常见 dropdown/comboBox，例如付款方式、交付方式、发票类型、币种、文档类型，不能继续当普通文本字段处理。

已内化：
- `analyze_template.py` 抽取 `w:dropDownList` / `w:comboBox` 的 `w:listItem` 为 `options`，并在 `spec_candidate` 写 `replacement_mode: "choice"`。
- `draft_spec.py` 对带 tag/alias 的 dropdown/comboBox 生成 choice 字段，保留可选项，方便人工复核。
- `render_pipeline.py --auto-content-controls` 保留 choice mode 和 options。
- `fill_by_spec.py` 对 dropdown 做枚举校验，值不在模板选项内时报错 `choice_value_not_in_options`；comboBox 或显式 `allow_unlisted_choice: true` 才允许自定义值，并在报告中写 `custom_value: true`。
- `run_regression_tests.py` 增加 `test_spec_content_control_choice`，覆盖分析、草案、填充、非法选项失败、自动内容控件 pipeline 和 verifier 保留检查。

## 2026-07-17 dataBinding/customXml 内化

GitHub 对照结论：
- OpenXmlTemplates、docx4j/OpenDoPE 一类路线说明，严肃 Word 模板常把内容控件绑定到 custom XML，而不是只靠可见文本或 tag。
- 完整 OpenDoPE 逻辑仍较大，但 dataBinding 对应的 customXml 数据源写回可以先做到可验证闭环，避免只改可见文本导致模板内数据源陈旧。

已内化：
- `analyze_template.py` 抽取 `w:dataBinding` 的 `xpath`、`storeItemID`、`prefixMappings`，binding-only 控件也生成 `spec_candidate`，字段 key 从 XPath 最后一段派生。
- `draft_spec.py` 把无 tag/alias 但有 dataBinding 的内容控件纳入草案字段，保留 binding locator。
- `render_pipeline.py --auto-content-controls` 支持用 binding 派生 key 或原始 XPath 匹配数据字段。
- `fill_by_spec.py` 支持按 `locator.binding`、`binding_xpath`、`store_item_id` 或 `index` 定位内容控件并填充显示内容；同时按 `storeItemID` 找到匹配的 `customXml/item*.xml`，用保守 XPath 写回绑定数据源，并在 render report 记录 `custom_xml_update`。
- `verify_fidelity.py` 把 dataBinding 纳入内容控件签名，确保渲染后 binding 元数据没有丢失或漂移。
- `run_regression_tests.py` 增加 `test_spec_content_control_databinding`，fixture 包含真实 `customXml/item1.xml`、`itemProps1.xml`、item rels 和 package rel，覆盖分析、draft、显式 spec、自动 spec、可见文本填充、customXml 写回和 verifier 保留检查。

## 2026-07-17 repeatingSection 内化

GitHub 对照结论：
- Word 内容控件路线不只有单值字段。合同明细、表单子项、论文附录条目这类重复结构可以用 Word 原生 `repeatingSection` / `repeatingSectionItem` 表达，比让 agent 临场重建版式更稳。
- 真实 DOCX 中 repeatingSection 常见命名空间是 `w15:`，不能只查 `w:` 标签名。
- 重复节填充必然改变内容控件数量，verifier 需要区分“有 render report 证明的克隆”与“无依据的 SDT 漂移”。

已内化：
- `analyze_template.py` 和 `verify_fidelity.py` 按 local-name 识别 `w15:repeatingSection` / `w15:repeatingSectionItem`。
- `analyze_template.py`、`draft_spec.py` 和 `render_pipeline.py --auto-content-controls` 对 tagged repeatingSection 生成 `replacement_mode: "repeating_section"`。
- `fill_by_spec.py` 只支持保守克隆：模板必须已有 `repeatingSection` 外壳和至少一个 `repeatingSectionItem` 示例块；数据必须是数组；每条数据克隆示例块，并在块内替换 `{{字段}}` 或同名嵌套内容控件。
- `verify_fidelity.py` 只有在 render report 出现 `content_control_repeating_section` 时，才允许 repeatingSection 内部克隆导致的内容控件数量变化。
- `run_regression_tests.py` 增加 `test_spec_content_control_repeating_section`，覆盖分析、draft、显式 spec、自动 spec、克隆填充和 verifier 保留检查。

## 2026-07-17 date 内容控件内化

GitHub 对照结论：
- 合同签署日期、报价有效期、报告日期、论文封面日期经常用 Word 原生 `w:date` 内容控件，不应只把它当普通文本控件处理。
- 日期控件有两层状态：可见 `w:t` 展示文本，以及 `w:date` 上的 `w:fullDate` 和 `w:dateFormat` 等元数据。只改显示文本会让控件内部日期陈旧。
- 不同地区日期展示格式差异很大，渲染器不应猜中文日期格式；对 `YYYY-MM-DD` 或 ISO datetime 可安全写 `w:fullDate`，非 ISO 展示文本只更新可见文本并报告 warning。

已内化：
- `analyze_template.py` 抽取 `w:date` 的 `fullDate`、`dateFormat`、`lid`、`storeMappedDataAs` 和 `calendar`，并在 `spec_candidate` 写 `replacement_mode: "date"`。
- `draft_spec.py` 和 `render_pipeline.py --auto-content-controls` 保留 date mode 和模板 date 元数据。
- `fill_by_spec.py` 新增 `content_control_date`：填充显示文本；当数据是 `YYYY-MM-DD`、ISO datetime，或对象里带 `full_date` 时，同步写回 `w:fullDate`；若只是中文展示日期，则不猜内部日期并在报告中写 warning。
- `run_regression_tests.py` 增加 `test_spec_content_control_date`，覆盖分析、draft、显式 spec、自动 spec、显示文本填充、`w:fullDate` 更新和 verifier 保留检查。

## 2026-07-17 locked content-control 内化

GitHub 对照结论：
- Word 内容控件不只是字段锚点，也可能表达模板作者的编辑边界。`w:lock` 中的 `contentLocked` 和 `sdtContentLocked` 应被当作风险门禁，而不是被普通文本替换绕过。
- 合同、审批单、学校论文模板里，锁定控件常用于保护固定条款、格式壳或只能由模板系统写入的区域。默认尊重锁定，比默认强行覆盖更符合高保真模板渲染。

已内化：
- `analyze_template.py` 抽取 `w:lock`，并在 `spec_candidate` 中保留 lock 值。
- `draft_spec.py` 和 `render_pipeline.py --auto-content-controls` 传递 lock 元数据，方便人工确认哪些字段是受保护区域。
- `fill_by_spec.py` 对 `contentLocked` / `sdtContentLocked` 默认报错 `content_control_locked`，只有字段显式 `allow_locked_content_control: true` 才允许填充；允许填充时在 render report 写 `content_control_lock`，保留可追溯证据。
- `run_regression_tests.py` 增加 `test_spec_content_control_lock_guard`，覆盖分析、草案、默认阻断、显式覆盖和 verifier 保留检查。

## 2026-07-17 multiline line-break 内化

GitHub 对照结论：
- `easy-template-x`、`docxtemplater` 这类成熟模板引擎会把多行文本转成 Word 原生换行结构，而不是把裸 `\n` 塞进 `w:t`。
- 单段字段里的换行和长正文多段不是同一件事。前者应该用 `w:br`，后者应该用 paragraph cloning、`reference_block` 或显式 `multiline_mode: "paragraphs"`。
- 插入 `w:br` 会带来预期 OOXML 结构变化，验证层必须有报告证据才能放行，不能简单忽略所有结构漂移。

已内化：
- `render_docx.py` 在 L1 占位符和 literal replacement 中把字段值里的 CRLF/LF 统一实体化为 `w:br`，并在 `text_format_checks` 写 `line_breaks_inserted` 与 `expected_structure_change: "line_breaks_inserted"`。
- `fill_by_spec.py` 在 token、literal、普通内容控件文本和默认单段段落替换中支持同样的 `w:br` 实体化，并把换行证据写入字段级 `format_check`。
- `verify_fidelity.py` 只对带有 `expected_structure_change: "line_breaks_inserted"` 的 tracked format 差异放行，其他格式漂移仍然失败。
- `run_regression_tests.py` 增加 `test_multiline_line_break_rendering`，同时覆盖 L1 和 L2 的 `w:br` 输出、报告证据和 verifier 放行。

## 2026-07-17 bookmark 字段内化

GitHub 对照结论：
- spec-driven DOCX 填充路线把 bookmark 当成稳定 locator 是合理的，但不能把 bookmark 所在整段都当字段。合同和论文模板里常见 `甲方：<bookmark>旧值</bookmark>` 这种行内字段。
- 空 bookmark 也很常见，相当于模板作者预留的插入点。填充时应保留 `bookmarkStart` / `bookmarkEnd`，在二者之间插入文本 run，并把这类结构变化写入报告。
- 空 bookmark 的字体字号不应该随便取段落第一段 run。更接近 Word 光标输入的做法，是优先继承 bookmark 左右最近 run 的 `w:rPr`，没有临近样式时再退回段落样式种子。
- bookmark 与 content control 一样是模板 API。它比可见文本锚点更稳定，但比 content control 少类型元数据，因此默认只做文本范围替换。

已内化：
- `analyze_template.py` 对正文、页眉、页脚、脚注、尾注的命名 bookmark 生成 inventory 和 `replacement_mode: "bookmark_text"` 的 `spec_candidate`，隐藏 `_` bookmark 只记录不自动提升。
- `draft_spec.py` 把命名 bookmark 提升为 L2 spec 字段，默认使用 `locator_type: "bookmark"` 和 `replacement_mode: "bookmark_text"`。
- `fill_by_spec.py` 默认只替换 bookmarkStart/bookmarkEnd 范围内文本；空 bookmark 会在 start/end 之间插入 run，优先继承最近相邻 run 的 `w:rPr`，在字段报告写 `run_style_source`，并在字段 `format_check` 写 `expected_structure_change: "bookmark_empty_range_inserted"`。
- `verify_fidelity.py` 只对有 render report 证据的空 bookmark 插入结构变化放行。
- `run_regression_tests.py` 增加 `test_spec_bookmark_text_replace`，覆盖 analyze、draft、行内 bookmark 替换、空 bookmark 插入、相邻 run 字体字号继承和 verifier 放行。

## 2026-07-17 空 run 样式保真内化

GitHub 对照结论：
- Word 内容控件常把“可填字段”表达成一个没有文本、但已经带 `w:rPr` 字体字号的空 run。成熟模板引擎的关键不是生成新文本，而是尽量复用模板已有 run/paragraph 属性。
- 如果渲染器在空 run 旁边新建无样式 run，DOCX 仍可能打开，但字体、字号、加粗、颜色会落到默认值，论文和合同模板肉眼看起来就会漂。
- run-level 内容控件必须保持 run-level。把它填成段落级结构会改变 inline flow，容易破坏同一行里的前后缀文本。

已内化：
- `fill_by_spec.py` 增加空文本 run 识别：当目标内容控件里存在只含 `w:rPr` 的 `w:r` 时，直接把文本和 `w:br` 写入该 run，报告 `run_reused: true`。
- 内容控件没有可复用空 run 但有段落时，新建 run 会优先复制段落中已有 run 的 `w:rPr`，减少字体字号丢失。
- `run_regression_tests.py` 增加 `test_spec_content_control_empty_run_style`，覆盖空 run 的 `Courier New` / `SimSun` / `w:sz` / bold 保留、run-level 结构不变、`tracked_text_format_preserved` 通过。

## 2026-07-17 content-control placeholder 状态内化

GitHub 对照结论：
- `OpenXmlTemplates` 与 Word 内容控件路线反复证明，内容控件不只是文本容器，而是带状态的模板 API。`w:sdtPr` 里的元数据和 `w:sdtContent` 里的可见文本一样重要。
- `OfficeAgent.NET` 的思路更接近 agent workflow：先 inspect 文档结构，再生成可验证的编辑计划，最后 commit 到 DOCX。我们的 `analyze_template.py` / `draft_spec.py` / `fill_by_spec.py` / `verify_fidelity.py` 应继续保持这种分阶段证据链。
- `w:showingPlcHdr` 表示内容控件仍处于 placeholder 展示状态。填入正式内容后若不清理，Word 可能继续把正式文本当占位提示处理，这属于状态漂移，不是纯视觉问题。

已内化：
- `analyze_template.py` 抽取内容控件的 `showing_placeholder`，并传入 `spec_candidate`。
- `draft_spec.py` 对带 tag/alias/dataBinding 的内容控件保留 `showing_placeholder`，让草案 spec 能暴露“这是占位控件”。
- `render_pipeline.py --auto-content-controls` 通过 analyze 结果继承 placeholder 状态，避免自动 spec 丢失模板作者意图。
- `fill_by_spec.py` 在普通文本、checkbox、date、choice 和 repeatingSection 内容控件填充后清理 `w:showingPlcHdr`，并在 render report 写 `placeholder_removed` 与 `expected_structure_change: "content_control_placeholder_removed"`。
- `verify_fidelity.py` 把 `showing_placeholder` 纳入内容控件签名；只有 render report 明确证明 placeholder marker 被填充清理时，才允许该状态从 true 变 false。
- `run_regression_tests.py` 在 `test_spec_content_control_text` 里构造真实 `w:showingPlcHdr` fixture，覆盖 analyze、显式 spec 填充、auto-content-control pipeline 和 verifier 放行。

## 2026-07-17 plain text multiLine 内容控件内化

GitHub 对照结论：
- 内容控件路线里，plain text 控件的 `w:text` 不是“普通文本”的同义词，它还可以用 `w:multiLine` 表达模板作者是否允许多行输入。
- 学校论文模板的摘要、备注栏、合同补充说明、客户需求描述等字段，经常需要在一个内容控件里保留换行。只要模板明确给了 `w:multiLine=1`，渲染器应把它当作模板 API 元数据，而不是仅从可见文本猜。
- 多行内容的表达仍应使用 Word 原生 `w:br`，不能把裸换行塞进 `w:t`；同时 verifier 要确认 `w:text/w:multiLine` 没被渲染器弄丢。

已内化：
- `analyze_template.py` 抽取 plain text 内容控件的 `text_control.multi_line` 和 `multi_line_raw`，并传入 `spec_candidate`。
- `draft_spec.py` 与 `render_pipeline.py --auto-content-controls` 透传 `text_control`，让显式草案和自动 spec 都保留多行能力。
- `fill_by_spec.py` 在普通内容控件文本填充报告中写 `text_control`；当模板允许 multiLine 时写 `content_control_multiline: true`，当单行 plain text 控件被塞入换行时写 warning。
- `verify_fidelity.py` 把 `text_control` 纳入内容控件签名，防止输出 DOCX 丢失 `w:multiLine`。
- `run_regression_tests.py` 扩展 `test_spec_content_control_text`，同时覆盖 block 内容控件、run-level 内容控件、placeholder 状态清理和 `w:text w:multiLine=1` 多行内容控件的 `w:br` 输出。

## 2026-07-17 hyperlink 字段内化

GitHub 对照结论：
- `docxtemplater`、`easy-template-x` 这类模板引擎处理链接时，关键不是只改可见文字，而是同时维护 DOCX package 里的 relationship。Word 的外部链接 URL 不在 `word/document.xml` 文本里，而在对应的 `word/_rels/*.xml.rels`。
- 合同、报价单、论文封面和报告页脚常把官网、邮箱、表单、飞书文档写成已有 hyperlink。把它当普通 literal 替换会保留显示文本，却可能让链接目标、`r:id` 或 wrapper 失真。
- 草案工具不能默认把所有链接提升为待填字段。导航链接、固定官网、页脚备案链接很多时候不是业务字段，应先作为 candidate 暴露，让人确认后再填。

已内化：
- `analyze_template.py` 新增 `hyperlinks` inventory，记录 `part`、`index`、`text`、`relationship_id`、`target`、`target_mode`、`relationship_part` 和可复制到 spec 的 `locator_type: "hyperlink"` candidate。
- `draft_spec.py` 把已有链接放入 `hyperlink_candidates` 和 warning，不自动写入可执行 spec 字段，避免 `--draft-spec` 误伤模板导航链接。
- `fill_by_spec.py` 支持 `locator_type: "hyperlink"`，可按可见文本、URL target、relationship id 或 index 定位模板已有 `w:hyperlink`；字段值为字符串时只替换显示文本，字段值为 `{text,url}` 时同时更新 `.rels` 外部链接目标。
- hyperlink 替换保留 `w:hyperlink` wrapper、relationship id、段落和 run 格式签名，并在 render report 写 `relationship_before`、`relationship_after`、`target_before`、`target`、`relationship_updated` 和字段级 `format_check`。
- `run_regression_tests.py` 新增 `test_spec_hyperlink_field`，覆盖 analyze、draft candidate、显示文本替换、URL target 更新、wrapper 保留和 verifier 的 `tracked_text_format_preserved`。
- `fill_by_spec.py` 新增 `replacement_mode: "insert_hyperlink"`：可把普通 placeholder、literal 或 text_anchor 替换为新的 `w:hyperlink`，创建或复用当前 text part `.rels` 中的 External hyperlink relationship，并尽量继承原占位符 run 的 `w:rPr`。
- 新 hyperlink 插入会在 render report 写 `action: "hyperlink_insert"`、`relationship_id`、`target`、`target_mode` 和 `expected_structure_change: "hyperlink_inserted"`；`verify_fidelity.py` 只对这种有证据的结构变化放行。
- `run_regression_tests.py` 新增 `test_spec_hyperlink_insert`，覆盖普通占位符到 `w:hyperlink` 的插入、External `.rels` target、后续文本保留和 verifier 放行。

## 2026-07-17 reference styleId 冲突门禁内化

GitHub 对照结论：
- `docxcompose`、`docxtemplater`、`easy-template-x` 等路线都绕不开一个事实：Word 段落引用的是 styleId，不是“样式长得像不像”。如果目标模板已有同名 styleId，克隆 reference 段落时不会自动带上 reference 的样式定义。
- 同名 styleId 但定义不同，比缺失样式更危险。缺失样式可以复制；同名冲突如果静默继续，输出 DOCX 能打开，段落也看似套了样式，但字体、字号、缩进或编号实际会沿用目标模板版本。
- 高保真场景里，这类冲突应该默认阻断，除非用户明确接受“使用目标模板同名样式，而不是 reference 样式定义”。

已内化：
- `fill_by_spec.py` 在 `import_missing_styles_from` 中对 reference block 用到的既有 styleId 计算 reference/target 样式 XML hash，发现不同就写入 `reference_styles.existing_style_definition_conflicts`。
- `reference_block` 默认遇到 `existing_style_definition_conflicts` 报错 `reference_style_conflicts`，只有字段显式 `allow_reference_style_conflicts: true` 才继续渲染。
- 允许冲突时仍不会覆盖目标模板已有样式，报告保留 reference/target hash，提醒这是一种人工认可的格式降级。
- `run_regression_tests.py` 新增 `test_reference_block_style_conflict_guard`，覆盖默认阻断和显式放行。

## 2026-07-17 条件块反推内化

GitHub 对照结论：
- 多已填文档反推模板时，字段、循环和条件不能用同一套 index diff 粗暴处理。可选条款会造成后续段落 index 位移，如果不先识别条件段，很容易把“位移”误判成字段变化。
- 条件推断要保守。成熟模板路线通常要求明确 marker 或结构锚点，自动推断只能覆盖非常清晰的整块缺失，不应该猜测改写过的语义条件。表格行条件尤其容易和明细循环混淆，必须要求明显可选信号和前后行锚点。
- 从第一份样张生成 placeholder template 时，给可选段落加显式 marker，比在生产时按文本删除更可审计，也方便后续人工改名和加条件。

已内化：
- `infer_template.py` 新增保守整段条件块推断：只识别“第一份样张里存在、至少一份其他样张整段缺失”的正文直系段落。
- 推断出的条件段会写入 `conditional_blocks` report，记录 paragraph indices、缺失样张、marker 文本和两套 spec：无模板时用 `paragraph_contains`，生成 placeholder template 时用 `marker_pair`。
- `write_placeholder_template` 会在可选段落前后插入 `{{#if key}}` / `{{/if key}}`，生成的 spec 可直接被 `fill_by_spec.py` 按 conditions keep/remove，并自动清理 marker。
- 普通 paragraph field 推断会跳过被识别为 optional 的第一样张段落，避免后续段落位移制造假字段。
- `infer_template.py` 新增明显可选表格行条件块推断：只识别第一份样张中有 optional/质保/支持/服务费/折扣等信号、至少一份其他样张缺失、且前后行锚点仍存在的中间行；生成 `table_row_contains` spec 时写入 `locator.table_index`，避免同名行跨表误删。
- 表格循环推断会跳过已识别为条件行的 row signature，并避开 Total/合计等汇总行，减少把可选费用行或汇总行误判成明细循环。
- `run_regression_tests.py` 新增 `test_infer_template_conditional_paragraphs`，覆盖推断、marker 注入、false 删除、true 保留和 marker 清理。
- `run_regression_tests.py` 新增 `test_infer_template_conditional_table_rows`，覆盖可选表格行推断、`table_index` locator、false 删除、true 保留和避免误判为 table_loop。

## 2026-07-17 Progressive Disclosure 内化

Skill 维护结论：
- `SKILL.md` 超过 500 行后，触发成本和上下文噪音都会上升。复杂能力不应该全部堆在入口文件里。
- 模板 spec 的 locator、reference block、conditional、table loop、image 和 hyperlink 示例属于“需要写 spec 时才读”的细节，适合放入一层 references。

已内化：
- 新增 `references/spec-patterns.md`，集中保存 `template_spec.json` 的核心形状、locator、text part、hyperlink、reference block、conditional block、table loop 和 image field 写法。
- `SKILL.md` 从 609 行压缩到 322 行，只保留主流程、路线选择和 reference 路由。
- 将既有 `references/fidelity-levels.md` 挂到主文档，供 L1/L2/L3 边界判断时按需读取。

## 2026-07-17 模板成熟度评估内化

真实模板测试结论：
- 公开高校论文模板和客户合同模板常常只是“格式样张”，不是机器可寻址的数据模板。只靠肉眼看起来像模板，不足以承诺 100% 自动填充。
- 在生产渲染前，需要一个客观的 readiness gate：先判定 L1/L2/L3、统计占位符/内容控件/bookmark/表格/缺字体，再决定能否承诺强保真。
- 字体探测是高频公共步骤。`analyze_template.py`、`prepare_fonts.py`、`verify_fidelity.py` 如果各自重复跑 macOS `system_profiler SPFontsDataType`，真实模板批量回归会被无关 I/O 拖慢。
- 浙江师范大学公开毕业论文 DOCX 模板实测：模板有 160 个 bookmark，其中绝大多数是 `_Toc...` 目录书签，另有非隐藏 `MTUpdateHome` 系统书签；这些不应被当作业务字段。修复后 readiness 判为 L2 `format-sample-draft-spec`，score 32，`can_claim_100_percent=false`，`draft_spec.py` 输出 0 字段并给 `no_stable_fields` warning。
- 学位论文模板常含自动目录、页码、交叉引用、公式、修订或嵌入对象。这些不是普通文本格式问题，而是 Word 的 field code / Office Math / revision / OLE 结构。填充器可以尽量不碰它们，但不能承诺自动刷新目录、公式编号和交叉引用。

已内化：
- 新增 `scripts/assess_template_readiness.py`，输入 DOCX 后自动调用 `analyze_template.py`，输出 `level`、`score`、`can_claim_100_percent`、`blockers`、`warnings`、`recommended_route` 和 `upgrade_actions`，并可生成 Markdown 报告。
- L1 占位符模板推荐 `render_pipeline.py`；有 tag/alias/dataBinding 内容控件的 L2 模板推荐 `--auto-content-controls`；只有示例文本的高校格式样张推荐 `--draft-spec`，并明确拒绝 100% 自动字段识别承诺。
- `analyze_template.py`、`draft_spec.py` 和 `assess_template_readiness.py` 过滤 Word/WPS/插件系统书签，如 `_Toc...`、`MTUpdateHome`、`OLE_LINK...`、`DDE_LINK...`，避免误判成稳定业务锚点。
- `draft_spec.py` 在没有任何稳定字段或 literal replacement 时写入 `no_stable_fields` warning，要求先加占位符、书签、内容控件 tag/alias 或手写 spec。
- `analyze_template.py` 新增 `complex_structures` inventory，统计 field code、field instruction、Office Math 公式、修订、嵌入对象、altChunk、drawing 和 comment anchor，并保留样本。
- `assess_template_readiness.py` 把 field code、公式、修订、嵌入对象和 altChunk 计入 `complex_risk_count`，降低 readiness score，并阻断 `can_claim_100_percent`，要求显式处理和 PDF/视觉验证。
- `run_regression_tests.py` 新增 `test_template_readiness_assessment`，覆盖 L1 占位符模板和 L2 高校格式样张。
- `analyze_template.py`、`prepare_fonts.py`、`verify_fidelity.py` 共享 `/tmp/template_fidelity_font_probe_cache.json` 字体探测缓存，默认 24 小时有效，可用 `TEMPLATE_FIDELITY_DISABLE_FONT_CACHE=1` 关闭或用 `TEMPLATE_FIDELITY_FONT_CACHE_TTL` 调整 TTL。

## 仍是下一阶段

- 条件段执行已支持 `marker_pair`、`paragraph_contains` 和 `table_row_contains`；多已填文档反推已支持保守整段条件段和明显可选表格行推断。无明显关键词的表格行条件、嵌套条件和语义改写条件仍需人工建 spec。
- 已支持替换模板里已有图片，也支持普通占位符/文本锚点插入新 hyperlink；凭空插入新图片、chart、raw XML 的插件化插入还没实现。
- reference DOCX 的长正文段落级克隆已支持 `reference_block`，适合论文正文、报告正文和长方案说明；缺失样式定义、段落直接编号定义、缺失样式内部编号定义、外部超链接关系、内嵌图片媒体、脚注、尾注和批注会合并到输出 DOCX。reference block 若含修订/域代码会默认报错并写入 `reference_complex_structures`，显式 `allow_reference_complex_structures: true` 才放行；目标已有同名样式但编号定义不同的冲突、reference block 修订/域代码语义级迁移仍需人工校验。
- PDF 视觉回归已有单页/多页像素级 diff，支持 `--visual-pages all`、页数上限、区域忽略和动态内容白名单；语义级版面对齐仍未实现。
