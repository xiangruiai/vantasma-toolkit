#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

try:
    from PIL import Image, ImageChops, ImageDraw, ImageStat
except Exception:
    Image = None
    ImageChops = None
    ImageDraw = None
    ImageStat = None

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


INVARIANT_PARTS = [
    "word/styles.xml",
    "word/fontTable.xml",
    "word/numbering.xml",
    "word/settings.xml",
    "word/theme/theme1.xml",
]

TEXT_MUTABLE_PARTS = {"word/footnotes.xml", "word/endnotes.xml"}
FONT_CACHE_PATH = Path(tempfile.gettempdir()) / "template_fidelity_font_probe_cache.json"
FONT_CACHE_TTL_SECONDS = 24 * 60 * 60


def qn(name):
    prefix, local = name.split(":", 1)
    return "{%s}%s" % (NS[prefix], local)


def attr(el, name):
    return el.get(qn(name)) if el is not None else None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def zip_ok(path):
    try:
        with ZipFile(path) as zf:
            bad = zf.testzip()
            return bad is None, bad
    except BadZipFile as exc:
        return False, str(exc)


def compare_parts(template, output, allowed_changed_parts=None):
    allowed_changed_parts = set(allowed_changed_parts or [])
    rows = []
    with ZipFile(template) as a, ZipFile(output) as b:
        a_names = set(a.namelist())
        b_names = set(b.namelist())
        for name in sorted(set(INVARIANT_PARTS)):
            if name not in a_names:
                continue
            if name not in b_names:
                rows.append({"part": name, "comparison": "hash", "status": "missing_in_output", "unchanged": False})
                continue
            ha = sha256(a.read(name))
            hb = sha256(b.read(name))
            unchanged = ha == hb
            rows.append(
                {
                    "part": name,
                    "comparison": "hash",
                    "status": "compared",
                    "unchanged": unchanged,
                    "allowed_change": (not unchanged) and name in allowed_changed_parts,
                    "template_sha256": ha,
                    "output_sha256": hb,
                }
            )
        for name in sorted(text_mutable_parts(a_names)):
            if name not in b_names:
                rows.append({"part": name, "comparison": "text_structure", "status": "missing_in_output", "structure_unchanged": False, "unchanged": False})
                continue
            template_raw = a.read(name)
            output_raw = b.read(name)
            template_structure = text_part_structure_digest(template_raw)
            output_structure = text_part_structure_digest(output_raw)
            structure_unchanged = template_structure == output_structure
            rows.append(
                {
                    "part": name,
                    "comparison": "text_structure",
                    "status": "compared",
                    "unchanged": structure_unchanged,
                    "structure_unchanged": structure_unchanged,
                    "text_changed": text_content(template_raw) != text_content(output_raw),
                    "template_sha256": sha256(template_raw),
                    "output_sha256": sha256(output_raw),
                    "template_structure_sha256": template_structure,
                    "output_structure_sha256": output_structure,
                }
            )
    return rows


def text_mutable_parts(names):
    parts = set(TEXT_MUTABLE_PARTS.intersection(names))
    parts.update(name for name in names if name.startswith("word/header") and name.endswith(".xml"))
    parts.update(name for name in names if name.startswith("word/footer") and name.endswith(".xml"))
    return parts


def text_content(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes.decode("utf-8", errors="ignore")
    return "".join(node.text or "" for node in root.findall(".//w:t", NS))


def text_part_structure_digest(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return sha256(xml_bytes)
    for node in root.findall(".//w:t", NS):
        node.text = ""
    return sha256(ET.tostring(root, encoding="utf-8"))


def parent_map(root):
    return {child: parent for parent in root.iter() for child in parent}


def ancestor(node, parents, tag_name):
    cur = node
    while cur in parents:
        cur = parents[cur]
        if cur.tag == qn(tag_name):
            return cur
    return None


def local_name(el):
    return el.tag.rsplit("}", 1)[-1] if "}" in el.tag else el.tag


def has_descendant_local(el, local_names):
    if el is None:
        return False
    return any(local_name(child) in local_names for child in el.iter())


def content_control_parts(names):
    parts = ["word/document.xml"]
    parts.extend(name for name in sorted(names) if name.startswith("word/header") and name.endswith(".xml"))
    parts.extend(name for name in sorted(names) if name.startswith("word/footer") and name.endswith(".xml"))
    for name in ["word/footnotes.xml", "word/endnotes.xml"]:
        if name in names:
            parts.append(name)
    return [name for name in parts if name in names]


def content_control_kind(sdt_pr):
    if sdt_pr is None:
        return None
    if has_descendant_local(sdt_pr, {"checkBox", "checkbox"}):
        return "checkBox"
    for name in ["repeatingSection", "repeatingSectionItem"]:
        if has_descendant_local(sdt_pr, {name}):
            return name
    for name in [
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
    ]:
        if sdt_pr.find(f"w:{name}", NS) is not None:
            return name
    return None


def ancestor_content_control_kind(node, parents, kind):
    cur = node
    while cur in parents:
        cur = parents[cur]
        if cur.tag == qn("w:sdt") and content_control_kind(cur.find("w:sdtPr", NS)) == kind:
            return True
    return False


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


def content_control_level(sdt, content, parents):
    if content is not None and any(child.tag == qn("w:p") for child in list(content)):
        return "block"
    if ancestor(sdt, parents, "w:p") is not None:
        return "inline"
    if ancestor(sdt, parents, "w:tc") is not None:
        return "cell"
    return "unknown"


def content_control_inventory_for_part(xml_bytes, part):
    root = ET.fromstring(xml_bytes)
    parents = parent_map(root)
    out = []
    for index, sdt in enumerate(root.findall(".//w:sdt", NS)):
        sdt_pr = sdt.find("w:sdtPr", NS)
        content = sdt.find("w:sdtContent", NS)
        tag = None
        alias = None
        lock = None
        showing_placeholder = False
        if sdt_pr is not None:
            tag_el = sdt_pr.find("w:tag", NS)
            alias_el = sdt_pr.find("w:alias", NS)
            lock_el = sdt_pr.find("w:lock", NS)
            tag = attr(tag_el, "w:val") if tag_el is not None else None
            alias = attr(alias_el, "w:val") if alias_el is not None else None
            lock = attr(lock_el, "w:val") if lock_el is not None else None
            showing_placeholder = sdt_pr.find("w:showingPlcHdr", NS) is not None
        out.append(
            {
                "part": part,
                "index": index,
                "level": content_control_level(sdt, content, parents),
                "kind": content_control_kind(sdt_pr),
                "tag": tag,
                "alias": alias,
                "binding": content_control_binding(sdt_pr),
                "lock": lock,
                "showing_placeholder": showing_placeholder,
                "text_control": content_control_text_properties(sdt_pr),
                "inside_repeating_section": ancestor_content_control_kind(sdt, parents, "repeatingSection"),
                "contains_table": bool(sdt.findall(".//w:tbl", NS)),
                "contains_image": bool(sdt.findall(".//w:drawing", NS)),
            }
        )
    return out


def content_control_inventory(path):
    out = []
    with ZipFile(path) as zf:
        names = set(zf.namelist())
        for part in content_control_parts(names):
            try:
                out.extend(content_control_inventory_for_part(zf.read(part), part))
            except ET.ParseError:
                out.append({"part": part, "error": "xml_parse_error"})
    return out


def content_control_signature(row):
    return {
        key: row.get(key)
        for key in [
            "part",
            "index",
            "level",
            "kind",
            "tag",
            "alias",
            "binding",
            "lock",
            "showing_placeholder",
            "text_control",
            "inside_repeating_section",
            "contains_table",
            "contains_image",
            "error",
        ]
        if key in row
    }


def content_control_signature_without_index(row):
    out = dict(row)
    out.pop("index", None)
    return out


def content_control_signature_key(row):
    return json.dumps(content_control_signature_without_index(row), sort_keys=True, ensure_ascii=False)


def content_control_signature_without_placeholder(row):
    out = content_control_signature_without_index(row)
    out.pop("showing_placeholder", None)
    return out


def content_control_placeholder_signature_key(row):
    return json.dumps(content_control_signature_without_placeholder(row), sort_keys=True, ensure_ascii=False)


def render_report_has_repeating_section_change(path):
    if not path:
        return False
    render = read_json(path)
    if render.get("error"):
        return False
    return any(
        isinstance(field, dict)
        and field.get("status") == "filled"
        and field.get("action") == "content_control_repeating_section"
        for field in render.get("fields", []) or []
    )


def render_report_has_content_control_placeholder_removed(path):
    if not path:
        return False
    render = read_json(path)
    if render.get("error"):
        return False
    return any(
        isinstance(field, dict)
        and field.get("status") == "filled"
        and field.get("expected_structure_change") == "content_control_placeholder_removed"
        and int(field.get("placeholder_removed") or 0) > 0
        for field in render.get("fields", []) or []
    )


def compare_content_controls(template, output, allow_repeating_section_changes=False, allow_placeholder_changes=False):
    template_controls = [content_control_signature(row) for row in content_control_inventory(template)]
    output_controls = [content_control_signature(row) for row in content_control_inventory(output)]
    missing = [row for row in template_controls if row not in output_controls]
    extra = [row for row in output_controls if row not in template_controls]
    allowed_repeating_signatures = {content_control_signature_key(row) for row in template_controls if row.get("inside_repeating_section")}
    allowed_missing = []
    allowed_extra = []
    allowed_placeholder_missing = []
    allowed_placeholder_extra = []
    if allow_repeating_section_changes:
        allowed_missing = [
            row
            for row in missing
            if row.get("inside_repeating_section")
            and content_control_signature_key(row) in allowed_repeating_signatures
        ]
        allowed_extra = [
            row
            for row in extra
            if row.get("inside_repeating_section")
            and content_control_signature_key(row) in allowed_repeating_signatures
        ]
    if allow_placeholder_changes:
        output_without_placeholder = {
            content_control_placeholder_signature_key(row)
            for row in output_controls
            if row.get("showing_placeholder") is False
        }
        template_with_placeholder = {
            content_control_placeholder_signature_key(row)
            for row in template_controls
            if row.get("showing_placeholder") is True
        }
        allowed_placeholder_missing = [
            row
            for row in missing
            if row.get("showing_placeholder") is True
            and content_control_placeholder_signature_key(row) in output_without_placeholder
        ]
        allowed_placeholder_extra = [
            row
            for row in extra
            if row.get("showing_placeholder") is False
            and content_control_placeholder_signature_key(row) in template_with_placeholder
        ]
    remaining_missing = [row for row in missing if row not in allowed_missing and row not in allowed_placeholder_missing]
    remaining_extra = [row for row in extra if row not in allowed_extra and row not in allowed_placeholder_extra]
    preserved = template_controls == output_controls or (
        (allow_repeating_section_changes or allow_placeholder_changes)
        and not remaining_missing
        and not remaining_extra
    )
    return {
        "template": template_controls,
        "output": output_controls,
        "template_count": len(template_controls),
        "output_count": len(output_controls),
        "preserved": preserved,
        "missing_or_changed": missing,
        "extra_or_changed": extra,
        "allowed_repeating_section_changes": {
            "enabled": allow_repeating_section_changes,
            "missing": allowed_missing,
            "extra": allowed_extra,
        },
        "allowed_placeholder_changes": {
            "enabled": allow_placeholder_changes,
            "missing": allowed_placeholder_missing,
            "extra": allowed_placeholder_extra,
        },
    }


def docx_text_and_tokens(path):
    tokens = set()
    texts = []
    with ZipFile(path) as zf:
        for name in zf.namelist():
            if not (name == "word/document.xml" or name.startswith("word/header") or name.startswith("word/footer") or name in {"word/footnotes.xml", "word/endnotes.xml"}):
                continue
            raw = zf.read(name)
            text = raw.decode("utf-8", errors="ignore")
            tokens.update(re.findall(r"\{\{[^{}]+\}\}", text))
            try:
                root = ET.fromstring(raw)
                texts.extend(t.text or "" for t in root.findall(".//w:t", NS))
            except ET.ParseError:
                pass
    return "".join(texts), sorted(tokens)


def parse_template_fonts(path):
    with ZipFile(path) as zf:
        if "word/fontTable.xml" not in zf.namelist():
            return []
        root = ET.fromstring(zf.read("word/fontTable.xml"))
        def attr(el, local):
            return el.get("{%s}%s" % (NS["w"], local))
        return sorted({attr(f, "name") for f in root.findall("w:font", NS) if attr(f, "name")})


FONT_ALIASES = {
    "宋体": ["宋体", "SimSun", "Songti", "STSong", "Songti SC"],
    "黑体": ["黑体", "SimHei", "Heiti", "STHeiti", "Heiti SC"],
    "仿宋": ["仿宋", "FangSong", "STFangsong"],
    "幼圆": ["幼圆", "YouYuan", "Yuanti", "Yuanti SC"],
    "ＭＳ ゴシック": ["ＭＳ ゴシック", "MS Gothic", "Hiragino Sans"],
    "ＭＳ 明朝": ["ＭＳ 明朝", "MS Mincho", "Hiragino Mincho"],
}


def installed_font_text():
    if os.environ.get("TEMPLATE_FIDELITY_DISABLE_FONT_CACHE") != "1":
        try:
            ttl = int(os.environ.get("TEMPLATE_FIDELITY_FONT_CACHE_TTL", str(FONT_CACHE_TTL_SECONDS)))
            if FONT_CACHE_PATH.exists() and time.time() - FONT_CACHE_PATH.stat().st_mtime <= ttl:
                cached = json.loads(FONT_CACHE_PATH.read_text(encoding="utf-8"))
                text = cached.get("text")
                if isinstance(text, str):
                    return text
        except Exception:
            pass

    chunks = []
    sources = []
    if platform.system() == "Darwin":
        try:
            cp = subprocess.run(["system_profiler", "SPFontsDataType"], capture_output=True, text=True, timeout=45)
            chunks.append(cp.stdout + "\n" + cp.stderr)
            sources.append("system_profiler SPFontsDataType")
        except Exception:
            pass
    for root in ["/System/Library/Fonts", "/Library/Fonts", str(Path.home() / "Library/Fonts"), str(Path.home() / ".local/share/fonts")]:
        p = Path(root)
        if p.exists():
            chunks.append("\n".join(str(x) for x in p.rglob("*") if x.suffix.lower() in {".ttf", ".otf", ".ttc"}))
            sources.append(root)
    text = "\n".join(chunks)
    if os.environ.get("TEMPLATE_FIDELITY_DISABLE_FONT_CACHE") != "1":
        try:
            tmp = FONT_CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps({"text": text, "sources": sources}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(FONT_CACHE_PATH)
        except Exception:
            pass
    return text


def check_fonts(fonts):
    text = installed_font_text()
    rows = []
    for font in fonts:
        probes = FONT_ALIASES.get(font, [font])
        evidence = [probe for probe in probes if re.search(re.escape(probe), text, re.I)]
        rows.append({"font": font, "available_likely": bool(evidence), "evidence": evidence[:8]})
    return rows


def convert_pdf(docx, outdir):
    soffice = shutil.which("soffice")
    if not soffice:
        return {"ok": False, "error": "soffice not found"}
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(
        [soffice, "--headless", "--invisible", "--norestore", "--convert-to", "pdf", "--outdir", str(outdir), str(docx)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    pdf = outdir / (Path(docx).stem + ".pdf")
    return {"ok": cp.returncode == 0 and pdf.exists(), "pdf": str(pdf), "stdout": cp.stdout, "stderr": cp.stderr, "returncode": cp.returncode}


def pdf_info(pdf):
    info = {"pdf": str(pdf)}
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        cp = subprocess.run([pdfinfo, str(pdf)], capture_output=True, text=True, timeout=30)
        info["pdfinfo"] = cp.stdout
        match = re.search(r"^Pages:\s+(\d+)", cp.stdout, re.M)
        if match:
            info["pages"] = int(match.group(1))
    pdffonts = shutil.which("pdffonts")
    if pdffonts:
        cp = subprocess.run([pdffonts, str(pdf)], capture_output=True, text=True, timeout=30)
        info["pdffonts"] = cp.stdout
        lines = [line for line in cp.stdout.splitlines() if line.strip()]
        font_rows = lines[2:] if len(lines) > 2 else []
        info["font_rows"] = font_rows
        info["font_names"] = [normalize_pdf_font_name(row) for row in font_rows]
        info["all_fonts_embedded"] = all((" yes " in (" " + row + " ")) for row in font_rows) if font_rows else None
    return info


def normalize_pdf_font_name(row):
    raw = row.split()[0] if row.split() else ""
    return raw.split("+", 1)[1] if "+" in raw else raw


def pdf_font_coverage(required_fonts, pdf_font_names):
    pdf_text = "\n".join(pdf_font_names)
    rows = []
    for font in required_fonts:
        probes = FONT_ALIASES.get(font, [font])
        matched = [probe for probe in probes if re.search(re.escape(probe), pdf_text, re.I)]
        rows.append({"font": font, "matched": bool(matched), "matched_aliases": matched})
    return rows


VISUAL_IGNORE_PRESETS = {
    "header": [{"page": "all", "x": 0, "y": 0, "width": 1, "height": 0.08, "unit": "fraction", "label": "header"}],
    "footer": [{"page": "all", "x": 0, "y": 0.92, "width": 1, "height": 0.08, "unit": "fraction", "label": "footer"}],
    "header-footer": [
        {"page": "all", "x": 0, "y": 0, "width": 1, "height": 0.08, "unit": "fraction", "label": "header"},
        {"page": "all", "x": 0, "y": 0.92, "width": 1, "height": 0.08, "unit": "fraction", "label": "footer"},
    ],
    "page-number-footer": [
        {"page": "all", "x": 0.35, "y": 0.93, "width": 0.3, "height": 0.05, "unit": "fraction", "label": "page_number_footer"}
    ],
}


def load_visual_ignore_config(path=None, presets=None):
    regions = []
    preset_names = []

    def extend_preset(name):
        if name not in VISUAL_IGNORE_PRESETS:
            valid = ", ".join(sorted(VISUAL_IGNORE_PRESETS))
            raise ValueError(f"Unknown visual ignore preset: {name}. Valid presets: {valid}")
        preset_names.append(name)
        for region in VISUAL_IGNORE_PRESETS[name]:
            row = dict(region)
            row.setdefault("kind", "preset")
            row.setdefault("preset", name)
            regions.append(row)

    def extend_regions(items, kind):
        for region in items or []:
            row = dict(region)
            row.setdefault("kind", kind)
            regions.append(row)

    loaded = {}
    if path:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            extend_regions(loaded, "region")
        else:
            for preset in loaded.get("presets", []):
                extend_preset(preset)
            extend_regions(loaded.get("regions", []), "region")
            extend_regions(loaded.get("allowed_changes", []), "allowed_change")
            extend_regions(loaded.get("dynamic_regions", []), "dynamic")
    for preset in presets or []:
        extend_preset(preset)
    return {"source": str(path) if path else None, "presets": preset_names, "regions": regions}


def page_matches(page_spec, page):
    if page_spec in (None, "all", "*"):
        return True
    if isinstance(page_spec, int):
        return page_spec == page
    if isinstance(page_spec, list):
        return any(page_matches(item, page) for item in page_spec)
    text = str(page_spec).strip()
    if "-" in text:
        start, end = text.split("-", 1)
        return int(start) <= page <= int(end)
    return int(text) == page


def normalize_region(region, image_size):
    width, height = image_size
    unit = region.get("unit", "fraction")
    x = float(region.get("x", 0))
    y = float(region.get("y", 0))
    w = float(region.get("width", region.get("w", 0)))
    h = float(region.get("height", region.get("h", 0)))
    if unit in {"fraction", "ratio", "relative"}:
        x, y, w, h = x * width, y * height, w * width, h * height
    left = max(0, min(width, int(round(x))))
    top = max(0, min(height, int(round(y))))
    right = max(left, min(width, int(round(x + w))))
    bottom = max(top, min(height, int(round(y + h))))
    return {
        "label": region.get("label"),
        "kind": region.get("kind", "region"),
        "unit": unit,
        "page": region.get("page", "all"),
        "box": [left, top, right, bottom],
        "pixels": max(0, right - left) * max(0, bottom - top),
    }


def regions_for_page(ignore_config, page, image_size):
    regions = []
    for region in (ignore_config or {}).get("regions", []):
        if page_matches(region.get("page", "all"), page):
            normalized = normalize_region(region, image_size)
            if normalized["pixels"] > 0:
                regions.append(normalized)
    return regions


def apply_ignore_regions(image, regions, fill=(255, 255, 255)):
    if not regions:
        return image
    if ImageDraw is None:
        return image
    image = image.copy()
    draw = ImageDraw.Draw(image)
    for region in regions:
        draw.rectangle(region["box"], fill=fill)
    return image


def save_ignore_overlay(image, regions, outdir, page):
    if not regions or ImageDraw is None:
        return None
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for region in regions:
        draw.rectangle(region["box"], outline=(255, 0, 0), width=4)
    path = Path(outdir) / f"visual-ignore-mask-page-{page:03d}.png"
    overlay.save(path)
    return str(path)


def render_pdf_page(pdf, outdir, prefix, page=1, dpi=120):
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return {"ok": False, "error": "pdftoppm not found"}
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    output_prefix = outdir / prefix
    cp = subprocess.run(
        [pdftoppm, "-png", "-r", str(dpi), "-f", str(page), "-singlefile", str(pdf), str(output_prefix)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    image_path = output_prefix.with_suffix(".png")
    return {
        "ok": cp.returncode == 0 and image_path.exists(),
        "image": str(image_path),
        "stdout": cp.stdout,
        "stderr": cp.stderr,
        "returncode": cp.returncode,
    }


def compare_pdf_page_visual(template_pdf, output_pdf, outdir, page=1, dpi=120, threshold=12, ignore_config=None):
    result = {
        "page": page,
        "dpi": dpi,
        "pixel_threshold": threshold,
        "template_render": render_pdf_page(template_pdf, outdir, f"template-page-{page:03d}", page, dpi),
        "output_render": render_pdf_page(output_pdf, outdir, f"output-page-{page:03d}", page, dpi),
    }
    if not result["template_render"].get("ok") or not result["output_render"].get("ok"):
        result["ok"] = False
        result["error"] = "render_failed"
        return result
    if Image is None:
        result["ok"] = False
        result["error"] = "Pillow not available"
        return result

    template_image = Image.open(result["template_render"]["image"]).convert("RGB")
    output_image = Image.open(result["output_render"]["image"]).convert("RGB")
    result["template_size"] = template_image.size
    result["output_size"] = output_image.size
    result["same_dimensions"] = template_image.size == output_image.size
    if not result["same_dimensions"]:
        result["ok"] = False
        result["error"] = "dimension_mismatch"
        return result

    ignored_regions = regions_for_page(ignore_config, page, template_image.size)
    ignore_overlay = save_ignore_overlay(template_image, ignored_regions, outdir, page)
    template_compare = apply_ignore_regions(template_image, ignored_regions)
    output_compare = apply_ignore_regions(output_image, ignored_regions)
    diff = ImageChops.difference(template_compare, output_compare)
    stat = ImageStat.Stat(diff)
    gray = diff.convert("L")
    binary = gray.point(lambda value: 255 if value > threshold else 0)
    hist = binary.histogram()
    changed_pixels = hist[255]
    total_pixels = template_image.size[0] * template_image.size[1]
    diff_path = Path(outdir) / f"visual-diff-page-{page:03d}.png"
    diff.save(diff_path)
    result.update(
        {
            "ok": True,
            "diff_image": str(diff_path),
            "rms": stat.rms,
            "changed_pixels": changed_pixels,
            "total_pixels": total_pixels,
            "changed_ratio": changed_pixels / total_pixels if total_pixels else None,
            "ignored_regions": ignored_regions,
            "ignored_pixels_estimate": sum(region["pixels"] for region in ignored_regions),
            "ignore_overlay": ignore_overlay,
        }
    )
    return result


def parse_visual_pages(spec, template_pages=None, output_pages=None, max_pages=20):
    limit = min([value for value in [template_pages, output_pages] if isinstance(value, int)] or [1])
    if not spec:
        spec = "1"
    spec = str(spec).strip().lower()
    if spec == "all":
        pages = list(range(1, limit + 1))
    else:
        pages = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                start_i = int(start)
                end_i = int(end)
                pages.extend(range(start_i, end_i + 1))
            else:
                pages.append(int(part))
        pages = [page for page in sorted(set(pages)) if page >= 1 and page <= limit]
    if max_pages and len(pages) > max_pages:
        pages = pages[:max_pages]
    return pages or [1]


def compare_pdf_pages_visual(template_pdf, output_pdf, outdir, pages, dpi=120, threshold=12, max_changed_ratio=0.08, ignore_config=None):
    page_results = [
        compare_pdf_page_visual(
            template_pdf,
            output_pdf,
            Path(outdir) / f"page-{page:03d}",
            page=page,
            dpi=dpi,
            threshold=threshold,
            ignore_config=ignore_config,
        )
        for page in pages
    ]
    changed_ratios = [row.get("changed_ratio") for row in page_results if row.get("changed_ratio") is not None]
    pages_over_limit = [row["page"] for row in page_results if row.get("changed_ratio") is not None and row["changed_ratio"] > max_changed_ratio]
    failed_pages = [row["page"] for row in page_results if not row.get("ok")]
    same_dimensions_all = all(row.get("same_dimensions") is True for row in page_results)
    summary = {
        "pages_requested": pages,
        "pages_compared": len(page_results),
        "failed_pages": failed_pages,
        "same_dimensions_all": same_dimensions_all,
        "max_changed_ratio": max(changed_ratios) if changed_ratios else None,
        "avg_changed_ratio": sum(changed_ratios) / len(changed_ratios) if changed_ratios else None,
        "pages_over_limit": pages_over_limit,
        "max_allowed_changed_ratio": max_changed_ratio,
        "ignore_regions_total": sum(len(row.get("ignored_regions", [])) for row in page_results),
        "ignore_config": ignore_config,
    }
    out = {"summary": summary, "pages": page_results}
    if len(page_results) == 1:
        out.update(page_results[0])
    out["ok"] = not failed_pages and same_dimensions_all and not pages_over_limit
    return out


def tracked_text_format_from_render_report(path):
    render = read_json(path)
    if render.get("error"):
        return {
            "source": str(path),
            "checked": False,
            "preserved": False,
            "error": render["error"],
            "checks": [],
            "failures": [{"source": str(path), "error": render["error"]}],
        }
    checks = []
    for row in render.get("text_format_checks", []) or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item.setdefault("source", "render_docx")
        item.setdefault("checked", True)
        checks.append(item)
    for field in render.get("fields", []) or []:
        if not isinstance(field, dict):
            continue
        format_check = field.get("format_check")
        if not isinstance(format_check, dict) or not format_check.get("checked"):
            continue
        item = dict(format_check)
        item.update(
            {
                "source": "fill_by_spec",
                "key": field.get("key"),
                "action": field.get("action"),
                "part": field.get("part"),
            }
        )
        checks.append(item)
    for loop in render.get("table_loops", []) or []:
        if not isinstance(loop, dict):
            continue
        format_check = loop.get("format_check")
        if not isinstance(format_check, dict) or not format_check.get("checked"):
            continue
        item = dict(format_check)
        item.update(
            {
                "source": "fill_by_spec",
                "key": loop.get("key"),
                "action": "table_loop",
                "part": loop.get("part"),
            }
        )
        checks.append(item)
    expected_structure_changes = {"line_breaks_inserted", "bookmark_empty_range_inserted", "content_control_placeholder_removed", "hyperlink_inserted"}
    failures = [
        row
        for row in checks
        if row.get("checked")
        and row.get("preserved") is False
        and row.get("expected_structure_change") not in expected_structure_changes
    ]
    return {
        "source": str(path),
        "checked": bool(checks),
        "checked_count": len(checks),
        "preserved": not failures,
        "checks": checks,
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description="Verify DOCX template fidelity after rendering.")
    parser.add_argument("template")
    parser.add_argument("output")
    parser.add_argument("--report", required=True)
    parser.add_argument("--pdf-outdir")
    parser.add_argument("--compare-template-pdf", action="store_true")
    parser.add_argument("--visual-compare", action="store_true", help="Render template/output PDF pages and compare pixels. Requires --pdf-outdir and --compare-template-pdf.")
    parser.add_argument("--visual-page", type=int, default=1)
    parser.add_argument("--visual-pages", help="Pages to compare, such as '1', '1,3-5', or 'all'. Defaults to --visual-page.")
    parser.add_argument("--max-visual-pages", type=int, default=20)
    parser.add_argument("--visual-dpi", type=int, default=120)
    parser.add_argument("--max-visual-changed-ratio", type=float, default=0.08)
    parser.add_argument("--visual-ignore-regions", help="JSON file with visual diff ignore regions and optional presets.")
    parser.add_argument("--visual-ignore-preset", action="append", default=[], help="Ignore preset: header, footer, header-footer, page-number-footer.")
    parser.add_argument("--allow-changed-part", action="append", default=[], help="OOXML part that may change intentionally, such as word/styles.xml.")
    parser.add_argument("--allow-style-changes", action="store_true", help="Allow word/styles.xml to change when reference styles are intentionally merged.")
    parser.add_argument("--render-report", help="Render report with tracked text format checks from render_docx.py or fill_by_spec.py.")
    parser.add_argument("--strict-fonts", action="store_true")
    args = parser.parse_args()

    template = Path(args.template).expanduser()
    output = Path(args.output).expanduser()
    report = {
        "template": str(template),
        "output": str(output),
        "checks": [],
        "part_comparison": [],
        "content_controls": {},
        "tracked_text_format": {},
        "fonts": {},
        "pdf": {},
        "status": "unknown",
    }

    for label, path in [("template_zip", template), ("output_zip", output)]:
        ok, detail = zip_ok(path)
        report["checks"].append({"name": label, "passed": ok, "detail": detail})

    text, tokens = docx_text_and_tokens(output)
    report["checks"].append({"name": "unresolved_placeholders", "passed": not tokens, "detail": tokens})
    report["text_length"] = len(text)

    allowed_changed_parts = set(args.allow_changed_part)
    if args.allow_style_changes:
        allowed_changed_parts.add("word/styles.xml")
    report["allowed_changed_parts"] = sorted(allowed_changed_parts)
    part_rows = compare_parts(template, output, allowed_changed_parts=allowed_changed_parts)
    report["part_comparison"] = part_rows
    changed = [row for row in part_rows if row.get("comparison") == "hash" and not row["unchanged"] and not row.get("allowed_change")]
    text_structure_changed = [row for row in part_rows if row.get("comparison") == "text_structure" and not row.get("structure_unchanged")]
    report["checks"].append({"name": "invariant_parts_unchanged", "passed": not changed, "detail": [row["part"] for row in changed]})
    report["checks"].append({"name": "text_part_structure_preserved", "passed": not text_structure_changed, "detail": [row["part"] for row in text_structure_changed]})
    content_control_comparison = compare_content_controls(
        template,
        output,
        allow_repeating_section_changes=render_report_has_repeating_section_change(args.render_report),
        allow_placeholder_changes=render_report_has_content_control_placeholder_removed(args.render_report),
    )
    report["content_controls"] = content_control_comparison
    report["checks"].append(
        {
            "name": "content_controls_preserved",
            "passed": content_control_comparison["preserved"],
            "detail": {
                "template_count": content_control_comparison["template_count"],
                "output_count": content_control_comparison["output_count"],
                "missing_or_changed": content_control_comparison["missing_or_changed"],
                "extra_or_changed": content_control_comparison["extra_or_changed"],
            },
        }
    )
    if args.render_report:
        tracked_format = tracked_text_format_from_render_report(args.render_report)
        report["tracked_text_format"] = tracked_format
        report["checks"].append(
            {
                "name": "tracked_text_format_preserved",
                "passed": tracked_format.get("preserved") is True,
                "detail": {
                    "source": tracked_format.get("source"),
                    "checked": tracked_format.get("checked"),
                    "checked_count": tracked_format.get("checked_count", 0),
                    "failures": tracked_format.get("failures", []),
                    "error": tracked_format.get("error"),
                },
            }
        )

    required_fonts = parse_template_fonts(template)
    font_rows = check_fonts(required_fonts)
    missing = [row["font"] for row in font_rows if not row["available_likely"]]
    report["fonts"] = {"required": required_fonts, "results": font_rows, "missing": missing}
    report["checks"].append({"name": "template_fonts_available", "passed": not missing, "detail": missing})

    if args.pdf_outdir:
        converted = convert_pdf(output, args.pdf_outdir)
        report["pdf"]["output_conversion"] = converted
        report["checks"].append({"name": "output_pdf_conversion", "passed": converted.get("ok", False), "detail": converted})
        if converted.get("ok"):
            output_pdf_info = pdf_info(Path(converted["pdf"]))
            report["pdf"]["output_info"] = output_pdf_info
            embedded = output_pdf_info.get("all_fonts_embedded")
            report["checks"].append({"name": "output_pdf_fonts_embedded", "passed": embedded is True, "detail": embedded})
            coverage = pdf_font_coverage(required_fonts, output_pdf_info.get("font_names", []))
            missing_in_pdf = [row["font"] for row in coverage if not row["matched"]]
            report["pdf"]["template_font_coverage"] = coverage
            report["checks"].append({"name": "output_pdf_uses_template_fonts", "passed": not missing_in_pdf, "detail": missing_in_pdf})
        if args.compare_template_pdf:
            template_conversion = convert_pdf(template, Path(args.pdf_outdir) / "_template")
            report["pdf"]["template_conversion"] = template_conversion
            if template_conversion.get("ok") and converted.get("ok"):
                template_info = pdf_info(Path(template_conversion["pdf"]))
                output_info = report["pdf"].get("output_info", {})
                report["pdf"]["template_info"] = template_info
                if "pages" in template_info and "pages" in output_info:
                    report["checks"].append(
                        {
                            "name": "page_count_same_as_template",
                            "passed": template_info["pages"] == output_info["pages"],
                            "detail": {"template_pages": template_info["pages"], "output_pages": output_info["pages"]},
                        }
                    )
                if args.visual_compare:
                    visual_dir = Path(args.pdf_outdir) / "_visual"
                    ignore_config = load_visual_ignore_config(args.visual_ignore_regions, args.visual_ignore_preset)
                    visual_pages = parse_visual_pages(
                        args.visual_pages or str(args.visual_page),
                        template_pages=template_info.get("pages"),
                        output_pages=output_info.get("pages"),
                        max_pages=args.max_visual_pages,
                    )
                    visual = compare_pdf_pages_visual(
                        Path(template_conversion["pdf"]),
                        Path(converted["pdf"]),
                        visual_dir,
                        pages=visual_pages,
                        dpi=args.visual_dpi,
                        max_changed_ratio=args.max_visual_changed_ratio,
                        ignore_config=ignore_config,
                    )
                    report["pdf"]["visual_compare"] = visual
                    report["checks"].append(
                        {
                            "name": "visual_pages_same_dimensions",
                            "passed": visual.get("summary", {}).get("same_dimensions_all") is True,
                            "detail": visual.get("summary"),
                        }
                    )
                    report["checks"].append(
                        {
                            "name": "visual_pages_changed_ratio_within_limit",
                            "passed": not visual.get("summary", {}).get("pages_over_limit"),
                            "detail": visual.get("summary"),
                        }
                    )

    failed = [check for check in report["checks"] if not check["passed"]]
    if args.strict_fonts and missing:
        report["status"] = "failed"
    else:
        report["status"] = "passed" if not failed else "warning"

    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
