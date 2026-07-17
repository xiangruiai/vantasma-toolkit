#!/usr/bin/env python3
import argparse
import difflib
import json
import re
import shutil
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "xml": "http://www.w3.org/XML/1998/namespace",
}

ET.register_namespace("w", NS["w"])

CONDITIONAL_TABLE_ROW_KEYWORDS = {
    "可选",
    "如需",
    "若",
    "质保",
    "维保",
    "售后",
    "支持",
    "服务费",
    "差旅",
    "折扣",
    "优惠",
    "赠送",
    "optional",
    "warranty",
    "support",
    "maintenance",
    "service fee",
    "discount",
    "travel",
}

SUMMARY_TABLE_ROW_KEYWORDS = {
    "合计",
    "总计",
    "小计",
    "总额",
    "总价",
    "total",
    "subtotal",
    "grand total",
}


def qn(name):
    prefix, local = name.split(":", 1)
    return "{%s}%s" % (NS[prefix], local)


def text_of(el):
    return "".join(t.text or "" for t in el.findall(".//w:t", NS))


def normalize_text(value):
    return re.sub(r"\s+", " ", (value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


def common_prefix(values):
    if not values:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while not value.startswith(prefix) and prefix:
            prefix = prefix[:-1]
    return prefix


def common_suffix(values):
    if not values:
        return ""
    suffix = values[0]
    for value in values[1:]:
        while not value.endswith(suffix) and suffix:
            suffix = suffix[1:]
    return suffix


def clean_key(value, fallback):
    value = normalize_text(value)
    value = re.sub(r"[\s:：,，.。;；/\\|()\[\]{}<>《》【】]+$", "", value)
    value = re.sub(r"^[\s:：,，.。;；/\\|()\[\]{}<>《》【】]+", "", value)
    value = re.sub(r"\s+", "", value)
    value = value[:24]
    return value or fallback


def label_from_prefix(prefix):
    prefix = normalize_text(prefix)
    for sep in ["：", ":"]:
        if sep in prefix:
            return prefix.rsplit(sep, 1)[0]
    return prefix


def derive_field(values, fallback):
    raw_values = [value or "" for value in values]
    prefix = common_prefix(raw_values)
    suffix = common_suffix([value[len(prefix):] for value in raw_values])
    variable_values = []
    for value in raw_values:
        end = len(value) - len(suffix) if suffix else len(value)
        variable_values.append(value[len(prefix):end])
    key = clean_key(label_from_prefix(prefix), fallback)
    if not prefix:
        key = fallback
    confidence = "high" if prefix and any(variable_values) else "medium"
    return {
        "key": key,
        "prefix": prefix,
        "suffix": suffix,
        "variable_values": variable_values,
        "confidence": confidence,
    }


def safe_unique_key(base, used):
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}{index}"
        index += 1
    used.add(candidate)
    return candidate


def set_text_preserve_runs(element, value):
    text_nodes = element.findall(".//w:t", NS)
    if not text_nodes:
        paragraph = element.find(".//w:p", NS)
        if paragraph is None and element.tag == qn("w:p"):
            paragraph = element
        if paragraph is None:
            return
        run = ET.SubElement(paragraph, qn("w:r"))
        text_node = ET.SubElement(run, qn("w:t"))
        text_nodes = [text_node]
    first = text_nodes[0]
    first.text = value
    if value.startswith(" ") or value.endswith(" "):
        first.set(qn("xml:space"), "preserve")
    for node in text_nodes[1:]:
        node.text = ""


def marker_paragraph(text):
    paragraph = ET.Element(qn("w:p"))
    run = ET.SubElement(paragraph, qn("w:r"))
    text_node = ET.SubElement(run, qn("w:t"))
    text_node.text = text
    return paragraph


def body_blocks(root):
    body = root.find("w:body", NS)
    if body is None:
        return []
    return [child for child in list(body) if child.tag in {qn("w:p"), qn("w:tbl")}]


def direct_body_paragraphs(root):
    return [block for block in body_blocks(root) if block.tag == qn("w:p")]


def direct_body_tables(root):
    return [block for block in body_blocks(root) if block.tag == qn("w:tbl")]


def table_rows(table):
    return table.findall("w:tr", NS)


def row_cells(row):
    return row.findall("w:tc", NS)


def row_texts(row):
    return [normalize_text(text_of(cell)) for cell in row_cells(row)]


def row_signature(row):
    return "\u241f".join(row_texts(row))


def docx_root(path):
    with ZipFile(path) as zf:
        return ET.fromstring(zf.read("word/document.xml"))


def is_text_part(name):
    return (
        name == "word/document.xml"
        or (name.startswith("word/header") and name.endswith(".xml"))
        or (name.startswith("word/footer") and name.endswith(".xml"))
        or name in {"word/footnotes.xml", "word/endnotes.xml"}
    )


def text_part_label(part):
    if part == "word/document.xml":
        return "正文"
    if part.startswith("word/header"):
        return "页眉"
    if part.startswith("word/footer"):
        return "页脚"
    if part == "word/footnotes.xml":
        return "脚注"
    if part == "word/endnotes.xml":
        return "尾注"
    return "文本部件"


def read_text_parts(path):
    parts = {}
    with ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            if name == "word/document.xml" or not is_text_part(name):
                continue
            root = ET.fromstring(zf.read(name))
            parts[name] = {
                "paragraphs": [normalize_text(text_of(p)) for p in root.findall(".//w:p", NS)]
            }
    return parts


def read_sample(path):
    root = docx_root(path)
    paragraphs = [normalize_text(text_of(p)) for p in direct_body_paragraphs(root)]
    tables = []
    for table in direct_body_tables(root):
        rows = table_rows(table)
        tables.append(
            {
                "row_texts": [row_texts(row) for row in rows],
                "row_signatures": [row_signature(row) for row in rows],
                "row_indices": list(range(len(rows))),
            }
        )
    return {"path": str(path), "paragraphs": paragraphs, "tables": tables, "text_parts": read_text_parts(path)}


def infer_paragraph_fields(samples, used=None, skip_base_indices=None):
    if used is None:
        used = set()
    skip_base_indices = set(skip_base_indices or [])
    fields = []
    min_count = min((len(sample["paragraphs"]) for sample in samples), default=0)
    for index in range(min_count):
        if index in skip_base_indices:
            continue
        values = [sample["paragraphs"][index] for sample in samples]
        if len(set(values)) <= 1 or not any(values):
            continue
        fallback = f"字段{len(fields) + 1:03d}"
        derived = derive_field(values, fallback)
        key = safe_unique_key(derived["key"], used)
        fields.append(
            {
                "key": key,
                "kind": "paragraph",
                "part": "word/document.xml",
                "paragraph_index": index,
                "base_text": values[0],
                "placeholder_text": f"{derived['prefix']}{{{{{key}}}}}{derived['suffix']}",
                "values": values,
                "variable_values": derived["variable_values"],
                "confidence": derived["confidence"],
                "spec": {
                    "key": key,
                    "part": "word/document.xml",
                    "locator_type": "text_anchor",
                    "locator": {"text": values[0], "target": "self", "match": "exact"},
                    "required": True,
                    "multiline_mode": "single_paragraph",
                },
            }
        )
    return fields


def deleted_base_ranges(base, other):
    ranges = []
    matcher = difflib.SequenceMatcher(a=base, b=other, autojunk=False)
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "delete" and i2 > i1:
            ranges.append((i1, i2))
    return ranges


def group_indices(indices):
    out = []
    current = []
    for index in sorted(indices):
        if not current or index == current[-1] + 1:
            current.append(index)
            continue
        out.append(current)
        current = [index]
    if current:
        out.append(current)
    return out


def infer_conditional_paragraph_blocks(samples, used=None):
    if used is None:
        used = set()
    if len(samples) < 2:
        return []
    base = samples[0]["paragraphs"]
    missing_by_index = {index: [] for index in range(len(base))}
    for sample in samples[1:]:
        for start, end in deleted_base_ranges(base, sample["paragraphs"]):
            for index in range(start, end):
                text = base[index]
                if text:
                    missing_by_index[index].append(sample["path"])
    candidate_indices = [index for index, paths in missing_by_index.items() if paths]
    blocks = []
    for group in group_indices(candidate_indices):
        texts = [base[index] for index in group if base[index]]
        if not texts:
            continue
        key_seed = clean_key("".join(texts)[:48], f"条件段{len(blocks) + 1:03d}")
        key = safe_unique_key(key_seed, used)
        start_marker = "{{#if " + key + "}}"
        end_marker = "{{/if " + key + "}}"
        missing_paths = sorted({path for index in group for path in missing_by_index[index]})
        blocks.append(
            {
                "key": key,
                "kind": "conditional_paragraph",
                "part": "word/document.xml",
                "paragraph_indices": group,
                "texts": texts,
                "missing_in_samples": missing_paths,
                "present_in_samples": [sample["path"] for sample in samples if sample["path"] not in missing_paths],
                "start_marker": start_marker,
                "end_marker": end_marker,
                "confidence": "medium",
                "spec": {
                    "key": key,
                    "locator_type": "paragraph_contains",
                    "locator": {"text": texts[0], "match": "exact"},
                    "condition": {"key": key},
                    "remove_markers": True,
                },
                "placeholder_spec": {
                    "key": key,
                    "locator_type": "marker_pair",
                    "locator": {"start": start_marker, "end": end_marker, "match": "exact"},
                    "condition": {"key": key},
                    "remove_markers": True,
                },
            }
        )
    return blocks


def row_has_optional_signal(cells):
    text = normalize_text(" ".join(cells)).lower()
    return any(keyword.lower() in text for keyword in CONDITIONAL_TABLE_ROW_KEYWORDS)


def row_anchor_text(cells):
    candidates = [cell for cell in cells if cell and not re.fullmatch(r"[\d,，.。%￥¥$€£\\/\-\s]+", cell)]
    if not candidates:
        candidates = [cell for cell in cells if cell]
    return max(candidates, key=len, default="")


def infer_conditional_table_row_blocks(samples, used=None):
    if used is None:
        used = set()
    if len(samples) < 2:
        return []
    blocks = []
    min_tables = min((len(sample["tables"]) for sample in samples), default=0)
    for table_index in range(min_tables):
        base_table = samples[0]["tables"][table_index]
        base_signatures = base_table["row_signatures"]
        for row_index, cells in enumerate(base_table["row_texts"]):
            if row_index <= 0 or row_index >= len(base_signatures) - 1:
                continue
            anchor = row_anchor_text(cells)
            if not anchor or not row_has_optional_signal(cells):
                continue
            previous_anchor = row_anchor_text(base_table["row_texts"][row_index - 1])
            next_anchor = row_anchor_text(base_table["row_texts"][row_index + 1])
            missing_paths = []
            for sample in samples[1:]:
                table = sample["tables"][table_index]
                anchors = [row_anchor_text(row) for row in table["row_texts"]]
                if anchor in anchors:
                    continue
                if previous_anchor and previous_anchor not in anchors:
                    continue
                if next_anchor and next_anchor not in anchors:
                    continue
                missing_paths.append(sample["path"])
            if not missing_paths:
                continue
            key_seed = clean_key(anchor, f"表格{table_index + 1}条件行{len(blocks) + 1:03d}")
            key = safe_unique_key(key_seed, used)
            block = {
                "key": key,
                "kind": "conditional_table_row",
                "part": "word/document.xml",
                "table_index": table_index,
                "row_index": row_index,
                "row_texts": cells,
                "row_signature": base_signatures[row_index],
                "anchor_text": anchor,
                "missing_in_samples": sorted(missing_paths),
                "present_in_samples": [sample["path"] for sample in samples if sample["path"] not in missing_paths],
                "confidence": "medium",
                "spec": {
                    "key": key,
                    "locator_type": "table_row_contains",
                    "locator": {"table_index": table_index, "text": anchor, "match": "contains"},
                    "condition": {"key": key},
                },
            }
            block["placeholder_spec"] = dict(block["spec"])
            blocks.append(block)
    return blocks


def infer_text_part_fields(samples, used=None):
    if used is None:
        used = set()
    fields = []
    if not samples:
        return fields
    common_parts = set(samples[0].get("text_parts", {}))
    for sample in samples[1:]:
        common_parts &= set(sample.get("text_parts", {}))
    for part in sorted(common_parts):
        min_count = min((len(sample["text_parts"][part]["paragraphs"]) for sample in samples), default=0)
        for index in range(min_count):
            values = [sample["text_parts"][part]["paragraphs"][index] for sample in samples]
            if len(set(values)) <= 1 or not any(values):
                continue
            fallback = f"{text_part_label(part)}字段{len(fields) + 1:03d}"
            derived = derive_field(values, fallback)
            key = safe_unique_key(derived["key"], used)
            fields.append(
                {
                    "key": key,
                    "kind": "text_part",
                    "part": part,
                    "part_label": text_part_label(part),
                    "paragraph_index": index,
                    "base_text": values[0],
                    "placeholder_text": f"{derived['prefix']}{{{{{key}}}}}{derived['suffix']}",
                    "values": values,
                    "variable_values": derived["variable_values"],
                    "confidence": derived["confidence"],
                    "spec": {
                        "key": key,
                        "part": part,
                        "locator_type": "text_anchor",
                        "locator": {"text": values[0], "target": "self", "match": "exact"},
                        "required": True,
                        "multiline_mode": "single_paragraph",
                    },
                }
            )
    return fields


def filtered_table(table, skip_signatures):
    if not skip_signatures:
        return table
    rows = [
        (index, cells, signature)
        for index, cells, signature in zip(table.get("row_indices", range(len(table["row_signatures"]))), table["row_texts"], table["row_signatures"])
        if signature not in skip_signatures
    ]
    return {
        "row_indices": [row[0] for row in rows],
        "row_texts": [row[1] for row in rows],
        "row_signatures": [row[2] for row in rows],
    }


def row_is_summary(cells):
    anchor = row_anchor_text(cells).lower()
    return any(keyword in anchor for keyword in SUMMARY_TABLE_ROW_KEYWORDS)


def infer_table_loops(samples, skip_table_row_signatures=None):
    skip_table_row_signatures = skip_table_row_signatures or {}
    loops = []
    min_tables = min((len(sample["tables"]) for sample in samples), default=0)
    for table_index in range(min_tables):
        skip_signatures = skip_table_row_signatures.get(table_index, set())
        tables = [filtered_table(sample["tables"][table_index], skip_signatures) for sample in samples]
        row_counts = [len(table["row_signatures"]) for table in tables]
        min_rows = min(row_counts, default=0)
        if not min_rows:
            continue

        prefix = 0
        while prefix < min_rows:
            values = [table["row_signatures"][prefix] for table in tables]
            if len(set(values)) != 1:
                break
            prefix += 1

        suffix = 0
        while suffix < min_rows - prefix:
            values = [table["row_signatures"][len(table["row_signatures"]) - 1 - suffix] for table in tables]
            if len(set(values)) != 1:
                break
            suffix += 1

        loop_start = prefix
        if len(set(row_counts)) > 1 and prefix == min_rows and min_rows > 1:
            loop_start = min_rows - 1
            suffix = 0

        middle_counts = [count - loop_start - suffix for count in row_counts]
        middle_varies = len(set(middle_counts)) > 1
        middle_changed = False
        if not middle_varies and middle_counts and middle_counts[0] > 0:
            for offset in range(middle_counts[0]):
                values = [table["row_signatures"][loop_start + offset] for table in tables]
                if len(set(values)) > 1:
                    middle_changed = True
                    break
        if not (middle_varies or middle_changed):
            continue
        if loop_start >= min_rows:
            continue

        header = tables[0]["row_texts"][loop_start - 1] if loop_start > 0 else []
        sample_row = tables[0]["row_texts"][loop_start] if loop_start < len(tables[0]["row_texts"]) else []
        if row_is_summary(sample_row):
            continue
        original_row_index = tables[0].get("row_indices", list(range(row_counts[0])))[loop_start]
        max_cols = max(len(header), len(sample_row))
        columns = []
        used = set()
        for col_index in range(max_cols):
            header_text = header[col_index] if col_index < len(header) else ""
            key = safe_unique_key(clean_key(header_text, f"列{col_index + 1}"), used)
            columns.append({"key": key, "cell_index": col_index})
        table_key = clean_key("".join(col["key"] for col in columns[:2]), f"表格{table_index + 1}明细")
        if not table_key.endswith("明细"):
            table_key = f"{table_key}明细"

        loops.append(
            {
                "key": table_key,
                "kind": "table_loop",
                "table_index": table_index,
                "row_index": original_row_index,
                "suffix_rows": suffix,
                "row_counts": row_counts,
                "middle_row_counts": middle_counts,
                "columns": columns,
                "samples": [
                    {
                        "path": sample["path"],
                        "rows": sample["tables"][table_index]["row_texts"][loop_start : row_counts[idx] - suffix if suffix else row_counts[idx]],
                    }
                    for idx, sample in enumerate(samples)
                ],
                "spec": {
                    "key": table_key,
                    "locator_type": "table_index",
                    "locator": {"table_index": table_index},
                    "row_index": original_row_index,
                    "remove_template_row": True,
                    "columns": columns,
                },
            }
        )
    return loops


def write_placeholder_template(base_docx, output_docx, fields, loops, conditional_blocks=None):
    conditional_blocks = conditional_blocks or []
    tmp = Path(tempfile.mkdtemp(prefix="tpl_infer_"))
    work = tmp / "work"
    try:
        with ZipFile(base_docx) as archive:
            archive.extractall(work)

        root_cache = {}

        def load_root(part):
            part_path = work / part
            if not part_path.exists():
                return None
            if part not in root_cache:
                root_cache[part] = ET.fromstring(part_path.read_bytes())
            return root_cache[part]

        document_root = load_root("word/document.xml")
        paragraphs = direct_body_paragraphs(document_root)
        for field in fields:
            part = field.get("part", "word/document.xml")
            index = field["paragraph_index"]
            if part == "word/document.xml":
                target_paragraphs = paragraphs
            else:
                root = load_root(part)
                target_paragraphs = root.findall(".//w:p", NS) if root is not None else []
            if 0 <= index < len(target_paragraphs):
                set_text_preserve_runs(target_paragraphs[index], field["placeholder_text"])

        body = document_root.find("w:body", NS)
        if body is not None:
            paragraphs = direct_body_paragraphs(document_root)
            paragraph_blocks = [block for block in conditional_blocks if block.get("kind") == "conditional_paragraph"]
            for block in sorted(paragraph_blocks, key=lambda row: row["paragraph_indices"][0], reverse=True):
                indices = block.get("paragraph_indices") or []
                if not indices:
                    continue
                start_index = indices[0]
                end_index = indices[-1]
                if start_index < 0 or end_index >= len(paragraphs):
                    continue
                children = list(body)
                try:
                    start_child_index = children.index(paragraphs[start_index])
                    end_child_index = children.index(paragraphs[end_index])
                except ValueError:
                    continue
                body.insert(end_child_index + 1, marker_paragraph(block["end_marker"]))
                body.insert(start_child_index, marker_paragraph(block["start_marker"]))

        tables = direct_body_tables(document_root)
        for loop in loops:
            table_index = loop["table_index"]
            if table_index < 0 or table_index >= len(tables):
                continue
            rows = table_rows(tables[table_index])
            row_index = loop["row_index"]
            if row_index < 0 or row_index >= len(rows):
                continue
            template_row = rows[row_index]
            cells = row_cells(template_row)
            for column in loop["columns"]:
                cell_index = column["cell_index"]
                if 0 <= cell_index < len(cells):
                    set_text_preserve_runs(cells[cell_index], "{{" + column["key"] + "}}")
            suffix = loop.get("suffix_rows", 0)
            end = len(rows) - suffix if suffix else len(rows)
            for extra_index in range(end - 1, row_index, -1):
                parent = rows[extra_index].getparent() if hasattr(rows[extra_index], "getparent") else tables[table_index]
                parent.remove(rows[extra_index])

        for part, root in root_cache.items():
            (work / part).write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
        output_docx = Path(output_docx)
        output_docx.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output_docx, "w", ZIP_DEFLATED) as archive:
            for file_path in work.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(work))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_markdown(report, path):
    lines = [
        "# Template Inference Report",
        "",
        f"- Samples: {len(report['samples'])}",
        f"- Paragraph fields: {len(report['paragraph_fields'])}",
        f"- Text-part fields: {len(report.get('text_part_fields', []))}",
        f"- Conditional blocks: {len(report.get('conditional_blocks', []))}",
        f"- Table loops: {len(report['table_loops'])}",
        "",
        "## Paragraph Fields",
        "",
    ]
    for field in report["paragraph_fields"]:
        lines.extend(
            [
                f"### {field['key']}",
                f"- Paragraph index: {field['paragraph_index']}",
                f"- Confidence: {field['confidence']}",
                f"- Placeholder: `{field['placeholder_text']}`",
                "",
            ]
        )
    lines.extend(["## Text-Part Fields", ""])
    for field in report.get("text_part_fields", []):
        lines.extend(
            [
                f"### {field['key']}",
                f"- Part: `{field['part']}` ({field.get('part_label', 'text part')})",
                f"- Paragraph index: {field['paragraph_index']}",
                f"- Confidence: {field['confidence']}",
                f"- Placeholder: `{field['placeholder_text']}`",
                "",
            ]
        )
    lines.extend(["## Conditional Blocks", ""])
    for block in report.get("conditional_blocks", []):
        locator = "table row" if block.get("kind") == "conditional_table_row" else "paragraph"
        location = (
            f"table {block['table_index']} row {block['row_index']}"
            if block.get("kind") == "conditional_table_row"
            else f"paragraphs {block['paragraph_indices']}"
        )
        lines.extend(
            [
                f"### {block['key']}",
                f"- Kind: {locator}",
                f"- Location: {location}",
                f"- Missing in samples: {len(block['missing_in_samples'])}",
                f"- Confidence: {block['confidence']}",
                "",
            ]
        )
    lines.extend(["## Table Loops", ""])
    for loop in report["table_loops"]:
        lines.extend(
            [
                f"### {loop['key']}",
                f"- Table index: {loop['table_index']}",
                f"- Template row index: {loop['row_index']}",
                f"- Row counts: {loop['row_counts']}",
                f"- Columns: {', '.join(col['key'] for col in loop['columns'])}",
                "",
            ]
        )
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def build_spec(template_source, fields, loops, conditional_blocks=None, placeholder_template=False):
    conditional_blocks = conditional_blocks or []
    field_specs = []
    for field in fields:
        if placeholder_template:
            field_specs.append(
                {
                    "key": field["key"],
                    "part": field.get("part", "word/document.xml"),
                    "locator_type": "placeholder",
                    "locator": {"token": "{{" + field["key"] + "}}"},
                    "replacement_mode": "token",
                    "required": True,
                    "multiline_mode": "single_paragraph",
                }
            )
        else:
            field_specs.append(field["spec"])
    return {
        "template_source": str(template_source),
        "conditional_blocks": [
            block["placeholder_spec"] if placeholder_template else block["spec"]
            for block in conditional_blocks
        ],
        "fields": field_specs,
        "table_loops": [loop["spec"] for loop in loops],
    }


def main():
    parser = argparse.ArgumentParser(description="Infer a reusable DOCX template/spec from multiple filled DOCX samples.")
    parser.add_argument("samples", nargs="+", help="Two or more filled DOCX files of the same document family.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--report-md")
    parser.add_argument("--spec-output")
    parser.add_argument("--template-output", help="Optional placeholder DOCX template generated from the first sample.")
    args = parser.parse_args()

    sample_paths = [Path(path).expanduser().resolve() for path in args.samples]
    if len(sample_paths) < 2:
        raise SystemExit("Need at least two filled DOCX samples.")
    missing = [str(path) for path in sample_paths if not path.exists()]
    if missing:
        raise SystemExit(f"Missing samples: {missing}")

    samples = [read_sample(path) for path in sample_paths]
    used = set()
    paragraph_conditionals = infer_conditional_paragraph_blocks(samples, used)
    table_row_conditionals = infer_conditional_table_row_blocks(samples, used)
    conditional_blocks = paragraph_conditionals + table_row_conditionals
    conditional_indices = {
        index
        for block in paragraph_conditionals
        for index in block.get("paragraph_indices", [])
    }
    fields = infer_paragraph_fields(samples, used, skip_base_indices=conditional_indices)
    text_part_fields = infer_text_part_fields(samples, used)
    all_fields = fields + text_part_fields
    skip_table_row_signatures = {}
    for block in table_row_conditionals:
        skip_table_row_signatures.setdefault(block["table_index"], set()).add(block["row_signature"])
    loops = infer_table_loops(samples, skip_table_row_signatures=skip_table_row_signatures)

    template_source = sample_paths[0]
    if args.template_output:
        write_placeholder_template(sample_paths[0], Path(args.template_output).expanduser(), all_fields, loops, conditional_blocks)
        template_source = Path(args.template_output).expanduser().resolve()

    spec = build_spec(template_source, all_fields, loops, conditional_blocks, placeholder_template=bool(args.template_output))
    report = {
        "samples": [str(path) for path in sample_paths],
        "paragraph_fields": fields,
        "text_part_fields": text_part_fields,
        "fields": all_fields,
        "conditional_blocks": conditional_blocks,
        "table_loops": loops,
        "spec": spec,
        "template_output": str(template_source) if args.template_output else None,
        "limitations": [
            "This is a structural diff, not a semantic guarantee. Review field names before production use.",
            "Conditional inference is conservative: it only detects whole direct-body paragraphs present in the first sample and missing from at least one other sample.",
            "Table-row conditional inference is keyword-gated and only detects obvious optional rows such as warranty, support, service fee, discount, or maintenance rows.",
            "Nested tables, images, non-obvious table-row conditionals, and cross-run partial replacements may need manual adjustment.",
            "Header/footer inference only covers paragraph text in common text parts; section-specific or linked header variants still need review.",
        ],
    }

    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.spec_output:
        Path(args.spec_output).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.report_md:
        write_markdown(report, args.report_md)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
