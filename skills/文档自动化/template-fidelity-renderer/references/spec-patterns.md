# Spec Patterns

Use this reference when writing or reviewing `template_spec.json`, especially for L2 templates without plain `{{field}}` placeholders, long-body reference blocks, optional clauses, table loops, images, or hyperlinks.

## Contents

- [Core Spec Shape](#core-spec-shape)
- [Locator Types](#locator-types)
- [Text Parts](#text-parts)
- [Multiline Text](#multiline-text)
- [Hyperlinks](#hyperlinks)
- [Reference Blocks](#reference-blocks)
- [Conditional Blocks](#conditional-blocks)
- [Table Loops](#table-loops)
- [Image Fields](#image-fields)

## Core Spec Shape

When a template has no `{{字段}}` but has stable paragraphs, bookmarks, content controls, or reference samples, create a `template_spec.json`:

```json
{
  "template_source": "template.docx",
  "reference_source": "reference.docx",
  "fields": [
    {
      "key": "论文标题",
      "label": "中文标题",
      "locator_type": "text_anchor",
      "locator": {"text": "[此处键入中文标题]", "target": "self"},
      "required": true,
      "multiline_mode": "single_paragraph"
    }
  ]
}
```

## Locator Types

- `placeholder`: template contains `{{字段}}`.
- `literal`: replace existing visible text.
- `paraId`: locate by Word `w14:paraId`.
- `text_anchor`: locate by visible text; supports `self`, `next_paragraph`, and `after`.
- `bookmark`: locate by Word bookmark. Default `replacement_mode: "bookmark_text"` only replaces text inside bookmarkStart/bookmarkEnd and keeps bookmark metadata. Empty bookmarks insert a run and inherit nearby `w:rPr`.
- `hyperlink`: locate an existing `w:hyperlink` by visible text, URL target, relationship id, or index. Use this to replace an existing link, not to create a new link.
- `content_control`: locate Word content controls by tag, alias, dataBinding, or index. It preserves `w:sdt`, `w:sdtPr`, wrapper metadata, lock metadata, placeholder state, and text-control metadata.

Content controls support explicit replacement modes: `checkbox`, `date`, `choice`, `repeating_section`, and `reference_block`.

## Text Parts

Fields default to `word/document.xml`. Add `part` for headers, footers, footnotes, or endnotes:

```json
{
  "key": "客户名称",
  "part": "headers",
  "locator_type": "placeholder",
  "locator": {"token": "{{客户名称}}"},
  "replacement_mode": "token",
  "required": true
}
```

Supported `part` values:

- Exact part paths, such as `word/header1.xml` or `word/footer1.xml`
- `headers` / `footers`
- Section objects, such as `{"type":"section_header","section_index":1,"reference_type":"default"}` or `section_footer`
- `notes`, meaning both `word/footnotes.xml` and `word/endnotes.xml`
- `all` / `text_parts`

For section headers/footers, `linked_to_previous=true` blocks by default. Set `allow_linked_section_part: true` only when intentionally editing the inherited previous-section part.

## Multiline Text

Single-paragraph values containing newlines are rendered as Word `w:br`, not raw `\n` in `w:t`. The render report records `line_breaks_inserted` and `expected_structure_change: "line_breaks_inserted"`.

True long body text should use `reference_block` or `multiline_mode: "paragraphs"`, not a single oversized field.

## Hyperlinks

### Existing Hyperlink

Use `locator_type: "hyperlink"` when the template already contains a hyperlink:

```json
{
  "key": "官网链接",
  "locator_type": "hyperlink",
  "locator": {
    "text": "旧官网",
    "match": "exact",
    "target": "https://old.example.com"
  },
  "replacement_mode": "hyperlink",
  "required": true
}
```

Data can change display text only:

```json
{"fields": {"官网链接": "新官网"}}
```

Or display text and URL together:

```json
{"fields": {"官网链接": {"text": "新官网", "url": "https://new.example.com"}}}
```

The render report must include `action: "hyperlink_replace"`, `relationship_before`, `relationship_after`, `target_before`, and `target`.

### New Hyperlink

Use `replacement_mode: "insert_hyperlink"` when a normal placeholder, literal text, or text anchor should become a real Word external link:

```json
{
  "key": "客户入口",
  "locator_type": "placeholder",
  "locator": {"token": "{{客户入口}}"},
  "replacement_mode": "insert_hyperlink",
  "required": true
}
```

Data:

```json
{
  "fields": {
    "客户入口": {
      "text": "客户门户",
      "url": "https://portal.example.com"
    }
  }
}
```

Notes:

- Supported locators: `placeholder`, `literal`, and `text_anchor`.
- To override the exact replaced text, set `replace_text` on the field or locator.
- The renderer creates or reuses an External hyperlink relationship in the current text part `.rels`.
- The report records `action: "hyperlink_insert"` and `expected_structure_change: "hyperlink_inserted"`; verifier allows only report-backed hyperlink insertion.

## Reference Blocks

Use `reference_block` for thesis/report body text or rich paragraphs that must clone styles from a reference DOCX:

```json
{
  "template_source": "template.docx",
  "reference_source": "reference-filled.docx",
  "fields": [
    {
      "key": "正文",
      "locator_type": "placeholder",
      "locator": {"token": "{{正文}}"},
      "replacement_mode": "reference_block",
      "reference_locator_type": "marker_pair",
      "reference_locator": {"start": "{{#正文样式}}", "end": "{{/正文样式}}"},
      "reference_style_policy": "last",
      "required": true
    }
  ]
}
```

Data may be an array or a string split by blank lines:

```json
{
  "fields": {
    "正文": [
      "第一章 引言",
      "生成式 AI 在学习场景中的影响正在被重新评估。",
      "本研究关注长期学习成本。"
    ]
  }
}
```

Reference block behavior:

- Replaces the target paragraph with cloned reference paragraphs.
- Reuses reference paragraph styles in order; extra paragraphs reuse the last style unless `reference_style_policy: "cycle"`.
- Imports missing style definitions and their dependencies.
- Imports direct numbering and missing-style internal numbering definitions, remapping old `numId` values.
- Imports external hyperlink relationships and remaps old `r:id`.
- Imports embedded image media/relationships and remaps old `r:embed`.
- Imports footnotes, endnotes, and comments with new IDs.
- Blocks field codes and tracked revisions by default with `reference_complex_structures_present`; set `allow_reference_complex_structures: true` only with manual review.
- Blocks same `styleId` definition conflicts by default with `reference_style_conflicts`; set `allow_reference_style_conflicts: true` only when accepting the target template’s existing style definition.

## Conditional Blocks

Use `conditional_blocks` for optional clauses, optional fee rows, and optional declaration pages:

```json
{
  "template_source": "template.docx",
  "conditional_blocks": [
    {
      "key": "质保条款",
      "condition": {"field": "包含质保", "equals": true},
      "locator_type": "marker_pair",
      "locator": {"start": "{{#if 质保条款}}", "end": "{{/if 质保条款}}"},
      "remove_markers": true
    },
    {
      "key": "现场支持费用行",
      "condition": "包含现场支持",
      "locator_type": "table_row_contains",
      "locator": {"table_index": 0, "text": "{{现场支持费}}"}
    }
  ]
}
```

Supported locators:

- `marker_pair`: remove or keep paragraphs between start/end markers. True removes markers and keeps content; false removes markers and content.
- `paragraph_contains`: remove or keep matching paragraphs.
- `table_row_contains`: remove or keep matching table rows. Prefer `locator.table_index` to avoid deleting rows in the wrong table.

Conditions:

- String: `"包含质保"` reads the truthiness of the same data key.
- Object: `{"field":"方案类型","in":["企业版","旗舰版"]}`, `{"field":"包含质保","equals":true}`, or `{"exists":"签章图片"}`.

Conditional blocks run before fields are filled, so deleted optional clauses do not leave unresolved placeholders.

## Table Loops

Use `table_loops` for quote details, payment milestones, appendix rows, and scoring tables:

```json
{
  "template_source": "template.docx",
  "table_loops": [
    {
      "key": "报价明细",
      "locator_type": "contains_text",
      "locator": {"text": "{{项目名称}}"},
      "row_index": 1,
      "remove_template_row": true,
      "columns": [
        {"key": "项目名称", "cell_index": 0},
        {"key": "数量", "cell_index": 1},
        {"key": "单价", "cell_index": 2},
        {"key": "小计", "cell_index": 3}
      ]
    }
  ]
}
```

Data:

```json
{
  "tables": {
    "报价明细": [
      {"项目名称": "AI 工作流设计", "数量": "1", "单价": "12000", "小计": "12000"},
      {"项目名称": "飞书多维表格搭建", "数量": "1", "单价": "8000", "小计": "8000"}
    ]
  }
}
```

If the template row already contains tokens like `{{项目名称}}`, `columns` can be omitted and tokens are replaced inside each cloned row.

For details inside nested tables, use `nested_contains_text` or `locator.prefer: "deepest"`:

```json
{
  "key": "附件明细",
  "locator_type": "nested_contains_text",
  "locator": {"text": "{{附件名称}}"},
  "row_index": 1,
  "remove_template_row": true
}
```

Table locators support `depth`, `min_depth`, `max_depth`, and `top_level_only`. Check `table_match.table_depth` in the render report.

## Image Fields

Prefer replacing an existing placeholder image, preserving its frame, size, cropping, wrapping, and relationship structure:

```json
{
  "template_source": "template.docx",
  "image_fields": [
    {
      "key": "公司logo",
      "locator_type": "image_index",
      "locator": {"index": 0},
      "required": true
    },
    {
      "key": "签章",
      "part": "footers",
      "locator_type": "image_alt_text",
      "locator": {"text": "seal", "match": "contains"},
      "required": true
    }
  ]
}
```

Data:

```json
{
  "images": {
    "公司logo": "assets/logo.png",
    "签章": "assets/seal.png"
  }
}
```

Supported locators:

- `image_index`: by image order in the text part.
- `image_alt_text`: by alt text, name, title, or description.
- `text_anchor`, `bookmark`, `content_control`: locate a paragraph or content control containing an image, then replace its first image.

If the new image extension differs from the template image, the script updates image relationships and `[Content_Types].xml`. Image dimensions and wrapping still come from the template’s existing image frame.
