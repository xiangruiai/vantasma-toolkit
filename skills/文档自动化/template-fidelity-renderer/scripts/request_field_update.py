#!/usr/bin/env python3
import argparse
import json
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile
from xml.etree import ElementTree as ET


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SETTINGS_PART = "word/settings.xml"


def detect_word_prefix(xml_text):
    match = re.search(r'xmlns:([A-Za-z_][\w.-]*)="' + re.escape(WORD_NS) + r'"', xml_text)
    return match.group(1) if match else "w"


def update_tag_value(tag_text, prefix, value):
    val_pattern = re.compile(rf'({re.escape(prefix)}:val\s*=\s*)(["\'])(.*?)(\2)', re.DOTALL)
    previous = None
    match = val_pattern.search(tag_text)
    if match:
        previous = match.group(3)
        tag_text = tag_text[: match.start(3)] + value + tag_text[match.end(3) :]
        return tag_text, previous
    close_index = tag_text.rfind("/>")
    if close_index == -1:
        close_index = tag_text.find(">")
    if close_index == -1:
        return tag_text, previous
    tag_text = tag_text[:close_index] + f' {prefix}:val="{value}"' + tag_text[close_index:]
    return tag_text, previous


def request_update_fields(settings_bytes, value="true"):
    text = settings_bytes.decode("utf-8", errors="strict")
    prefix = detect_word_prefix(text)
    pattern = re.compile(rf"<{re.escape(prefix)}:updateFields\b[^>]*(?:/>|>.*?</{re.escape(prefix)}:updateFields>)", re.DOTALL)
    previous_values = []
    changed_count = 0

    def replace(match):
        nonlocal changed_count
        replacement, previous = update_tag_value(match.group(0), prefix, value)
        previous_values.append(previous)
        if replacement != match.group(0):
            changed_count += 1
        return replacement

    if pattern.search(text):
        updated = pattern.sub(replace, text)
        created = False
    else:
        closing = f"</{prefix}:settings>"
        insertion = f'<{prefix}:updateFields {prefix}:val="{value}"/>'
        if closing not in text:
            raise ValueError(f"Could not find {closing} in {SETTINGS_PART}.")
        updated = text.replace(closing, insertion + closing, 1)
        previous_values = []
        changed_count = 1
        created = True

    ET.fromstring(updated.encode("utf-8"))
    return updated.encode("utf-8"), {
        "created": created,
        "updated_existing": not created,
        "previous_values": previous_values,
        "update_field_elements_changed": changed_count,
        "changed": updated.encode("utf-8") != settings_bytes,
        "word_namespace_prefix": prefix,
    }


def copy_docx_with_settings(input_docx, output_docx, new_settings):
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    same_path = input_docx.resolve() == output_docx.resolve()
    target = output_docx
    tmp_path = None
    if same_path:
        handle = tempfile.NamedTemporaryFile(prefix=output_docx.stem + ".", suffix=".docx", dir=str(output_docx.parent), delete=False)
        tmp_path = Path(handle.name)
        handle.close()
        target = tmp_path

    try:
        with ZipFile(input_docx, "r") as src, ZipFile(target, "w", ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = new_settings if info.filename == SETTINGS_PART else src.read(info.filename)
                dst.writestr(info, data)
        if same_path:
            tmp_path.replace(output_docx)
    except Exception:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
        raise


def write_report(path, report):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Request Word to update DOCX fields on open by setting w:updateFields=true.")
    parser.add_argument("input_docx")
    parser.add_argument("--output", help="Output DOCX. Defaults to in-place update.")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    input_docx = Path(args.input_docx).expanduser()
    output_docx = Path(args.output).expanduser() if args.output else input_docx
    report = {
        "status": "unknown",
        "input": str(input_docx),
        "output": str(output_docx),
        "settings_part": SETTINGS_PART,
        "requested_value": "true",
        "changed_parts": [],
        "limitations": [
            "This sets Word's updateFields request flag. It does not calculate field results by itself.",
            "Open the DOCX in Word or a compatible processor, accept/update fields if prompted, then run PDF or visual verification for final acceptance.",
        ],
        "errors": [],
    }

    try:
        with ZipFile(input_docx, "r") as archive:
            names = set(archive.namelist())
            if SETTINGS_PART not in names:
                raise ValueError(f"{SETTINGS_PART} is missing; cannot request field updates without a settings part.")
            settings_bytes = archive.read(SETTINGS_PART)
        new_settings, details = request_update_fields(settings_bytes, value="true")
        report.update(details)
        if details["changed"]:
            report["changed_parts"].append(SETTINGS_PART)
        if details["changed"] or input_docx.resolve() != output_docx.resolve():
            copy_docx_with_settings(input_docx, output_docx, new_settings)
        report["status"] = "passed"
    except (BadZipFile, OSError, ValueError, ET.ParseError, UnicodeDecodeError) as exc:
        report["status"] = "failed"
        report["errors"].append(str(exc))
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
