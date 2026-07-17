#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def safe_name(value):
    text = str(value or "artifact")
    cleaned = []
    for char in text:
        if char.isalnum() or char in {"-", "_", "."}:
            cleaned.append(char)
        else:
            cleaned.append("_")
    name = "".join(cleaned).strip("._")
    return name or "artifact"


def add_artifact(candidates, key, path):
    if not path:
        return
    artifact_path = Path(path).expanduser()
    candidates.append({"key": key, "path": str(artifact_path)})


def collect_artifacts(summary):
    candidates = []
    reports = summary.get("reports") if isinstance(summary.get("reports"), dict) else {}
    add_artifact(candidates, "output_docx", summary.get("output"))
    for key, value in reports.items():
        add_artifact(candidates, f"report_{key}", value)
    pdf = summary.get("pdf") if isinstance(summary.get("pdf"), dict) else {}
    add_artifact(candidates, "output_pdf", pdf.get("output_pdf"))

    seen = set()
    included = []
    missing = []
    for row in candidates:
        path = Path(row["path"]).expanduser()
        identity = str(path.resolve()) if path.exists() else str(path)
        if identity in seen:
            continue
        seen.add(identity)
        target = included if path.exists() and path.is_file() else missing
        target.append({"key": row["key"], "path": str(path)})
    return included, missing


def artifact_arcname(row, used):
    path = Path(row["path"])
    stem = safe_name(row["key"])
    filename = safe_name(path.name)
    candidate = f"artifacts/{stem}__{filename}"
    counter = 2
    while candidate in used:
        candidate = f"artifacts/{stem}-{counter}__{filename}"
        counter += 1
    used.add(candidate)
    return candidate


def build_manifest(summary, included, missing, source):
    delivery_gate = summary.get("delivery_gate") if isinstance(summary.get("delivery_gate"), dict) else {}
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_pipeline_json": str(Path(source).expanduser()),
        "template": summary.get("template"),
        "output": summary.get("output"),
        "pipeline_status": summary.get("status"),
        "delivery_gate": {
            "status": delivery_gate.get("status"),
            "decision": delivery_gate.get("decision"),
            "blocker_count": len(delivery_gate.get("blockers") or []),
            "warning_count": len(delivery_gate.get("warnings") or []),
            "blockers": delivery_gate.get("blockers") or [],
            "warnings": delivery_gate.get("warnings") or [],
        },
        "included_artifacts": included,
        "missing_artifacts": missing,
    }


def write_package(summary, source, output_zip, include_blocked=False, manifest_output=None):
    delivery_gate = summary.get("delivery_gate") if isinstance(summary.get("delivery_gate"), dict) else {}
    gate_status = delivery_gate.get("status")
    included, missing = collect_artifacts(summary)
    manifest = build_manifest(summary, included, missing, source)
    if gate_status == "blocked" and not include_blocked:
        return {
            "status": "blocked",
            "error": "delivery_gate_blocked",
            "message": "Delivery gate is blocked. Re-run with --include-blocked to create an evidence package anyway.",
            "manifest": manifest,
        }

    output_zip = Path(output_zip).expanduser()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    used = set()
    packaged = []
    with ZipFile(output_zip, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("README.txt", "Template Fidelity Renderer delivery package. See manifest.json and artifacts/.\n")
        for row in included:
            arcname = artifact_arcname(row, used)
            archive.write(Path(row["path"]), arcname)
            packaged.append({**row, "archive_path": arcname})

    manifest["packaged_artifacts"] = packaged
    if manifest_output:
        Path(manifest_output).expanduser().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "packaged",
        "package": str(output_zip),
        "delivery_gate_status": gate_status,
        "included_count": len(included),
        "missing_count": len(missing),
        "manifest": manifest,
    }


def main():
    parser = argparse.ArgumentParser(description="Create a delivery ZIP package from a template-fidelity pipeline report.")
    parser.add_argument("pipeline_json")
    parser.add_argument("--output", required=True, help="Output ZIP path.")
    parser.add_argument("--manifest-output", help="Write manifest JSON next to the ZIP or elsewhere.")
    parser.add_argument("--include-blocked", action="store_true", help="Package artifacts even when delivery_gate.status is blocked.")
    args = parser.parse_args()

    summary = read_json(args.pipeline_json)
    if summary.get("error"):
        result = {"status": "failed", "error": "pipeline_json_unreadable", "detail": summary.get("error")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    result = write_package(
        summary,
        args.pipeline_json,
        args.output,
        include_blocked=args.include_blocked,
        manifest_output=args.manifest_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "packaged":
        return 0
    if result["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
