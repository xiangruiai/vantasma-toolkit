#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from zipfile import ZipFile

from request_field_update import copy_docx_with_settings, request_update_fields, SETTINGS_PART


DOCX_FILTER = "Office Open XML Text"
PDF_FILTER = "writer_pdf_Export"
REFRESH_BACKENDS = ["auto", "request-only", "libreoffice-cli", "libreoffice-uno", "word-applescript"]
CORE_TEMPLATE_PARTS = {
    "[Content_Types].xml",
    "word/fontTable.xml",
    "word/numbering.xml",
    "word/settings.xml",
    "word/styles.xml",
    "word/stylesWithEffects.xml",
    "word/theme/theme1.xml",
}


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_command(command, timeout):
    cp = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return {
        "command": [str(part) for part in command],
        "returncode": cp.returncode,
        "stdout": cp.stdout[-4000:],
        "stderr": cp.stderr[-4000:],
        "ok": cp.returncode == 0,
    }


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def is_text_part(part):
    name = Path(part).name
    return (
        part == "word/document.xml"
        or (part.startswith("word/header") and name.endswith(".xml"))
        or (part.startswith("word/footer") and name.endswith(".xml"))
        or part in {"word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"}
    )


def docx_part_hashes(path):
    with ZipFile(path, "r") as archive:
        return {name: sha256_bytes(archive.read(name)) for name in archive.namelist() if not name.endswith("/")}


def compare_docx_packages(before_docx, after_docx):
    before_docx = Path(before_docx)
    after_docx = Path(after_docx)
    result = {
        "status": "unknown",
        "before": str(before_docx),
        "after": str(after_docx),
        "changed_part_count": 0,
        "added_part_count": 0,
        "removed_part_count": 0,
        "changed_parts": [],
        "added_parts": [],
        "removed_parts": [],
        "core_risk_parts_changed": [],
        "text_parts_changed": [],
        "relationship_parts_changed": [],
        "media_parts_changed": [],
        "notes": [],
    }
    if not before_docx.exists() or not after_docx.exists():
        result["status"] = "not_available"
        result["notes"].append("Before or after DOCX is missing; package drift could not be measured.")
        return result
    try:
        before = docx_part_hashes(before_docx)
        after = docx_part_hashes(after_docx)
    except Exception as exc:
        result["status"] = "failed"
        result["notes"].append(str(exc))
        return result
    before_parts = set(before)
    after_parts = set(after)
    changed = sorted(part for part in before_parts & after_parts if before[part] != after[part])
    added = sorted(after_parts - before_parts)
    removed = sorted(before_parts - after_parts)
    result.update(
        {
            "status": "passed",
            "changed_part_count": len(changed),
            "added_part_count": len(added),
            "removed_part_count": len(removed),
            "changed_parts": changed,
            "added_parts": added,
            "removed_parts": removed,
            "core_risk_parts_changed": sorted((set(changed) | set(added) | set(removed)) & CORE_TEMPLATE_PARTS),
            "text_parts_changed": [part for part in changed if is_text_part(part)],
            "relationship_parts_changed": [part for part in changed if part.endswith(".rels")],
            "media_parts_changed": [part for part in sorted(set(changed) | set(added) | set(removed)) if part.startswith("word/media/")],
        }
    )
    if result["core_risk_parts_changed"]:
        result["notes"].append("External engine changed core template parts; inspect field-refreshed verification before delivery.")
    if result["text_parts_changed"]:
        result["notes"].append("External engine changed text-bearing parts; confirm changes are limited to expected field results.")
    return result


def find_soffice(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_path = os.environ.get("SOFFICE")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    if platform.system() == "Darwin":
        candidates.extend(
            [
                Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
                Path("/Applications/OpenOffice.app/Contents/MacOS/soffice"),
            ]
        )
    path_hit = shutil.which("soffice")
    if path_hit:
        candidates.append(Path(path_hit))
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    return None


def find_libreoffice_python(soffice):
    candidates = []
    if soffice:
        soffice_path = Path(soffice)
        candidates.extend(
            [
                soffice_path.parent / "python",
                soffice_path.parent.parent / "Resources" / "python",
                soffice_path.parent.parent / "program" / "python",
            ]
        )
    if platform.system() == "Darwin":
        candidates.extend(
            [
                Path("/Applications/LibreOffice.app/Contents/Resources/python"),
                Path("/Applications/LibreOffice.app/Contents/MacOS/python"),
            ]
        )
    candidates.append(Path(sys.executable))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def file_url(path):
    return Path(path).resolve().as_uri()


def converted_file(outdir, source_path, suffix):
    expected = Path(outdir) / f"{Path(source_path).stem}{suffix}"
    if expected.exists():
        return expected
    matches = sorted(Path(outdir).glob(f"{Path(source_path).stem}*{suffix}"))
    return matches[0] if matches else expected


def apply_update_fields_flag(input_docx, output_docx):
    from zipfile import ZipFile

    with ZipFile(input_docx, "r") as archive:
        if SETTINGS_PART not in archive.namelist():
            raise ValueError(f"{SETTINGS_PART} is missing; cannot request field updates without a settings part.")
        settings = archive.read(SETTINGS_PART)
    updated_settings, details = request_update_fields(settings, value="true")
    copy_docx_with_settings(Path(input_docx), Path(output_docx), updated_settings)
    return {
        "status": "passed",
        "settings_part": SETTINGS_PART,
        "requested_value": "true",
        "changed_parts": [SETTINGS_PART] if details.get("changed") else [],
        **details,
    }


def libreoffice_uno_script():
    return r'''
import argparse
import json
import sys
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue

DOCX_FILTER = "Office Open XML Text"
PDF_FILTER = "writer_pdf_Export"


def prop(name, value):
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def connect(port, timeout):
    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local_ctx)
    end = time.time() + timeout
    last_error = None
    while time.time() < end:
        try:
            return resolver.resolve(f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext")
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Could not connect to LibreOffice UNO listener: {last_error}")


def file_url(path):
    return Path(path).resolve().as_uri()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pdf-output")
    parser.add_argument("--connect-timeout", type=float, default=20)
    args = parser.parse_args()

    ctx = connect(args.port, args.connect_timeout)
    service = ctx.ServiceManager
    desktop = service.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    load_props = (prop("Hidden", True), prop("UpdateDocMode", 3))
    doc = desktop.loadComponentFromURL(file_url(args.input), "_blank", 0, load_props)
    if doc is None:
        raise RuntimeError("LibreOffice could not open the DOCX.")

    result = {
        "document_indexes_updated": None,
        "text_fields_refreshed": None,
        "links_updated": None,
        "docx_saved": False,
        "pdf_saved": False,
    }
    try:
        try:
            indexes = doc.getDocumentIndexes()
            for index in range(indexes.getCount()):
                indexes.getByIndex(index).update()
            result["document_indexes_updated"] = indexes.getCount()
        except Exception as exc:
            result["document_indexes_error"] = str(exc)
        try:
            fields = doc.getTextFields()
            fields.refresh()
            result["text_fields_refreshed"] = True
        except Exception as exc:
            result["text_fields_error"] = str(exc)
        try:
            doc.updateLinks()
            result["links_updated"] = True
        except Exception as exc:
            result["links_error"] = str(exc)
        doc.storeAsURL(file_url(args.output), (prop("FilterName", DOCX_FILTER),))
        result["docx_saved"] = True
        if args.pdf_output:
            doc.storeToURL(file_url(args.pdf_output), (prop("FilterName", PDF_FILTER),))
            result["pdf_saved"] = True
    finally:
        doc.close(True)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'''


def refresh_with_libreoffice(input_docx, output_docx, pdf_output, timeout, soffice=None):
    soffice = find_soffice(soffice)
    if not soffice:
        return {"ok": False, "backend": "libreoffice-uno", "error": "soffice not found"}
    port = free_port()
    profile_dir = Path(tempfile.mkdtemp(prefix="template-fidelity-lo-profile-"))
    script_path = Path(tempfile.mkdtemp(prefix="template-fidelity-lo-script-")) / "refresh_uno.py"
    script_path.write_text(libreoffice_uno_script(), encoding="utf-8")
    accept = f"socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    process = subprocess.Popen(
        [
            soffice,
            "--headless",
            "--invisible",
            "--norestore",
            "--nodefault",
            f"-env:UserInstallation={profile_dir.as_uri()}",
            f"--accept={accept}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    python_bin = find_libreoffice_python(soffice)
    try:
        python_probe = run_command([python_bin, "--version"], 15)
    except Exception as exc:
        python_probe = {"ok": False, "error": str(exc), "command": [python_bin, "--version"]}
    if not python_probe.get("ok"):
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
        return {
            "ok": False,
            "backend": "libreoffice-uno",
            "soffice": soffice,
            "python": python_bin,
            "error": "LibreOffice Python runner failed preflight; UNO refresh cannot run in this environment.",
            "python_probe": python_probe,
            "listener_stdout": stdout[-2000:],
            "listener_stderr": stderr[-2000:],
            "docx_saved": Path(output_docx).exists(),
            "pdf_saved": bool(pdf_output and Path(pdf_output).exists()),
        }
    command = [
        python_bin,
        str(script_path),
        "--port",
        str(port),
        "--input",
        str(input_docx),
        "--output",
        str(output_docx),
    ]
    if pdf_output:
        command.extend(["--pdf-output", str(pdf_output)])
    try:
        step = run_command(command, timeout)
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
    result = {
        "ok": step["ok"] and Path(output_docx).exists(),
        "backend": "libreoffice-uno",
        "soffice": soffice,
        "python": python_bin,
        "python_probe": python_probe,
        "command": step,
        "listener_stdout": stdout[-2000:],
        "listener_stderr": stderr[-2000:],
        "docx_saved": Path(output_docx).exists(),
        "pdf_saved": bool(pdf_output and Path(pdf_output).exists()),
    }
    try:
        result["uno_result"] = json.loads(step.get("stdout") or "{}")
    except json.JSONDecodeError:
        pass
    return result


def refresh_with_libreoffice_cli(input_docx, output_docx, pdf_output, timeout, soffice=None):
    soffice = find_soffice(soffice)
    if not soffice:
        return {"ok": False, "backend": "libreoffice-cli", "error": "soffice not found"}
    profile_dir = Path(tempfile.mkdtemp(prefix="template-fidelity-lo-cli-profile-"))
    docx_dir = Path(tempfile.mkdtemp(prefix="template-fidelity-lo-cli-docx-"))
    pdf_dir = Path(tempfile.mkdtemp(prefix="template-fidelity-lo-cli-pdf-")) if pdf_output else None
    profile_arg = f"-env:UserInstallation={profile_dir.as_uri()}"
    docx_command = [
        soffice,
        "--headless",
        "--norestore",
        "--nodefault",
        profile_arg,
        "--convert-to",
        "docx",
        "--outdir",
        str(docx_dir),
        str(input_docx),
    ]
    result = {
        "ok": False,
        "backend": "libreoffice-cli",
        "soffice": soffice,
        "profile_dir": str(profile_dir),
        "docx_saved": False,
        "pdf_saved": False,
    }
    try:
        docx_step = run_command(docx_command, timeout)
        converted_docx = converted_file(docx_dir, input_docx, ".docx")
        result["docx_command"] = docx_step
        result["converted_docx"] = str(converted_docx)
        if docx_step.get("ok") and converted_docx.exists():
            shutil.copy2(converted_docx, output_docx)
            result["docx_saved"] = Path(output_docx).exists()
        if result["docx_saved"] and pdf_output:
            pdf_command = [
                soffice,
                "--headless",
                "--norestore",
                "--nodefault",
                profile_arg,
                "--convert-to",
                "pdf",
                "--outdir",
                str(pdf_dir),
                str(output_docx),
            ]
            pdf_step = run_command(pdf_command, timeout)
            converted_pdf = converted_file(pdf_dir, output_docx, ".pdf")
            result["pdf_command"] = pdf_step
            result["converted_pdf"] = str(converted_pdf)
            if pdf_step.get("ok") and converted_pdf.exists():
                shutil.copy2(converted_pdf, pdf_output)
                result["pdf_saved"] = Path(pdf_output).exists()
        result["ok"] = bool(result["docx_saved"])
        if not result["ok"]:
            result["error"] = "LibreOffice CLI conversion did not produce a refreshed DOCX."
        return result
    finally:
        if os.environ.get("TEMPLATE_FIDELITY_KEEP_LIBREOFFICE_CLI_WORKDIRS") != "1":
            shutil.rmtree(profile_dir, ignore_errors=True)
            shutil.rmtree(docx_dir, ignore_errors=True)
            if pdf_dir:
                shutil.rmtree(pdf_dir, ignore_errors=True)


def applescript_quote(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def word_applescript():
    return r'''
on run argv
  set inputPath to item 1 of argv
  set outputPath to item 2 of argv
  set pdfPath to ""
  if (count of argv) > 2 then set pdfPath to item 3 of argv
  tell application "Microsoft Word"
    activate
    set visible to false
    open POSIX file inputPath
    set docRef to active document
    do Visual Basic "On Error Resume Next" & return & ¬
      "Dim story As Range" & return & ¬
      "For Each story In ActiveDocument.StoryRanges" & return & ¬
      "  story.Fields.Update" & return & ¬
      "  Do While Not (story.NextStoryRange Is Nothing)" & return & ¬
      "    Set story = story.NextStoryRange" & return & ¬
      "    story.Fields.Update" & return & ¬
      "  Loop" & return & ¬
      "Next story" & return & ¬
      "Dim toc As TableOfContents" & return & ¬
      "For Each toc In ActiveDocument.TablesOfContents" & return & ¬
      "  toc.Update" & return & ¬
      "Next toc" & return & ¬
      "Dim tof As TableOfFigures" & return & ¬
      "For Each tof In ActiveDocument.TablesOfFigures" & return & ¬
      "  tof.Update" & return & ¬
      "Next tof"
    save as docRef file name outputPath file format format XML document
    if pdfPath is not "" then save as docRef file name pdfPath file format format PDF
    close docRef saving no
  end tell
end run
'''


def refresh_with_word(input_docx, output_docx, pdf_output, timeout):
    if platform.system() != "Darwin":
        return {"ok": False, "backend": "word-applescript", "error": "Microsoft Word AppleScript backend is macOS-only."}
    if not Path("/Applications/Microsoft Word.app").exists():
        return {"ok": False, "backend": "word-applescript", "error": "Microsoft Word.app not found in /Applications."}
    osascript = shutil.which("osascript")
    if not osascript:
        return {"ok": False, "backend": "word-applescript", "error": "osascript not found."}
    script_path = Path(tempfile.mkdtemp(prefix="template-fidelity-word-script-")) / "refresh_word.applescript"
    script_path.write_text(word_applescript(), encoding="utf-8")
    command = [osascript, str(script_path), str(input_docx), str(output_docx)]
    if pdf_output:
        command.append(str(pdf_output))
    step = run_command(command, timeout)
    return {
        "ok": step["ok"] and Path(output_docx).exists(),
        "backend": "word-applescript",
        "command": step,
        "docx_saved": Path(output_docx).exists(),
        "pdf_saved": bool(pdf_output and Path(pdf_output).exists()),
    }


def choose_backends(backend):
    if backend == "auto":
        if platform.system() == "Darwin":
            return ["word-applescript", "libreoffice-cli", "libreoffice-uno", "request-only"]
        return ["libreoffice-cli", "libreoffice-uno", "request-only"]
    return [backend]


def main():
    parser = argparse.ArgumentParser(description="Refresh or request refresh for Word DOCX fields, with an audit report.")
    parser.add_argument("input_docx")
    parser.add_argument("--output", required=True, help="DOCX output path for the refreshed/requested document.")
    parser.add_argument("--pdf-output", help="Optional PDF output path when the selected backend supports export.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--backend", choices=REFRESH_BACKENDS, default="auto")
    parser.add_argument("--soffice", help="Optional LibreOffice soffice executable path.")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    input_docx = Path(args.input_docx).expanduser()
    output_docx = Path(args.output).expanduser()
    pdf_output = Path(args.pdf_output).expanduser() if args.pdf_output else None
    report = {
        "status": "unknown",
        "input": str(input_docx),
        "output": str(output_docx),
        "pdf_output": str(pdf_output) if pdf_output else None,
        "requested_backend": args.backend,
        "selected_backend": None,
        "request_docx": None,
        "request_update_fields": {},
        "attempts": [],
        "actual_field_results_refresh": False,
        "post_refresh_drift": {},
        "limitations": [],
        "errors": [],
    }

    backends = choose_backends(args.backend)
    staging_docx = None
    request_docx = output_docx
    if any(backend != "request-only" for backend in backends):
        handle = tempfile.NamedTemporaryFile(prefix="template-fidelity-field-request-", suffix=".docx", dir=str(output_docx.parent), delete=False)
        staging_docx = Path(handle.name)
        handle.close()
        request_docx = staging_docx
    report["request_docx"] = str(request_docx)

    try:
        output_docx.parent.mkdir(parents=True, exist_ok=True)
        if pdf_output:
            pdf_output.parent.mkdir(parents=True, exist_ok=True)
        report["request_update_fields"] = apply_update_fields_flag(input_docx, request_docx)
    except Exception as exc:
        report["status"] = "failed"
        report["errors"].append(str(exc))
        write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    for backend in backends:
        if backend == "request-only":
            if request_docx.resolve() != output_docx.resolve():
                shutil.copy2(request_docx, output_docx)
            report["selected_backend"] = "request-only"
            report["status"] = "passed" if args.backend == "request-only" else "warning"
            report["limitations"].append("Only w:updateFields=true was written. Field results were not recalculated in this run.")
            break
        if backend == "libreoffice-cli":
            attempt = refresh_with_libreoffice_cli(request_docx, output_docx, pdf_output, args.timeout, soffice=args.soffice)
        elif backend == "libreoffice-uno":
            attempt = refresh_with_libreoffice(request_docx, output_docx, pdf_output, args.timeout, soffice=args.soffice)
        elif backend == "word-applescript":
            attempt = refresh_with_word(request_docx, output_docx, pdf_output, args.timeout)
        else:
            attempt = {"ok": False, "backend": backend, "error": "unknown backend"}
        report["attempts"].append(attempt)
        if attempt.get("ok"):
            report["selected_backend"] = attempt.get("backend")
            report["actual_field_results_refresh"] = True
            report["status"] = "passed"
            break

    if report["status"] == "unknown":
        report["status"] = "failed"
        report["errors"].append("No field refresh backend succeeded.")

    if output_docx.exists():
        report["post_refresh_drift"] = compare_docx_packages(request_docx, output_docx)

    if report["actual_field_results_refresh"]:
        report["limitations"].append("Field refresh was attempted through an external document engine; verify the produced DOCX/PDF visually before final delivery.")
        drift = report.get("post_refresh_drift") or {}
        if drift.get("core_risk_parts_changed"):
            report["limitations"].append("External document engine changed core template parts; the refreshed sidecar must pass its own fidelity verification before delivery.")
    else:
        report["limitations"].append("For final acceptance, open the DOCX in Word or a compatible processor, update fields, then rerun PDF/visual verification.")
    if staging_docx and staging_docx.exists() and os.environ.get("TEMPLATE_FIDELITY_KEEP_REFRESH_STAGING") != "1":
        try:
            staging_docx.unlink()
            report["request_docx_retained"] = False
        except OSError as exc:
            report["request_docx_retained"] = True
            report["errors"].append(f"Could not delete staging request DOCX: {exc}")
    elif staging_docx:
        report["request_docx_retained"] = True

    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
