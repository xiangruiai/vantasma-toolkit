#!/usr/bin/env python3
import argparse
import json
import posixpath
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
}


def qn(name):
    prefix, local = name.split(":", 1)
    return "{%s}%s" % (NS[prefix], local)


def attr(el, name):
    return el.get(qn(name)) if el is not None else None


def text_of(el):
    return "".join(t.text or "" for t in el.findall(".//w:t", NS))


def local_name(el):
    return el.tag.rsplit("}", 1)[-1] if "}" in el.tag else el.tag


def has_descendant_local(el, local_names):
    if el is None:
        return False
    return any(local_name(child) in local_names for child in el.iter())


def text_part_names(names):
    parts = ["word/document.xml"]
    for name in sorted(names):
        if name.startswith("word/header") or name.startswith("word/footer"):
            parts.append(name)
    for name in ["word/footnotes.xml", "word/endnotes.xml"]:
        if name in names:
            parts.append(name)
    return [name for name in parts if name in names]


def read_xml(zf, name):
    return ET.fromstring(zf.read(name))


def rels_part_name(part):
    part = part.lstrip("/")
    package_dir = posixpath.dirname(part)
    filename = posixpath.basename(part)
    if package_dir:
        return posixpath.join(package_dir, "_rels", filename + ".rels")
    return posixpath.join("_rels", filename + ".rels")


def relationships_for_part(zf, part, names):
    rels_name = rels_part_name(part)
    if rels_name not in names:
        return {}
    root = read_xml(zf, rels_name)
    relationships = {}
    for node in root:
        if local_name(node) != "Relationship":
            continue
        relationship_id = node.get("Id")
        if not relationship_id:
            continue
        relationships[relationship_id] = {
            "type": node.get("Type"),
            "target": node.get("Target"),
            "target_mode": node.get("TargetMode"),
            "part": rels_name,
        }
    return relationships


def visible_sample_tokens(text):
    tokens = []
    patterns = [
        r"\[[^\[\]]*(?:此处)?(?:键入|输入|填写|填入|录入)[^\[\]]+\]",
        r"【[^【】]*(?:此处)?(?:键入|输入|填写|填入|录入)[^【】]+】",
        r"（[^（）]*(?:此处)?(?:键入|输入|填写|填入|录入)[^（）]+）",
        r"\([^()]*(?:type|enter|insert|input|fill in)[^()]+\)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            tokens.append(match.group(0).strip())
    stripped = text.strip()
    if re.fullmatch(r"摘要内容[。.]?", stripped):
        tokens.append(stripped)
    if re.fullmatch(r"关键词[:：]\s*关键词\s*1[，,;；、 ].*", stripped):
        tokens.append(stripped)
    if re.fullmatch(r"Abstract\s+content[.]?", stripped, flags=re.IGNORECASE):
        tokens.append(stripped)
    if re.fullmatch(r"Key\s*words?[:：].*", stripped, flags=re.IGNORECASE) and re.search(r"keyword\s*1", stripped, flags=re.IGNORECASE):
        tokens.append(stripped)
    return list(dict.fromkeys(tokens))


def clean_key(text):
    value = text.strip()
    pairs = [("[", "]"), ("【", "】"), ("（", "）"), ("(", ")")]
    changed = True
    while changed:
        changed = False
        for left, right in pairs:
            if value.startswith(left) and value.endswith(right):
                value = value[len(left) : -len(right)].strip()
                changed = True
    cleaned = re.sub(r"^(请|请在此处|此处)?\s*(键入|输入|填写|填入|录入|type|enter|insert|input|fill in)\s*", "", value, flags=re.IGNORECASE)
    if cleaned == value:
        cleaned = re.sub(r"^.*?(键入|输入|填写|填入|录入)\s*", "", value)
    value = cleaned
    value = re.sub(r"[。．.…]+$", "", value).strip()
    if re.fullmatch(r"摘要内容", value):
        return "摘要"
    if value.startswith("关键词"):
        return "关键词"
    if re.fullmatch(r"abstract\s+content", value, flags=re.IGNORECASE):
        return "abstract"
    if re.match(r"key\s*words?", value, flags=re.IGNORECASE):
        return "keywords"
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"^[：:]+|[：:]+$", "", value).strip("_ ")
    return value or "field"


def is_system_bookmark_name(name):
    if not name:
        return True
    if name.startswith("_"):
        return True
    system_names = {
        "MTUpdateHome",
        "MTEditEquation",
        "MTEqRef",
        "OLE_LINK",
        "DDE_LINK",
    }
    if name in system_names:
        return True
    if re.match(r"^(OLE_LINK|DDE_LINK|MTTemp|MTEqn|MTPref|MTRange)", name):
        return True
    return False


def unique_key(base, used):
    key = base
    if key not in used:
        used.add(key)
        return key
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    key = f"{base}_{index}"
    used.add(key)
    return key


def paragraph_inventory(root, part):
    items = []
    for index, para in enumerate(root.findall(".//w:p", NS)):
        text = text_of(para).strip()
        if not text:
            continue
        items.append(
            {
                "part": part,
                "index": index,
                "para_id": para.get(qn("w14:paraId"), ""),
                "text": text,
            }
        )
    return items


def content_control_kind(sdt_pr):
    if sdt_pr is None:
        return None
    if has_descendant_local(sdt_pr, {"checkBox", "checkbox"}):
        return "checkBox"
    for name in ["repeatingSection", "repeatingSectionItem"]:
        if has_descendant_local(sdt_pr, {name}):
            return name
    for name in ["text", "richText", "picture", "date", "dropDownList", "comboBox"]:
        if sdt_pr.find(f"w:{name}", NS) is not None:
            return name
    return None


def content_control_choice_options(sdt_pr):
    if sdt_pr is None:
        return []
    choice_node = sdt_pr.find("w:dropDownList", NS) or sdt_pr.find("w:comboBox", NS)
    if choice_node is None:
        return []
    options = []
    seen = set()
    for item in choice_node.findall("w:listItem", NS):
        display_text = attr(item, "w:displayText")
        value = attr(item, "w:value")
        if not display_text and not value:
            continue
        key = (display_text or "", value or "")
        if key in seen:
            continue
        seen.add(key)
        options.append({"display_text": display_text or value, "value": value or display_text})
    return options


def content_control_date_properties(sdt_pr):
    if sdt_pr is None:
        return {}
    date_node = sdt_pr.find("w:date", NS)
    if date_node is None:
        return {}
    out = {
        "full_date": attr(date_node, "w:fullDate"),
        "format": attr(date_node.find("w:dateFormat", NS), "w:val"),
        "lid": attr(date_node.find("w:lid", NS), "w:val"),
        "store_mapped_data_as": attr(date_node.find("w:storeMappedDataAs", NS), "w:val"),
        "calendar": attr(date_node.find("w:calendar", NS), "w:val"),
    }
    return {key: value for key, value in out.items() if value}


def word_bool(value):
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "on", "yes"}


def content_control_text_properties(sdt_pr):
    if sdt_pr is None:
        return {}
    text_node = sdt_pr.find("w:text", NS)
    if text_node is None:
        return {}
    raw_multi_line = attr(text_node, "w:multiLine")
    out = {
        "multi_line": word_bool(raw_multi_line),
    }
    if raw_multi_line is not None:
        out["multi_line_raw"] = raw_multi_line
    return out


def content_control_binding(sdt_pr):
    if sdt_pr is None:
        return None
    binding = sdt_pr.find("w:dataBinding", NS)
    if binding is None:
        return None
    out = {
        "xpath": attr(binding, "w:xpath"),
        "store_item_id": attr(binding, "w:storeItemID"),
        "prefix_mappings": attr(binding, "w:prefixMappings"),
    }
    return {key: value for key, value in out.items() if value}


def key_from_binding(binding):
    xpath = (binding or {}).get("xpath") or ""
    parts = [part for part in xpath.strip().split("/") if part and part != "."]
    if not parts:
        return None
    leaf = parts[-1]
    if leaf in {"text()", "node()"} and len(parts) > 1:
        leaf = parts[-2]
    leaf = re.sub(r"\[.*?\]", "", leaf)
    leaf = leaf.split(":", 1)[-1]
    leaf = leaf.lstrip("@").strip()
    leaf = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", leaf).strip("_")
    return leaf or None


def content_control_candidates(root, part):
    out = []
    for index, sdt in enumerate(root.findall(".//w:sdt", NS)):
        sdt_pr = sdt.find("w:sdtPr", NS)
        if sdt_pr is None:
            continue
        tag_el = sdt_pr.find("w:tag", NS)
        alias_el = sdt_pr.find("w:alias", NS)
        lock_el = sdt_pr.find("w:lock", NS)
        tag = attr(tag_el, "w:val") if tag_el is not None else None
        alias = attr(alias_el, "w:val") if alias_el is not None else None
        lock = attr(lock_el, "w:val") if lock_el is not None else None
        binding = content_control_binding(sdt_pr)
        if not tag and not alias and not binding:
            continue
        showing_placeholder = sdt_pr.find("w:showingPlcHdr", NS) is not None
        kind = content_control_kind(sdt_pr)
        options = content_control_choice_options(sdt_pr)
        date_properties = content_control_date_properties(sdt_pr)
        text_properties = content_control_text_properties(sdt_pr)
        if tag:
            locator = {"tag": tag}
        elif alias:
            locator = {"alias": alias}
        else:
            locator = {"binding": binding}
        row = {
            "source": "content_control",
            "key_base": clean_key(tag or alias or key_from_binding(binding) or f"content_control_{index}"),
            "locator_type": "content_control",
            "locator": locator,
            "kind": kind,
            "part": part,
            "text": text_of(sdt).strip()[:240],
            "control_index": index,
            "showing_placeholder": showing_placeholder,
        }
        if lock:
            row["lock"] = lock
        if binding:
            row["binding"] = binding
        if options:
            row["options"] = options
        if date_properties:
            row["date"] = date_properties
        if text_properties:
            row["text_control"] = text_properties
        out.append(row)
    return out


def bookmark_candidates(root, part):
    out = []
    for index, bookmark in enumerate(root.findall(".//w:bookmarkStart", NS)):
        name = attr(bookmark, "w:name")
        bookmark_id = attr(bookmark, "w:id")
        if not name or is_system_bookmark_name(name):
            continue
        out.append(
            {
                "source": "bookmark",
                "key_base": clean_key(name),
                "locator_type": "bookmark",
                "locator": {"name": name},
                "replacement_mode": "bookmark_text",
                "part": part,
                "bookmark_index": index,
                "bookmark_id": bookmark_id,
            }
        )
    return out


def hyperlink_candidates(root, part, relationships):
    out = []
    for index, hyperlink in enumerate(root.findall(".//w:hyperlink", NS)):
        relationship_id = attr(hyperlink, "r:id")
        relationship = relationships.get(relationship_id, {}) if relationship_id else {}
        text = text_of(hyperlink).strip()
        if not text and not relationship.get("target"):
            continue
        locator = {}
        if text:
            locator["text"] = text
            locator["match"] = "exact"
        if relationship.get("target"):
            locator["target"] = relationship["target"]
        if not locator:
            locator["index"] = index
        out.append(
            {
                "source": "hyperlink",
                "key_base": clean_key(text or relationship.get("target") or f"hyperlink_{index}"),
                "locator_type": "hyperlink",
                "locator": locator,
                "replacement_mode": "hyperlink",
                "part": part,
                "hyperlink_index": index,
                "text": text[:240],
                "relationship_id": relationship_id,
                "target": relationship.get("target"),
                "target_mode": relationship.get("target_mode"),
                "relationship_type": relationship.get("type"),
            }
        )
    return out


def placeholder_candidates(paragraphs):
    out = []
    for para in paragraphs:
        for token in re.findall(r"\{\{([^{}]+)\}\}", para["text"]):
            key = token.strip()
            if not key:
                continue
            out.append(
                {
                    "source": "placeholder",
                    "key_base": clean_key(key),
                    "locator_type": "placeholder",
                    "locator": {"token": "{{" + key + "}}"},
                    "part": para["part"],
                    "paragraph_index": para["index"],
                    "text": para["text"][:240],
                }
            )
    return out


def visible_sample_candidates(paragraphs):
    out = []
    counts = Counter()
    locations = defaultdict(list)
    for para in paragraphs:
        for sample in visible_sample_tokens(para["text"]):
            counts[sample] += 1
            locations[sample].append({"part": para["part"], "paragraph_index": para["index"]})
            out.append(
                {
                    "source": "visible_sample",
                    "key_base": clean_key(sample),
                    "locator_type": "literal",
                    "locator": {"text": sample},
                    "part": para["part"],
                    "paragraph_index": para["index"],
                    "sample_text": sample,
                    "paragraph_text": para["text"][:240],
                    "full_paragraph": para["text"].strip() == sample,
                }
            )
    return out, counts, locations


def field_from_candidate(candidate, key):
    field = {
        "key": key,
        "locator_type": candidate["locator_type"],
        "locator": candidate["locator"],
        "required": False,
        "draft_source": candidate["source"],
    }
    if candidate.get("part") and candidate["part"] != "word/document.xml":
        field["part"] = candidate["part"]
    if candidate["locator_type"] == "placeholder":
        field["replacement_mode"] = "token"
    if candidate["locator_type"] == "bookmark":
        field["replacement_mode"] = candidate.get("replacement_mode", "bookmark_text")
        if candidate.get("bookmark_id"):
            field["bookmark_id"] = candidate["bookmark_id"]
    if candidate["locator_type"] == "content_control" and candidate.get("kind") == "checkBox":
        field["replacement_mode"] = "checkbox"
    if candidate["locator_type"] == "content_control" and candidate.get("kind") in {"dropDownList", "comboBox"}:
        field["replacement_mode"] = "choice"
        if candidate.get("options"):
            field["options"] = candidate["options"]
    if candidate["locator_type"] == "content_control" and candidate.get("kind") == "date":
        field["replacement_mode"] = "date"
        if candidate.get("date"):
            field["date"] = candidate["date"]
    if candidate["locator_type"] == "content_control" and candidate.get("kind") == "repeatingSection":
        field["replacement_mode"] = "repeating_section"
    if candidate["locator_type"] == "content_control" and candidate.get("lock"):
        field["lock"] = candidate["lock"]
    if candidate["locator_type"] == "content_control" and candidate.get("showing_placeholder"):
        field["showing_placeholder"] = True
    if candidate["locator_type"] == "content_control" and candidate.get("text_control"):
        field["text_control"] = candidate["text_control"]
    if candidate["locator_type"] == "content_control" and candidate.get("binding"):
        field["binding"] = candidate["binding"]
    if candidate["locator_type"] == "literal":
        field["label"] = candidate.get("sample_text")
        field["replacement_mode"] = "literal_text"
        field["multiline_mode"] = "single_paragraph"
    return field


def draft_from_docx(path, todo_prefix="TODO: "):
    path = Path(path).expanduser().resolve()
    with ZipFile(path) as zf:
        names = set(zf.namelist())
        text_parts = text_part_names(names)
        paragraphs = []
        control_candidates = []
        bookmark_rows = []
        hyperlink_rows = []
        for part in text_parts:
            root = read_xml(zf, part)
            paragraphs.extend(paragraph_inventory(root, part))
            control_candidates.extend(content_control_candidates(root, part))
            bookmark_rows.extend(bookmark_candidates(root, part))
            hyperlink_rows.extend(hyperlink_candidates(root, part, relationships_for_part(zf, part, names)))

    placeholder_rows = placeholder_candidates(paragraphs)
    sample_rows, sample_counts, sample_locations = visible_sample_candidates(paragraphs)
    used_keys = set()
    fields = []
    field_keys_by_sample = {}
    warnings = []

    for row in placeholder_rows + control_candidates + bookmark_rows:
        key = unique_key(row["key_base"], used_keys)
        fields.append(field_from_candidate(row, key))

    for row in hyperlink_rows:
        warnings.append(
            {
                "type": "hyperlink_candidate",
                "key_base": row["key_base"],
                "text": row.get("text"),
                "target": row.get("target"),
                "part": row["part"],
                "hyperlink_index": row["hyperlink_index"],
                "message": "Existing hyperlink can be promoted manually to a spec field with locator_type hyperlink; it is not auto-filled by draft_spec to avoid changing navigation links accidentally.",
            }
        )

    literal_replacements = {}
    literal_candidates = []
    spec_sample_fields_added = set()
    for row in sample_rows:
        base = row["key_base"]
        key = field_keys_by_sample.get(row["sample_text"])
        if key is None:
            key = unique_key(base, used_keys)
            field_keys_by_sample[row["sample_text"]] = key
        replacement = f"{todo_prefix}{key}"
        literal_replacements[row["sample_text"]] = replacement
        literal_candidates.append(
            {
                "key": key,
                "sample_text": row["sample_text"],
                "replacement": replacement,
                "part": row["part"],
                "paragraph_index": row["paragraph_index"],
                "full_paragraph": row["full_paragraph"],
            }
        )
        if row["full_paragraph"] and row["sample_text"] not in spec_sample_fields_added:
            fields.append(field_from_candidate(row, key))
            spec_sample_fields_added.add(row["sample_text"])
        else:
            warnings.append(
                {
                    "type": "embedded_visible_sample",
                    "key": key,
                    "sample_text": row["sample_text"],
                    "part": row["part"],
                    "paragraph_index": row["paragraph_index"],
                    "message": "Sample text is embedded inside a larger paragraph; use literal_replacements or manually review before making it a spec field.",
                }
            )

    for sample, count in sample_counts.items():
        if count > 1:
            warnings.append(
                {
                    "type": "duplicate_visible_sample",
                    "sample_text": sample,
                    "count": count,
                    "locations": sample_locations[sample],
                    "message": "The same sample text appears multiple times; one literal replacement would update every occurrence.",
                }
            )

    if not fields and not literal_replacements:
        warnings.append(
            {
                "type": "no_stable_fields",
                "message": "No placeholders, tagged content controls, usable bookmarks, hyperlinks, or conservative visible sample fields were found. Treat this DOCX as a format sample and add placeholders/bookmarks/content-control tags or write a manual template_spec.json before production filling.",
            }
        )

    spec = {
        "template_source": str(path),
        "fields": fields,
        "draft_meta": {
            "generated_by": "draft_spec.py",
            "field_count": len(fields),
            "visible_sample_count": len(literal_candidates),
            "warnings_count": len(warnings),
        },
    }
    data = {
        "fields": {field["key"]: f"{todo_prefix}{field['key']}" for field in fields},
        "literal_replacements": literal_replacements,
    }
    report = {
        "template": str(path),
        "text_parts": text_parts,
        "spec_field_count": len(fields),
        "literal_replacement_count": len(literal_replacements),
        "placeholder_candidates": placeholder_rows,
        "content_control_candidates": control_candidates,
        "bookmark_candidates": bookmark_rows,
        "hyperlink_candidates": hyperlink_rows,
        "visible_sample_candidates": literal_candidates,
        "warnings": warnings,
        "spec": spec,
        "data_scaffold": data,
    }
    return spec, data, report


def write_json(path, payload):
    Path(path).expanduser().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path, report):
    lines = [
        "# Template Spec Draft",
        "",
        f"- Template: `{report['template']}`",
        f"- Spec fields: {report['spec_field_count']}",
        f"- Literal replacements: {report['literal_replacement_count']}",
        f"- Warnings: {len(report['warnings'])}",
        "",
        "## Fields",
    ]
    for field in report["spec"]["fields"]:
        part = field.get("part", "word/document.xml")
        lines.append(f"- `{field['key']}` via `{field['locator_type']}` in `{part}`")
    if report["visible_sample_candidates"]:
        lines.extend(["", "## Literal Replacements"])
        for row in report["visible_sample_candidates"]:
            lines.append(f"- `{row['sample_text']}` -> `{row['replacement']}`")
    if report["hyperlink_candidates"]:
        lines.extend(["", "## Hyperlink Candidates"])
        for row in report["hyperlink_candidates"]:
            lines.append(f"- `{row.get('text') or row.get('target')}` in `{row['part']}` -> `{row.get('target') or ''}`")
    if report["warnings"]:
        lines.extend(["", "## Warnings"])
        for row in report["warnings"]:
            lines.append(f"- `{row['type']}`: {row['message']}")
    Path(path).expanduser().write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Draft a conservative template_spec.json and data scaffold from one DOCX template.")
    parser.add_argument("template")
    parser.add_argument("--spec-output", help="Write draft template_spec.json")
    parser.add_argument("--data-output", help="Write TODO data scaffold JSON")
    parser.add_argument("--report", help="Write full draft report JSON")
    parser.add_argument("--report-md", help="Write a human-readable Markdown summary")
    parser.add_argument("--todo-prefix", default="TODO: ", help="Placeholder value prefix for generated data scaffolds.")
    args = parser.parse_args()

    template = Path(args.template).expanduser()
    if not template.exists():
        print(f"Template not found: {template}", file=sys.stderr)
        return 2
    spec, data, report = draft_from_docx(template, todo_prefix=args.todo_prefix)
    if args.spec_output:
        write_json(args.spec_output, spec)
    if args.data_output:
        write_json(args.data_output, data)
    if args.report:
        write_json(args.report, report)
    if args.report_md:
        write_markdown(args.report_md, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
