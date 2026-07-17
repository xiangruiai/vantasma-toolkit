#!/usr/bin/env python3
import argparse
import hashlib
import json
import posixpath
import re
import shutil
import sys
import tempfile
from pathlib import Path
from xml.dom import Node, minidom
from zipfile import ZIP_DEFLATED, ZipFile


IMAGE_CONTENT_TYPES = {
    "bmp": "image/bmp",
    "gif": "image/gif",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}

RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORDPROCESSINGML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CUSTOM_XML_PROPS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps"
HYPERLINK_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"

NOTE_CONFIGS = {
    "footnotes": {
        "part": "word/footnotes.xml",
        "root": "w:footnotes",
        "item": "w:footnote",
        "reference_local": "footnoteReference",
        "relationship_type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes",
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
        "report_key": "footnotes",
    },
    "endnotes": {
        "part": "word/endnotes.xml",
        "root": "w:endnotes",
        "item": "w:endnote",
        "reference_local": "endnoteReference",
        "relationship_type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes",
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml",
        "report_key": "endnotes",
    },
}

COMMENT_CONFIG = {
    "part": "word/comments.xml",
    "root": "w:comments",
    "item": "w:comment",
    "reference_locals": ["commentRangeStart", "commentRangeEnd", "commentReference"],
    "relationship_type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
    "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
}

FIELD_CODE_LOCALS = {"fldSimple", "fldChar", "instrText", "fldData", "delInstrText"}

TRACKED_REVISION_LOCALS = {
    "ins",
    "del",
    "delText",
    "moveFrom",
    "moveTo",
    "moveFromRangeStart",
    "moveFromRangeEnd",
    "moveToRangeStart",
    "moveToRangeEnd",
    "customXmlInsRangeStart",
    "customXmlInsRangeEnd",
    "customXmlDelRangeStart",
    "customXmlDelRangeEnd",
    "customXmlMoveFromRangeStart",
    "customXmlMoveFromRangeEnd",
    "customXmlMoveToRangeStart",
    "customXmlMoveToRangeEnd",
    "cellIns",
    "cellDel",
    "cellMerge",
    "pPrChange",
    "rPrChange",
    "tblPrChange",
    "trPrChange",
    "tcPrChange",
    "sectPrChange",
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def safe_text(value):
    return "" if value is None else str(value)


def numeric_id_sort_key(value):
    text = safe_text(value)
    if text.lstrip("-").isdigit():
        return (0, int(text))
    return (1, text)


def normalize_text(value):
    return re.sub(r"\s+", " ", safe_text(value).replace("\r\n", "\n").replace("\r", "\n")).strip()


def normalize_store_item_id(value):
    return safe_text(value).strip().strip("{}").lower()


MISSING = object()
FALSE_STRINGS = {"", "0", "false", "no", "n", "off", "none", "null", "否", "不", "无", "假", "关闭"}
CHECKBOX_MODES = {"checkbox", "check_box", "content_control_checkbox"}
CHOICE_MODES = {"choice", "dropdown", "drop_down", "drop_down_list", "combo_box", "combobox", "content_control_choice"}
DATE_MODES = {"date", "date_control", "content_control_date"}
REPEATING_SECTION_MODES = {"repeating_section", "repeatingSection", "content_control_repeating_section"}
BOOKMARK_TEXT_MODES = {"bookmark_text", "bookmark", "inline_bookmark"}
HYPERLINK_INSERT_MODES = {"insert_hyperlink", "hyperlink_insert", "new_hyperlink", "create_hyperlink"}
CONTENT_LOCK_VALUES = {"contentLocked", "sdtContentLocked"}


def truthy(value):
    if value is MISSING or value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in FALSE_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def nested_value(source, path):
    if not isinstance(source, dict) or not path:
        return MISSING
    cur = source
    for part in safe_text(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return MISSING
        cur = cur[part]
    return cur


def data_value(raw_data, field_data, key):
    if not key:
        return MISSING
    sources = []
    if isinstance(raw_data, dict):
        for section in ["conditions", "fields", "images", "tables"]:
            if isinstance(raw_data.get(section), dict):
                sources.append(raw_data[section])
        sources.append(raw_data)
    if isinstance(field_data, dict):
        sources.insert(0, field_data)
    for source in sources:
        value = nested_value(source, key)
        if value is not MISSING:
            return value
    return MISSING


def values_equal(actual, expected):
    if isinstance(expected, bool):
        return truthy(actual) is expected
    return actual == expected or safe_text(actual) == safe_text(expected)


def evaluate_condition(block, raw_data, field_data):
    condition = block.get("condition", block.get("when", block.get("if", block.get("key"))))
    if isinstance(condition, str):
        value = data_value(raw_data, field_data, condition)
        return truthy(value), value, condition
    if not isinstance(condition, dict):
        value = data_value(raw_data, field_data, block.get("key"))
        return truthy(value), value, block.get("key")
    key = condition.get("field") or condition.get("key") or condition.get("path") or condition.get("exists")
    value = data_value(raw_data, field_data, key)
    if "exists" in condition:
        passed = value is not MISSING and value not in (None, "")
    elif "equals" in condition:
        passed = values_equal(value, condition.get("equals"))
    elif "not_equals" in condition:
        passed = not values_equal(value, condition.get("not_equals"))
    elif "in" in condition:
        passed = any(values_equal(value, item) for item in condition.get("in", []))
    elif "not_in" in condition:
        passed = not any(values_equal(value, item) for item in condition.get("not_in", []))
    else:
        passed = truthy(value)
    return passed, value, key


def paragraph_values(value):
    if isinstance(value, list):
        values = [safe_text(item) for item in value]
    else:
        values = [
            block.strip()
            for block in re.split(r"\n\s*\n", safe_text(value).replace("\r\n", "\n").replace("\r", "\n"))
            if block.strip()
        ]
    return values or [""]


def normalize_line_breaks(value):
    return safe_text(value).replace("\r\n", "\n").replace("\r", "\n")


def needs_space_preserve(value):
    text = safe_text(value)
    return text.startswith(" ") or text.endswith(" ")


def line_break_count(value):
    return normalize_line_breaks(value).count("\n")


class DocxWork:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.tmp = Path(tempfile.mkdtemp(prefix="tpl_fidelity_"))
        self.work = self.tmp / "work"
        self.work.mkdir(parents=True, exist_ok=True)
        with ZipFile(self.path) as archive:
            archive.extractall(self.work)
        self.doms = {}
        self.part_paths = {}
        self.part_resolutions = {}
        self.last_resolved_part = None
        self.last_part_resolution = None
        self.last_line_breaks_inserted = 0
        self.last_content_control_placeholder_removed = 0
        if not (self.work / "word" / "document.xml").exists():
            raise RuntimeError(f"Missing word/document.xml in {self.path}")
        self.dom = self.load_part("word/document.xml")

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load_package_xml(self, part):
        part = safe_text(part).lstrip("/")
        if part in self.doms:
            return self.doms[part]
        part_path = self.work / part
        if not part_path.exists():
            return None
        dom = minidom.parse(str(part_path))
        self.doms[part] = dom
        self.part_paths[part] = part_path
        return dom

    def load_part(self, part):
        part = self.normalize_part_name(part)
        return self.load_package_xml(part)

    @staticmethod
    def normalize_part_name(part):
        part = safe_text(part).lstrip("/")
        if part in {"", "body", "document"}:
            return "word/document.xml"
        if part.endswith(".xml") and not part.startswith("word/"):
            return "word/" + part
        return part

    def available_text_parts(self):
        parts = ["word/document.xml"]
        word_dir = self.work / "word"
        if word_dir.exists():
            for pattern in ["header*.xml", "footer*.xml"]:
                parts.extend("word/" + path.name for path in sorted(word_dir.glob(pattern)))
            for name in ["footnotes.xml", "endnotes.xml"]:
                if (word_dir / name).exists():
                    parts.append("word/" + name)
        return list(dict.fromkeys(parts))

    def section_properties(self):
        dom = self.load_part("word/document.xml")
        if dom is None:
            return []
        return self.elements_by_local_name(dom, "sectPr")

    @staticmethod
    def section_part_kind(spec):
        raw = safe_text(spec.get("type") or spec.get("kind") or spec.get("part_type") or spec.get("target")).lower()
        if raw in {"section_header", "header", "headers"}:
            return "header"
        if raw in {"section_footer", "footer", "footers"}:
            return "footer"
        return ""

    @staticmethod
    def normalize_reference_type(value):
        text = safe_text(value or "default").lower()
        aliases = {"primary": "default", "odd": "default", "normal": "default"}
        return aliases.get(text, text)

    def document_relationship_target(self, relationship_id):
        rels_dom = self.load_rels_for_part("word/document.xml")
        relationship = self.relationship_by_id(rels_dom, relationship_id)
        if relationship is None:
            return None, None
        target = relationship.getAttribute("Target")
        return self.relationship_target_package_path("word/document.xml", target), target

    def section_text_part_from_spec(self, spec):
        kind = self.section_part_kind(spec)
        if not kind:
            return None
        sections = self.section_properties()
        if not sections:
            return None
        raw_index = spec.get("section_index", spec.get("section", spec.get("index", 0)))
        section_index = int(raw_index)
        if section_index < 0:
            section_index = len(sections) + section_index
        if section_index < 0 or section_index >= len(sections):
            return None
        reference_type = self.normalize_reference_type(
            spec.get("reference_type") or spec.get("header_type") or spec.get("footer_type") or spec.get("type_name")
        )
        follow_previous = truthy(spec.get("follow_previous", True))
        reference_local = f"{kind}Reference"
        search_indices = range(section_index, -1, -1) if follow_previous else [section_index]
        for current_index in search_indices:
            section = sections[current_index]
            for reference in self.elements_by_local_name(section, reference_local):
                node_type = self.normalize_reference_type(reference.getAttribute("w:type") or reference.getAttribute("type"))
                if node_type != reference_type:
                    continue
                relationship_id = reference.getAttribute("r:id") or reference.getAttribute("id")
                if not relationship_id:
                    continue
                package_path, relationship_target = self.document_relationship_target(relationship_id)
                if not package_path:
                    continue
                part = self.normalize_part_name(package_path)
                return {
                    "part": part,
                    "kind": kind,
                    "reference_type": reference_type,
                    "requested_section_index": section_index,
                    "source_section_index": current_index,
                    "linked_to_previous": current_index != section_index,
                    "relationship_id": relationship_id,
                    "relationship_target": relationship_target,
                }
        return None

    def expand_part_spec(self, part_spec):
        if part_spec in (None, "", "body", "document"):
            return ["word/document.xml"]
        if isinstance(part_spec, list):
            out = []
            for item in part_spec:
                out.extend(self.expand_part_spec(item))
            return list(dict.fromkeys(out))
        if isinstance(part_spec, dict):
            resolution = self.section_text_part_from_spec(part_spec)
            if resolution:
                self.part_resolutions[resolution["part"]] = resolution
                return [resolution["part"]]
            return []
        part = safe_text(part_spec)
        if part in {"all", "text_parts", "all_text"}:
            return self.available_text_parts()
        if part in {"headers", "header"}:
            return [p for p in self.available_text_parts() if p.startswith("word/header")]
        if part in {"footers", "footer"}:
            return [p for p in self.available_text_parts() if p.startswith("word/footer")]
        if part in {"notes", "footnotes_endnotes"}:
            return [p for p in self.available_text_parts() if p in {"word/footnotes.xml", "word/endnotes.xml"}]
        return [self.normalize_part_name(part)]

    def field_parts(self, field):
        locator = field.get("locator", {})
        part_spec = field.get("part") or field.get("parts") or locator.get("part") or locator.get("parts")
        return self.expand_part_spec(part_spec)

    def paragraphs(self, part="word/document.xml"):
        dom = self.load_part(part)
        if dom is None:
            return []
        return [node for node in dom.getElementsByTagName("w:p") if node.nodeType == Node.ELEMENT_NODE]

    def tables(self, part="word/document.xml"):
        dom = self.load_part(part)
        if dom is None:
            return []
        return [node for node in dom.getElementsByTagName("w:tbl") if node.nodeType == Node.ELEMENT_NODE]

    @staticmethod
    def ancestor_count_by_tag(node, tag):
        count = 0
        parent = node.parentNode
        while parent is not None:
            if parent.nodeType == Node.ELEMENT_NODE and getattr(parent, "tagName", "") == tag:
                count += 1
            parent = parent.parentNode
        return count

    @staticmethod
    def table_depth(table):
        return DocxWork.ancestor_count_by_tag(table, "w:tbl")

    def filter_tables_by_depth(self, tables, locator):
        if truthy(locator.get("top_level_only")):
            tables = [table for table in tables if self.table_depth(table) == 0]
        if "depth" in locator:
            depth = int(locator.get("depth"))
            tables = [table for table in tables if self.table_depth(table) == depth]
        if "min_depth" in locator:
            min_depth = int(locator.get("min_depth"))
            tables = [table for table in tables if self.table_depth(table) >= min_depth]
        if "max_depth" in locator:
            max_depth = int(locator.get("max_depth"))
            tables = [table for table in tables if self.table_depth(table) <= max_depth]
        return tables

    @staticmethod
    def element_children(node, tag=None):
        children = [child for child in node.childNodes if child.nodeType == Node.ELEMENT_NODE]
        if tag:
            children = [child for child in children if child.tagName == tag]
        return children

    @staticmethod
    def first_child(node, tag):
        for child in DocxWork.element_children(node):
            if child.tagName == tag:
                return child
        return None

    @staticmethod
    def nodes_with_tag(node, tag):
        nodes = []
        if getattr(node, "tagName", None) == tag:
            nodes.append(node)
        nodes.extend(node.getElementsByTagName(tag))
        return nodes

    @staticmethod
    def format_child_xml(node, tag):
        child = DocxWork.first_child(node, tag)
        return child.toxml() if child is not None else ""

    @staticmethod
    def text_format_signature(nodes):
        if not isinstance(nodes, list):
            nodes = [nodes]
        paragraphs = []
        runs = []
        controls = []
        for node in nodes:
            paragraphs.extend(DocxWork.nodes_with_tag(node, "w:p"))
            runs.extend(DocxWork.nodes_with_tag(node, "w:r"))
            controls.extend(DocxWork.nodes_with_tag(node, "w:sdt"))
        signature = {
            "paragraph_pPr": [DocxWork.format_child_xml(node, "w:pPr") for node in paragraphs],
            "run_rPr": [DocxWork.format_child_xml(node, "w:rPr") for node in runs],
            "content_control_sdtPr": [DocxWork.format_child_xml(node, "w:sdtPr") for node in controls],
        }
        payload = json.dumps(signature, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "paragraph_count": len(paragraphs),
            "run_count": len(runs),
            "content_control_count": len(controls),
        }

    @staticmethod
    def text_format_check(before_node, after_nodes, scope):
        before = DocxWork.text_format_signature(before_node)
        after = DocxWork.text_format_signature(after_nodes)
        return {
            "checked": True,
            "scope": scope,
            "preserved": before["sha256"] == after["sha256"],
            "before": before,
            "after": after,
        }

    @staticmethod
    def table_row_format_signature(row):
        rows = DocxWork.nodes_with_tag(row, "w:tr")
        cells = DocxWork.nodes_with_tag(row, "w:tc")
        tables = DocxWork.nodes_with_tag(row, "w:tbl")
        paragraphs = DocxWork.nodes_with_tag(row, "w:p")
        runs = DocxWork.nodes_with_tag(row, "w:r")
        signature = {
            "table_tblPr": [DocxWork.format_child_xml(node, "w:tblPr") for node in tables],
            "row_trPr": [DocxWork.format_child_xml(node, "w:trPr") for node in rows],
            "cell_tcPr": [DocxWork.format_child_xml(node, "w:tcPr") for node in cells],
            "paragraph_pPr": [DocxWork.format_child_xml(node, "w:pPr") for node in paragraphs],
            "run_rPr": [DocxWork.format_child_xml(node, "w:rPr") for node in runs],
        }
        payload = json.dumps(signature, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "table_count": len(tables),
            "row_count": len(rows),
            "cell_count": len(cells),
            "paragraph_count": len(paragraphs),
            "run_count": len(runs),
        }

    @staticmethod
    def table_loop_format_check(template_signature, row_checks):
        failures = [row for row in row_checks if not row.get("preserved")]
        return {
            "checked": bool(row_checks),
            "scope": "table_loop_rows",
            "preserved": not failures,
            "template": template_signature,
            "rows_checked": len(row_checks),
            "row_checks": row_checks,
            "failures": failures,
        }

    @staticmethod
    def paragraph_text(paragraph):
        chunks = []
        for node in paragraph.getElementsByTagName("w:t"):
            if node.firstChild:
                chunks.append(node.firstChild.data)
        return "".join(chunks)

    @staticmethod
    def element_text(element):
        chunks = []
        for node in element.getElementsByTagName("w:t"):
            if node.firstChild:
                chunks.append(node.firstChild.data)
        return "".join(chunks)

    @staticmethod
    def parent_paragraph(node):
        cur = node
        while cur is not None:
            if cur.nodeType == Node.ELEMENT_NODE and getattr(cur, "tagName", None) == "w:p":
                return cur
            cur = cur.parentNode
        return None

    def find_para_id(self, para_id, part="word/document.xml"):
        for paragraph in self.paragraphs(part):
            if paragraph.getAttribute("w14:paraId") == para_id:
                return paragraph
        return None

    def find_text_anchor(self, locator, part="word/document.xml"):
        needle = locator.get("text") or locator.get("anchor_text")
        if not needle:
            return None
        match = locator.get("match", "contains")
        target = normalize_text(needle)
        paragraphs = self.paragraphs(part)
        for index, paragraph in enumerate(paragraphs):
            text = normalize_text(self.paragraph_text(paragraph))
            ok = (text == target) if match == "exact" else (target in text)
            if match == "regex":
                ok = bool(re.search(needle, text))
            if not ok:
                continue
            action_target = locator.get("target", "self")
            if action_target == "next_paragraph":
                return paragraphs[index + 1] if index + 1 < len(paragraphs) else None
            if action_target == "after":
                return {"insert_after": paragraph}
            return paragraph
        return None

    def find_bookmark(self, locator, part="word/document.xml"):
        bookmark = self.find_bookmark_start(locator, part)
        if bookmark is None:
            return None
        return self.parent_paragraph(bookmark)

    @staticmethod
    def hyperlink_relationship_id(hyperlink):
        return hyperlink.getAttribute("r:id") or hyperlink.getAttribute("id")

    def hyperlink_relationship_info(self, hyperlink, part):
        relationship_id = self.hyperlink_relationship_id(hyperlink)
        relationship_part = self.rels_part_name(part)
        info = {
            "relationship_id": relationship_id,
            "relationship_part": relationship_part,
        }
        if not relationship_id:
            anchor = hyperlink.getAttribute("w:anchor") or hyperlink.getAttribute("anchor")
            if anchor:
                info["anchor"] = anchor
            return info
        rels_dom = self.load_rels_for_part(part)
        if rels_dom is None:
            info["relationship_error"] = "relationships_part_not_found"
            return info
        relationship = self.relationship_by_id(rels_dom, relationship_id)
        if relationship is None:
            info["relationship_error"] = "relationship_id_not_found"
            return info
        info.update(
            {
                "relationship_type": relationship.getAttribute("Type"),
                "target": relationship.getAttribute("Target"),
                "target_mode": relationship.getAttribute("TargetMode"),
            }
        )
        return info

    def hyperlink_matches(self, hyperlink, locator, part, index):
        desired_index = locator.get("index")
        if desired_index is not None and int(desired_index) != index:
            return False
        desired_text = locator.get("text") or locator.get("display_text") or locator.get("label")
        if desired_text:
            match = locator.get("match", "contains")
            current_text = normalize_text(self.element_text(hyperlink))
            needle = normalize_text(desired_text)
            if match == "exact":
                if current_text != needle:
                    return False
            elif match == "regex":
                if not re.search(safe_text(desired_text), current_text):
                    return False
            elif needle not in current_text:
                return False
        desired_relationship_id = locator.get("relationship_id") or locator.get("r_id") or locator.get("rid")
        relationship_id = self.hyperlink_relationship_id(hyperlink)
        if desired_relationship_id and safe_text(desired_relationship_id) != safe_text(relationship_id):
            return False
        desired_anchor = locator.get("anchor") or locator.get("bookmark")
        if desired_anchor:
            anchor = hyperlink.getAttribute("w:anchor") or hyperlink.getAttribute("anchor")
            if safe_text(desired_anchor) != anchor:
                return False
        desired_target = locator.get("target") or locator.get("url") or locator.get("href")
        desired_target_mode = locator.get("target_mode") or locator.get("TargetMode")
        if desired_target or desired_target_mode:
            info = self.hyperlink_relationship_info(hyperlink, part)
            if desired_target and info.get("target") != safe_text(desired_target):
                return False
            if desired_target_mode and info.get("target_mode") != safe_text(desired_target_mode):
                return False
        return True

    def find_hyperlink(self, locator, part="word/document.xml"):
        dom = self.load_part(part)
        if dom is None:
            return None
        hyperlinks = self.elements_by_local_name(dom, "hyperlink")
        for index, hyperlink in enumerate(hyperlinks):
            if self.hyperlink_matches(hyperlink, locator, part, index):
                return hyperlink
        return None

    def find_bookmark_start(self, locator, part="word/document.xml"):
        name = locator.get("name") or locator.get("bookmark") or locator.get("bookmark_name")
        bookmark_id = locator.get("id") or locator.get("bookmark_id")
        if not name and bookmark_id is None:
            return None
        dom = self.load_part(part)
        if dom is None:
            return None
        for bookmark in dom.getElementsByTagName("w:bookmarkStart"):
            if name and bookmark.getAttribute("w:name") == name:
                return bookmark
            if bookmark_id is not None and bookmark.getAttribute("w:id") == safe_text(bookmark_id):
                return bookmark
        return None

    def find_bookmark_end(self, bookmark_id, part="word/document.xml"):
        dom = self.load_part(part)
        if dom is None:
            return None
        for bookmark in dom.getElementsByTagName("w:bookmarkEnd"):
            if bookmark.getAttribute("w:id") == safe_text(bookmark_id):
                return bookmark
        return None

    def bookmark_range(self, locator, part="word/document.xml"):
        start = self.find_bookmark_start(locator, part)
        if start is None:
            return None, "bookmark_start_not_found"
        bookmark_id = start.getAttribute("w:id") or start.getAttribute("id")
        end = self.find_bookmark_end(bookmark_id, part)
        if end is None:
            return None, "bookmark_end_not_found"
        paragraph = self.parent_paragraph(start)
        if paragraph is None or self.parent_paragraph(end) is not paragraph:
            return None, "bookmark_paragraph_range_not_supported"
        nodes = self.sibling_nodes_between(start, end)
        if nodes is None:
            return None, "bookmark_range_not_same_parent"
        return {
            "start": start,
            "end": end,
            "nodes": nodes,
            "inner_nodes": nodes[1:-1],
            "paragraph": paragraph,
            "id": bookmark_id,
            "name": start.getAttribute("w:name"),
        }, None

    def run_pr_from_run(self, run):
        run_pr = self.first_child(run, "w:rPr")
        return run_pr.cloneNode(True) if run_pr is not None else None

    def nearest_run_pr(self, anchor, direction):
        if direction == "previous":
            node = anchor.previousSibling
            step = "previousSibling"
        else:
            node = anchor.nextSibling
            step = "nextSibling"
        while node is not None:
            if node.nodeType == Node.ELEMENT_NODE:
                if getattr(node, "tagName", None) == "w:r":
                    run_pr = self.run_pr_from_run(node)
                    if run_pr is not None:
                        return run_pr
                runs = list(node.getElementsByTagName("w:r"))
                if direction == "previous":
                    runs = list(reversed(runs))
                for run in runs:
                    run_pr = self.run_pr_from_run(run)
                    if run_pr is not None:
                        return run_pr
            node = getattr(node, step)
        return None

    def bookmark_insert_run_pr(self, bookmark):
        previous_run_pr = self.nearest_run_pr(bookmark["start"], "previous")
        if previous_run_pr is not None:
            return previous_run_pr, "previous_run"
        next_run_pr = self.nearest_run_pr(bookmark["end"], "next")
        if next_run_pr is not None:
            return next_run_pr, "next_run"
        _, run_pr = self.style_seed(bookmark["paragraph"])
        return run_pr, "paragraph_seed" if run_pr is not None else "none"

    def replace_bookmark_text(self, locator, value, part="word/document.xml"):
        bookmark, error = self.bookmark_range(locator, part)
        if error:
            return {"action": "bookmark_text_replace", "status": "error", "error": error}
        text_nodes = []
        for node in bookmark["inner_nodes"]:
            if node.nodeType != Node.ELEMENT_NODE:
                continue
            if getattr(node, "tagName", "") == "w:t":
                text_nodes.append(node)
            text_nodes.extend(node.getElementsByTagName("w:t"))
        if text_nodes:
            self.set_text_node_value(text_nodes[0], safe_text(value))
            for node in text_nodes[1:]:
                self.set_text_node_value(node, "")
            line_breaks_inserted = self.materialize_line_breaks_in_text_nodes(text_nodes)
            return {
                "action": "bookmark_text_replace",
                "bookmark_name": bookmark["name"],
                "bookmark_id": bookmark["id"],
                "text_nodes_changed": len(text_nodes),
                "line_breaks_inserted": line_breaks_inserted,
                "run_inserted": False,
            }
        run_pr, run_style_source = self.bookmark_insert_run_pr(bookmark)
        run, line_breaks_inserted = self.build_text_run(bookmark["start"].ownerDocument, value, run_pr)
        bookmark["end"].parentNode.insertBefore(run, bookmark["end"])
        return {
            "action": "bookmark_text_replace",
            "bookmark_name": bookmark["name"],
            "bookmark_id": bookmark["id"],
            "text_nodes_changed": 1,
            "line_breaks_inserted": line_breaks_inserted,
            "run_inserted": True,
            "run_style_source": run_style_source,
            "expected_structure_change": "bookmark_empty_range_inserted",
        }

    @staticmethod
    def hyperlink_value(value, existing_text):
        if isinstance(value, dict):
            text_key = next((key for key in ["text", "display_text", "label"] if key in value), None)
            url_key = next((key for key in ["url", "href", "target"] if key in value), None)
            display_text = safe_text(value[text_key]) if text_key is not None else existing_text
            url = MISSING if url_key is None else safe_text(value[url_key])
            return display_text, url, text_key is not None, url_key is not None
        return safe_text(value), MISSING, True, False

    @staticmethod
    def hyperlink_insert_value(value, field):
        display_text, url, text_provided, url_provided = DocxWork.hyperlink_value(value, "")
        hyperlink_spec = field.get("hyperlink") if isinstance(field.get("hyperlink"), dict) else {}
        if url is MISSING:
            url = (
                field.get("url")
                or field.get("href")
                or field.get("target_url")
                or field.get("hyperlink_url")
                or hyperlink_spec.get("url")
                or hyperlink_spec.get("href")
                or hyperlink_spec.get("target")
            )
            url_provided = bool(url)
        if not display_text:
            display_text = (
                field.get("display_text")
                or field.get("label")
                or hyperlink_spec.get("text")
                or hyperlink_spec.get("display_text")
                or hyperlink_spec.get("label")
                or url
                or ""
            )
            text_provided = bool(display_text)
        return safe_text(display_text), safe_text(url), text_provided, url_provided

    def ensure_external_hyperlink_relationship(self, part, url):
        relationship_part = self.rels_part_name(part)
        if not url:
            return {"status": "error", "error": "hyperlink_url_empty", "relationship_part": relationship_part}
        rels_dom = self.ensure_rels_for_part(part)
        existing_id = self.matching_relationship_id_for_target(rels_dom, HYPERLINK_REL, url, "External")
        if existing_id:
            return {
                "status": "ok",
                "relationship_id": existing_id,
                "relationship_part": relationship_part,
                "relationship_type": HYPERLINK_REL,
                "target": url,
                "target_mode": "External",
                "relationship_reused": True,
                "relationship_created": False,
            }
        relationship_id = self.next_relationship_id(rels_dom)
        node = rels_dom.createElement("Relationship")
        node.setAttribute("Id", relationship_id)
        node.setAttribute("Type", HYPERLINK_REL)
        node.setAttribute("Target", url)
        node.setAttribute("TargetMode", "External")
        rels_dom.documentElement.appendChild(node)
        return {
            "status": "ok",
            "relationship_id": relationship_id,
            "relationship_part": relationship_part,
            "relationship_type": HYPERLINK_REL,
            "target": url,
            "target_mode": "External",
            "relationship_reused": False,
            "relationship_created": True,
        }

    def build_external_hyperlink(self, dom, relationship_id, display_text, run_pr=None):
        hyperlink = dom.createElement("w:hyperlink")
        hyperlink.setAttribute("r:id", relationship_id)
        run, line_breaks_inserted = self.build_text_run(dom, display_text, run_pr)
        hyperlink.appendChild(run)
        return hyperlink, line_breaks_inserted

    @staticmethod
    def ancestor_by_tag(node, tag):
        cur = node
        while cur is not None:
            if cur.nodeType == Node.ELEMENT_NODE and getattr(cur, "tagName", None) == tag:
                return cur
            cur = cur.parentNode
        return None

    @staticmethod
    def direct_child_under(node, ancestor):
        cur = node
        previous = None
        while cur is not None and cur is not ancestor:
            previous = cur
            cur = cur.parentNode
        return previous if cur is ancestor else None

    @staticmethod
    def insert_sibling_after(parent, new_node, anchor):
        if anchor is None or anchor.parentNode is not parent:
            parent.appendChild(new_node)
            return
        if anchor.nextSibling is not None:
            parent.insertBefore(new_node, anchor.nextSibling)
        else:
            parent.appendChild(new_node)

    def hyperlink_pattern_for_field(self, field):
        locator = field.get("locator") or {}
        locator_type = field.get("locator_type")
        if field.get("replace_text"):
            return safe_text(field.get("replace_text"))
        if locator.get("replace_text"):
            return safe_text(locator.get("replace_text"))
        if locator_type == "placeholder":
            return safe_text(locator.get("token") or ("{{" + field.get("key", "") + "}}"))
        if locator_type == "literal":
            return safe_text(locator.get("text") or locator.get("literal"))
        if locator_type == "text_anchor":
            return safe_text(locator.get("text") or locator.get("anchor_text"))
        return ""

    def replace_text_with_hyperlink(self, element, pattern, value, field, part):
        display_text, url, text_provided, url_provided = self.hyperlink_insert_value(value, field)
        if not url:
            return {"action": "hyperlink_insert", "status": "error", "error": "hyperlink_url_empty"}
        if not display_text:
            return {"action": "hyperlink_insert", "status": "error", "error": "hyperlink_display_text_empty"}
        if not pattern:
            return {"action": "hyperlink_insert", "status": "error", "error": "hyperlink_pattern_empty"}
        text_nodes = element.getElementsByTagName("w:t")
        segments = self.text_node_segments(text_nodes)
        joined = "".join(segment["text"] for segment in segments)
        spans = self.find_spans(joined, pattern)
        if not spans:
            return {"action": "hyperlink_insert", "status": "error", "error": "hyperlink_pattern_not_found", "pattern": pattern}

        start, end = spans[0]
        touched = [segment for segment in segments if segment["end"] > start and segment["start"] < end]
        if not touched:
            return {"action": "hyperlink_insert", "status": "error", "error": "hyperlink_pattern_not_found", "pattern": pattern}
        first_node = touched[0]["node"]
        last_node = touched[-1]["node"]
        paragraph = self.parent_paragraph(first_node)
        if paragraph is None or self.parent_paragraph(last_node) is not paragraph:
            return {"action": "hyperlink_insert", "status": "error", "error": "hyperlink_pattern_crosses_paragraphs", "pattern": pattern}

        first_text = self.text_node_value(first_node)
        last_text = self.text_node_value(last_node)
        first_local_start = max(0, start - touched[0]["start"])
        last_local_end = min(len(touched[-1]["text"]), end - touched[-1]["start"])
        prefix = first_text[:first_local_start]
        suffix = last_text[last_local_end:]

        first_run = self.ancestor_by_tag(first_node, "w:r")
        run_pr = self.run_pr_from_run(first_run) if first_run is not None else None
        relationship = self.ensure_external_hyperlink_relationship(part, url)
        if relationship.get("status") == "error":
            return {"action": "hyperlink_insert", "status": "error", **relationship}
        hyperlink, line_breaks_inserted = self.build_external_hyperlink(first_node.ownerDocument, relationship["relationship_id"], display_text, run_pr)

        if first_node is last_node:
            self.set_text_node_value(first_node, prefix)
            first_child = self.direct_child_under(first_node, paragraph)
            self.insert_sibling_after(paragraph, hyperlink, first_child)
            if suffix:
                suffix_run, suffix_breaks = self.build_text_run(first_node.ownerDocument, suffix, run_pr)
                self.insert_sibling_after(paragraph, suffix_run, hyperlink)
                line_breaks_inserted += suffix_breaks
        else:
            for index, segment in enumerate(touched):
                node = segment["node"]
                if index == 0:
                    self.set_text_node_value(node, prefix)
                elif index == len(touched) - 1:
                    self.set_text_node_value(node, suffix)
                else:
                    self.set_text_node_value(node, "")
            if suffix:
                insert_before = self.direct_child_under(last_node, paragraph)
                if insert_before is not None:
                    paragraph.insertBefore(hyperlink, insert_before)
                else:
                    paragraph.appendChild(hyperlink)
            else:
                last_child = self.direct_child_under(last_node, paragraph)
                self.insert_sibling_after(paragraph, hyperlink, last_child)

        return {
            "action": "hyperlink_insert",
            "pattern": pattern,
            "display_text": display_text,
            "text_provided": text_provided,
            "url_provided": url_provided,
            "occurrences_found": len(spans),
            "occurrences_replaced": 1,
            "line_breaks_inserted": line_breaks_inserted,
            "expected_structure_change": "hyperlink_inserted",
            **{key: row for key, row in relationship.items() if key != "status"},
        }

    def update_hyperlink_relationship(self, hyperlink, part, url):
        relationship_id = self.hyperlink_relationship_id(hyperlink)
        relationship_part = self.rels_part_name(part)
        if not relationship_id:
            return {
                "status": "error",
                "error": "hyperlink_relationship_id_not_found",
                "relationship_part": relationship_part,
            }
        if not url:
            return {
                "status": "error",
                "error": "hyperlink_url_empty",
                "relationship_id": relationship_id,
                "relationship_part": relationship_part,
            }
        rels_dom = self.load_rels_for_part(part)
        if rels_dom is None:
            return {
                "status": "error",
                "error": "relationships_part_not_found",
                "relationship_id": relationship_id,
                "relationship_part": relationship_part,
            }
        relationship = self.relationship_by_id(rels_dom, relationship_id)
        if relationship is None:
            return {
                "status": "error",
                "error": "relationship_id_not_found",
                "relationship_id": relationship_id,
                "relationship_part": relationship_part,
            }
        old_target = relationship.getAttribute("Target")
        old_target_mode = relationship.getAttribute("TargetMode")
        old_type = relationship.getAttribute("Type")
        relationship.setAttribute("Target", url)
        relationship.setAttribute("TargetMode", "External")
        if not old_type:
            relationship.setAttribute("Type", HYPERLINK_REL)
        return {
            "status": "ok",
            "relationship_id": relationship_id,
            "relationship_part": relationship_part,
            "relationship_type": old_type or HYPERLINK_REL,
            "target_before": old_target,
            "target": url,
            "target_mode_before": old_target_mode,
            "target_mode": "External",
            "relationship_updated": old_target != url or old_target_mode != "External",
        }

    def replace_hyperlink(self, hyperlink, value, part):
        old_text = self.element_text(hyperlink)
        display_text, url, text_provided, url_provided = self.hyperlink_value(value, old_text)
        text_nodes = hyperlink.getElementsByTagName("w:t")
        if text_provided and not text_nodes:
            return {"action": "hyperlink_replace", "status": "error", "error": "hyperlink_text_node_not_found"}

        relationship_before = self.hyperlink_relationship_info(hyperlink, part)
        line_breaks_inserted = 0
        text_nodes_changed = 0
        if text_provided:
            self.set_text_node_value(text_nodes[0], display_text)
            for node in text_nodes[1:]:
                self.set_text_node_value(node, "")
            line_breaks_inserted = self.materialize_line_breaks_in_text_nodes(text_nodes)
            text_nodes_changed = len(text_nodes)

        relationship_update = {}
        if url_provided:
            relationship_update = self.update_hyperlink_relationship(hyperlink, part, url)
            if relationship_update.get("status") == "error":
                return {"action": "hyperlink_replace", "status": "error", **relationship_update}

        relationship_after = self.hyperlink_relationship_info(hyperlink, part)
        summary = {
            "action": "hyperlink_replace",
            "display_text_before": old_text,
            "display_text": self.element_text(hyperlink),
            "text_provided": text_provided,
            "url_provided": url_provided,
            "text_nodes_changed": text_nodes_changed,
            "line_breaks_inserted": line_breaks_inserted,
            "relationship_before": relationship_before,
            "relationship_after": relationship_after,
        }
        if relationship_update:
            summary.update({key: value for key, value in relationship_update.items() if key != "status"})
        return summary

    def find_content_control(self, locator, part="word/document.xml", return_content=False):
        desired_tag = locator.get("tag")
        desired_alias = locator.get("alias")
        desired_index = locator.get("index")
        desired_binding = locator.get("binding") or {}
        if locator.get("binding_xpath"):
            desired_binding = {**desired_binding, "xpath": locator.get("binding_xpath")}
        if locator.get("binding_store_item_id") or locator.get("store_item_id") or locator.get("storeItemID"):
            desired_binding = {
                **desired_binding,
                "store_item_id": locator.get("binding_store_item_id") or locator.get("store_item_id") or locator.get("storeItemID"),
            }
        dom = self.load_part(part)
        if dom is None:
            return None
        for index, sdt in enumerate(dom.getElementsByTagName("w:sdt")):
            sdt_pr = self.first_child(sdt, "w:sdtPr")
            if not sdt_pr:
                continue
            if desired_index is not None and int(desired_index) != index:
                continue
            if desired_tag:
                tag_el = self.first_child(sdt_pr, "w:tag")
                if not tag_el or tag_el.getAttribute("w:val") != desired_tag:
                    continue
            if desired_alias:
                alias_el = self.first_child(sdt_pr, "w:alias")
                if not alias_el or alias_el.getAttribute("w:val") != desired_alias:
                    continue
            if desired_binding and not self.content_control_binding_matches(sdt_pr, desired_binding):
                continue
            content = self.first_child(sdt, "w:sdtContent")
            if not content:
                continue
            if locator.get("target") in {"sdt", "control", "content_control"}:
                return sdt
            if return_content or locator.get("target") in {"content", "sdt_content"}:
                return content
            for child in self.element_children(content):
                if child.tagName == "w:p":
                    return child
            return content
        return None

    def content_control_binding(self, sdt_pr):
        binding = self.first_descendant_by_local_name(sdt_pr, "dataBinding")
        if binding is None:
            return {}
        out = {
            "xpath": self.attribute_by_local_name(binding, "xpath"),
            "store_item_id": self.attribute_by_local_name(binding, "storeItemID"),
            "prefix_mappings": self.attribute_by_local_name(binding, "prefixMappings"),
        }
        return {key: value for key, value in out.items() if value}

    def content_control_binding_matches(self, sdt_pr, desired_binding):
        actual = self.content_control_binding(sdt_pr)
        if not actual:
            return False
        for key in ["xpath", "store_item_id", "prefix_mappings"]:
            desired = desired_binding.get(key)
            if desired is None:
                continue
            actual_value = actual.get(key)
            if key == "store_item_id":
                if safe_text(actual_value).strip("{}").lower() != safe_text(desired).strip("{}").lower():
                    return False
            elif actual_value != desired:
                return False
        return True

    @staticmethod
    def ancestor_node_by_tag(node, tag):
        current = node
        while current is not None:
            if current.nodeType == Node.ELEMENT_NODE and getattr(current, "tagName", "") == tag:
                return current
            current = current.parentNode
        return None

    def content_control_for_node(self, node):
        if node is None or isinstance(node, dict):
            return None
        return self.ancestor_node_by_tag(node, "w:sdt")

    def content_control_lock_summary(self, node):
        sdt = self.content_control_for_node(node)
        if sdt is None:
            return {}
        sdt_pr = self.first_child(sdt, "w:sdtPr")
        lock_node = self.first_child(sdt_pr, "w:lock") if sdt_pr is not None else None
        lock = self.attribute_by_local_name(lock_node, "val")
        if not lock:
            return {"lock": None, "locked": False, "content_locked": False, "sdt_locked": False}
        return {
            "lock": lock,
            "locked": True,
            "content_locked": lock in CONTENT_LOCK_VALUES,
            "sdt_locked": lock in {"sdtLocked", "sdtContentLocked"},
        }

    def content_control_text_properties(self, node):
        sdt = self.content_control_for_node(node)
        if sdt is None:
            return {}
        sdt_pr = self.first_child(sdt, "w:sdtPr")
        if sdt_pr is None:
            return {}
        text_node = self.first_descendant_by_local_name(sdt_pr, "text")
        if text_node is None:
            return {}
        raw_multi_line = self.attribute_by_local_name(text_node, "multiLine")
        out = {
            "multi_line": truthy(raw_multi_line),
        }
        if raw_multi_line:
            out["multi_line_raw"] = raw_multi_line
        return out

    @staticmethod
    def annotate_content_control_text_properties(summary, text_properties):
        if text_properties:
            summary["text_control"] = text_properties
            if text_properties.get("multi_line"):
                summary["content_control_multiline"] = True
            elif summary.get("line_breaks_inserted"):
                summary["warning"] = "text_control_multiline_not_enabled"
        return summary

    def remove_content_control_placeholder_marker(self, node):
        sdt = self.content_control_for_node(node)
        if sdt is None:
            return 0
        sdt_pr = self.first_child(sdt, "w:sdtPr")
        if sdt_pr is None:
            return 0
        removed = 0
        for child in list(self.element_children(sdt_pr)):
            if self.tag_local_name(child) == "showingPlcHdr":
                sdt_pr.removeChild(child)
                removed += 1
        return removed

    @staticmethod
    def annotate_content_control_placeholder_summary(summary, removed):
        if removed:
            summary["placeholder_removed"] = removed
            summary["expected_structure_change"] = "content_control_placeholder_removed"
        return summary

    def custom_xml_item_parts(self):
        custom_dir = self.work / "customXml"
        if not custom_dir.exists():
            return []
        parts = []
        for path in sorted(custom_dir.glob("*.xml")):
            name = path.name
            if name.startswith("itemProps"):
                continue
            parts.append(path.relative_to(self.work).as_posix())
        return parts

    def custom_xml_props_part_for_item(self, item_part):
        rels_dom = self.load_rels_for_part(item_part)
        if rels_dom is None:
            return None
        for relationship in self.relationship_nodes(rels_dom):
            if relationship.getAttribute("Type") != CUSTOM_XML_PROPS_REL:
                continue
            target = relationship.getAttribute("Target")
            if target:
                return self.relationship_target_package_path(item_part, target)
        return None

    def custom_xml_item_store_id(self, item_part):
        props_part = self.custom_xml_props_part_for_item(item_part)
        if not props_part:
            return None
        props_dom = self.load_package_xml(props_part)
        if props_dom is None:
            return None
        for item in self.elements_by_local_name(props_dom, "datastoreItem"):
            item_id = self.attribute_by_local_name(item, "itemID")
            if item_id:
                return item_id
        return None

    def custom_xml_parts_for_binding(self, binding):
        parts = self.custom_xml_item_parts()
        store_item_id = normalize_store_item_id((binding or {}).get("store_item_id"))
        if not store_item_id:
            return parts
        matched = []
        for part in parts:
            if normalize_store_item_id(self.custom_xml_item_store_id(part)) == store_item_id:
                matched.append(part)
        return matched

    @staticmethod
    def parse_custom_xml_xpath(xpath):
        text = safe_text(xpath).strip()
        if not text:
            return None, "custom_xml_xpath_missing"
        if not text.startswith("/"):
            return None, "custom_xml_xpath_must_be_absolute"
        segments = []
        for raw in [part for part in text.split("/") if part]:
            if raw in {"text()", "node()"}:
                segments.append({"kind": "text"})
                continue
            if raw.startswith("@"):
                name = raw[1:].split(":", 1)[-1].strip()
                if not name:
                    return None, "custom_xml_xpath_attribute_missing"
                segments.append({"kind": "attribute", "name": name})
                continue
            match = re.fullmatch(r"([^\[\]]+)(?:\[(\d+)\])?", raw)
            if not match:
                return None, "custom_xml_xpath_unsupported_predicate"
            name = match.group(1).split(":", 1)[-1].strip()
            index = int(match.group(2) or "1")
            if not name:
                return None, "custom_xml_xpath_element_missing"
            segments.append({"kind": "element", "name": name, "index": index})
        if not segments:
            return None, "custom_xml_xpath_empty"
        return segments, None

    @staticmethod
    def direct_element_children_by_local_name(node, local_name):
        return [
            child
            for child in getattr(node, "childNodes", [])
            if child.nodeType == Node.ELEMENT_NODE and DocxWork.tag_local_name(child) == local_name
        ]

    @staticmethod
    def node_text(node):
        chunks = []

        def visit(cur):
            for child in getattr(cur, "childNodes", []):
                if child.nodeType == Node.TEXT_NODE:
                    chunks.append(child.data)
                elif child.nodeType == Node.ELEMENT_NODE:
                    visit(child)

        visit(node)
        return "".join(chunks)

    def set_custom_xml_element_text(self, element, value):
        if any(child.nodeType == Node.ELEMENT_NODE for child in getattr(element, "childNodes", [])):
            return {"updated": False, "error": "custom_xml_target_has_child_elements"}
        old_value = self.node_text(element)
        for child in list(element.childNodes):
            element.removeChild(child)
        element.appendChild(element.ownerDocument.createTextNode(safe_text(value)))
        return {
            "updated": True,
            "target_kind": "element",
            "old_value": old_value,
            "new_value": safe_text(value),
        }

    def set_custom_xml_attribute_text(self, element, attribute_name, value):
        actual_name = attribute_name
        if getattr(element, "attributes", None):
            for index in range(element.attributes.length):
                attr_node = element.attributes.item(index)
                if attr_node.name.split(":")[-1] == attribute_name:
                    actual_name = attr_node.name
                    break
        old_value = element.getAttribute(actual_name)
        element.setAttribute(actual_name, safe_text(value))
        return {
            "updated": True,
            "target_kind": "attribute",
            "attribute": actual_name,
            "old_value": old_value,
            "new_value": safe_text(value),
        }

    def set_custom_xml_xpath_value(self, dom, xpath, value):
        segments, error = self.parse_custom_xml_xpath(xpath)
        if error:
            return {"updated": False, "error": error, "xpath": xpath}
        current = dom.documentElement
        if current is None:
            return {"updated": False, "error": "custom_xml_document_empty", "xpath": xpath}
        if segments[0]["kind"] != "element":
            return {"updated": False, "error": "custom_xml_xpath_root_must_be_element", "xpath": xpath}
        if self.tag_local_name(current) != segments[0]["name"]:
            return {"updated": False, "error": "custom_xml_xpath_root_not_found", "xpath": xpath, "root": self.tag_local_name(current)}
        if segments[0].get("index", 1) != 1:
            return {"updated": False, "error": "custom_xml_xpath_root_index_not_found", "xpath": xpath}
        for segment in segments[1:]:
            if segment["kind"] == "text":
                result = self.set_custom_xml_element_text(current, value)
                result["xpath"] = xpath
                return result
            if segment["kind"] == "attribute":
                result = self.set_custom_xml_attribute_text(current, segment["name"], value)
                result["xpath"] = xpath
                return result
            children = self.direct_element_children_by_local_name(current, segment["name"])
            index = segment.get("index", 1) - 1
            if index < 0 or index >= len(children):
                return {
                    "updated": False,
                    "error": "custom_xml_xpath_not_found",
                    "xpath": xpath,
                    "missing_segment": segment["name"],
                    "segment_index": segment.get("index", 1),
                }
            current = children[index]
        result = self.set_custom_xml_element_text(current, value)
        result["xpath"] = xpath
        return result

    def update_custom_xml_for_binding(self, binding, value):
        binding = binding or {}
        xpath = binding.get("xpath")
        if not xpath:
            return {"attempted": False, "reason": "binding_xpath_missing"}
        parts = self.custom_xml_parts_for_binding(binding)
        if not parts:
            return {
                "attempted": True,
                "updated": False,
                "error": "custom_xml_item_not_found",
                "xpath": xpath,
                "store_item_id": binding.get("store_item_id"),
            }
        attempts = []
        for part in parts:
            dom = self.load_package_xml(part)
            if dom is None:
                attempts.append({"part": part, "updated": False, "error": "custom_xml_part_unreadable"})
                continue
            result = self.set_custom_xml_xpath_value(dom, xpath, value)
            result["part"] = part
            attempts.append(result)
            if result.get("updated"):
                return {
                    "attempted": True,
                    "updated": True,
                    "part": part,
                    "xpath": xpath,
                    "store_item_id": binding.get("store_item_id"),
                    "target_kind": result.get("target_kind"),
                    "attribute": result.get("attribute"),
                    "old_value": result.get("old_value"),
                    "new_value": result.get("new_value"),
                }
        return {
            "attempted": True,
            "updated": False,
            "error": "custom_xml_xpath_update_failed",
            "xpath": xpath,
            "store_item_id": binding.get("store_item_id"),
            "attempts": attempts,
        }

    @staticmethod
    def field_binding(field):
        locator = field.get("locator") or {}
        binding = dict(field.get("binding") or locator.get("binding") or {})
        if locator.get("binding_xpath"):
            binding["xpath"] = locator.get("binding_xpath")
        for key in ["store_item_id", "binding_store_item_id", "storeItemID"]:
            if locator.get(key):
                binding["store_item_id"] = locator.get(key)
        return binding

    def update_custom_xml_for_field(self, field, value):
        binding = self.field_binding(field)
        if not binding:
            return {"attempted": False, "reason": "field_has_no_binding"}
        return self.update_custom_xml_for_binding(binding, value)

    @staticmethod
    def elements_by_local_name(node, local_name):
        out = []
        if node.nodeType == Node.ELEMENT_NODE and getattr(node, "tagName", "").split(":")[-1] == local_name:
            out.append(node)
        for child in getattr(node, "childNodes", []):
            out.extend(DocxWork.elements_by_local_name(child, local_name))
        return out

    @staticmethod
    def tag_local_name(node):
        return getattr(node, "tagName", "").split(":")[-1]

    @staticmethod
    def element_local_counts(nodes, local_names):
        counts = {}

        def visit(node):
            if node.nodeType == Node.ELEMENT_NODE:
                local_name = DocxWork.tag_local_name(node)
                if local_name in local_names:
                    counts[local_name] = counts.get(local_name, 0) + 1
            for child in getattr(node, "childNodes", []):
                visit(child)

        for node in nodes:
            visit(node)
        return dict(sorted(counts.items()))

    @staticmethod
    def reference_complex_structure_summary(nodes):
        field_counts = DocxWork.element_local_counts(nodes, FIELD_CODE_LOCALS)
        revision_counts = DocxWork.element_local_counts(nodes, TRACKED_REVISION_LOCALS)
        field_total = sum(field_counts.values())
        revision_total = sum(revision_counts.values())
        return {
            "field_codes": {"total": field_total, "by_tag": field_counts},
            "tracked_revisions": {"total": revision_total, "by_tag": revision_counts},
            "has_field_codes": field_total > 0,
            "has_tracked_revisions": revision_total > 0,
            "has_complex_structures": field_total > 0 or revision_total > 0,
        }

    @staticmethod
    def match_text(value, needle, match="contains"):
        value = safe_text(value)
        needle = safe_text(needle)
        if match == "exact":
            return value == needle
        if match == "regex":
            return bool(re.search(needle, value))
        return needle in value

    def image_drawings(self, part="word/document.xml"):
        dom = self.load_part(part)
        if dom is None:
            return []
        return self.elements_by_local_name(dom, "drawing")

    def find_image_index(self, locator, part="word/document.xml"):
        drawings = self.image_drawings(part)
        index = int(locator.get("index", locator.get("image_index", 0)))
        if index < 0 or index >= len(drawings):
            return None
        return drawings[index]

    def find_image_alt_text(self, locator, part="word/document.xml"):
        needle = locator.get("text") or locator.get("alt_text") or locator.get("name") or locator.get("descr") or locator.get("title")
        if not needle:
            return None
        match = locator.get("match", "contains")
        for drawing in self.image_drawings(part):
            texts = []
            for doc_pr in self.elements_by_local_name(drawing, "docPr"):
                for attr_name in ["name", "descr", "title"]:
                    attr_value = doc_pr.getAttribute(attr_name)
                    if attr_value:
                        texts.append(attr_value)
            if any(self.match_text(text, needle, match) for text in texts):
                return drawing
        return None

    def resolve(self, field):
        locator_type = field.get("locator_type")
        locator = field.get("locator", {})
        self.last_resolved_part = None
        self.last_part_resolution = None
        for part in self.field_parts(field):
            if locator_type == "placeholder":
                token = locator.get("token") or ("{{" + field.get("key", "") + "}}")
                resolved = self.find_text_anchor({"text": token, "target": "self"}, part)
            elif locator_type == "literal":
                resolved = self.find_text_anchor({"text": locator.get("text") or locator.get("literal"), "target": "self"}, part)
            elif locator_type == "paraId":
                para_id = locator.get("para_id") or (locator.get("para_ids") or [None])[0]
                resolved = self.find_para_id(para_id, part) if para_id else None
            elif locator_type == "text_anchor":
                resolved = self.find_text_anchor(locator, part)
            elif locator_type == "bookmark":
                resolved = self.find_bookmark(locator, part)
            elif locator_type == "hyperlink":
                resolved = self.find_hyperlink(locator, part)
            elif locator_type == "content_control":
                replacement_mode = field.get("replacement_mode")
                if replacement_mode in CHECKBOX_MODES or replacement_mode in CHOICE_MODES or replacement_mode in DATE_MODES or replacement_mode in REPEATING_SECTION_MODES:
                    locator = {**locator, "target": "sdt"}
                use_content = (
                    replacement_mode not in {"reference_block", "reference_paragraphs"} | CHECKBOX_MODES | CHOICE_MODES | DATE_MODES | REPEATING_SECTION_MODES
                    and field.get("multiline_mode") != "reference_paragraphs"
                )
                resolved = self.find_content_control(locator, part, return_content=use_content)
            elif locator_type == "image_index":
                resolved = self.find_image_index(locator, part)
            elif locator_type == "image_alt_text":
                resolved = self.find_image_alt_text(locator, part)
            else:
                raise RuntimeError(f"Unsupported locator_type for fill_by_spec: {locator_type}")
            if resolved:
                self.last_resolved_part = part
                self.last_part_resolution = self.part_resolutions.get(part)
                return resolved
        return None

    def style_seed(self, paragraph):
        cloned = paragraph.cloneNode(False)
        p_pr = self.first_child(paragraph, "w:pPr")
        if p_pr is not None:
            cloned.appendChild(p_pr.cloneNode(True))
        run_pr = None
        for run in self.element_children(paragraph, "w:r"):
            run_pr = self.first_child(run, "w:rPr")
            if run_pr is not None:
                run_pr = run_pr.cloneNode(True)
                break
        return cloned, run_pr

    def build_text_run(self, dom, text, run_pr=None):
        run = dom.createElement("w:r")
        if run_pr is not None:
            run.appendChild(run_pr.cloneNode(True))
        lines = normalize_line_breaks(text).split("\n")
        for index, line in enumerate(lines):
            if index:
                run.appendChild(dom.createElement("w:br"))
            text_node = dom.createElement("w:t")
            if needs_space_preserve(line) or line == "":
                text_node.setAttribute("xml:space", "preserve")
            text_node.appendChild(dom.createTextNode(line))
            run.appendChild(text_node)
        return run, max(0, len(lines) - 1)

    def append_text_to_existing_run(self, run, text):
        dom = run.ownerDocument
        lines = normalize_line_breaks(text).split("\n")
        for index, line in enumerate(lines):
            if index:
                run.appendChild(dom.createElement("w:br"))
            text_node = dom.createElement("w:t")
            if needs_space_preserve(line) or line == "":
                text_node.setAttribute("xml:space", "preserve")
            text_node.appendChild(dom.createTextNode(line))
            run.appendChild(text_node)
        return max(0, len(lines) - 1)

    @staticmethod
    def run_can_receive_text(run):
        if run.getElementsByTagName("w:t"):
            return False
        payload_children = [
            child
            for child in DocxWork.element_children(run)
            if getattr(child, "tagName", None) != "w:rPr"
        ]
        return not payload_children

    def first_empty_text_run(self, node):
        for run in node.getElementsByTagName("w:r"):
            if self.run_can_receive_text(run):
                return run
        return None

    def append_text_run(self, paragraph, text, run_pr=None):
        run, breaks_inserted = self.build_text_run(paragraph.ownerDocument, text, run_pr)
        paragraph.appendChild(run)
        return breaks_inserted

    def append_break(self, paragraph, run_pr=None):
        dom = paragraph.ownerDocument
        run = dom.createElement("w:r")
        if run_pr is not None:
            run.appendChild(run_pr.cloneNode(True))
        run.appendChild(dom.createElement("w:br"))
        paragraph.appendChild(run)

    def build_paragraph(self, source_paragraph, text, multiline_mode):
        paragraph, run_pr = self.style_seed(source_paragraph)
        if multiline_mode == "line_breaks":
            lines = safe_text(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
            for index, line in enumerate(lines):
                if index:
                    self.append_break(paragraph, run_pr)
                self.append_text_run(paragraph, line, run_pr)
            return [paragraph]
        if multiline_mode == "paragraphs":
            blocks = [b.strip() for b in re.split(r"\n\s*\n", safe_text(text).replace("\r\n", "\n").replace("\r", "\n")) if b.strip()]
            if not blocks:
                blocks = [""]
            out = []
            for block in blocks:
                p, rp = self.style_seed(source_paragraph)
                self.append_text_run(p, block, rp)
                out.append(p)
            return out
        self.append_text_run(paragraph, safe_text(text), run_pr)
        return [paragraph]

    def clear_element_children(self, element):
        children = [child for child in element.childNodes]
        for child in children:
            element.removeChild(child)
        return len(children)

    @staticmethod
    def first_descendant_by_local_name(node, local_name):
        for child in getattr(node, "childNodes", []):
            if child.nodeType == Node.ELEMENT_NODE and DocxWork.tag_local_name(child) == local_name:
                return child
            found = DocxWork.first_descendant_by_local_name(child, local_name)
            if found is not None:
                return found
        return None

    @staticmethod
    def attribute_by_local_name(node, local_name):
        if node is None or not getattr(node, "attributes", None):
            return None
        for index in range(node.attributes.length):
            attr_node = node.attributes.item(index)
            if attr_node.name.split(":")[-1] == local_name:
                return attr_node.value
        return None

    @staticmethod
    def set_val_attribute(node, value, preferred_prefix="w14"):
        if node is None:
            return
        names = []
        if getattr(node, "attributes", None):
            for index in range(node.attributes.length):
                attr_node = node.attributes.item(index)
                if attr_node.name.split(":")[-1] == "val":
                    names.append(attr_node.name)
        if not names:
            names = [f"{preferred_prefix}:val"]
        for name in names:
            node.setAttribute(name, safe_text(value))

    @staticmethod
    def set_attribute_by_local_name(node, local_name, value, preferred_prefix="w"):
        if node is None:
            return
        names = []
        if getattr(node, "attributes", None):
            for index in range(node.attributes.length):
                attr_node = node.attributes.item(index)
                if attr_node.name.split(":")[-1] == local_name:
                    names.append(attr_node.name)
        if not names:
            names = [f"{preferred_prefix}:{local_name}"]
        for name in names:
            node.setAttribute(name, safe_text(value))

    def checkbox_state_symbol(self, checkbox, checked):
        state_name = "checkedState" if checked else "uncheckedState"
        state = self.first_descendant_by_local_name(checkbox, state_name)
        raw = self.attribute_by_local_name(state, "val")
        if raw:
            try:
                codepoint = int(raw, 16)
                if 0 <= codepoint <= 0x10FFFF:
                    return chr(codepoint)
            except ValueError:
                pass
        return "☒" if checked else "☐"

    def set_content_control_display_text(self, content, text):
        self.last_line_breaks_inserted = 0
        self.last_content_control_placeholder_removed = self.remove_content_control_placeholder_marker(content)
        text_nodes = list(content.getElementsByTagName("w:t"))
        if text_nodes:
            self.set_text_node_value(text_nodes[0], text)
            for node in text_nodes[1:]:
                self.set_text_node_value(node, "")
            self.last_line_breaks_inserted = self.materialize_line_breaks_in_element(content)
            return len(text_nodes)
        empty_run = self.first_empty_text_run(content)
        if empty_run is not None:
            self.last_line_breaks_inserted = self.append_text_to_existing_run(empty_run, text)
            return 1
        runs = self.element_children(content, "w:r")
        if runs:
            text_node = content.ownerDocument.createElement("w:t")
            text_node.appendChild(content.ownerDocument.createTextNode(normalize_line_breaks(text)))
            runs[0].appendChild(text_node)
            self.last_line_breaks_inserted = self.materialize_line_breaks_in_element(content)
            return 1
        paragraphs = self.element_children(content, "w:p")
        if paragraphs:
            _, run_pr = self.style_seed(paragraphs[0])
            self.last_line_breaks_inserted = self.append_text_run(paragraphs[0], text, run_pr)
            return 1
        run = content.ownerDocument.createElement("w:r")
        text_node = content.ownerDocument.createElement("w:t")
        text_node.appendChild(content.ownerDocument.createTextNode(normalize_line_breaks(text)))
        run.appendChild(text_node)
        content.appendChild(run)
        self.last_line_breaks_inserted = self.materialize_line_breaks_in_element(content)
        return 1

    def set_content_control_checkbox(self, sdt, value):
        sdt_pr = self.first_child(sdt, "w:sdtPr")
        content = self.first_child(sdt, "w:sdtContent")
        checkbox = self.first_descendant_by_local_name(sdt_pr, "checkbox") or self.first_descendant_by_local_name(sdt_pr, "checkBox")
        if checkbox is None:
            return {"action": "content_control_checkbox", "status": "error", "error": "checkbox_control_not_found"}
        checked = truthy(value)
        checked_node = self.first_descendant_by_local_name(checkbox, "checked")
        if checked_node is None:
            prefix = checkbox.tagName.split(":", 1)[0] if ":" in checkbox.tagName else "w14"
            checked_node = checkbox.ownerDocument.createElement(f"{prefix}:checked")
            checkbox.appendChild(checked_node)
        self.set_val_attribute(checked_node, "1" if checked else "0")
        symbol = self.checkbox_state_symbol(checkbox, checked)
        text_nodes_changed = self.set_content_control_display_text(content, symbol) if content is not None else 0
        summary = {
            "action": "content_control_checkbox",
            "checked": checked,
            "display_text": symbol,
            "text_nodes_changed": text_nodes_changed,
        }
        return self.annotate_content_control_placeholder_summary(summary, self.last_content_control_placeholder_removed)

    def content_control_choice_container(self, sdt):
        sdt_pr = self.first_child(sdt, "w:sdtPr")
        if sdt_pr is None:
            return None
        return self.first_descendant_by_local_name(sdt_pr, "dropDownList") or self.first_descendant_by_local_name(sdt_pr, "comboBox")

    def content_control_choice_options(self, choice_container):
        options = []
        seen = set()
        for item in self.elements_by_local_name(choice_container, "listItem"):
            display_text = self.attribute_by_local_name(item, "displayText")
            value = self.attribute_by_local_name(item, "value")
            if not display_text and not value:
                continue
            option = {"display_text": display_text or value, "value": value or display_text}
            key = (option["display_text"], option["value"])
            if key in seen:
                continue
            seen.add(key)
            options.append(option)
        return options

    @staticmethod
    def match_choice_option(options, value):
        raw = safe_text(value)
        normalized = normalize_text(raw)
        for option in options:
            candidates = [option.get("display_text"), option.get("value")]
            if any(raw == safe_text(candidate) for candidate in candidates):
                return option
            if any(normalized == normalize_text(candidate) for candidate in candidates):
                return option
        return None

    def set_content_control_choice(self, sdt, value, allow_unlisted_choice=False):
        content = self.first_child(sdt, "w:sdtContent")
        choice_container = self.content_control_choice_container(sdt)
        if choice_container is None:
            return {"action": "content_control_choice", "status": "error", "error": "choice_control_not_found"}
        kind = self.tag_local_name(choice_container)
        options = self.content_control_choice_options(choice_container)
        matched = self.match_choice_option(options, value)
        if matched:
            display_text = matched.get("display_text") or matched.get("value") or safe_text(value)
            selected_value = matched.get("value") or display_text
            custom_value = False
        elif kind == "comboBox" or allow_unlisted_choice:
            display_text = safe_text(value)
            selected_value = display_text
            custom_value = True
        else:
            return {
                "action": "content_control_choice",
                "status": "error",
                "error": "choice_value_not_in_options",
                "control_kind": kind,
                "value": safe_text(value),
                "options": options,
            }
        text_nodes_changed = self.set_content_control_display_text(content, display_text) if content is not None else 0
        summary = {
            "action": "content_control_choice",
            "control_kind": kind,
            "selected_display_text": display_text,
            "selected_value": selected_value,
            "matched_option": matched,
            "custom_value": custom_value,
            "options": options,
            "text_nodes_changed": text_nodes_changed,
        }
        return self.annotate_content_control_placeholder_summary(summary, self.last_content_control_placeholder_removed)

    @staticmethod
    def normalized_word_full_date(value):
        raw = safe_text(value).strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return f"{raw}T00:00:00Z"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?", raw):
            return raw
        return None

    @staticmethod
    def date_value_parts(value, explicit_full_date=None):
        if isinstance(value, dict):
            display = (
                value.get("display_text")
                or value.get("display")
                or value.get("text")
                or value.get("value")
                or value.get("date")
                or value.get("full_date")
                or ""
            )
            full_date_source = explicit_full_date or value.get("full_date") or value.get("iso") or value.get("date") or value.get("value")
        else:
            display = safe_text(value)
            full_date_source = explicit_full_date or value
        return safe_text(display), DocxWork.normalized_word_full_date(full_date_source)

    def content_control_date_properties(self, date_node):
        if date_node is None:
            return {}
        out = {
            "full_date": self.attribute_by_local_name(date_node, "fullDate"),
            "format": self.attribute_by_local_name(self.first_descendant_by_local_name(date_node, "dateFormat"), "val"),
            "lid": self.attribute_by_local_name(self.first_descendant_by_local_name(date_node, "lid"), "val"),
            "store_mapped_data_as": self.attribute_by_local_name(self.first_descendant_by_local_name(date_node, "storeMappedDataAs"), "val"),
            "calendar": self.attribute_by_local_name(self.first_descendant_by_local_name(date_node, "calendar"), "val"),
        }
        return {key: value for key, value in out.items() if value}

    def set_content_control_date(self, sdt, value, full_date=None):
        content = self.first_child(sdt, "w:sdtContent")
        sdt_pr = self.first_child(sdt, "w:sdtPr")
        date_node = self.first_descendant_by_local_name(sdt_pr, "date")
        if date_node is None:
            return {"action": "content_control_date", "status": "error", "error": "date_control_not_found"}
        display_text, normalized_full_date = self.date_value_parts(value, explicit_full_date=full_date)
        before = self.content_control_date_properties(date_node)
        full_date_updated = False
        if normalized_full_date:
            self.set_attribute_by_local_name(date_node, "fullDate", normalized_full_date, preferred_prefix="w")
            full_date_updated = before.get("full_date") != normalized_full_date
        text_nodes_changed = self.set_content_control_display_text(content, display_text) if content is not None else 0
        after = self.content_control_date_properties(date_node)
        summary = {
            "action": "content_control_date",
            "selected_display_text": display_text,
            "full_date": normalized_full_date,
            "full_date_updated": full_date_updated,
            "date": after,
            "date_before": before,
            "text_nodes_changed": text_nodes_changed,
            "custom_xml_value": normalized_full_date or display_text,
        }
        if display_text and not normalized_full_date:
            summary["warning"] = "date_full_date_not_updated_non_iso_value"
        return self.annotate_content_control_placeholder_summary(summary, self.last_content_control_placeholder_removed)

    def content_control_kind_from_pr(self, sdt_pr):
        if sdt_pr is None:
            return None
        if self.first_descendant_by_local_name(sdt_pr, "checkbox") or self.first_descendant_by_local_name(sdt_pr, "checkBox"):
            return "checkBox"
        for name in ["repeatingSection", "repeatingSectionItem", "dropDownList", "comboBox", "date", "text", "richText"]:
            if self.first_descendant_by_local_name(sdt_pr, name):
                return name
        return None

    def content_control_key_candidates(self, sdt):
        sdt_pr = self.first_child(sdt, "w:sdtPr")
        keys = []
        if sdt_pr is None:
            return keys
        for tag_name in ["w:tag", "w:alias"]:
            node = self.first_child(sdt_pr, tag_name)
            value = self.attribute_by_local_name(node, "val")
            if value and value not in keys:
                keys.append(value)
        xpath = self.content_control_binding(sdt_pr).get("xpath")
        if xpath:
            for part in reversed([part for part in xpath.strip().split("/") if part and part != "."]):
                clean = re.sub(r"\[.*?\]", "", part).split(":", 1)[-1].lstrip("@").strip()
                if clean and clean not in {"text()", "node()"} and clean not in keys:
                    keys.append(clean)
                    break
        return keys

    def fill_nested_content_controls_in_repeating_item(self, item, row_data):
        changed = 0
        for sdt in item.getElementsByTagName("w:sdt"):
            sdt_pr = self.first_child(sdt, "w:sdtPr")
            kind = self.content_control_kind_from_pr(sdt_pr)
            if kind in {"repeatingSection", "repeatingSectionItem"}:
                continue
            content = self.first_child(sdt, "w:sdtContent")
            if content is None:
                continue
            matched_key = next((candidate for candidate in self.content_control_key_candidates(sdt) if candidate in row_data), None)
            if matched_key is None:
                continue
            if kind == "checkBox":
                self.set_content_control_checkbox(sdt, row_data[matched_key])
            elif kind in {"dropDownList", "comboBox"}:
                self.set_content_control_choice(sdt, row_data[matched_key], allow_unlisted_choice=(kind == "comboBox"))
            elif kind == "date":
                self.set_content_control_date(sdt, row_data[matched_key])
            else:
                self.set_content_control_display_text(content, row_data[matched_key])
            changed += 1
        return changed

    def direct_repeating_section_items(self, content):
        items = []
        for child in self.element_children(content, "w:sdt"):
            sdt_pr = self.first_child(child, "w:sdtPr")
            if self.content_control_kind_from_pr(sdt_pr) == "repeatingSectionItem":
                items.append(child)
        return items

    def set_content_control_repeating_section(self, sdt, value):
        sdt_pr = self.first_child(sdt, "w:sdtPr")
        content = self.first_child(sdt, "w:sdtContent")
        if self.content_control_kind_from_pr(sdt_pr) != "repeatingSection":
            return {"action": "content_control_repeating_section", "status": "error", "error": "repeating_section_control_not_found"}
        if content is None:
            return {"action": "content_control_repeating_section", "status": "error", "error": "repeating_section_content_not_found"}
        if not isinstance(value, list):
            return {"action": "content_control_repeating_section", "status": "error", "error": "repeating_section_value_must_be_array"}
        template_items = self.direct_repeating_section_items(content)
        if not template_items:
            return {"action": "content_control_repeating_section", "status": "error", "error": "repeating_section_item_not_found"}

        placeholder_removed = self.remove_content_control_placeholder_marker(sdt)
        seed = template_items[0].cloneNode(True)
        removed_children = self.clear_element_children(content)
        token_counts = {}
        nested_content_controls_filled = 0
        for row in value:
            row_data = row if isinstance(row, dict) else {"value": row, "text": row}
            clone = seed.cloneNode(True)
            counts = self.replace_tokens_in_element(clone, row_data)
            for token, count in counts.items():
                token_counts[token] = token_counts.get(token, 0) + count
            nested_content_controls_filled += self.fill_nested_content_controls_in_repeating_item(clone, row_data)
            content.appendChild(clone)
        summary = {
            "action": "content_control_repeating_section",
            "items_created": len(value),
            "template_items_used": len(template_items),
            "content_children_removed": removed_children,
            "token_counts": token_counts,
            "nested_content_controls_filled": nested_content_controls_filled,
        }
        return self.annotate_content_control_placeholder_summary(summary, placeholder_removed)

    def set_content_control_text(self, content, value, multiline_mode="single_paragraph"):
        placeholder_removed = self.remove_content_control_placeholder_marker(content)
        text_properties = self.content_control_text_properties(content)
        if multiline_mode in {"paragraphs", "line_breaks"}:
            paragraphs = self.element_children(content, "w:p")
            if paragraphs:
                seed = paragraphs[0]
                new_paragraphs = self.build_paragraph(seed, value, multiline_mode)
                removed_children = self.clear_element_children(content)
                for paragraph in new_paragraphs:
                    content.appendChild(paragraph)
                summary = {
                    "action": "content_control_text",
                    "paragraphs_created": len(new_paragraphs),
                    "text_nodes_changed": len(new_paragraphs),
                    "content_children_removed": removed_children,
                }
                summary = self.annotate_content_control_text_properties(summary, text_properties)
                return self.annotate_content_control_placeholder_summary(summary, placeholder_removed)

        text_nodes = list(content.getElementsByTagName("w:t"))
        if text_nodes:
            self.set_text_node_value(text_nodes[0], safe_text(value))
            for node in text_nodes[1:]:
                self.set_text_node_value(node, "")
            line_breaks_inserted = self.materialize_line_breaks_in_element(content)
            summary = {
                "action": "content_control_text",
                "paragraphs_created": 0,
                "text_nodes_changed": len(text_nodes),
                "content_children_removed": 0,
                "line_breaks_inserted": line_breaks_inserted,
            }
            summary = self.annotate_content_control_text_properties(summary, text_properties)
            return self.annotate_content_control_placeholder_summary(summary, placeholder_removed)

        empty_run = self.first_empty_text_run(content)
        if empty_run is not None:
            line_breaks_inserted = self.append_text_to_existing_run(empty_run, safe_text(value))
            summary = {
                "action": "content_control_text",
                "paragraphs_created": 0,
                "text_nodes_changed": 1,
                "content_children_removed": 0,
                "line_breaks_inserted": line_breaks_inserted,
                "run_reused": True,
            }
            summary = self.annotate_content_control_text_properties(summary, text_properties)
            return self.annotate_content_control_placeholder_summary(summary, placeholder_removed)

        paragraphs = self.element_children(content, "w:p")
        if paragraphs:
            _, run_pr = self.style_seed(paragraphs[0])
            line_breaks_inserted = self.append_text_run(paragraphs[0], safe_text(value), run_pr)
            summary = {
                "action": "content_control_text",
                "paragraphs_created": 0,
                "text_nodes_changed": 1,
                "content_children_removed": 0,
                "line_breaks_inserted": line_breaks_inserted,
                "run_style_seeded": run_pr is not None,
            }
            summary = self.annotate_content_control_text_properties(summary, text_properties)
            return self.annotate_content_control_placeholder_summary(summary, placeholder_removed)

        paragraph = content.ownerDocument.createElement("w:p")
        line_breaks_inserted = self.append_text_run(paragraph, safe_text(value))
        content.appendChild(paragraph)
        summary = {
            "action": "content_control_text",
            "paragraphs_created": 1,
            "text_nodes_changed": 1,
            "content_children_removed": 0,
            "line_breaks_inserted": line_breaks_inserted,
        }
        summary = self.annotate_content_control_text_properties(summary, text_properties)
        return self.annotate_content_control_placeholder_summary(summary, placeholder_removed)

    def replace_paragraph(self, old_paragraph, new_paragraphs):
        parent = old_paragraph.parentNode
        for paragraph in new_paragraphs:
            parent.insertBefore(paragraph, old_paragraph)
        parent.removeChild(old_paragraph)

    def insert_after(self, anchor, new_paragraphs):
        parent = anchor.parentNode
        next_sibling = anchor.nextSibling
        for paragraph in new_paragraphs:
            if next_sibling is None:
                parent.appendChild(paragraph)
            else:
                parent.insertBefore(paragraph, next_sibling)

    def find_table(self, loop):
        locator_type = loop.get("locator_type", "table_index")
        locator = loop.get("locator", {})
        self.last_resolved_part = None
        self.last_table_match = None
        for part in self.field_parts(loop):
            tables = self.filter_tables_by_depth(self.tables(part), locator)
            if locator_type == "table_index":
                index = int(locator.get("table_index", loop.get("table_index", 0)))
                if 0 <= index < len(tables):
                    self.last_resolved_part = part
                    table = tables[index]
                    self.last_table_match = {
                        "part": part,
                        "locator_type": locator_type,
                        "table_index": index,
                        "table_depth": self.table_depth(table),
                        "tables_considered": len(tables),
                    }
                    return tables[index]
            elif locator_type in {"contains_text", "text_anchor", "nested_contains_text"}:
                if locator_type == "nested_contains_text":
                    locator = {**locator, "min_depth": locator.get("min_depth", 1), "prefer": locator.get("prefer", "deepest")}
                    tables = self.filter_tables_by_depth(self.tables(part), locator)
                needle = locator.get("text") or locator.get("anchor_text")
                if not needle:
                    return None
                target = normalize_text(needle)
                matches = []
                for table in tables:
                    text = normalize_text(self.element_text(table))
                    if target in text:
                        matches.append(table)
                if matches:
                    total_matches = len(matches)
                    match_policy = safe_text(locator.get("prefer") or loop.get("table_match_policy") or "first").lower()
                    if match_policy in {"deepest", "inner", "nested", "max_depth"}:
                        depth = max(self.table_depth(table) for table in matches)
                        matches = [table for table in matches if self.table_depth(table) == depth]
                    elif match_policy in {"shallowest", "outer", "top", "min_depth"}:
                        depth = min(self.table_depth(table) for table in matches)
                        matches = [table for table in matches if self.table_depth(table) == depth]
                    table = matches[0]
                    self.last_resolved_part = part
                    self.last_table_match = {
                        "part": part,
                        "locator_type": locator_type,
                        "table_depth": self.table_depth(table),
                        "tables_considered": len(tables),
                        "tables_matched": total_matches,
                        "tables_after_policy": len(matches),
                        "match_policy": match_policy,
                    }
                    return table
            else:
                raise RuntimeError(f"Unsupported table locator_type: {locator_type}")
        return None

    def table_rows(self, table):
        return self.element_children(table, "w:tr")

    def table_cells(self, row):
        return self.element_children(row, "w:tc")

    def find_marker_pair(self, locator, part="word/document.xml"):
        start_text = locator.get("start") or locator.get("start_text")
        end_text = locator.get("end") or locator.get("end_text")
        if not start_text or not end_text:
            return None
        match = locator.get("match", "contains")
        paragraphs = self.paragraphs(part)
        start_index = None
        for index, paragraph in enumerate(paragraphs):
            if self.match_text(normalize_text(self.paragraph_text(paragraph)), normalize_text(start_text), match):
                start_index = index
                break
        if start_index is None:
            return None
        for index in range(start_index, len(paragraphs)):
            paragraph = paragraphs[index]
            if self.match_text(normalize_text(self.paragraph_text(paragraph)), normalize_text(end_text), match):
                return {"start": paragraphs[start_index], "end": paragraph, "start_text": start_text, "end_text": end_text}
        return None

    def paragraphs_from_marker_pair(self, locator, part="word/document.xml", include_markers=False):
        pair = self.find_marker_pair(locator, part)
        if not pair:
            return []
        paragraphs = self.paragraphs(part)
        try:
            start_index = paragraphs.index(pair["start"])
            end_index = paragraphs.index(pair["end"])
        except ValueError:
            return []
        if include_markers:
            return paragraphs[start_index : end_index + 1]
        return paragraphs[start_index + 1 : end_index]

    def find_paragraphs_containing(self, locator, part="word/document.xml"):
        needle = locator.get("text") or locator.get("anchor_text")
        if not needle:
            return []
        match = locator.get("match", "contains")
        target = normalize_text(needle)
        out = []
        for paragraph in self.paragraphs(part):
            if self.match_text(normalize_text(self.paragraph_text(paragraph)), target, match):
                out.append(paragraph)
        return out

    def find_table_rows_containing(self, locator, part="word/document.xml"):
        needle = locator.get("text") or locator.get("anchor_text")
        if not needle:
            return []
        match = locator.get("match", "contains")
        target = normalize_text(needle)
        out = []
        tables = self.tables(part)
        desired_table_index = locator.get("table_index")
        if desired_table_index is not None:
            try:
                desired_table_index = int(desired_table_index)
            except (TypeError, ValueError):
                return []
            tables = [tables[desired_table_index]] if 0 <= desired_table_index < len(tables) else []
        for table in tables:
            for row in self.table_rows(table):
                if self.match_text(normalize_text(self.element_text(row)), target, match):
                    out.append(row)
        return out

    @staticmethod
    def sibling_nodes_between(start, end):
        if start.parentNode is not end.parentNode:
            return None
        nodes = []
        cur = start
        while cur is not None:
            nodes.append(cur)
            if cur is end:
                return nodes
            cur = cur.nextSibling
        return None

    @staticmethod
    def remove_nodes(nodes):
        removed = 0
        for node in list(nodes):
            parent = node.parentNode
            if parent is not None:
                parent.removeChild(node)
                removed += 1
        return removed

    def apply_conditional_block(self, block, include):
        locator_type = block.get("locator_type", "marker_pair")
        locator = block.get("locator", {})
        remove_markers = block.get("remove_markers", True)
        for part in self.field_parts(block):
            if locator_type == "marker_pair":
                pair = self.find_marker_pair(locator, part)
                if not pair:
                    continue
                self.last_resolved_part = part
                nodes = self.sibling_nodes_between(pair["start"], pair["end"])
                if nodes is None:
                    return {"status": "error", "error": "conditional_markers_not_same_parent", "part": part}
                if not include:
                    removed = self.remove_nodes(nodes)
                    return {"status": "removed", "action": "remove_marker_pair", "part": part, "nodes_removed": removed}
                removed = 0
                if remove_markers:
                    if pair["start"] is pair["end"]:
                        counts = self.replace_patterns_across_text_nodes(
                            pair["start"].getElementsByTagName("w:t"),
                            {pair["start_text"]: "", pair["end_text"]: ""},
                        )
                        removed = sum(counts.values())
                    else:
                        removed = self.remove_nodes([pair["end"], pair["start"]])
                return {"status": "kept", "action": "keep_marker_pair", "part": part, "markers_removed": removed}
            if locator_type in {"paragraph_contains", "paragraph"}:
                paragraphs = self.find_paragraphs_containing(locator, part)
                if not paragraphs:
                    continue
                self.last_resolved_part = part
                if include:
                    return {"status": "kept", "action": "keep_paragraphs", "part": part, "nodes_matched": len(paragraphs)}
                removed = self.remove_nodes(paragraphs)
                return {"status": "removed", "action": "remove_paragraphs", "part": part, "nodes_removed": removed}
            if locator_type in {"table_row_contains", "table_row"}:
                rows = self.find_table_rows_containing(locator, part)
                if not rows:
                    continue
                self.last_resolved_part = part
                if include:
                    return {"status": "kept", "action": "keep_table_rows", "part": part, "nodes_matched": len(rows)}
                removed = self.remove_nodes(rows)
                return {"status": "removed", "action": "remove_table_rows", "part": part, "nodes_removed": removed}
            raise RuntimeError(f"Unsupported conditional locator_type: {locator_type}")
        return {"status": "error", "error": "conditional_locator_not_found", "locator_type": locator_type}

    def reference_paragraphs(self, locator_type, locator, part="word/document.xml"):
        if locator_type == "marker_pair":
            return self.paragraphs_from_marker_pair(locator, part, include_markers=bool(locator.get("include_markers", False)))
        if locator_type in {"paragraph_contains", "paragraph", "text_anchor"}:
            return self.find_paragraphs_containing(locator, part)
        if locator_type == "paraId":
            para_ids = locator.get("para_ids")
            if not para_ids:
                para_id = locator.get("para_id")
                para_ids = [para_id] if para_id else []
            paragraphs = []
            for para_id in para_ids:
                paragraph = self.find_para_id(para_id, part)
                if paragraph is not None:
                    paragraphs.append(paragraph)
            return paragraphs
        raise RuntimeError(f"Unsupported reference locator_type: {locator_type}")

    def find_reference_paragraphs(self, field):
        reference = field.get("reference", {}) if isinstance(field.get("reference"), dict) else {}
        locator_type = field.get("reference_locator_type") or reference.get("locator_type") or "marker_pair"
        locator = field.get("reference_locator") or reference.get("locator") or {}
        part_spec = field.get("reference_part") or reference.get("part") or reference.get("parts") or "word/document.xml"
        for part in self.expand_part_spec(part_spec):
            paragraphs = self.reference_paragraphs(locator_type, locator, part)
            if paragraphs:
                self.last_resolved_part = part
                return paragraphs
        return []

    @staticmethod
    def clear_paragraph_tracking_ids(paragraph):
        for attr in ["w14:paraId", "w14:textId", "w:rsidR", "w:rsidRDefault", "w:rsidP"]:
            if paragraph.hasAttribute(attr):
                paragraph.removeAttribute(attr)

    def set_paragraph_visible_text(self, paragraph, text):
        text_nodes = paragraph.getElementsByTagName("w:t")
        if text_nodes:
            self.set_text_node_value(text_nodes[0], safe_text(text))
            for node in text_nodes[1:]:
                self.set_text_node_value(node, "")
            return
        _, run_pr = self.style_seed(paragraph)
        self.append_text_run(paragraph, safe_text(text), run_pr)

    def build_reference_paragraphs(self, target_paragraph, reference_paragraphs, values, style_policy="last"):
        target_doc = target_paragraph.ownerDocument
        out = []
        for index, value in enumerate(values):
            if style_policy == "cycle":
                reference_paragraph = reference_paragraphs[index % len(reference_paragraphs)]
            else:
                reference_paragraph = reference_paragraphs[min(index, len(reference_paragraphs) - 1)]
            paragraph = target_doc.importNode(reference_paragraph, True)
            self.clear_paragraph_tracking_ids(paragraph)
            self.set_paragraph_visible_text(paragraph, value)
            out.append(paragraph)
        return out

    @staticmethod
    def style_ids_in_paragraphs(paragraphs):
        style_ids = set()
        for paragraph in paragraphs:
            for node in paragraph.getElementsByTagName("w:pStyle"):
                style_id = node.getAttribute("w:val")
                if style_id:
                    style_ids.add(style_id)
            for node in paragraph.getElementsByTagName("w:rStyle"):
                style_id = node.getAttribute("w:val")
                if style_id:
                    style_ids.add(style_id)
        return style_ids

    @staticmethod
    def styles_by_id(styles_dom):
        if styles_dom is None:
            return {}
        styles = {}
        for node in styles_dom.getElementsByTagName("w:style"):
            style_id = node.getAttribute("w:styleId")
            if style_id:
                styles[style_id] = node
        return styles

    @staticmethod
    def style_dependency_ids(style_node):
        dependencies = set()
        for child in DocxWork.element_children(style_node):
            if child.tagName in {"w:basedOn", "w:next", "w:link", "w:styleLink", "w:numStyleLink"}:
                style_id = child.getAttribute("w:val")
                if style_id:
                    dependencies.add(style_id)
        return dependencies

    @staticmethod
    def style_definition_hash(style_node):
        if style_node is None:
            return None
        return hashlib.sha256(style_node.toxml().encode("utf-8")).hexdigest()

    @staticmethod
    def style_display_name(style_node):
        if style_node is None:
            return ""
        for child in DocxWork.element_children(style_node):
            if child.tagName == "w:name":
                return child.getAttribute("w:val")
        return ""

    def import_missing_styles_from(self, reference_work, reference_paragraphs):
        used_style_ids = self.style_ids_in_paragraphs(reference_paragraphs)
        if not used_style_ids:
            return {
                "used_style_ids": [],
                "merged_style_ids": [],
                "missing_style_ids": [],
                "existing_style_definition_conflicts": [],
                "merged_style_numbering": [],
                "merged_style_num_ids": [],
                "existing_style_numbering_conflicts": [],
            }
        target_styles_dom = self.load_package_xml("word/styles.xml")
        reference_styles_dom = reference_work.load_package_xml("word/styles.xml")
        if target_styles_dom is None or reference_styles_dom is None:
            return {
                "used_style_ids": sorted(used_style_ids),
                "merged_style_ids": [],
                "missing_style_ids": sorted(used_style_ids),
                "existing_style_definition_conflicts": [],
                "merged_style_numbering": [],
                "merged_style_num_ids": [],
                "existing_style_numbering_conflicts": [],
                "style_merge_warning": "styles_part_missing",
            }
        target_styles = self.styles_by_id(target_styles_dom)
        reference_styles = self.styles_by_id(reference_styles_dom)
        wanted = list(used_style_ids)
        seen = set()
        ordered = []
        missing = set()
        while wanted:
            style_id = wanted.pop(0)
            if style_id in seen or style_id in target_styles:
                continue
            seen.add(style_id)
            style_node = reference_styles.get(style_id)
            if style_node is None:
                missing.add(style_id)
                continue
            ordered.append(style_id)
            for dependency in sorted(self.style_dependency_ids(style_node)):
                if dependency not in seen and dependency not in target_styles:
                    wanted.append(dependency)
        merged = []
        root = target_styles_dom.documentElement
        for style_id in ordered:
            style_node = reference_styles.get(style_id)
            if style_node is None or style_id in target_styles:
                continue
            style_clone = target_styles_dom.importNode(style_node, True)
            root.appendChild(style_clone)
            target_styles[style_id] = style_clone
            merged.append(style_id)
        merged_style_numbering = []
        merged_style_num_ids = set()
        for style_id in merged:
            style_node = target_styles.get(style_id)
            num_ids = sorted(self.num_ids_in_nodes([style_node]))
            if num_ids:
                merged_style_numbering.append({"style_id": style_id, "num_ids": num_ids})
                merged_style_num_ids.update(num_ids)
        existing_style_definition_conflicts = []
        existing_style_numbering_conflicts = []
        for style_id in sorted(used_style_ids):
            target_style = target_styles.get(style_id)
            reference_style = reference_styles.get(style_id)
            if target_style is None or reference_style is None or style_id in merged:
                continue
            reference_hash = self.style_definition_hash(reference_style)
            target_hash = self.style_definition_hash(target_style)
            if reference_hash != target_hash:
                existing_style_definition_conflicts.append(
                    {
                        "style_id": style_id,
                        "reference_name": self.style_display_name(reference_style),
                        "target_name": self.style_display_name(target_style),
                        "reference_sha256": reference_hash,
                        "target_sha256": target_hash,
                    }
                )
            reference_num_ids = sorted(self.num_ids_in_nodes([reference_style]))
            target_num_ids = sorted(self.num_ids_in_nodes([target_style]))
            if reference_num_ids and reference_num_ids != target_num_ids:
                existing_style_numbering_conflicts.append(
                    {
                        "style_id": style_id,
                        "reference_num_ids": reference_num_ids,
                        "target_num_ids": target_num_ids,
                    }
                )
        return {
            "used_style_ids": sorted(used_style_ids),
            "merged_style_ids": merged,
            "missing_style_ids": sorted(missing),
            "existing_style_definition_conflicts": existing_style_definition_conflicts,
            "merged_style_numbering": merged_style_numbering,
            "merged_style_num_ids": sorted(merged_style_num_ids),
            "existing_style_numbering_conflicts": existing_style_numbering_conflicts,
        }

    @staticmethod
    def num_ids_in_nodes(nodes):
        num_ids = set()
        for parent in nodes:
            if parent is None:
                continue
            for node in parent.getElementsByTagName("w:numId"):
                num_id = node.getAttribute("w:val")
                if num_id:
                    num_ids.add(num_id)
        return num_ids

    @staticmethod
    def num_ids_in_paragraphs(paragraphs):
        return DocxWork.num_ids_in_nodes(paragraphs)

    @staticmethod
    def numbering_nodes_by_id(numbering_dom, tag_name, attr_name):
        if numbering_dom is None:
            return {}
        nodes = {}
        for node in numbering_dom.getElementsByTagName(tag_name):
            value = node.getAttribute(attr_name)
            if value:
                nodes[value] = node
        return nodes

    @staticmethod
    def max_numeric_id(values):
        numeric = [int(value) for value in values if safe_text(value).isdigit()]
        return max(numeric) if numeric else 0

    @staticmethod
    def abstract_num_id_for_num(num_node):
        for child in num_node.getElementsByTagName("w:abstractNumId"):
            value = child.getAttribute("w:val")
            if value:
                return value
        return None

    @staticmethod
    def set_first_child_attr(node, child_tag, attr_name, value):
        for child in node.getElementsByTagName(child_tag):
            child.setAttribute(attr_name, safe_text(value))
            return True
        return False

    def import_missing_numbering_from(self, reference_work, reference_paragraphs, extra_num_ids=None):
        used_num_ids = self.num_ids_in_paragraphs(reference_paragraphs)
        used_num_ids.update(safe_text(num_id) for num_id in (extra_num_ids or []) if safe_text(num_id))
        if not used_num_ids:
            return {"used_num_ids": [], "imported_num_ids": [], "missing_num_ids": [], "missing_abstract_num_ids": [], "num_id_map": {}}
        target_numbering_dom = self.load_package_xml("word/numbering.xml")
        reference_numbering_dom = reference_work.load_package_xml("word/numbering.xml")
        if target_numbering_dom is None or reference_numbering_dom is None:
            return {
                "used_num_ids": sorted(used_num_ids),
                "imported_num_ids": [],
                "missing_num_ids": sorted(used_num_ids),
                "missing_abstract_num_ids": [],
                "num_id_map": {},
                "numbering_merge_warning": "numbering_part_missing",
            }
        target_nums = self.numbering_nodes_by_id(target_numbering_dom, "w:num", "w:numId")
        target_abstracts = self.numbering_nodes_by_id(target_numbering_dom, "w:abstractNum", "w:abstractNumId")
        reference_nums = self.numbering_nodes_by_id(reference_numbering_dom, "w:num", "w:numId")
        reference_abstracts = self.numbering_nodes_by_id(reference_numbering_dom, "w:abstractNum", "w:abstractNumId")
        next_num_id = self.max_numeric_id(target_nums.keys()) + 1
        next_abstract_id = self.max_numeric_id(target_abstracts.keys()) + 1
        imported = []
        missing_num_ids = []
        missing_abstract_num_ids = []
        num_id_map = {}
        root = target_numbering_dom.documentElement
        for old_num_id in sorted(used_num_ids, key=lambda value: int(value) if safe_text(value).isdigit() else safe_text(value)):
            reference_num = reference_nums.get(old_num_id)
            if reference_num is None:
                missing_num_ids.append(old_num_id)
                continue
            old_abstract_id = self.abstract_num_id_for_num(reference_num)
            reference_abstract = reference_abstracts.get(old_abstract_id)
            if old_abstract_id is None or reference_abstract is None:
                missing_abstract_num_ids.append(old_abstract_id or "")
                continue
            new_abstract_id = safe_text(next_abstract_id)
            next_abstract_id += 1
            new_num_id = safe_text(next_num_id)
            next_num_id += 1
            abstract_clone = target_numbering_dom.importNode(reference_abstract, True)
            abstract_clone.setAttribute("w:abstractNumId", new_abstract_id)
            num_clone = target_numbering_dom.importNode(reference_num, True)
            num_clone.setAttribute("w:numId", new_num_id)
            self.set_first_child_attr(num_clone, "w:abstractNumId", "w:val", new_abstract_id)
            root.appendChild(abstract_clone)
            root.appendChild(num_clone)
            num_id_map[old_num_id] = new_num_id
            imported.append({"old_num_id": old_num_id, "new_num_id": new_num_id, "old_abstract_num_id": old_abstract_id, "new_abstract_num_id": new_abstract_id})
        return {
            "used_num_ids": sorted(used_num_ids),
            "imported_num_ids": imported,
            "missing_num_ids": missing_num_ids,
            "missing_abstract_num_ids": missing_abstract_num_ids,
            "num_id_map": num_id_map,
        }

    @staticmethod
    def remap_numbering_ids(paragraphs, num_id_map):
        if not num_id_map:
            return 0
        changed = 0
        for paragraph in paragraphs:
            for node in paragraph.getElementsByTagName("w:numId"):
                old_value = node.getAttribute("w:val")
                if old_value in num_id_map:
                    node.setAttribute("w:val", safe_text(num_id_map[old_value]))
                    changed += 1
        return changed

    def remap_style_numbering_ids(self, style_ids, num_id_map):
        if not style_ids or not num_id_map:
            return 0
        styles_dom = self.load_package_xml("word/styles.xml")
        if styles_dom is None:
            return 0
        styles = self.styles_by_id(styles_dom)
        return self.remap_numbering_ids([styles[style_id] for style_id in style_ids if style_id in styles], num_id_map)

    @staticmethod
    def text_node_value(node):
        return node.firstChild.data if node.firstChild else ""

    @staticmethod
    def set_text_node_value(node, value):
        value = normalize_line_breaks(value)
        if node.firstChild:
            node.firstChild.data = value
        elif value:
            node.appendChild(node.ownerDocument.createTextNode(value))
        if needs_space_preserve(value):
            node.setAttribute("xml:space", "preserve")

    @staticmethod
    def set_text_node_space_attribute(node, value):
        if needs_space_preserve(value):
            node.setAttribute("xml:space", "preserve")
        elif node.hasAttribute("xml:space"):
            node.removeAttribute("xml:space")

    @staticmethod
    def text_node_attribute_pairs(node):
        pairs = []
        if not getattr(node, "attributes", None):
            return pairs
        for index in range(node.attributes.length):
            attr_node = node.attributes.item(index)
            if attr_node.name == "xml:space":
                continue
            pairs.append((attr_node.name, attr_node.value))
        return pairs

    def replace_text_node_with_line_breaks(self, node):
        value = self.text_node_value(node)
        if "\n" not in value or node.parentNode is None:
            return 0
        parent = node.parentNode
        doc = node.ownerDocument
        attributes = self.text_node_attribute_pairs(node)
        lines = value.split("\n")
        replacements = []
        for index, line in enumerate(lines):
            if index:
                replacements.append(doc.createElement("w:br"))
            text_node = doc.createElement(getattr(node, "tagName", "w:t"))
            for attr_name, attr_value in attributes:
                text_node.setAttribute(attr_name, attr_value)
            self.set_text_node_space_attribute(text_node, line)
            text_node.appendChild(doc.createTextNode(line))
            replacements.append(text_node)
        for replacement in replacements:
            parent.insertBefore(replacement, node)
        parent.removeChild(node)
        return max(0, len(lines) - 1)

    def materialize_line_breaks_in_text_nodes(self, text_nodes):
        breaks_inserted = 0
        for node in list(text_nodes):
            if node.parentNode is None:
                continue
            breaks_inserted += self.replace_text_node_with_line_breaks(node)
        return breaks_inserted

    def materialize_line_breaks_in_element(self, element):
        return self.materialize_line_breaks_in_text_nodes(element.getElementsByTagName("w:t"))

    def text_node_segments(self, text_nodes):
        segments = []
        offset = 0
        for node in text_nodes:
            text = self.text_node_value(node)
            segments.append({"node": node, "start": offset, "end": offset + len(text), "text": text})
            offset += len(text)
        return segments

    @staticmethod
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

    def replace_span(self, text_nodes, segments, start, end, replacement):
        touched = [segment for segment in segments if segment["end"] > start and segment["start"] < end]
        if not touched:
            return
        for index, segment in enumerate(touched):
            node = segment["node"]
            current = self.text_node_value(node)
            local_start = max(0, start - segment["start"])
            local_end = min(len(segment["text"]), end - segment["start"])
            before = current[:local_start]
            after = current[local_end:]
            if index == 0:
                if len(touched) == 1:
                    self.set_text_node_value(node, before + replacement + after)
                else:
                    self.set_text_node_value(node, before + replacement)
            elif index == len(touched) - 1:
                self.set_text_node_value(node, after)
            else:
                self.set_text_node_value(node, "")

    def replace_patterns_across_text_nodes(self, text_nodes, replacements):
        self.last_line_breaks_inserted = 0
        counts = {pattern: 0 for pattern in replacements}
        changed = False
        for pattern, replacement in replacements.items():
            segments = self.text_node_segments(text_nodes)
            joined = "".join(segment["text"] for segment in segments)
            spans = self.find_spans(joined, pattern)
            for start, end in reversed(spans):
                self.replace_span(text_nodes, segments, start, end, safe_text(replacement))
            if spans:
                changed = True
            counts[pattern] = len(spans)
        if changed:
            self.last_line_breaks_inserted = self.materialize_line_breaks_in_text_nodes(text_nodes)
        return counts

    def replace_tokens_in_element(self, element, values):
        return self.replace_patterns_across_text_nodes(
            element.getElementsByTagName("w:t"),
            {"{{" + str(key) + "}}": safe_text(value) for key, value in values.items()},
        )

    def clear_cell_paragraphs(self, cell):
        paragraphs = self.element_children(cell, "w:p")
        for paragraph in paragraphs:
            cell.removeChild(paragraph)
        return paragraphs

    def set_cell_text(self, cell, value, multiline_mode):
        existing = self.element_children(cell, "w:p")
        seed = existing[0] if existing else cell.ownerDocument.createElement("w:p")
        new_paragraphs = self.build_paragraph(seed, value, multiline_mode)
        self.clear_cell_paragraphs(cell)
        for paragraph in new_paragraphs:
            cell.appendChild(paragraph)
        return len(new_paragraphs)

    def fill_table_loop(self, loop, rows_data):
        table = self.find_table(loop)
        if table is None:
            return {"key": loop.get("key"), "status": "error", "error": "table_locator_not_found"}
        rows = self.table_rows(table)
        if not rows:
            return {"key": loop.get("key"), "status": "error", "error": "table_has_no_rows", "table_match": self.last_table_match or {}}
        row_index = int(loop.get("row_index", 1 if len(rows) > 1 else 0))
        if row_index < 0 or row_index >= len(rows):
            return {"key": loop.get("key"), "status": "error", "error": "row_index_out_of_range", "table_match": self.last_table_match or {}, "row_index": row_index, "row_count": len(rows)}

        template_row = rows[row_index]
        template_row_format = self.table_row_format_signature(template_row)
        row_format_checks = []
        parent = template_row.parentNode
        multiline_mode = loop.get("multiline_mode", "single_paragraph")
        columns = loop.get("columns", [])
        inserted = 0
        token_counts = {}

        for row_values in rows_data:
            if not isinstance(row_values, dict):
                row_values = {"value": row_values}
            cloned_row = template_row.cloneNode(True)
            counts = self.replace_tokens_in_element(cloned_row, row_values)
            for token, count in counts.items():
                token_counts[token] = token_counts.get(token, 0) + count
            if columns:
                cells = self.table_cells(cloned_row)
                for column in columns:
                    source_key = column.get("key") or column.get("field") or column.get("source")
                    if source_key is None:
                        continue
                    cell_index = int(column.get("cell_index", column.get("cell", 0)))
                    if cell_index < 0 or cell_index >= len(cells):
                        continue
                    if source_key in row_values:
                        self.set_cell_text(cells[cell_index], row_values.get(source_key), column.get("multiline_mode", multiline_mode))
            cloned_signature = self.table_row_format_signature(cloned_row)
            row_format_checks.append(
                {
                    "row_index": inserted,
                    "preserved": template_row_format["sha256"] == cloned_signature["sha256"],
                    "after": cloned_signature,
                }
            )
            parent.insertBefore(cloned_row, template_row)
            inserted += 1

        if loop.get("remove_template_row", True):
            parent.removeChild(template_row)
        elif not rows_data and loop.get("blank_when_empty", True):
            for cell in self.table_cells(template_row):
                self.set_cell_text(cell, "", multiline_mode)

        return {
            "key": loop.get("key"),
            "status": "filled",
            "table_locator_type": loop.get("locator_type", "table_index"),
            "part": self.last_resolved_part,
            "table_match": self.last_table_match or {},
            "row_index": row_index,
            "row_count_before": len(rows),
            "rows_inserted": inserted,
            "template_row_removed": bool(loop.get("remove_template_row", True)),
            "token_counts": token_counts,
            "format_check": self.table_loop_format_check(template_row_format, row_format_checks),
        }

    @staticmethod
    def rels_part_name(part):
        part = safe_text(part).lstrip("/")
        package_dir = posixpath.dirname(part)
        filename = posixpath.basename(part)
        if package_dir:
            return posixpath.join(package_dir, "_rels", filename + ".rels")
        return posixpath.join("_rels", filename + ".rels")

    @staticmethod
    def source_part_from_rels(rels_part):
        rels_part = safe_text(rels_part).lstrip("/")
        rels_dir = posixpath.dirname(rels_part)
        source_dir = posixpath.dirname(rels_dir) if posixpath.basename(rels_dir) == "_rels" else rels_dir
        filename = posixpath.basename(rels_part)
        source_name = filename[:-5] if filename.endswith(".rels") else filename
        if source_dir:
            return posixpath.join(source_dir, source_name)
        return source_name

    def load_rels_for_part(self, part):
        return self.load_package_xml(self.rels_part_name(part))

    def ensure_rels_for_part(self, part):
        rels_part = self.rels_part_name(part)
        dom = self.load_package_xml(rels_part)
        if dom is not None:
            return dom
        dom = minidom.Document()
        root = dom.createElement("Relationships")
        root.setAttribute("xmlns", RELATIONSHIPS_NS)
        dom.appendChild(root)
        self.doms[rels_part] = dom
        self.part_paths[rels_part] = self.work / rels_part
        return dom

    @staticmethod
    def relationship_nodes(rels_dom):
        if rels_dom is None:
            return []
        return [node for node in rels_dom.getElementsByTagName("Relationship") if node.nodeType == Node.ELEMENT_NODE]

    @staticmethod
    def relationship_by_id(rels_dom, relationship_id):
        for node in DocxWork.relationship_nodes(rels_dom):
            if node.getAttribute("Id") == relationship_id:
                return node
        return None

    @staticmethod
    def next_relationship_id(rels_dom):
        used = {node.getAttribute("Id") for node in DocxWork.relationship_nodes(rels_dom)}
        numeric = []
        for relationship_id in used:
            match = re.fullmatch(r"rId(\d+)", relationship_id or "")
            if match:
                numeric.append(int(match.group(1)))
        candidate = max(numeric, default=0) + 1
        while f"rId{candidate}" in used:
            candidate += 1
        return f"rId{candidate}"

    @staticmethod
    def matching_relationship_id(rels_dom, relationship):
        desired_type = relationship.getAttribute("Type")
        desired_target = relationship.getAttribute("Target")
        desired_mode = relationship.getAttribute("TargetMode")
        for node in DocxWork.relationship_nodes(rels_dom):
            if (
                node.getAttribute("Type") == desired_type
                and node.getAttribute("Target") == desired_target
                and node.getAttribute("TargetMode") == desired_mode
            ):
                return node.getAttribute("Id")
        return None

    @staticmethod
    def relationship_target_package_path(part, target):
        target = safe_text(target)
        if target.startswith("/"):
            return posixpath.normpath(target.lstrip("/"))
        return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))

    @staticmethod
    def relative_target_for_part(part, package_path):
        base = posixpath.dirname(part) or "."
        return posixpath.relpath(package_path, base)

    def ensure_content_type_override(self, part, content_type):
        dom = self.load_package_xml("[Content_Types].xml")
        if dom is None:
            return False
        part_name = "/" + safe_text(part).lstrip("/")
        root = dom.documentElement
        for node in root.getElementsByTagName("Override"):
            if node.getAttribute("PartName") == part_name:
                if node.getAttribute("ContentType") != content_type:
                    node.setAttribute("ContentType", content_type)
                return True
        node = dom.createElement("Override")
        node.setAttribute("PartName", part_name)
        node.setAttribute("ContentType", content_type)
        root.appendChild(node)
        return True

    def ensure_part_relationship(self, source_part, relationship_type, target_package_path):
        rels_dom = self.ensure_rels_for_part(source_part)
        target = self.relative_target_for_part(source_part, target_package_path)
        existing_id = self.matching_relationship_id_for_target(rels_dom, relationship_type, target, "")
        if existing_id:
            return existing_id
        relationship_id = self.next_relationship_id(rels_dom)
        node = rels_dom.createElement("Relationship")
        node.setAttribute("Id", relationship_id)
        node.setAttribute("Type", relationship_type)
        node.setAttribute("Target", target)
        rels_dom.documentElement.appendChild(node)
        return relationship_id

    def ensure_notes_part(self, config):
        dom = self.load_package_xml(config["part"])
        if dom is None:
            dom = minidom.Document()
            root = dom.createElement(config["root"])
            root.setAttribute("xmlns:w", WORDPROCESSINGML_NS)
            dom.appendChild(root)
            self.doms[config["part"]] = dom
            self.part_paths[config["part"]] = self.work / config["part"]
        self.ensure_content_type_override(config["part"], config["content_type"])
        self.ensure_part_relationship("word/document.xml", config["relationship_type"], config["part"])
        return dom

    @staticmethod
    def hyperlink_relationship_ids(nodes):
        ids = set()
        for node in nodes:
            for hyperlink in DocxWork.elements_by_local_name(node, "hyperlink"):
                relationship_id = hyperlink.getAttribute("r:id") or hyperlink.getAttribute("id")
                if relationship_id:
                    ids.add(relationship_id)
        return ids

    @staticmethod
    def remap_hyperlink_relationship_ids(nodes, id_map):
        if not id_map:
            return 0
        changed = 0
        for node in nodes:
            for hyperlink in DocxWork.elements_by_local_name(node, "hyperlink"):
                old_id = hyperlink.getAttribute("r:id") or hyperlink.getAttribute("id")
                if old_id in id_map:
                    if hyperlink.hasAttribute("r:id"):
                        hyperlink.setAttribute("r:id", id_map[old_id])
                    else:
                        hyperlink.setAttribute("id", id_map[old_id])
                    changed += 1
        return changed

    def import_hyperlink_relationships_from(self, reference_work, reference_part, target_part, nodes):
        hyperlink_ids = sorted(self.hyperlink_relationship_ids(nodes))
        if not hyperlink_ids:
            return {
                "used_relationship_ids": [],
                "imported_relationships": [],
                "reused_relationships": [],
                "missing_relationship_ids": [],
                "relationship_id_map": {},
                "refs_remapped": 0,
            }
        reference_rels = reference_work.load_rels_for_part(reference_part)
        if reference_rels is None:
            return {
                "used_relationship_ids": hyperlink_ids,
                "imported_relationships": [],
                "reused_relationships": [],
                "missing_relationship_ids": hyperlink_ids,
                "relationship_id_map": {},
                "refs_remapped": 0,
                "relationship_merge_warning": "reference_relationships_part_missing",
            }
        target_rels = self.ensure_rels_for_part(target_part)
        imported = []
        reused = []
        missing = []
        id_map = {}
        for old_id in hyperlink_ids:
            relationship = self.relationship_by_id(reference_rels, old_id)
            if relationship is None:
                missing.append(old_id)
                continue
            existing_id = self.matching_relationship_id(target_rels, relationship)
            if existing_id:
                id_map[old_id] = existing_id
                reused.append({"old_relationship_id": old_id, "new_relationship_id": existing_id, "target": relationship.getAttribute("Target")})
                continue
            new_id = self.next_relationship_id(target_rels)
            clone = target_rels.importNode(relationship, True)
            clone.setAttribute("Id", new_id)
            if clone.getAttribute("TargetMode") != "External" and clone.getAttribute("Target"):
                package_path = self.relationship_target_package_path(reference_part, clone.getAttribute("Target"))
                clone.setAttribute("Target", self.relative_target_for_part(target_part, package_path))
            target_rels.documentElement.appendChild(clone)
            id_map[old_id] = new_id
            imported.append(
                {
                    "old_relationship_id": old_id,
                    "new_relationship_id": new_id,
                    "type": clone.getAttribute("Type"),
                    "target": clone.getAttribute("Target"),
                    "target_mode": clone.getAttribute("TargetMode"),
                }
            )
        refs_remapped = self.remap_hyperlink_relationship_ids(nodes, id_map)
        return {
            "used_relationship_ids": hyperlink_ids,
            "imported_relationships": imported,
            "reused_relationships": reused,
            "missing_relationship_ids": missing,
            "relationship_id_map": id_map,
            "refs_remapped": refs_remapped,
        }

    @staticmethod
    def embedded_image_relationship_ids(nodes):
        ids = set()
        for node in nodes:
            for blip in DocxWork.elements_by_local_name(node, "blip"):
                relationship_id = blip.getAttribute("r:embed") or blip.getAttribute("embed")
                if relationship_id:
                    ids.add(relationship_id)
        return ids

    @staticmethod
    def remap_embedded_image_relationship_ids(nodes, id_map):
        if not id_map:
            return 0
        changed = 0
        for node in nodes:
            for blip in DocxWork.elements_by_local_name(node, "blip"):
                old_id = blip.getAttribute("r:embed") or blip.getAttribute("embed")
                if old_id in id_map:
                    if blip.hasAttribute("r:embed"):
                        blip.setAttribute("r:embed", id_map[old_id])
                    else:
                        blip.setAttribute("embed", id_map[old_id])
                    changed += 1
        return changed

    def media_destination_path(self, source_package_path, source_bytes):
        source_package_path = posixpath.normpath(safe_text(source_package_path).lstrip("/"))
        candidate = source_package_path
        destination = self.work / candidate
        if not destination.exists() or destination.read_bytes() == source_bytes:
            return candidate
        stem, ext = posixpath.splitext(source_package_path)
        index = 1
        while True:
            candidate = f"{stem}_ref{index}{ext}"
            destination = self.work / candidate
            if not destination.exists() or destination.read_bytes() == source_bytes:
                return candidate
            index += 1

    def matching_relationship_id_for_target(self, rels_dom, relationship_type, target, target_mode=""):
        for node in self.relationship_nodes(rels_dom):
            if (
                node.getAttribute("Type") == relationship_type
                and node.getAttribute("Target") == target
                and node.getAttribute("TargetMode") == target_mode
            ):
                return node.getAttribute("Id")
        return None

    @staticmethod
    def note_reference_ids(nodes, reference_local):
        ids = set()
        for node in nodes:
            for reference in DocxWork.elements_by_local_name(node, reference_local):
                note_id = reference.getAttribute("w:id") or reference.getAttribute("id")
                if note_id:
                    ids.add(note_id)
        return ids

    @staticmethod
    def remap_note_reference_ids(nodes, reference_local, id_map):
        if not id_map:
            return 0
        changed = 0
        for node in nodes:
            for reference in DocxWork.elements_by_local_name(node, reference_local):
                old_id = reference.getAttribute("w:id") or reference.getAttribute("id")
                if old_id in id_map:
                    if reference.hasAttribute("w:id"):
                        reference.setAttribute("w:id", id_map[old_id])
                    else:
                        reference.setAttribute("id", id_map[old_id])
                    changed += 1
        return changed

    @staticmethod
    def note_nodes_by_id(notes_dom, item_tag):
        if notes_dom is None:
            return {}
        nodes = {}
        for node in notes_dom.getElementsByTagName(item_tag):
            note_id = node.getAttribute("w:id") or node.getAttribute("id")
            if note_id:
                nodes[note_id] = node
        return nodes

    @staticmethod
    def max_note_id(notes_dom, item_tag):
        values = []
        for note_id in DocxWork.note_nodes_by_id(notes_dom, item_tag):
            if safe_text(note_id).lstrip("-").isdigit():
                value = int(note_id)
                if value >= 0:
                    values.append(value)
        return max(values) if values else 0

    def import_note_references_from(self, reference_work, config, nodes):
        used_note_ids = sorted(self.note_reference_ids(nodes, config["reference_local"]), key=numeric_id_sort_key)
        if not used_note_ids:
            return {
                "used_note_ids": [],
                "imported_notes": [],
                "missing_note_ids": [],
                "note_id_map": {},
                "refs_remapped": 0,
            }
        reference_dom = reference_work.load_package_xml(config["part"])
        if reference_dom is None:
            return {
                "used_note_ids": used_note_ids,
                "imported_notes": [],
                "missing_note_ids": used_note_ids,
                "note_id_map": {},
                "refs_remapped": 0,
                "note_merge_warning": "reference_note_part_missing",
            }
        target_dom = self.ensure_notes_part(config)
        reference_notes = self.note_nodes_by_id(reference_dom, config["item"])
        existing_ids = set(self.note_nodes_by_id(target_dom, config["item"]).keys())
        next_id = self.max_note_id(target_dom, config["item"]) + 1
        imported = []
        missing = []
        id_map = {}
        for old_id in used_note_ids:
            note_node = reference_notes.get(old_id)
            if note_node is None or not safe_text(old_id).lstrip("-").isdigit() or int(old_id) < 1:
                missing.append(old_id)
                continue
            while safe_text(next_id) in existing_ids:
                next_id += 1
            new_id = safe_text(next_id)
            next_id += 1
            existing_ids.add(new_id)
            note_clone = target_dom.importNode(note_node, True)
            if note_clone.hasAttribute("w:id"):
                note_clone.setAttribute("w:id", new_id)
            else:
                note_clone.setAttribute("id", new_id)
            target_dom.documentElement.appendChild(note_clone)
            id_map[old_id] = new_id
            imported.append({"old_note_id": old_id, "new_note_id": new_id})
        refs_remapped = self.remap_note_reference_ids(nodes, config["reference_local"], id_map)
        return {
            "used_note_ids": used_note_ids,
            "imported_notes": imported,
            "missing_note_ids": missing,
            "note_id_map": id_map,
            "refs_remapped": refs_remapped,
        }

    def ensure_comments_part(self):
        dom = self.load_package_xml(COMMENT_CONFIG["part"])
        if dom is None:
            dom = minidom.Document()
            root = dom.createElement(COMMENT_CONFIG["root"])
            root.setAttribute("xmlns:w", WORDPROCESSINGML_NS)
            dom.appendChild(root)
            self.doms[COMMENT_CONFIG["part"]] = dom
            self.part_paths[COMMENT_CONFIG["part"]] = self.work / COMMENT_CONFIG["part"]
        self.ensure_content_type_override(COMMENT_CONFIG["part"], COMMENT_CONFIG["content_type"])
        self.ensure_part_relationship("word/document.xml", COMMENT_CONFIG["relationship_type"], COMMENT_CONFIG["part"])
        return dom

    @staticmethod
    def comment_reference_ids(nodes):
        ids = set()
        for node in nodes:
            for local_name in COMMENT_CONFIG["reference_locals"]:
                for reference in DocxWork.elements_by_local_name(node, local_name):
                    comment_id = reference.getAttribute("w:id") or reference.getAttribute("id")
                    if comment_id:
                        ids.add(comment_id)
        return ids

    @staticmethod
    def remap_comment_reference_ids(nodes, id_map):
        if not id_map:
            return 0
        changed = 0
        for node in nodes:
            for local_name in COMMENT_CONFIG["reference_locals"]:
                for reference in DocxWork.elements_by_local_name(node, local_name):
                    old_id = reference.getAttribute("w:id") or reference.getAttribute("id")
                    if old_id in id_map:
                        if reference.hasAttribute("w:id"):
                            reference.setAttribute("w:id", id_map[old_id])
                        else:
                            reference.setAttribute("id", id_map[old_id])
                        changed += 1
        return changed

    @staticmethod
    def comment_nodes_by_id(comments_dom):
        if comments_dom is None:
            return {}
        nodes = {}
        for node in comments_dom.getElementsByTagName(COMMENT_CONFIG["item"]):
            comment_id = node.getAttribute("w:id") or node.getAttribute("id")
            if comment_id:
                nodes[comment_id] = node
        return nodes

    @staticmethod
    def max_comment_id(comments_dom):
        values = []
        for comment_id in DocxWork.comment_nodes_by_id(comments_dom):
            if safe_text(comment_id).lstrip("-").isdigit():
                value = int(comment_id)
                if value >= 0:
                    values.append(value)
        return max(values) if values else -1

    def import_comment_references_from(self, reference_work, nodes):
        used_comment_ids = sorted(self.comment_reference_ids(nodes), key=numeric_id_sort_key)
        if not used_comment_ids:
            return {
                "used_comment_ids": [],
                "imported_comments": [],
                "missing_comment_ids": [],
                "comment_id_map": {},
                "refs_remapped": 0,
            }
        reference_dom = reference_work.load_package_xml(COMMENT_CONFIG["part"])
        if reference_dom is None:
            return {
                "used_comment_ids": used_comment_ids,
                "imported_comments": [],
                "missing_comment_ids": used_comment_ids,
                "comment_id_map": {},
                "refs_remapped": 0,
                "comment_merge_warning": "reference_comments_part_missing",
            }
        target_dom = self.ensure_comments_part()
        reference_comments = self.comment_nodes_by_id(reference_dom)
        existing_ids = set(self.comment_nodes_by_id(target_dom).keys())
        next_id = self.max_comment_id(target_dom) + 1
        imported = []
        missing = []
        id_map = {}
        for old_id in used_comment_ids:
            comment_node = reference_comments.get(old_id)
            if comment_node is None or not safe_text(old_id).lstrip("-").isdigit() or int(old_id) < 0:
                missing.append(old_id)
                continue
            while safe_text(next_id) in existing_ids:
                next_id += 1
            new_id = safe_text(next_id)
            next_id += 1
            existing_ids.add(new_id)
            comment_clone = target_dom.importNode(comment_node, True)
            if comment_clone.hasAttribute("w:id"):
                comment_clone.setAttribute("w:id", new_id)
            else:
                comment_clone.setAttribute("id", new_id)
            target_dom.documentElement.appendChild(comment_clone)
            id_map[old_id] = new_id
            imported.append({"old_comment_id": old_id, "new_comment_id": new_id})
        refs_remapped = self.remap_comment_reference_ids(nodes, id_map)
        return {
            "used_comment_ids": used_comment_ids,
            "imported_comments": imported,
            "missing_comment_ids": missing,
            "comment_id_map": id_map,
            "refs_remapped": refs_remapped,
        }

    def import_embedded_image_relationships_from(self, reference_work, reference_part, target_part, nodes):
        image_ids = sorted(self.embedded_image_relationship_ids(nodes))
        if not image_ids:
            return {
                "used_relationship_ids": [],
                "imported_relationships": [],
                "reused_relationships": [],
                "missing_relationship_ids": [],
                "missing_media_paths": [],
                "unsupported_media": [],
                "relationship_id_map": {},
                "refs_remapped": 0,
            }
        reference_rels = reference_work.load_rels_for_part(reference_part)
        if reference_rels is None:
            return {
                "used_relationship_ids": image_ids,
                "imported_relationships": [],
                "reused_relationships": [],
                "missing_relationship_ids": image_ids,
                "missing_media_paths": [],
                "unsupported_media": [],
                "relationship_id_map": {},
                "refs_remapped": 0,
                "relationship_merge_warning": "reference_relationships_part_missing",
            }
        target_rels = self.ensure_rels_for_part(target_part)
        imported = []
        reused = []
        missing_relationship_ids = []
        missing_media_paths = []
        unsupported_media = []
        id_map = {}
        for old_id in image_ids:
            relationship = self.relationship_by_id(reference_rels, old_id)
            if relationship is None:
                missing_relationship_ids.append(old_id)
                continue
            if relationship.getAttribute("TargetMode") == "External":
                unsupported_media.append({"relationship_id": old_id, "target": relationship.getAttribute("Target"), "reason": "external_image_relationship"})
                continue
            source_package_path = self.relationship_target_package_path(reference_part, relationship.getAttribute("Target"))
            source_path = reference_work.work / source_package_path
            if not source_path.exists():
                missing_media_paths.append({"relationship_id": old_id, "media_path": source_package_path})
                continue
            ext = self.normalized_image_ext(source_package_path)
            if not self.image_content_type(ext):
                unsupported_media.append({"relationship_id": old_id, "media_path": source_package_path, "extension": ext})
                continue
            source_bytes = source_path.read_bytes()
            target_package_path = self.media_destination_path(source_package_path, source_bytes)
            destination = self.work / target_package_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                destination.write_bytes(source_bytes)
            self.ensure_image_content_type(ext)
            target = self.relative_target_for_part(target_part, target_package_path)
            relationship_type = relationship.getAttribute("Type")
            existing_id = self.matching_relationship_id_for_target(target_rels, relationship_type, target, relationship.getAttribute("TargetMode"))
            if existing_id:
                id_map[old_id] = existing_id
                reused.append({"old_relationship_id": old_id, "new_relationship_id": existing_id, "media_path": target_package_path})
                continue
            new_id = self.next_relationship_id(target_rels)
            clone = target_rels.importNode(relationship, True)
            clone.setAttribute("Id", new_id)
            clone.setAttribute("Target", target)
            if clone.hasAttribute("TargetMode") and not relationship.getAttribute("TargetMode"):
                clone.removeAttribute("TargetMode")
            target_rels.documentElement.appendChild(clone)
            id_map[old_id] = new_id
            imported.append(
                {
                    "old_relationship_id": old_id,
                    "new_relationship_id": new_id,
                    "type": relationship_type,
                    "source_media_path": source_package_path,
                    "media_path": target_package_path,
                    "target": target,
                    "target_mode": clone.getAttribute("TargetMode"),
                }
            )
        refs_remapped = self.remap_embedded_image_relationship_ids(nodes, id_map)
        return {
            "used_relationship_ids": image_ids,
            "imported_relationships": imported,
            "reused_relationships": reused,
            "missing_relationship_ids": missing_relationship_ids,
            "missing_media_paths": missing_media_paths,
            "unsupported_media": unsupported_media,
            "relationship_id_map": id_map,
            "refs_remapped": refs_remapped,
        }

    @staticmethod
    def normalized_image_ext(path):
        ext = Path(path).suffix.lower().lstrip(".")
        return "jpg" if ext == "jpeg" else ext

    @staticmethod
    def image_content_type(ext):
        return IMAGE_CONTENT_TYPES.get(ext)

    def ensure_image_content_type(self, ext):
        content_type = self.image_content_type(ext)
        if not content_type:
            return False
        dom = self.load_package_xml("[Content_Types].xml")
        if dom is None:
            return False
        root = dom.documentElement
        for node in root.getElementsByTagName("Default"):
            if node.getAttribute("Extension").lower() == ext:
                if not node.getAttribute("ContentType"):
                    node.setAttribute("ContentType", content_type)
                return True
        node = dom.createElement("Default")
        node.setAttribute("Extension", ext)
        node.setAttribute("ContentType", content_type)
        root.appendChild(node)
        return True

    def embedded_image_ids(self, element):
        ids = []
        for blip in self.elements_by_local_name(element, "blip"):
            rid = blip.getAttribute("r:embed") or blip.getAttribute("embed")
            if rid:
                ids.append(rid)
        return ids

    def package_path_is_referenced(self, package_path):
        package_path = posixpath.normpath(safe_text(package_path).lstrip("/"))
        for rels_path in self.work.rglob("*.rels"):
            rels_part = rels_path.relative_to(self.work).as_posix()
            rels_dom = self.doms.get(rels_part)
            if rels_dom is None:
                try:
                    rels_dom = minidom.parse(str(rels_path))
                except Exception:
                    continue
            source_part = self.source_part_from_rels(rels_part)
            for relationship in rels_dom.getElementsByTagName("Relationship"):
                if relationship.getAttribute("TargetMode") == "External":
                    continue
                target = relationship.getAttribute("Target")
                if not target:
                    continue
                if self.relationship_target_package_path(source_part, target) == package_path:
                    return True
        return False

    def replace_image_in_element(self, element, image_path):
        part = self.last_resolved_part
        if not part:
            return {"status": "error", "error": "image_part_not_resolved"}
        image_path = Path(image_path).expanduser().resolve()
        if not image_path.exists():
            return {"status": "error", "error": "image_source_not_found", "image_source": str(image_path)}
        source_ext = self.normalized_image_ext(image_path)
        if not self.image_content_type(source_ext):
            return {"status": "error", "error": "unsupported_image_type", "image_source": str(image_path), "extension": source_ext}
        image_ids = self.embedded_image_ids(element)
        if not image_ids:
            return {"status": "error", "error": "image_relationship_not_found"}
        relationship_id = image_ids[0]
        rels_dom = self.load_rels_for_part(part)
        if rels_dom is None:
            return {"status": "error", "error": "relationships_part_not_found", "part": part}
        relationship = None
        for node in rels_dom.getElementsByTagName("Relationship"):
            if node.getAttribute("Id") == relationship_id:
                relationship = node
                break
        if relationship is None:
            return {"status": "error", "error": "relationship_id_not_found", "relationship_id": relationship_id, "part": part}
        if relationship.getAttribute("TargetMode") == "External":
            return {"status": "error", "error": "external_image_relationship_not_supported", "relationship_id": relationship_id}
        target = relationship.getAttribute("Target")
        old_package_path = self.relationship_target_package_path(part, target)
        old_ext = self.normalized_image_ext(old_package_path)
        if source_ext == old_ext:
            new_package_path = old_package_path
            relationship_updated = False
        else:
            stem = posixpath.splitext(old_package_path)[0]
            new_package_path = stem + "." + source_ext
            relationship.setAttribute("Target", self.relative_target_for_part(part, new_package_path))
            self.ensure_image_content_type(source_ext)
            relationship_updated = True
        destination = self.work / new_package_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image_path, destination)
        removed_old_media = False
        if relationship_updated and not self.package_path_is_referenced(old_package_path):
            old_destination = self.work / old_package_path
            if old_destination.exists():
                old_destination.unlink()
                removed_old_media = True
        return {
            "status": "filled",
            "action": "image_replace",
            "part": part,
            "relationship_id": relationship_id,
            "media_path": new_package_path,
            "old_media_path": old_package_path,
            "image_source": str(image_path),
            "relationship_updated": relationship_updated,
            "removed_old_media": removed_old_media,
        }

    def pack(self, output):
        for part, dom in self.doms.items():
            part_path = self.work / part
            part_path.parent.mkdir(parents=True, exist_ok=True)
            part_path.write_bytes(dom.toxml(encoding="utf-8"))
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for file_path in self.work.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(self.work))


def resolve_path(base, value):
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def attach_custom_xml_update(entry, work, field, value):
    update = work.update_custom_xml_for_field(field, value)
    if not update.get("attempted"):
        return True
    entry["custom_xml_update"] = update
    if update.get("updated"):
        return True
    entry.setdefault("warnings", []).append(update.get("error", "custom_xml_update_failed"))
    if field.get("require_custom_xml_update", field.get("strict_custom_xml_update", False)):
        entry["status"] = "error"
        entry["error"] = update.get("error", "custom_xml_update_failed")
        return False
    return True


def annotate_expected_line_breaks(format_check, line_breaks_inserted):
    if isinstance(format_check, dict) and line_breaks_inserted:
        format_check["line_breaks_inserted"] = line_breaks_inserted
        format_check["expected_structure_change"] = "line_breaks_inserted"
    return format_check


def annotate_expected_bookmark_insert(format_check, fill_summary):
    if isinstance(format_check, dict) and fill_summary.get("run_inserted"):
        format_check["bookmark_run_inserted"] = True
        format_check["expected_structure_change"] = "bookmark_empty_range_inserted"
        if fill_summary.get("line_breaks_inserted"):
            format_check["line_breaks_inserted"] = fill_summary["line_breaks_inserted"]
    return format_check


def annotate_expected_hyperlink_insert(format_check, fill_summary):
    if isinstance(format_check, dict) and fill_summary.get("expected_structure_change") == "hyperlink_inserted":
        format_check["expected_structure_change"] = "hyperlink_inserted"
        format_check["hyperlink_inserted"] = True
        if fill_summary.get("line_breaks_inserted"):
            format_check["line_breaks_inserted"] = fill_summary["line_breaks_inserted"]
    return format_check


def main():
    parser = argparse.ArgumentParser(description="Fill a DOCX template from a template spec with locators.")
    parser.add_argument("spec")
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    spec = load_json(spec_path)
    raw_data = load_json(args.data)
    if "fields" in raw_data and isinstance(raw_data["fields"], dict):
        field_data = raw_data["fields"]
    else:
        field_data = raw_data
    table_data = raw_data.get("tables", {}) if isinstance(raw_data, dict) else {}
    image_data = raw_data.get("images", {}) if isinstance(raw_data, dict) else {}
    base = spec_path.parent
    data_base = Path(args.data).resolve().parent
    template = resolve_path(base, spec.get("template_source"))
    if template is None or not template.exists():
        print(f"Missing template_source: {spec.get('template_source')}", file=sys.stderr)
        return 2
    reference_source = resolve_path(base, spec.get("reference_source"))
    if spec.get("reference_source") and (reference_source is None or not reference_source.exists()):
        print(f"Missing reference_source: {spec.get('reference_source')}", file=sys.stderr)
        return 2

    work = DocxWork(template)
    reference_work = DocxWork(reference_source) if reference_source else None
    report = {
        "spec": str(spec_path),
        "template": str(template),
        "reference": str(reference_source) if reference_source else None,
        "output": str(Path(args.output).resolve()),
        "conditional_blocks": [],
        "fields": [],
        "image_fields": [],
        "table_loops": [],
    }
    try:
        for block in spec.get("conditional_blocks", []):
            key = block.get("key")
            entry = {"key": key, "status": "pending"}
            include, condition_value, condition_key = evaluate_condition(block, raw_data, field_data)
            entry.update(
                {
                    "condition_key": condition_key,
                    "condition_value": None if condition_value is MISSING else condition_value,
                    "condition_passed": include,
                }
            )
            result = work.apply_conditional_block(block, include)
            entry.update(result)
            report["conditional_blocks"].append(entry)
        for field in spec.get("fields", []):
            key = field.get("key")
            entry = {"key": key, "status": "pending"}
            value = field_data.get(key)
            if value in (None, ""):
                if field.get("required"):
                    entry.update({"status": "error", "error": "missing_required_value"})
                    report["fields"].append(entry)
                    continue
                entry.update({"status": "skipped", "reason": "empty"})
                report["fields"].append(entry)
                continue
            resolved = work.resolve(field)
            if not resolved:
                entry.update({"status": "error", "error": "locator_not_found"})
                report["fields"].append(entry)
                continue
            if (
                work.last_part_resolution
                and work.last_part_resolution.get("linked_to_previous")
                and not field.get("allow_linked_section_part", field.get("allow_linked_to_previous", False))
            ):
                entry.update(
                    {
                        "status": "error",
                        "error": "section_part_linked_to_previous",
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution,
                    }
                )
                report["fields"].append(entry)
                continue
            if field.get("locator_type") == "content_control":
                lock_summary = work.content_control_lock_summary(resolved)
                if lock_summary.get("lock"):
                    entry["content_control_lock"] = lock_summary
                if (
                    lock_summary.get("content_locked")
                    and not field.get("allow_locked_content_control", field.get("allow_content_locked_control", False))
                ):
                    entry.update(
                        {
                            "status": "error",
                            "error": "content_control_locked",
                            "part": work.last_resolved_part,
                            "part_resolution": work.last_part_resolution or {},
                            "content_control_lock": lock_summary,
                        }
                    )
                    report["fields"].append(entry)
                    continue
            replacement_mode = field.get("replacement_mode")
            if replacement_mode in HYPERLINK_INSERT_MODES:
                before_format_node = resolved.cloneNode(True)
                pattern = work.hyperlink_pattern_for_field(field)
                fill_summary = work.replace_text_with_hyperlink(resolved, pattern, value, field, work.last_resolved_part)
                if fill_summary.get("status") == "error":
                    entry.update({"status": "error", **fill_summary, "part": work.last_resolved_part, "part_resolution": work.last_part_resolution or {}})
                    report["fields"].append(entry)
                    continue
                format_check = annotate_expected_hyperlink_insert(
                    work.text_format_check(before_format_node, resolved, "hyperlink_insert"),
                    fill_summary,
                )
                entry.update(
                    {
                        "status": "filled",
                        **fill_summary,
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "value_length": len(safe_text(fill_summary.get("display_text"))),
                        "format_check": format_check,
                    }
                )
                report["fields"].append(entry)
                continue
            if (
                field.get("locator_type") == "bookmark"
                and replacement_mode not in {"paragraph", "replace", "reference_block", "reference_paragraphs"}
            ):
                before_format_node = resolved.cloneNode(True)
                fill_summary = work.replace_bookmark_text(field.get("locator") or {}, value, work.last_resolved_part)
                if fill_summary.get("status") == "error":
                    entry.update({"status": "error", **fill_summary, "part": work.last_resolved_part, "part_resolution": work.last_part_resolution or {}})
                    report["fields"].append(entry)
                    continue
                format_check = work.text_format_check(before_format_node, resolved, "bookmark_text_replace")
                format_check = annotate_expected_line_breaks(format_check, fill_summary.get("line_breaks_inserted", 0))
                format_check = annotate_expected_bookmark_insert(format_check, fill_summary)
                entry.update(
                    {
                        "status": "filled",
                        **fill_summary,
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "value_length": len(safe_text(value)),
                        "format_check": format_check,
                    }
                )
                report["fields"].append(entry)
                continue
            if (
                field.get("locator_type") == "hyperlink"
                and replacement_mode not in {"paragraph", "replace", "reference_block", "reference_paragraphs"}
            ):
                before_format_node = resolved.cloneNode(True)
                fill_summary = work.replace_hyperlink(resolved, value, work.last_resolved_part)
                if fill_summary.get("status") == "error":
                    entry.update({"status": "error", **fill_summary, "part": work.last_resolved_part, "part_resolution": work.last_part_resolution or {}})
                    report["fields"].append(entry)
                    continue
                format_check = annotate_expected_line_breaks(
                    work.text_format_check(before_format_node, resolved, "hyperlink_replace"),
                    fill_summary.get("line_breaks_inserted", 0),
                )
                entry.update(
                    {
                        "status": "filled",
                        **fill_summary,
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "value_length": len(safe_text(fill_summary.get("display_text"))),
                        "format_check": format_check,
                    }
                )
                if fill_summary.get("line_breaks_inserted"):
                    entry["line_breaks_inserted"] = fill_summary["line_breaks_inserted"]
                report["fields"].append(entry)
                continue
            if replacement_mode == "token" or (field.get("locator_type") == "placeholder" and replacement_mode not in {"reference_block", "reference_paragraphs"}):
                before_format_node = resolved.cloneNode(True)
                counts = work.replace_tokens_in_element(resolved, {key: value})
                line_breaks_inserted = work.last_line_breaks_inserted
                if not any(counts.values()):
                    entry.update({"status": "error", "error": "token_not_found", "token": "{{" + str(key) + "}}"})
                    report["fields"].append(entry)
                    continue
                format_check = annotate_expected_line_breaks(
                    work.text_format_check(before_format_node, resolved, "token_replace"),
                    line_breaks_inserted,
                )
                entry.update(
                    {
                        "status": "filled",
                        "action": "token_replace",
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "token_counts": counts,
                        "value_length": len(safe_text(value)),
                        "format_check": format_check,
                    }
                )
                if line_breaks_inserted:
                    entry["line_breaks_inserted"] = line_breaks_inserted
                report["fields"].append(entry)
                continue
            if (
                field.get("locator_type") == "literal"
                and field.get("multiline_mode", "single_paragraph") == "single_paragraph"
                and replacement_mode not in {"paragraph", "replace", "reference_block", "reference_paragraphs"}
            ):
                literal_text = (field.get("locator") or {}).get("text") or (field.get("locator") or {}).get("literal")
                before_format_node = resolved.cloneNode(True)
                counts = work.replace_patterns_across_text_nodes(
                    resolved.getElementsByTagName("w:t"),
                    {literal_text: value},
                )
                line_breaks_inserted = work.last_line_breaks_inserted
                if not any(counts.values()):
                    entry.update({"status": "error", "error": "literal_not_found", "literal": literal_text})
                    report["fields"].append(entry)
                    continue
                format_check = annotate_expected_line_breaks(
                    work.text_format_check(before_format_node, resolved, "literal_text_replace"),
                    line_breaks_inserted,
                )
                entry.update(
                    {
                        "status": "filled",
                        "action": "literal_text_replace",
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "literal_counts": counts,
                        "value_length": len(safe_text(value)),
                        "format_check": format_check,
                    }
                )
                if line_breaks_inserted:
                    entry["line_breaks_inserted"] = line_breaks_inserted
                report["fields"].append(entry)
                continue
            if field.get("locator_type") == "content_control" and replacement_mode in CHECKBOX_MODES:
                fill_summary = work.set_content_control_checkbox(resolved, value)
                if fill_summary.get("status") == "error":
                    entry.update({"status": "error", **fill_summary, "part": work.last_resolved_part, "part_resolution": work.last_part_resolution or {}})
                    report["fields"].append(entry)
                    continue
                entry.update(
                    {
                        "status": "filled",
                        **fill_summary,
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "value": bool(fill_summary.get("checked")),
                    }
                )
                attach_custom_xml_update(entry, work, field, fill_summary.get("checked"))
                report["fields"].append(entry)
                continue
            if field.get("locator_type") == "content_control" and replacement_mode in CHOICE_MODES:
                fill_summary = work.set_content_control_choice(resolved, value, allow_unlisted_choice=field.get("allow_unlisted_choice", False))
                if fill_summary.get("status") == "error":
                    entry.update({"status": "error", **fill_summary, "part": work.last_resolved_part, "part_resolution": work.last_part_resolution or {}})
                    report["fields"].append(entry)
                    continue
                entry.update(
                    {
                        "status": "filled",
                        **fill_summary,
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "value": fill_summary.get("selected_display_text"),
                    }
                )
                attach_custom_xml_update(entry, work, field, fill_summary.get("selected_value"))
                report["fields"].append(entry)
                continue
            if field.get("locator_type") == "content_control" and replacement_mode in DATE_MODES:
                fill_summary = work.set_content_control_date(resolved, value, full_date=field.get("full_date", field.get("date_full_date")))
                if fill_summary.get("status") == "error":
                    entry.update({"status": "error", **fill_summary, "part": work.last_resolved_part, "part_resolution": work.last_part_resolution or {}})
                    report["fields"].append(entry)
                    continue
                entry.update(
                    {
                        "status": "filled",
                        **fill_summary,
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "value": fill_summary.get("selected_display_text"),
                    }
                )
                if fill_summary.get("warning"):
                    entry.setdefault("warnings", []).append(fill_summary["warning"])
                attach_custom_xml_update(entry, work, field, fill_summary.get("custom_xml_value"))
                report["fields"].append(entry)
                continue
            if field.get("locator_type") == "content_control" and replacement_mode in REPEATING_SECTION_MODES:
                fill_summary = work.set_content_control_repeating_section(resolved, value)
                if fill_summary.get("status") == "error":
                    entry.update({"status": "error", **fill_summary, "part": work.last_resolved_part, "part_resolution": work.last_part_resolution or {}})
                    report["fields"].append(entry)
                    continue
                entry.update(
                    {
                        "status": "filled",
                        **fill_summary,
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "value_items": len(value) if isinstance(value, list) else None,
                    }
                )
                report["fields"].append(entry)
                continue
            if replacement_mode in {"reference_block", "reference_paragraphs"} or field.get("multiline_mode") == "reference_paragraphs":
                if reference_work is None:
                    entry.update({"status": "error", "error": "reference_source_required"})
                    report["fields"].append(entry)
                    continue
                target_part = work.last_resolved_part
                reference_paragraphs = reference_work.find_reference_paragraphs(field)
                if not reference_paragraphs:
                    entry.update({"status": "error", "error": "reference_locator_not_found"})
                    report["fields"].append(entry)
                    continue
                reference_part = reference_work.last_resolved_part
                complex_structure_summary = reference_work.reference_complex_structure_summary(reference_paragraphs)
                if complex_structure_summary.get("has_complex_structures") and not field.get("allow_reference_complex_structures", False):
                    entry.update(
                        {
                            "status": "error",
                            "error": "reference_complex_structures_present",
                            "part": target_part,
                            "reference_part": reference_part,
                            "reference_complex_structures": complex_structure_summary,
                        }
                    )
                    report["fields"].append(entry)
                    continue
                style_merge = work.import_missing_styles_from(reference_work, reference_paragraphs)
                if style_merge.get("missing_style_ids") and not field.get("allow_missing_reference_styles", False):
                    entry.update({"status": "error", "error": "reference_styles_missing", "reference_complex_structures": complex_structure_summary, **style_merge})
                    report["fields"].append(entry)
                    continue
                if (
                    style_merge.get("existing_style_definition_conflicts")
                    and not field.get("allow_reference_style_conflicts", field.get("allow_existing_style_definition_conflicts", False))
                ):
                    entry.update(
                        {
                            "status": "error",
                            "error": "reference_style_conflicts",
                            "reference_complex_structures": complex_structure_summary,
                            "reference_styles": style_merge,
                        }
                    )
                    report["fields"].append(entry)
                    continue
                numbering_merge = work.import_missing_numbering_from(
                    reference_work,
                    reference_paragraphs,
                    style_merge.get("merged_style_num_ids", []),
                )
                if (
                    numbering_merge.get("missing_num_ids") or numbering_merge.get("missing_abstract_num_ids")
                ) and not field.get("allow_missing_reference_numbering", False):
                    entry.update({"status": "error", "error": "reference_numbering_missing", "reference_complex_structures": complex_structure_summary, "reference_styles": style_merge, "reference_numbering": numbering_merge})
                    report["fields"].append(entry)
                    continue
                values = paragraph_values(value)
                if isinstance(resolved, dict) and "insert_after" in resolved:
                    source = resolved["insert_after"]
                    new_paragraphs = work.build_reference_paragraphs(
                        source,
                        reference_paragraphs,
                        values,
                        field.get("reference_style_policy", "last"),
                    )
                    action = "insert_after_reference_block"
                else:
                    new_paragraphs = work.build_reference_paragraphs(
                        resolved,
                        reference_paragraphs,
                        values,
                        field.get("reference_style_policy", "last"),
                    )
                    action = "replace_reference_block"
                numbering_refs_remapped = work.remap_numbering_ids(new_paragraphs, numbering_merge.get("num_id_map", {}))
                style_numbering_refs_remapped = work.remap_style_numbering_ids(style_merge.get("merged_style_ids", []), numbering_merge.get("num_id_map", {}))
                relationship_merge = work.import_hyperlink_relationships_from(reference_work, reference_part, target_part, new_paragraphs)
                embedded_image_merge = work.import_embedded_image_relationships_from(reference_work, reference_part, target_part, new_paragraphs)
                relationship_merge["embedded_images"] = embedded_image_merge
                relationship_errors = (
                    relationship_merge.get("missing_relationship_ids")
                    or embedded_image_merge.get("missing_relationship_ids")
                    or embedded_image_merge.get("missing_media_paths")
                    or embedded_image_merge.get("unsupported_media")
                )
                if relationship_errors and not field.get("allow_missing_reference_relationships", False):
                    entry.update(
                        {
                            "status": "error",
                            "error": "reference_relationships_missing",
                            "reference_complex_structures": complex_structure_summary,
                            "reference_styles": style_merge,
                            "reference_numbering": numbering_merge,
                            "reference_relationships": relationship_merge,
                        }
                    )
                    report["fields"].append(entry)
                    continue
                note_merge = {
                    key: work.import_note_references_from(reference_work, config, new_paragraphs)
                    for key, config in NOTE_CONFIGS.items()
                }
                note_errors = any(row.get("missing_note_ids") for row in note_merge.values())
                if note_errors and not field.get("allow_missing_reference_notes", False):
                    entry.update(
                        {
                            "status": "error",
                            "error": "reference_notes_missing",
                            "reference_complex_structures": complex_structure_summary,
                            "reference_styles": style_merge,
                            "reference_numbering": numbering_merge,
                            "reference_relationships": relationship_merge,
                            "reference_notes": note_merge,
                        }
                    )
                    report["fields"].append(entry)
                    continue
                comment_merge = work.import_comment_references_from(reference_work, new_paragraphs)
                if comment_merge.get("missing_comment_ids") and not field.get("allow_missing_reference_comments", False):
                    entry.update(
                        {
                            "status": "error",
                            "error": "reference_comments_missing",
                            "reference_complex_structures": complex_structure_summary,
                            "reference_styles": style_merge,
                            "reference_numbering": numbering_merge,
                            "reference_relationships": relationship_merge,
                            "reference_notes": note_merge,
                            "reference_comments": comment_merge,
                        }
                    )
                    report["fields"].append(entry)
                    continue
                if isinstance(resolved, dict) and "insert_after" in resolved:
                    work.insert_after(source, new_paragraphs)
                else:
                    work.replace_paragraph(resolved, new_paragraphs)
                entry.update(
                    {
                        "status": "filled",
                        "action": action,
                        "part": target_part,
                        "part_resolution": work.last_part_resolution or {},
                        "reference_part": reference_part,
                        "paragraphs_created": len(new_paragraphs),
                        "reference_paragraphs_used": len(reference_paragraphs),
                        "reference_styles": style_merge,
                        "reference_numbering": numbering_merge,
                        "reference_relationships": relationship_merge,
                        "reference_notes": note_merge,
                        "reference_comments": comment_merge,
                        "reference_complex_structures": complex_structure_summary,
                        "numbering_refs_remapped": numbering_refs_remapped,
                        "style_numbering_refs_remapped": style_numbering_refs_remapped,
                        "value_paragraphs": len(values),
                        "value_length": len(safe_text(value)),
                    }
                )
                report["fields"].append(entry)
                continue
            multiline_mode = field.get("multiline_mode", "single_paragraph")
            if field.get("locator_type") == "content_control" and getattr(resolved, "tagName", "") == "w:sdtContent":
                before_format_node = resolved.cloneNode(True)
                fill_summary = work.set_content_control_text(resolved, value, multiline_mode)
                line_breaks_inserted = fill_summary.get("line_breaks_inserted", 0)
                if multiline_mode in {"paragraphs", "line_breaks"}:
                    format_check = {
                        "checked": False,
                        "scope": "content_control_text",
                        "reason": "multiline_mode_changes_structure",
                    }
                else:
                    format_check = annotate_expected_line_breaks(
                        work.text_format_check(before_format_node, resolved, "content_control_text"),
                        line_breaks_inserted,
                    )
                entry.update(
                    {
                        "status": "filled",
                        **fill_summary,
                        "part": work.last_resolved_part,
                        "part_resolution": work.last_part_resolution or {},
                        "value_length": len(safe_text(value)),
                        "format_check": format_check,
                    }
                )
                attach_custom_xml_update(entry, work, field, value)
                report["fields"].append(entry)
                continue
            if isinstance(resolved, dict) and "insert_after" in resolved:
                source = resolved["insert_after"]
                before_format_node = source.cloneNode(True)
                new_paragraphs = work.build_paragraph(source, value, multiline_mode)
                work.insert_after(source, new_paragraphs)
                action = "insert_after"
            else:
                before_format_node = resolved.cloneNode(True)
                new_paragraphs = work.build_paragraph(resolved, value, multiline_mode)
                work.replace_paragraph(resolved, new_paragraphs)
                action = "replace"
            if multiline_mode in {"paragraphs", "line_breaks"}:
                format_check = {
                    "checked": False,
                    "scope": action,
                    "reason": "multiline_mode_changes_structure",
                }
            else:
                format_check = annotate_expected_line_breaks(
                    work.text_format_check(before_format_node, new_paragraphs, action),
                    line_break_count(value),
                )
            entry.update(
                {
                    "status": "filled",
                    "action": action,
                    "part": work.last_resolved_part,
                    "part_resolution": work.last_part_resolution or {},
                    "paragraphs_created": len(new_paragraphs),
                    "value_length": len(safe_text(value)),
                    "format_check": format_check,
                }
            )
            if multiline_mode not in {"paragraphs", "line_breaks"} and line_break_count(value):
                entry["line_breaks_inserted"] = line_break_count(value)
            report["fields"].append(entry)
        for image_field in spec.get("image_fields", []):
            key = image_field.get("key")
            entry = {"key": key, "status": "pending"}
            image_value = None
            if isinstance(image_data, dict):
                image_value = image_data.get(key)
            if image_value in (None, "") and isinstance(field_data, dict):
                image_value = field_data.get(key)
            if image_value in (None, ""):
                image_value = image_field.get("source") or image_field.get("image_source")
            if image_value in (None, ""):
                if image_field.get("required"):
                    entry.update({"status": "error", "error": "missing_required_image"})
                    report["image_fields"].append(entry)
                    continue
                entry.update({"status": "skipped", "reason": "empty"})
                report["image_fields"].append(entry)
                continue
            image_path = resolve_path(data_base, image_value)
            resolved = work.resolve(image_field)
            if not resolved:
                entry.update({"status": "error", "error": "image_locator_not_found"})
                report["image_fields"].append(entry)
                continue
            entry.update(work.replace_image_in_element(resolved, image_path))
            report["image_fields"].append(entry)
        for loop in spec.get("table_loops", []):
            key = loop.get("key")
            rows_data = table_data.get(key)
            if rows_data is None:
                rows_data = field_data.get(key)
            entry = {"key": key, "status": "pending"}
            if rows_data in (None, ""):
                if loop.get("required"):
                    entry.update({"status": "error", "error": "missing_required_table"})
                    report["table_loops"].append(entry)
                    continue
                rows_data = []
            if not isinstance(rows_data, list):
                entry.update({"status": "error", "error": "table_data_must_be_list"})
                report["table_loops"].append(entry)
                continue
            entry.update(work.fill_table_loop(loop, rows_data))
            report["table_loops"].append(entry)
        errors = [
            row
            for row in report["conditional_blocks"] + report["fields"] + report["image_fields"] + report["table_loops"]
            if row.get("status") == "error"
        ]
        if errors:
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        work.pack(args.output)
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        if reference_work is not None:
            reference_work.cleanup()
        work.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
