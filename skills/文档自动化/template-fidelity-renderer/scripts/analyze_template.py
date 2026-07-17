#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import platform
import posixpath
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
}

RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
FONT_CACHE_PATH = Path(tempfile.gettempdir()) / "template_fidelity_font_probe_cache.json"
FONT_CACHE_TTL_SECONDS = 24 * 60 * 60


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


def part_hashes(zf):
    important = [
        "word/styles.xml",
        "word/fontTable.xml",
        "word/numbering.xml",
        "word/settings.xml",
        "word/theme/theme1.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
    ]
    for name in zf.namelist():
        if name.startswith("word/header") or name.startswith("word/footer"):
            important.append(name)
    out = {}
    names = set(zf.namelist())
    for name in sorted(set(important)):
        if name in names:
            out[name] = hashlib.sha256(zf.read(name)).hexdigest()
    return out


def rpr_summary(rpr):
    if rpr is None:
        return {}
    out = {}
    fonts = rpr.find("w:rFonts", NS)
    if fonts is not None:
        values = {k.split("}", 1)[-1]: v for k, v in fonts.attrib.items()}
        if values:
            out["fonts"] = values
    sz = rpr.find("w:sz", NS)
    if sz is not None and attr(sz, "w:val"):
        out["size_pt"] = int(attr(sz, "w:val")) / 2
    szcs = rpr.find("w:szCs", NS)
    if szcs is not None and attr(szcs, "w:val"):
        out["size_cs_pt"] = int(attr(szcs, "w:val")) / 2
    if rpr.find("w:b", NS) is not None:
        out["bold"] = True
    if rpr.find("w:i", NS) is not None:
        out["italic"] = True
    color = rpr.find("w:color", NS)
    if color is not None:
        out["color"] = attr(color, "w:val")
    return out


def ppr_summary(ppr):
    if ppr is None:
        return {}
    out = {}
    pstyle = ppr.find("w:pStyle", NS)
    if pstyle is not None:
        out["style"] = attr(pstyle, "w:val")
    jc = ppr.find("w:jc", NS)
    if jc is not None:
        out["align"] = attr(jc, "w:val")
    ind = ppr.find("w:ind", NS)
    if ind is not None:
        out["indent"] = {k.split("}", 1)[-1]: v for k, v in ind.attrib.items()}
    spacing = ppr.find("w:spacing", NS)
    if spacing is not None:
        out["spacing"] = {k.split("}", 1)[-1]: v for k, v in spacing.attrib.items()}
    numpr = ppr.find("w:numPr", NS)
    if numpr is not None:
        out["numbering"] = {}
        ilvl = numpr.find("w:ilvl", NS)
        numid = numpr.find("w:numId", NS)
        if ilvl is not None:
            out["numbering"]["level"] = attr(ilvl, "w:val")
        if numid is not None:
            out["numbering"]["numId"] = attr(numid, "w:val")
    return out


def parent_map(root):
    return {child: parent for parent in root.iter() for child in parent}


def ancestor(node, parents, tag_name):
    cur = node
    while cur in parents:
        cur = parents[cur]
        if cur.tag == qn(tag_name):
            return cur
    return None


def content_control_kind(sdt_pr):
    if sdt_pr is None:
        return None
    if has_descendant_local(sdt_pr, {"checkBox", "checkbox"}):
        return "checkBox"
    for name in ["repeatingSection", "repeatingSectionItem"]:
        if has_descendant_local(sdt_pr, {name}):
            return name
    known = [
        "text",
        "richText",
        "picture",
        "date",
        "dropDownList",
        "comboBox",
        "checkBox",
        "citation",
        "docPartObj",
        "group",
        "repeatingSection",
        "repeatingSectionItem",
        "equation",
    ]
    for name in known:
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


def clean_field_key(text):
    value = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", (text or "").strip()).strip("_")
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


def content_control_level(sdt, content, parents):
    if content is not None and any(child.tag == qn("w:p") for child in list(content)):
        return "block"
    if ancestor(sdt, parents, "w:p") is not None:
        return "inline"
    if ancestor(sdt, parents, "w:tc") is not None:
        return "cell"
    return "unknown"


def spec_candidate_for_content_control(item):
    locator = {}
    if item.get("tag"):
        locator["tag"] = item["tag"]
    elif item.get("alias"):
        locator["alias"] = item["alias"]
    elif item.get("binding"):
        locator["binding"] = item["binding"]
    else:
        locator["index"] = item["index"]
    key = item.get("tag") or item.get("alias") or key_from_binding(item.get("binding")) or f"content_control_{item['index']}"
    candidate = {
        "key": key,
        "locator_type": "content_control",
        "locator": locator,
        "required": False,
    }
    if item.get("binding"):
        candidate["binding"] = item["binding"]
    if item.get("lock"):
        candidate["lock"] = item["lock"]
    if item.get("showing_placeholder"):
        candidate["showing_placeholder"] = True
    if item.get("kind") == "checkBox":
        candidate["replacement_mode"] = "checkbox"
    if item.get("kind") in {"dropDownList", "comboBox"}:
        candidate["replacement_mode"] = "choice"
        if item.get("options"):
            candidate["options"] = item["options"]
    if item.get("kind") == "date":
        candidate["replacement_mode"] = "date"
        if item.get("date"):
            candidate["date"] = item["date"]
    if item.get("text_control"):
        candidate["text_control"] = item["text_control"]
    if item.get("kind") == "repeatingSection":
        candidate["replacement_mode"] = "repeating_section"
    if item.get("part") != "word/document.xml":
        candidate["part"] = item.get("part")
    return candidate


def spec_candidate_for_bookmark(item):
    candidate = {
        "key": clean_field_key(item.get("name") or f"bookmark_{item.get('id') or 'field'}"),
        "locator_type": "bookmark",
        "locator": {"name": item.get("name")} if item.get("name") else {"id": item.get("id")},
        "replacement_mode": "bookmark_text",
        "required": False,
    }
    if item.get("part") != "word/document.xml":
        candidate["part"] = item.get("part")
    return candidate


def spec_candidate_for_hyperlink(item):
    locator = {}
    if item.get("text"):
        locator["text"] = item["text"]
        locator["match"] = "exact"
    if item.get("target"):
        locator["target"] = item["target"]
    if not locator:
        locator["index"] = item["index"]
    key = clean_field_key(item.get("text") or item.get("target") or f"hyperlink_{item['index']}")
    candidate = {
        "key": key,
        "locator_type": "hyperlink",
        "locator": locator,
        "replacement_mode": "hyperlink",
        "required": False,
    }
    if item.get("part") != "word/document.xml":
        candidate["part"] = item.get("part")
    return candidate


def bookmark_inventory(root, part):
    parents = parent_map(root)
    paragraphs = root.findall(".//w:p", NS)
    paragraph_indexes = {paragraph: index for index, paragraph in enumerate(paragraphs)}
    ends = {attr(end, "w:id"): end for end in root.findall(".//w:bookmarkEnd", NS)}
    items = []
    for bookmark in root.findall(".//w:bookmarkStart", NS):
        name = attr(bookmark, "w:name")
        bookmark_id = attr(bookmark, "w:id")
        paragraph = ancestor(bookmark, parents, "w:p")
        end = ends.get(bookmark_id)
        end_paragraph = ancestor(end, parents, "w:p") if end is not None else None
        hidden = bool(name and name.startswith("_"))
        system = is_system_bookmark_name(name)
        item = {
            "part": part,
            "name": name,
            "id": bookmark_id,
            "hidden": hidden,
            "system": system and not hidden,
            "paragraph_index": paragraph_indexes.get(paragraph),
            "same_paragraph": paragraph is not None and paragraph is end_paragraph,
            "text": text_of(paragraph).strip()[:240] if paragraph is not None else "",
        }
        if name and not hidden and not system:
            item["spec_candidate"] = spec_candidate_for_bookmark(item)
        items.append(item)
    return items


def hyperlink_inventory(root, part, relationships):
    parents = parent_map(root)
    paragraphs = root.findall(".//w:p", NS)
    paragraph_indexes = {paragraph: index for index, paragraph in enumerate(paragraphs)}
    items = []
    for index, hyperlink in enumerate(root.findall(".//w:hyperlink", NS)):
        relationship_id = attr(hyperlink, "r:id")
        relationship = relationships.get(relationship_id, {}) if relationship_id else {}
        paragraph = ancestor(hyperlink, parents, "w:p")
        item = {
            "part": part,
            "index": index,
            "paragraph_index": paragraph_indexes.get(paragraph),
            "text": text_of(hyperlink).strip()[:240],
            "relationship_id": relationship_id,
            "target": relationship.get("target"),
            "target_mode": relationship.get("target_mode"),
            "relationship_type": relationship.get("type"),
            "relationship_part": relationship.get("part"),
        }
        anchor = attr(hyperlink, "w:anchor")
        if anchor:
            item["anchor"] = anchor
        if item.get("text") or item.get("target"):
            item["spec_candidate"] = spec_candidate_for_hyperlink(item)
        items.append({key: value for key, value in item.items() if value not in (None, "")})
    return items


def content_control_inventory(root, part):
    parents = parent_map(root)
    paragraphs = root.findall(".//w:p", NS)
    paragraph_indexes = {paragraph: index for index, paragraph in enumerate(paragraphs)}
    items = []
    for idx, sdt in enumerate(root.findall(".//w:sdt", NS)):
        sdt_pr = sdt.find("w:sdtPr", NS)
        content = sdt.find("w:sdtContent", NS)
        tag = None
        alias = None
        lock = None
        if sdt_pr is not None:
            tag_el = sdt_pr.find("w:tag", NS)
            alias_el = sdt_pr.find("w:alias", NS)
            lock_el = sdt_pr.find("w:lock", NS)
            tag = attr(tag_el, "w:val") if tag_el is not None else None
            alias = attr(alias_el, "w:val") if alias_el is not None else None
            lock = attr(lock_el, "w:val") if lock_el is not None else None
        showing_placeholder = sdt_pr is not None and sdt_pr.find("w:showingPlcHdr", NS) is not None
        paragraph = ancestor(sdt, parents, "w:p")
        item = {
            "part": part,
            "index": idx,
            "level": content_control_level(sdt, content, parents),
            "kind": content_control_kind(sdt_pr),
            "tag": tag,
            "alias": alias,
            "lock": lock,
            "paragraph_index": paragraph_indexes.get(paragraph),
            "showing_placeholder": showing_placeholder,
            "contains_table": bool(sdt.findall(".//w:tbl", NS)),
            "contains_image": bool(sdt.findall(".//w:drawing", NS)),
            "text": text_of(sdt).strip()[:240],
        }
        binding = content_control_binding(sdt_pr)
        if binding:
            item["binding"] = binding
        options = content_control_choice_options(sdt_pr)
        if options:
            item["options"] = options
        date_properties = content_control_date_properties(sdt_pr)
        if date_properties:
            item["date"] = date_properties
        text_properties = content_control_text_properties(sdt_pr)
        if text_properties:
            item["text_control"] = text_properties
        item["spec_candidate"] = spec_candidate_for_content_control(item)
        items.append(item)
    return items


def complex_structure_inventory(root, part):
    parents = parent_map(root)
    paragraphs = root.findall(".//w:p", NS)
    paragraph_indexes = {paragraph: index for index, paragraph in enumerate(paragraphs)}
    counts = Counter()
    field_instructions = []
    samples = []

    def paragraph_index_for(node):
        paragraph = ancestor(node, parents, "w:p")
        return paragraph_indexes.get(paragraph)

    def add_sample(kind, node, detail=None):
        if len(samples) >= 30:
            return
        paragraph = ancestor(node, parents, "w:p")
        row = {
            "kind": kind,
            "part": part,
            "paragraph_index": paragraph_indexes.get(paragraph),
            "paragraph_text": text_of(paragraph).strip()[:180] if paragraph is not None else "",
        }
        if detail:
            row["detail"] = detail
        samples.append(row)

    for node in root.iter():
        name = local_name(node)
        if name == "fldSimple":
            counts["field_code_markers"] += 1
            instruction = ""
            for key, value in node.attrib.items():
                if key.rsplit("}", 1)[-1] == "instr":
                    instruction = (value or "").strip()
                    break
            if instruction:
                counts["field_instruction_count"] += 1
                field_instructions.append(
                    {
                        "part": part,
                        "paragraph_index": paragraph_index_for(node),
                        "instruction": instruction[:240],
                    }
                )
            add_sample("field_code", node, instruction[:120] if instruction else None)
        elif name in {"fldChar", "instrText"}:
            counts["field_code_markers"] += 1
            if name == "instrText" and (node.text or "").strip():
                instruction = (node.text or "").strip()
                counts["field_instruction_count"] += 1
                field_instructions.append(
                    {
                        "part": part,
                        "paragraph_index": paragraph_index_for(node),
                        "instruction": instruction[:240],
                    }
                )
                add_sample("field_code", node, instruction[:120])
            elif name == "fldChar":
                add_sample("field_code", node)
        elif name in {"oMath", "oMathPara"}:
            counts["equation_count"] += 1
            add_sample("equation", node)
        elif name in {"object", "OLEObject"}:
            counts["embedded_object_count"] += 1
            add_sample("embedded_object", node)
        elif name == "altChunk":
            counts["alt_chunk_count"] += 1
            add_sample("alt_chunk", node)
        elif name in {"ins", "del", "moveFrom", "moveTo", "moveFromRangeStart", "moveToRangeStart", "moveFromRangeEnd", "moveToRangeEnd"}:
            counts["revision_count"] += 1
            add_sample("revision", node)
        elif name in {"commentRangeStart", "commentRangeEnd", "commentReference"}:
            counts["comment_anchor_count"] += 1
            add_sample("comment_anchor", node)
        elif name in {"drawing", "pict"}:
            counts["drawing_count"] += 1

    return {
        "counts": dict(counts),
        "field_instructions": field_instructions[:30],
        "samples": samples,
    }


def collect_installed_font_text():
    if os.environ.get("TEMPLATE_FIDELITY_DISABLE_FONT_CACHE") != "1":
        try:
            ttl = int(os.environ.get("TEMPLATE_FIDELITY_FONT_CACHE_TTL", str(FONT_CACHE_TTL_SECONDS)))
            if FONT_CACHE_PATH.exists() and time.time() - FONT_CACHE_PATH.stat().st_mtime <= ttl:
                cached = json.loads(FONT_CACHE_PATH.read_text(encoding="utf-8"))
                text = cached.get("text")
                sources = cached.get("sources")
                if isinstance(text, str) and isinstance(sources, list):
                    return text, [str(source) for source in sources] + [f"cache:{FONT_CACHE_PATH}"]
        except Exception:
            pass

    chunks = []
    source = []
    if platform.system() == "Darwin":
        try:
            cp = subprocess.run(
                ["system_profiler", "SPFontsDataType"],
                capture_output=True,
                text=True,
                timeout=45,
            )
            chunks.append(cp.stdout + "\n" + cp.stderr)
            source.append("system_profiler SPFontsDataType")
        except Exception as exc:
            source.append(f"system_profiler failed: {exc}")
    for root in [
        "/System/Library/Fonts",
        "/Library/Fonts",
        str(Path.home() / "Library/Fonts"),
        str(Path.home() / ".local/share/fonts"),
    ]:
        p = Path(root)
        if p.exists():
            files = [str(x) for x in p.rglob("*") if x.suffix.lower() in {".ttf", ".otf", ".ttc"}]
            chunks.append("\n".join(files))
            source.append(root)
    text = "\n".join(chunks)
    if os.environ.get("TEMPLATE_FIDELITY_DISABLE_FONT_CACHE") != "1":
        try:
            tmp = FONT_CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps({"text": text, "sources": source}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(FONT_CACHE_PATH)
        except Exception:
            pass
    return text, source


FONT_ALIASES = {
    "宋体": ["宋体", "SimSun", "Songti", "STSong", "Songti SC"],
    "黑体": ["黑体", "SimHei", "Heiti", "STHeiti", "Heiti SC"],
    "仿宋": ["仿宋", "FangSong", "STFangsong"],
    "幼圆": ["幼圆", "YouYuan", "Yuanti", "Yuanti SC"],
    "ＭＳ ゴシック": ["ＭＳ ゴシック", "MS Gothic", "Hiragino Sans"],
    "ＭＳ 明朝": ["ＭＳ 明朝", "MS Mincho", "Hiragino Mincho"],
}


def check_fonts(fonts):
    installed_text, sources = collect_installed_font_text()
    results = []
    for font in fonts:
        probes = FONT_ALIASES.get(font, [font])
        evidence = []
        for probe in probes:
            if re.search(re.escape(probe), installed_text, re.I):
                evidence.append(probe)
        results.append(
            {
                "font": font,
                "available_likely": bool(evidence),
                "evidence": evidence[:8],
            }
        )
    return {
        "sources": sources,
        "required_fonts": fonts,
        "results": results,
        "missing_fonts": [r["font"] for r in results if not r["available_likely"]],
    }


def analyze_docx(path):
    with ZipFile(path) as zf:
        names = set(zf.namelist())
        document = read_xml(zf, "word/document.xml")
        text_parts = text_part_names(names)
        styles = read_xml(zf, "word/styles.xml") if "word/styles.xml" in names else None
        font_table = read_xml(zf, "word/fontTable.xml") if "word/fontTable.xml" in names else None
        numbering = read_xml(zf, "word/numbering.xml") if "word/numbering.xml" in names else None

        font_names = []
        if font_table is not None:
            font_names = sorted({attr(f, "w:name") for f in font_table.findall("w:font", NS) if attr(f, "w:name")})

        style_items = []
        if styles is not None:
            for style in styles.findall("w:style", NS):
                sid = attr(style, "w:styleId")
                stype = attr(style, "w:type")
                name = style.find("w:name", NS)
                style_items.append(
                    {
                        "id": sid,
                        "type": stype,
                        "name": attr(name, "w:val") if name is not None else sid,
                        "based_on": attr(style.find("w:basedOn", NS), "w:val"),
                        "paragraph": ppr_summary(style.find("w:pPr", NS)),
                        "run": rpr_summary(style.find("w:rPr", NS)),
                    }
                )

        paragraphs = document.findall(".//w:p", NS)
        pstyle_counter = Counter()
        direct_fonts = Counter()
        direct_sizes = Counter()
        samples_by_style = defaultdict(list)
        paragraph_inventory = []
        texts = []
        placeholders = Counter()
        for index, para in enumerate(paragraphs):
            text = text_of(para).strip()
            if text:
                texts.append(text)
            pstyle = None
            ppr = para.find("w:pPr", NS)
            if ppr is not None:
                style_el = ppr.find("w:pStyle", NS)
                if style_el is not None:
                    pstyle = attr(style_el, "w:val")
            key = pstyle or "(none)"
            pstyle_counter[key] += 1
            if text and len(samples_by_style[key]) < 3:
                samples_by_style[key].append(text[:120])
            paragraph_inventory.append(
                {
                    "index": index,
                    "para_id": para.get(qn("w14:paraId"), ""),
                    "text_id": para.get(qn("w14:textId"), ""),
                    "style_id": pstyle,
                    "text": text[:240],
                }
            )
            for run in para.findall("w:r", NS):
                rpr = run.find("w:rPr", NS)
                if rpr is None:
                    continue
                fonts = rpr.find("w:rFonts", NS)
                if fonts is not None:
                    for value in fonts.attrib.values():
                        direct_fonts[value] += 1
                size = rpr.find("w:sz", NS)
                if size is not None and attr(size, "w:val"):
                    direct_sizes[str(int(attr(size, "w:val")) / 2)] += 1
            for match in re.findall(r"\{\{[^{}]+\}\}", text):
                placeholders[match] += 1

        sections = []
        for sect in document.findall(".//w:sectPr", NS):
            pg_sz = sect.find("w:pgSz", NS)
            pg_mar = sect.find("w:pgMar", NS)
            sections.append(
                {
                    "page_size_twips": {k.split("}", 1)[-1]: v for k, v in pg_sz.attrib.items()} if pg_sz is not None else {},
                    "page_margin_twips": {k.split("}", 1)[-1]: v for k, v in pg_mar.attrib.items()} if pg_mar is not None else {},
                    "headers": len(sect.findall("w:headerReference", NS)),
                    "footers": len(sect.findall("w:footerReference", NS)),
                }
            )

        tables = []
        for tbl in document.findall(".//w:tbl", NS):
            rows = tbl.findall("w:tr", NS)
            tables.append(
                {
                    "rows": len(rows),
                    "max_cols": max((len(row.findall("w:tc", NS)) for row in rows), default=0),
                    "sample": text_of(tbl).strip()[:180],
                }
            )

        numbering_summary = {}
        if numbering is not None:
            abstract = numbering.findall("w:abstractNum", NS)
            nums = numbering.findall("w:num", NS)
            numbering_summary = {
                "abstract_count": len(abstract),
                "num_count": len(nums),
                "levels_per_abstract": [len(a.findall("w:lvl", NS)) for a in abstract],
            }

        bookmarks = []
        hyperlinks = []
        content_controls = []
        complex_parts = []
        for part in text_parts:
            root = document if part == "word/document.xml" else read_xml(zf, part)
            relationships = relationships_for_part(zf, part, names)
            bookmarks.extend(bookmark_inventory(root, part))
            hyperlinks.extend(hyperlink_inventory(root, part, relationships))
            content_controls.extend(content_control_inventory(root, part))
            complex_parts.append(complex_structure_inventory(root, part))
        complex_counts = Counter()
        complex_field_instructions = []
        complex_samples = []
        for row in complex_parts:
            complex_counts.update(row.get("counts") or {})
            complex_field_instructions.extend(row.get("field_instructions") or [])
            complex_samples.extend(row.get("samples") or [])

        return {
            "source_file": str(path),
            "docx_parts": sorted(names),
            "text_parts": text_parts,
            "hashes": part_hashes(zf),
            "fonts": check_fonts(font_names),
            "styles": {
                "count": len(style_items),
                "counts": dict(Counter(s["type"] for s in style_items)),
                "items": style_items,
            },
            "paragraphs": {
                "count": len(paragraphs),
                "top_styles": pstyle_counter.most_common(30),
                "samples_by_style": dict(samples_by_style),
                "direct_fonts": direct_fonts.most_common(30),
                "direct_sizes_pt": direct_sizes.most_common(30),
                "inventory": paragraph_inventory,
            },
            "sections": sections,
            "tables": {"count": len(tables), "items": tables[:50]},
            "numbering": numbering_summary,
            "bookmarks": bookmarks,
            "hyperlinks": hyperlinks,
            "content_controls": content_controls,
            "complex_structures": {
                "counts": dict(complex_counts),
                "field_instructions": complex_field_instructions[:50],
                "samples": complex_samples[:50],
            },
            "placeholders": dict(placeholders),
            "first_text_samples": texts[:30],
        }


def main():
    parser = argparse.ArgumentParser(description="Analyze a DOCX template for fidelity rendering.")
    parser.add_argument("template")
    parser.add_argument("--output", "-o")
    args = parser.parse_args()

    path = Path(args.template).expanduser()
    if not path.exists():
        print(f"Template not found: {path}", file=sys.stderr)
        return 2
    report = analyze_docx(path)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
