#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from check_delivery import evaluate_delivery, render_delivery_markdown


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def markdown_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def markdown_list(items, empty="- None"):
    if not items:
        return [empty]
    lines = []
    for item in items:
        lines.append(f"- {markdown_value(item)}")
    return lines


def failed_check_lines(checks):
    if not checks:
        return ["- None"]
    lines = []
    for check in checks:
        name = check.get("name", "unknown_check") if isinstance(check, dict) else "unknown_check"
        detail = check.get("detail") if isinstance(check, dict) else check
        detail_text = markdown_value(detail)
        if len(detail_text) > 500:
            detail_text = detail_text[:497] + "..."
        lines.append(f"- {name}: {detail_text}")
    return lines


def render_pipeline_markdown(summary):
    reports = summary.get("reports") or {}
    field_refresh = summary.get("field_refresh_status") or {}
    field_update = summary.get("field_update_status") or {}
    drift = field_refresh.get("post_refresh_drift") or {}
    delivery_gate = summary.get("delivery_gate") or {}
    steps = summary.get("steps") or []
    failed_steps = [step for step in steps if not step.get("ok")]
    status = summary.get("status", "unknown")
    decision = {
        "passed": "Ready for delivery if the requested scope matches this pipeline run.",
        "warning": "Review the risks below before delivery.",
        "failed": "Do not deliver until failed steps or checks are fixed.",
    }.get(status, "Review this report before delivery.")

    lines = [
        "# Template Fidelity Pipeline Report",
        "",
        f"- Status: {status}",
        f"- Decision: {decision}",
        f"- Template: {markdown_value(summary.get('template'))}",
        f"- Output: {markdown_value(summary.get('output'))}",
        "",
        "## Artifacts",
    ]
    artifact_rows = [
        ("Analysis", reports.get("analysis")),
        ("Font plan", reports.get("font_plan")),
        ("Render report", reports.get("render")),
        ("Verify report", reports.get("verify")),
        ("Pipeline JSON", reports.get("summary")),
        ("Draft markdown", reports.get("draft_markdown")),
        ("Field update", reports.get("field_update")),
        ("Field refresh", reports.get("field_refresh")),
        ("Field-refreshed DOCX", reports.get("field_refreshed_output")),
        ("Field-refreshed PDF", reports.get("field_refreshed_pdf")),
        ("Field-refreshed verify", reports.get("field_refreshed_verify")),
    ]
    for label, path in artifact_rows:
        if path:
            lines.append(f"- {label}: {path}")

    lines.extend(["", "## Risks"])
    lines.append(f"- Missing fonts: {markdown_value(summary.get('missing_fonts') or [])}")
    lines.append(f"- Failed steps: {len(failed_steps)}")
    for step in failed_steps:
        lines.append(f"  - {step.get('name')}: returncode={step.get('returncode')}")
    lines.append(f"- Verification status: {markdown_value(summary.get('verify_status'))}")
    lines.extend(failed_check_lines(summary.get("verify_failed_checks") or []))

    if delivery_gate:
        lines.extend(
            [
                "",
                "## Delivery Gate",
                f"- Status: {markdown_value(delivery_gate.get('status'))}",
                f"- Decision: {markdown_value(delivery_gate.get('decision'))}",
                f"- Blockers: {len(delivery_gate.get('blockers') or [])}",
                f"- Warnings: {len(delivery_gate.get('warnings') or [])}",
            ]
        )

    if field_update:
        lines.extend(
            [
                "",
                "## Field Update Request",
                f"- Requested: {markdown_value(field_update.get('requested'))}",
                f"- Status: {markdown_value(field_update.get('status'))}",
                f"- Changed parts: {markdown_value(field_update.get('changed_parts') or [])}",
                f"- Limitations: {markdown_value(field_update.get('limitations') or [])}",
            ]
        )

    if field_refresh:
        lines.extend(
            [
                "",
                "## Field Refresh Sidecar",
                f"- Requested: {markdown_value(field_refresh.get('requested'))}",
                f"- Status: {markdown_value(field_refresh.get('status'))}",
                f"- Selected backend: {markdown_value(field_refresh.get('selected_backend'))}",
                f"- Actual field results refresh: {markdown_value(field_refresh.get('actual_field_results_refresh'))}",
                f"- Sidecar verify status: {markdown_value(field_refresh.get('verify_status'))}",
                "- Sidecar failed checks:",
            ]
        )
        lines.extend(failed_check_lines(field_refresh.get("verify_failed_checks") or []))
        if drift:
            lines.extend(
                [
                    "",
                    "## Post-Refresh Package Drift",
                    f"- Drift status: {markdown_value(drift.get('status'))}",
                    f"- Changed parts: {markdown_value(drift.get('changed_part_count'))}",
                    f"- Added parts: {markdown_value(drift.get('added_part_count'))}",
                    f"- Removed parts: {markdown_value(drift.get('removed_part_count'))}",
                    f"- Core risk parts changed: {markdown_value(drift.get('core_risk_parts_changed') or [])}",
                    f"- Text parts changed count: {markdown_value(drift.get('text_parts_changed_count'))}",
                    f"- Relationship parts changed count: {markdown_value(drift.get('relationship_parts_changed_count'))}",
                    f"- Media parts changed: {markdown_value(drift.get('media_parts_changed') or [])}",
                    "- Notes:",
                ]
            )
            lines.extend(markdown_list(drift.get("notes") or []))

    draft_status = summary.get("draft_status")
    if draft_status:
        lines.extend(
            [
                "",
                "## Draft Spec",
                f"- Field count: {markdown_value(draft_status.get('field_count'))}",
                f"- Literal replacement count: {markdown_value(draft_status.get('literal_replacement_count'))}",
                f"- Warnings count: {markdown_value(draft_status.get('warnings_count'))}",
                "- Warnings:",
            ]
        )
        lines.extend(markdown_list(draft_status.get("warnings") or []))

    lines.extend(["", "## Pipeline Steps"])
    for step in steps:
        outcome = "ok" if step.get("ok") else "failed"
        lines.append(f"- {step.get('name')}: {outcome} (returncode={step.get('returncode')})")
    lines.append("")
    return "\n".join(lines)


def run_step(name, command, allow_warning=False):
    cp = subprocess.run(command, capture_output=True, text=True)
    ok = cp.returncode == 0 or allow_warning
    return {
        "name": name,
        "ok": ok,
        "returncode": cp.returncode,
        "command": command,
        "stdout": cp.stdout[-4000:],
        "stderr": cp.stderr[-4000:],
    }


def resolve_template_from_spec(spec_path):
    spec = read_json(spec_path)
    source = spec.get("template_source")
    if not source:
        return None
    template = Path(source).expanduser()
    if not template.is_absolute():
        template = (Path(spec_path).resolve().parent / template).resolve()
    return template


def render_merged_reference_styles(render_report):
    render = read_json(render_report)
    fields = render.get("fields", []) or []
    if isinstance(fields, dict):
        fields = fields.values()
    for field in fields:
        if not isinstance(field, dict):
            continue
        styles = field.get("reference_styles") or {}
        if styles.get("merged_style_ids"):
            return True
    return False


def render_imported_reference_numbering(render_report):
    render = read_json(render_report)
    fields = render.get("fields", []) or []
    if isinstance(fields, dict):
        fields = fields.values()
    for field in fields:
        if not isinstance(field, dict):
            continue
        numbering = field.get("reference_numbering") or {}
        if numbering.get("imported_num_ids"):
            return True
    return False


def field_update_changed_settings(field_update_report):
    report = read_json(field_update_report)
    return report.get("status") == "passed" and "word/settings.xml" in (report.get("changed_parts") or [])


def field_data_from_raw(raw_data):
    if isinstance(raw_data, dict) and isinstance(raw_data.get("fields"), dict):
        return raw_data["fields"]
    if isinstance(raw_data, dict):
        return raw_data
    return {}


def matching_content_control_field(control, field_data):
    if not isinstance(field_data, dict):
        return None
    binding = control.get("binding") or {}
    for key in [
        control.get("tag"),
        control.get("alias"),
        (control.get("spec_candidate") or {}).get("key"),
        binding.get("xpath"),
    ]:
        if key and key in field_data:
            return key
    return None


def build_auto_content_control_spec(template, analysis, raw_data):
    field_data = field_data_from_raw(raw_data)
    fields = []
    seen_keys = set()
    for control in analysis.get("content_controls", []) or []:
        candidate = control.get("spec_candidate") or {}
        locator = dict(candidate.get("locator") or {})
        if not (locator.get("tag") or locator.get("alias") or locator.get("binding")):
            continue
        key = matching_content_control_field(control, field_data)
        if not key or key in seen_keys:
            continue
        field = {
            "key": key,
            "locator_type": "content_control",
            "locator": locator,
            "required": True,
        }
        if candidate.get("replacement_mode"):
            field["replacement_mode"] = candidate["replacement_mode"]
        if candidate.get("options"):
            field["options"] = candidate["options"]
        if candidate.get("date"):
            field["date"] = candidate["date"]
        if candidate.get("text_control"):
            field["text_control"] = candidate["text_control"]
        if candidate.get("lock"):
            field["lock"] = candidate["lock"]
        if candidate.get("showing_placeholder"):
            field["showing_placeholder"] = True
        if candidate.get("part"):
            field["part"] = candidate["part"]
        fields.append(field)
        seen_keys.add(key)
    return {
        "template_source": str(Path(template).resolve()),
        "generated_by": "render_pipeline.py --auto-content-controls",
        "fields": fields,
    }


def main():
    parser = argparse.ArgumentParser(description="Run the full DOCX template fidelity pipeline.")
    parser.add_argument("--template", help="DOCX template. Optional when --spec has template_source.")
    parser.add_argument("--data", help="JSON data for rendering.")
    parser.add_argument("--spec", help="Template spec for L2 locator/table-loop rendering.")
    parser.add_argument("--auto-content-controls", action="store_true", help="Generate a temporary content-control spec from analyze_template.py and fill matching data fields by tag/alias.")
    parser.add_argument("--draft-spec", action="store_true", help="Generate a conservative L2 draft spec from one DOCX template; used for rendering when --spec and --auto-content-controls do not provide a spec.")
    parser.add_argument("--output", help="Output DOCX path.")
    parser.add_argument("--report-dir", help="Directory for analysis/font/render/verify reports.")
    parser.add_argument("--pdf", action="store_true", help="Also export PDF during verification when soffice is available.")
    parser.add_argument("--compare-template-pdf", action="store_true", help="Compare template/output page counts after PDF export.")
    parser.add_argument("--visual-compare", action="store_true", help="Render template/output PDF pages and compare pixels. Implies --pdf and --compare-template-pdf.")
    parser.add_argument("--visual-page", type=int, default=1)
    parser.add_argument("--visual-pages", help="Pages to compare, such as '1', '1,3-5', or 'all'. Defaults to --visual-page.")
    parser.add_argument("--max-visual-pages", type=int, default=20)
    parser.add_argument("--visual-dpi", type=int, default=120)
    parser.add_argument("--max-visual-changed-ratio", type=float, default=0.08)
    parser.add_argument("--visual-ignore-regions", help="JSON file with visual diff ignore regions and optional presets.")
    parser.add_argument("--visual-ignore-preset", action="append", default=[])
    parser.add_argument("--strict-render", action="store_true", help="Pass --strict to render_docx.py.")
    parser.add_argument("--request-field-update", action="store_true", help="Set w:updateFields=true after rendering so Word can refresh TOC, page numbers, references, and similar fields on open.")
    parser.add_argument("--refresh-fields", action="store_true", help="Create a sidecar DOCX/PDF by running refresh_fields.py after rendering. Keeps the primary output available for invariant verification.")
    parser.add_argument("--field-refresh-backend", choices=["auto", "request-only", "libreoffice-cli", "libreoffice-uno", "word-applescript"], default="auto")
    parser.add_argument("--fail-on-warning", action="store_true", help="Return non-zero when verification status is not passed.")
    parser.add_argument("--analyze-only", action="store_true", help="Only analyze the template and prepare the font plan.")
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    scripts = skill_dir / "scripts"

    template = Path(args.template).expanduser() if args.template else None
    if template is None and args.spec:
        template = resolve_template_from_spec(args.spec)
    if template is None or not template.exists():
        print("Missing template. Provide --template or a --spec with template_source.", file=sys.stderr)
        return 2

    output = Path(args.output).expanduser() if args.output else None
    if not args.analyze_only and output is None:
        print("Missing --output for render mode.", file=sys.stderr)
        return 2
    if not args.analyze_only and not args.data:
        print("Missing --data for render mode.", file=sys.stderr)
        return 2

    report_dir = Path(args.report_dir).expanduser() if args.report_dir else (output.parent if output else template.parent)
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = output.stem if output else template.stem

    analysis_report = report_dir / f"{stem}.analysis.json"
    font_report = report_dir / f"{stem}.font-plan.json"
    render_report = report_dir / f"{stem}.render.json"
    verify_report = report_dir / f"{stem}.verify.json"
    summary_report = report_dir / f"{stem}.pipeline.json"
    summary_markdown_report = report_dir / f"{stem}.pipeline.md"
    delivery_report = report_dir / f"{stem}.delivery.json"
    delivery_markdown_report = report_dir / f"{stem}.delivery.md"
    auto_spec_report = report_dir / f"{stem}.auto-content-controls.spec.json"
    draft_spec_report = report_dir / f"{stem}.draft.spec.json"
    draft_data_report = report_dir / f"{stem}.draft.data.json"
    draft_report = report_dir / f"{stem}.draft.report.json"
    draft_md_report = report_dir / f"{stem}.draft.md"
    field_update_report = report_dir / f"{stem}.field-update.json"
    field_refresh_report = report_dir / f"{stem}.field-refresh.json"
    field_refreshed_output = report_dir / f"{stem}.field-refreshed.docx"
    field_refreshed_pdf = report_dir / f"{stem}.field-refreshed.pdf"
    field_refreshed_verify_report = report_dir / f"{stem}.field-refreshed.verify.json"
    pdf_dir = report_dir / f"{stem}.pdf"
    field_refreshed_pdf_dir = report_dir / f"{stem}.field-refreshed.verify.pdf"

    steps = []
    steps.append(
        run_step(
            "analyze_template",
            [sys.executable, str(scripts / "analyze_template.py"), str(template), "--output", str(analysis_report)],
        )
    )
    steps.append(
        run_step(
            "prepare_fonts",
            [sys.executable, str(scripts / "prepare_fonts.py"), str(template), "--report", str(font_report)],
            allow_warning=True,
        )
    )
    if args.draft_spec:
        steps.append(
            run_step(
                "draft_spec",
                [
                    sys.executable,
                    str(scripts / "draft_spec.py"),
                    str(template),
                    "--spec-output",
                    str(draft_spec_report),
                    "--data-output",
                    str(draft_data_report),
                    "--report",
                    str(draft_report),
                    "--report-md",
                    str(draft_md_report),
                ],
            )
        )

    if not args.analyze_only:
        output.parent.mkdir(parents=True, exist_ok=True)
        render_spec = Path(args.spec).expanduser() if args.spec else None
        if args.auto_content_controls and not render_spec:
            analysis = read_json(analysis_report)
            raw_data = read_json(args.data)
            auto_spec = build_auto_content_control_spec(template, analysis, raw_data)
            auto_spec_report.write_text(json.dumps(auto_spec, ensure_ascii=False, indent=2), encoding="utf-8")
            matched_fields = [field.get("key") for field in auto_spec.get("fields", [])]
            steps.append(
                {
                    "name": "auto_content_control_spec",
                    "ok": bool(matched_fields),
                    "returncode": 0 if matched_fields else 1,
                    "command": ["generate", str(auto_spec_report)],
                    "stdout": json.dumps({"matched_fields": matched_fields}, ensure_ascii=False),
                    "stderr": "" if matched_fields else "No content controls matched data fields by tag or alias.",
                }
            )
            render_spec = auto_spec_report if matched_fields else None
        if args.draft_spec and not render_spec and draft_spec_report.exists():
            render_spec = draft_spec_report
        if render_spec:
            render_command = [
                sys.executable,
                str(scripts / "fill_by_spec.py"),
                str(render_spec),
                "--data",
                str(Path(args.data).expanduser()),
                "--output",
                str(output),
                "--report",
                str(render_report),
            ]
        else:
            render_command = [
                sys.executable,
                str(scripts / "render_docx.py"),
                str(template),
                "--data",
                str(Path(args.data).expanduser()),
                "--output",
                str(output),
                "--report",
                str(render_report),
            ]
            if args.strict_render:
                render_command.append("--strict")
        steps.append(run_step("render", render_command))
        if args.refresh_fields:
            args.request_field_update = True
        if args.request_field_update:
            steps.append(
                run_step(
                    "request_field_update",
                    [
                        sys.executable,
                        str(scripts / "request_field_update.py"),
                        str(output),
                        "--output",
                        str(output),
                        "--report",
                        str(field_update_report),
                    ],
                )
            )
        if args.refresh_fields:
            refresh_command = [
                sys.executable,
                str(scripts / "refresh_fields.py"),
                str(output),
                "--output",
                str(field_refreshed_output),
                "--report",
                str(field_refresh_report),
                "--backend",
                args.field_refresh_backend,
            ]
            if args.pdf:
                refresh_command.extend(["--pdf-output", str(field_refreshed_pdf)])
            steps.append(run_step("refresh_fields", refresh_command, allow_warning=True))

        verify_command = [
            sys.executable,
            str(scripts / "verify_fidelity.py"),
            str(template),
            str(output),
            "--report",
            str(verify_report),
        ]
        if render_report.exists():
            verify_command.extend(["--render-report", str(render_report)])
        if render_report.exists() and render_merged_reference_styles(render_report):
            verify_command.extend(["--allow-changed-part", "word/styles.xml"])
        if render_report.exists() and render_imported_reference_numbering(render_report):
            verify_command.extend(["--allow-changed-part", "word/numbering.xml"])
        if args.request_field_update and field_update_report.exists() and field_update_changed_settings(field_update_report):
            verify_command.extend(["--allow-changed-part", "word/settings.xml"])
        if args.visual_compare:
            args.pdf = True
            args.compare_template_pdf = True
        if args.pdf:
            verify_command.extend(["--pdf-outdir", str(pdf_dir)])
        if args.compare_template_pdf:
            verify_command.append("--compare-template-pdf")
        if args.visual_compare:
            verify_command.extend(
                [
                    "--visual-compare",
                    "--visual-page",
                    str(args.visual_page),
                    "--visual-pages",
                    args.visual_pages or str(args.visual_page),
                    "--max-visual-pages",
                    str(args.max_visual_pages),
                    "--visual-dpi",
                    str(args.visual_dpi),
                    "--max-visual-changed-ratio",
                    str(args.max_visual_changed_ratio),
                ]
            )
            if args.visual_ignore_regions:
                verify_command.extend(["--visual-ignore-regions", str(Path(args.visual_ignore_regions).expanduser())])
            for preset in args.visual_ignore_preset:
                verify_command.extend(["--visual-ignore-preset", preset])
        steps.append(run_step("verify_fidelity", verify_command, allow_warning=not args.fail_on_warning))
        if args.refresh_fields and field_refreshed_output.exists():
            field_refreshed_verify_command = [
                sys.executable,
                str(scripts / "verify_fidelity.py"),
                str(template),
                str(field_refreshed_output),
                "--report",
                str(field_refreshed_verify_report),
            ]
            if render_report.exists():
                field_refreshed_verify_command.extend(["--render-report", str(render_report)])
            if render_report.exists() and render_merged_reference_styles(render_report):
                field_refreshed_verify_command.extend(["--allow-changed-part", "word/styles.xml"])
            if render_report.exists() and render_imported_reference_numbering(render_report):
                field_refreshed_verify_command.extend(["--allow-changed-part", "word/numbering.xml"])
            if args.request_field_update and field_update_report.exists() and field_update_changed_settings(field_update_report):
                field_refreshed_verify_command.extend(["--allow-changed-part", "word/settings.xml"])
            if args.pdf:
                field_refreshed_verify_command.extend(["--pdf-outdir", str(field_refreshed_pdf_dir)])
            if args.compare_template_pdf:
                field_refreshed_verify_command.append("--compare-template-pdf")
            if args.visual_compare:
                field_refreshed_verify_command.extend(
                    [
                        "--visual-compare",
                        "--visual-page",
                        str(args.visual_page),
                        "--visual-pages",
                        args.visual_pages or str(args.visual_page),
                        "--max-visual-pages",
                        str(args.max_visual_pages),
                        "--visual-dpi",
                        str(args.visual_dpi),
                        "--max-visual-changed-ratio",
                        str(args.max_visual_changed_ratio),
                    ]
                )
                if args.visual_ignore_regions:
                    field_refreshed_verify_command.extend(["--visual-ignore-regions", str(Path(args.visual_ignore_regions).expanduser())])
                for preset in args.visual_ignore_preset:
                    field_refreshed_verify_command.extend(["--visual-ignore-preset", preset])
            steps.append(run_step("verify_field_refreshed", field_refreshed_verify_command, allow_warning=True))

    analysis = read_json(analysis_report) if analysis_report.exists() else {}
    fonts = read_json(font_report) if font_report.exists() else {}
    render = read_json(render_report) if render_report.exists() else {}
    verify = read_json(verify_report) if verify_report.exists() else {}
    field_refreshed_verify = read_json(field_refreshed_verify_report) if field_refreshed_verify_report.exists() else {}
    draft = read_json(draft_report) if draft_report.exists() else {}
    field_update = read_json(field_update_report) if field_update_report.exists() else {}
    field_refresh = read_json(field_refresh_report) if field_refresh_report.exists() else {}
    field_refresh_drift = field_refresh.get("post_refresh_drift") or {}
    failed_steps = [step for step in steps if not step["ok"]]
    missing_fonts = fonts.get("missing_fonts", [])
    verify_status = verify.get("status")
    field_refreshed_verify_status = field_refreshed_verify.get("status")
    draft_warnings = draft.get("warnings", []) if isinstance(draft.get("warnings"), list) else []

    status = "passed"
    if failed_steps:
        status = "failed"
    elif args.analyze_only and missing_fonts:
        status = "warning"
    elif draft_warnings:
        status = "warning"
    elif field_refresh.get("status") == "warning":
        status = "warning"
    elif field_refresh_drift.get("core_risk_parts_changed"):
        status = "warning"
    elif verify_status and verify_status != "passed":
        status = "warning"
    elif field_refreshed_verify_status and field_refreshed_verify_status != "passed":
        status = "warning"

    summary = {
        "status": status,
        "template": str(template.resolve()),
        "output": str(output.resolve()) if output else None,
        "reports": {
            "analysis": str(analysis_report),
            "font_plan": str(font_report),
            "auto_content_control_spec": str(auto_spec_report) if auto_spec_report.exists() else None,
            "draft_spec": str(draft_spec_report) if draft_spec_report.exists() else None,
            "draft_data": str(draft_data_report) if draft_data_report.exists() else None,
            "draft_report": str(draft_report) if draft_report.exists() else None,
            "draft_markdown": str(draft_md_report) if draft_md_report.exists() else None,
            "field_update": str(field_update_report) if field_update_report.exists() else None,
            "field_refresh": str(field_refresh_report) if field_refresh_report.exists() else None,
            "field_refreshed_output": str(field_refreshed_output) if field_refreshed_output.exists() else None,
            "field_refreshed_pdf": str(field_refreshed_pdf) if field_refreshed_pdf.exists() else None,
            "field_refreshed_verify": str(field_refreshed_verify_report) if field_refreshed_verify_report.exists() else None,
            "render": str(render_report) if render_report.exists() else None,
            "verify": str(verify_report) if verify_report.exists() else None,
            "summary": str(summary_report),
            "summary_markdown": str(summary_markdown_report),
            "delivery_gate": str(delivery_report),
            "delivery_gate_markdown": str(delivery_markdown_report),
        },
        "missing_fonts": missing_fonts,
        "draft_status": {
            "field_count": draft.get("spec_field_count"),
            "literal_replacement_count": draft.get("literal_replacement_count"),
            "warnings_count": len(draft_warnings),
            "warnings": draft_warnings[:20],
        } if draft else None,
        "template_stats": {
            "paragraph_count": analysis.get("paragraphs", {}).get("count"),
            "table_count": analysis.get("tables", {}).get("count") if isinstance(analysis.get("tables"), dict) else None,
            "section_count": len(analysis.get("sections", [])) if isinstance(analysis.get("sections"), list) else None,
        },
        "render_status": {
            "conditional_blocks": render.get("conditional_blocks"),
            "fields": render.get("fields"),
            "image_fields": render.get("image_fields"),
            "table_loops": render.get("table_loops"),
            "unresolved_tokens": render.get("unresolved_tokens"),
        },
        "field_update_status": {
            "requested": bool(args.request_field_update),
            "status": field_update.get("status"),
            "changed_parts": field_update.get("changed_parts"),
            "limitations": field_update.get("limitations"),
        } if args.request_field_update or field_update else None,
        "field_refresh_status": {
            "requested": bool(args.refresh_fields),
            "status": field_refresh.get("status"),
            "selected_backend": field_refresh.get("selected_backend"),
            "actual_field_results_refresh": field_refresh.get("actual_field_results_refresh"),
            "output": field_refresh.get("output"),
            "pdf_output": field_refresh.get("pdf_output"),
            "limitations": field_refresh.get("limitations"),
            "post_refresh_drift": {
                "status": field_refresh_drift.get("status"),
                "changed_part_count": field_refresh_drift.get("changed_part_count"),
                "added_part_count": field_refresh_drift.get("added_part_count"),
                "removed_part_count": field_refresh_drift.get("removed_part_count"),
                "core_risk_parts_changed": field_refresh_drift.get("core_risk_parts_changed") or [],
                "text_parts_changed_count": len(field_refresh_drift.get("text_parts_changed") or []),
                "relationship_parts_changed_count": len(field_refresh_drift.get("relationship_parts_changed") or []),
                "media_parts_changed": field_refresh_drift.get("media_parts_changed") or [],
                "notes": field_refresh_drift.get("notes") or [],
            } if field_refresh_drift else None,
            "verify_status": field_refreshed_verify_status,
            "verify_failed_checks": [check for check in field_refreshed_verify.get("checks", []) if not check.get("passed", False)] if field_refreshed_verify else [],
        } if args.refresh_fields or field_refresh else None,
        "verify_status": verify_status,
        "verify_failed_checks": [check for check in verify.get("checks", []) if not check.get("passed", False)],
        "pdf": {
            "output_pdf": verify.get("pdf", {}).get("output_conversion", {}).get("pdf"),
            "visual_compare": verify.get("pdf", {}).get("visual_compare"),
        },
        "steps": steps,
    }
    delivery_gate = evaluate_delivery(
        summary,
        {
            "require_pdf": bool(args.pdf),
            "require_visual_compare": bool(args.visual_compare),
            "require_actual_field_refresh": False,
        },
    )
    summary["delivery_gate"] = delivery_gate
    summary_report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_markdown_report.write_text(render_pipeline_markdown(summary), encoding="utf-8")
    delivery_report.write_text(json.dumps(delivery_gate, ensure_ascii=False, indent=2), encoding="utf-8")
    delivery_markdown_report.write_text(render_delivery_markdown(delivery_gate), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if status == "failed" or (args.fail_on_warning and status != "passed"):
        return 1
    if shutil.which("soffice") is None and args.pdf:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
