#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "xml": "http://www.w3.org/XML/1998/namespace",
}

ET.register_namespace("w", NS["w"])


def load_data(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "fields" not in data and "literal_replacements" not in data:
        data = {"fields": data}
    fields = {str(k): "" if v is None else str(v) for k, v in data.get("fields", {}).items()}
    literal = {str(k): "" if v is None else str(v) for k, v in data.get("literal_replacements", {}).items()}
    return fields, literal


def xml_parts(names, include_headers=True, include_footers=True):
    parts = ["word/document.xml"]
    if include_headers:
        parts.extend(sorted(n for n in names if n.startswith("word/header") and n.endswith(".xml")))
    if include_footers:
        parts.extend(sorted(n for n in names if n.startswith("word/footer") and n.endswith(".xml")))
    for optional in ["word/footnotes.xml", "word/endnotes.xml"]:
        if optional in names:
            parts.append(optional)
    return parts


def qn(name):
    prefix, local = name.split(":", 1)
    return "{%s}%s" % (NS[prefix], local)


def text_node_segments(text_nodes):
    segments = []
    offset = 0
    for node in text_nodes:
        text = node.text or ""
        segments.append({"node": node, "start": offset, "end": offset + len(text), "text": text})
        offset += len(text)
    return segments


def find_spans(text, pattern):
    if not pattern:
        return []
    spans = []
    index = 0
    while True:
        found = text.find(pattern, index)
        if found < 0:
            break
        spans.append((found, found + len(pattern)))
        index = found + len(pattern)
    return spans


def normalize_line_breaks(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def needs_space_preserve(text):
    return text.startswith(" ") or text.endswith(" ")


def set_text_node(node, text):
    text = normalize_line_breaks(text)
    node.text = text
    if needs_space_preserve(text):
        node.set(qn("xml:space"), "preserve")


def make_text_node_like(source, text):
    node = ET.Element(source.tag, {key: value for key, value in source.attrib.items() if key != qn("xml:space")})
    if needs_space_preserve(text):
        node.set(qn("xml:space"), "preserve")
    node.text = text
    return node


def materialize_line_breaks(root):
    parent_map = {child: parent for parent in root.iter() for child in list(parent)}
    breaks_inserted = 0
    for node in list(root.iter(qn("w:t"))):
        text = node.text or ""
        if "\n" not in text:
            continue
        parent = parent_map.get(node)
        if parent is None:
            continue
        children = list(parent)
        index = children.index(node)
        replacements = []
        lines = text.split("\n")
        for line_index, line in enumerate(lines):
            if line_index:
                replacements.append(ET.Element(qn("w:br")))
            replacements.append(make_text_node_like(node, line))
        if replacements:
            replacements[-1].tail = node.tail
        parent.remove(node)
        for offset, replacement in enumerate(replacements):
            parent.insert(index + offset, replacement)
        breaks_inserted += max(0, len(lines) - 1)
    return breaks_inserted


def replace_span(text_nodes, segments, start, end, replacement):
    touched = [segment for segment in segments if segment["end"] > start and segment["start"] < end]
    if not touched:
        return
    for index, segment in enumerate(touched):
        node = segment["node"]
        current = node.text or ""
        local_start = max(0, start - segment["start"])
        local_end = min(len(segment["text"]), end - segment["start"])
        before = current[:local_start]
        after = current[local_end:]
        if index == 0:
            if len(touched) == 1:
                set_text_node(node, before + replacement + after)
            else:
                set_text_node(node, before + replacement)
        elif index == len(touched) - 1:
            set_text_node(node, after)
        else:
            set_text_node(node, "")


def replace_patterns_across_text_nodes(text_nodes, replacements):
    counts = {pattern: 0 for pattern in replacements}
    for pattern, replacement in replacements.items():
        segments = text_node_segments(text_nodes)
        joined = "".join(segment["text"] for segment in segments)
        spans = find_spans(joined, pattern)
        for start, end in reversed(spans):
            replace_span(text_nodes, segments, start, end, replacement)
        counts[pattern] = len(spans)
    return counts


def replace_in_xml(xml_bytes, fields, literal):
    root = ET.fromstring(xml_bytes)
    text_nodes = root.findall(".//w:t", NS)
    replacement_counts = replace_patterns_across_text_nodes(
        text_nodes,
        {"{{" + key + "}}": value for key, value in fields.items()},
    )
    literal_counts = replace_patterns_across_text_nodes(text_nodes, literal)
    changed = any(replacement_counts.values()) or any(literal_counts.values())
    line_breaks_inserted = materialize_line_breaks(root) if changed else 0

    return ET.tostring(root, encoding="utf-8", xml_declaration=True), changed, replacement_counts, literal_counts, line_breaks_inserted


def text_format_structure_digest(xml_bytes):
    root = ET.fromstring(xml_bytes)
    for node in root.findall(".//w:t", NS):
        node.text = ""
        node.attrib.pop(qn("xml:space"), None)
    return hashlib.sha256(ET.tostring(root, encoding="utf-8")).hexdigest()


def unresolved_tokens_in_xml(xml_bytes):
    text = xml_bytes.decode("utf-8", errors="ignore")
    return sorted(set(re.findall(r"\{\{[^{}]+\}\}", text)))


def main():
    parser = argparse.ArgumentParser(description="Fill a DOCX template while preserving its OOXML structure.")
    parser.add_argument("template")
    parser.add_argument("--data", required=True, help="JSON with fields and optional literal_replacements")
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument("--report")
    parser.add_argument("--strict", action="store_true", help="Fail when a field/literal replacement is not used or tokens remain.")
    parser.add_argument("--no-headers", action="store_true")
    parser.add_argument("--no-footers", action="store_true")
    args = parser.parse_args()

    template = Path(args.template).expanduser()
    output = Path(args.output).expanduser()
    if not template.exists():
        print(f"Template not found: {template}", file=sys.stderr)
        return 2
    fields, literal = load_data(args.data)

    report = {
        "template": str(template),
        "output": str(output),
        "fields": sorted(fields),
        "literal_replacements": sorted(literal),
        "parts_changed": [],
        "text_format_checks": [],
        "replacement_counts": {},
        "literal_counts": {},
        "line_breaks_inserted": {},
        "unresolved_tokens": [],
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(template, "r") as zin, ZipFile(output, "w", ZIP_DEFLATED) as zout:
        names = set(zin.namelist())
        target_parts = set(xml_parts(names, not args.no_headers, not args.no_footers))
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in target_parts:
                before_format_digest = text_format_structure_digest(data)
                new_data, changed, counts, literal_counts, line_breaks_inserted = replace_in_xml(data, fields, literal)
                after_format_digest = text_format_structure_digest(new_data)
                if changed:
                    data = new_data
                    report["parts_changed"].append(item.filename)
                    format_check = {
                        "part": item.filename,
                        "scope": "part_text_format_structure",
                        "preserved": before_format_digest == after_format_digest,
                        "before_sha256": before_format_digest,
                        "after_sha256": after_format_digest,
                    }
                    if line_breaks_inserted:
                        format_check["line_breaks_inserted"] = line_breaks_inserted
                        format_check["expected_structure_change"] = "line_breaks_inserted"
                        report["line_breaks_inserted"][item.filename] = line_breaks_inserted
                    report["text_format_checks"].append(format_check)
                for key, value in counts.items():
                    report["replacement_counts"][key] = report["replacement_counts"].get(key, 0) + value
                for key, value in literal_counts.items():
                    report["literal_counts"][key] = report["literal_counts"].get(key, 0) + value
                report["unresolved_tokens"].extend(unresolved_tokens_in_xml(data))
            zout.writestr(item, data)

    report["unresolved_tokens"] = sorted(set(report["unresolved_tokens"]))
    unused_fields = [k for k, v in report["replacement_counts"].items() if v == 0]
    unused_literal = [k for k, v in report["literal_counts"].items() if v == 0]
    report["unused_fields"] = unused_fields
    report["unused_literal_replacements"] = unused_literal

    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.strict and (unused_fields or unused_literal or report["unresolved_tokens"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
