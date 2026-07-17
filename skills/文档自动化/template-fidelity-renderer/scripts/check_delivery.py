#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def as_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [value]


def issue(code, message, detail=None):
    row = {"code": code, "message": message}
    if detail is not None:
        row["detail"] = detail
    return row


def failed_check_is_allowed(check, options):
    name = check.get("name") if isinstance(check, dict) else None
    if options.get("allow_missing_fonts") and name in {
        "template_fonts_available",
        "output_pdf_uses_template_fonts",
    }:
        return True
    return False


def blocking_failed_checks(checks, options):
    return [
        check
        for check in as_list(checks)
        if isinstance(check, dict)
        and not check.get("passed", False)
        and not failed_check_is_allowed(check, options)
    ]


def collect_render_errors(render_status):
    errors = []
    if not isinstance(render_status, dict):
        return errors
    for section in ["fields", "image_fields", "conditional_blocks", "table_loops"]:
        rows = render_status.get(section)
        if isinstance(rows, dict):
            rows = list(rows.values())
        for row in as_list(rows):
            if isinstance(row, dict) and row.get("status") in {"error", "failed", "missing"}:
                errors.append({"section": section, "item": row})
    return errors


def path_exists(path):
    return bool(path) and Path(path).expanduser().exists()


def default_options(**overrides):
    options = {
        "allow_missing_fonts": False,
        "allow_refresh_core_drift": False,
        "require_pdf": False,
        "require_visual_compare": False,
        "require_actual_field_refresh": False,
    }
    options.update(overrides)
    return options


def evaluate_delivery(summary, options=None):
    options = default_options(**(options or {}))
    blockers = []
    warnings = []
    reports = summary.get("reports") if isinstance(summary.get("reports"), dict) else {}

    if summary.get("error"):
        blockers.append(issue("pipeline_json_unreadable", "Pipeline JSON could not be read.", summary.get("error")))

    output = summary.get("output")
    if not path_exists(output):
        blockers.append(issue("output_missing", "Primary output DOCX is missing.", output))

    if summary.get("status") == "failed":
        blockers.append(issue("pipeline_failed", "Pipeline status is failed."))
    elif summary.get("status") == "warning":
        warnings.append(issue("pipeline_warning", "Pipeline status is warning; review details before delivery."))

    failed_steps = [step for step in as_list(summary.get("steps")) if isinstance(step, dict) and not step.get("ok")]
    if failed_steps:
        blockers.append(issue("failed_pipeline_steps", "One or more pipeline steps failed.", failed_steps))

    missing_fonts = as_list(summary.get("missing_fonts"))
    if missing_fonts:
        target = warnings if options["allow_missing_fonts"] else blockers
        target.append(issue("missing_fonts", "Template fonts are missing in this environment.", missing_fonts))

    verify_status = summary.get("verify_status")
    if not verify_status:
        blockers.append(issue("verification_missing", "Verification report status is missing."))
    elif verify_status == "failed":
        blockers.append(issue("verification_failed", "Verification status is failed."))
    elif verify_status == "warning":
        warnings.append(issue("verification_warning", "Verification status is warning."))

    failed_verify_checks = blocking_failed_checks(summary.get("verify_failed_checks"), options)
    if failed_verify_checks:
        blockers.append(issue("failed_verify_checks", "Verification has failed checks.", failed_verify_checks))

    render_status = summary.get("render_status") or {}
    unresolved = render_status.get("unresolved_tokens") if isinstance(render_status, dict) else None
    if unresolved:
        blockers.append(issue("unresolved_tokens", "Rendered DOCX still has unresolved placeholders.", unresolved))
    render_errors = collect_render_errors(render_status)
    if render_errors:
        blockers.append(issue("render_errors", "Render report contains failed fields, images, conditions, or table loops.", render_errors))

    pdf = summary.get("pdf") if isinstance(summary.get("pdf"), dict) else {}
    output_pdf = pdf.get("output_pdf")
    if options["require_pdf"] and not path_exists(output_pdf):
        blockers.append(issue("pdf_missing", "PDF output is required but missing.", output_pdf))

    visual = pdf.get("visual_compare")
    if options["require_visual_compare"] and not visual:
        blockers.append(issue("visual_compare_missing", "Visual comparison is required but missing."))
    elif isinstance(visual, dict):
        visual_summary = visual.get("summary") or {}
        if visual_summary.get("same_dimensions_all") is False:
            blockers.append(issue("visual_dimensions_changed", "Visual comparison found page dimension drift.", visual_summary))
        if visual_summary.get("pages_over_limit"):
            blockers.append(issue("visual_diff_over_limit", "Visual comparison found pages over the allowed diff ratio.", visual_summary))

    field_update = summary.get("field_update_status")
    if isinstance(field_update, dict) and field_update.get("requested"):
        warnings.append(issue("field_update_request", "DOCX requests Word-side field updates; this is not field-result recalculation.", field_update.get("limitations")))

    field_refresh = summary.get("field_refresh_status")
    if isinstance(field_refresh, dict) and field_refresh.get("requested"):
        if field_refresh.get("status") == "failed":
            blockers.append(issue("field_refresh_failed", "Field refresh sidecar step failed."))
        elif field_refresh.get("status") == "warning":
            warnings.append(issue("field_refresh_warning", "Field refresh sidecar status is warning."))
        actual_refresh = field_refresh.get("actual_field_results_refresh")
        if options["require_actual_field_refresh"] and actual_refresh is not True:
            blockers.append(issue("field_results_not_refreshed", "Actual Word field results refresh was required but not proven.", actual_refresh))
        elif actual_refresh is not True:
            warnings.append(issue("field_results_not_refreshed", "Actual Word field results refresh was not proven.", actual_refresh))
        sidecar_failed = blocking_failed_checks(field_refresh.get("verify_failed_checks"), options)
        if sidecar_failed:
            blockers.append(issue("field_refreshed_verify_failed", "Field-refreshed sidecar has failed verification checks.", sidecar_failed))
        drift = field_refresh.get("post_refresh_drift") or {}
        core_risk = drift.get("core_risk_parts_changed") or []
        if core_risk:
            target = warnings if options["allow_refresh_core_drift"] else blockers
            target.append(issue("refresh_core_drift", "External field-refresh engine changed core template parts.", core_risk))
        changed_count = drift.get("changed_part_count") or 0
        if changed_count and not core_risk:
            warnings.append(issue("refresh_package_drift", "External field-refresh engine changed DOCX package parts.", drift))

    if blockers:
        status = "blocked"
        decision = "Do not deliver until blockers are fixed or explicitly accepted."
    elif warnings:
        status = "needs_review"
        decision = "Review warnings before delivery."
    else:
        status = "ready"
        decision = "Ready for delivery for the scope covered by this pipeline run."

    return {
        "status": status,
        "decision": decision,
        "blockers": blockers,
        "warnings": warnings,
        "options": options,
        "artifacts": {
            "output": output,
            "pipeline_summary": reports.get("summary"),
            "pipeline_markdown": reports.get("summary_markdown"),
            "verify": reports.get("verify"),
            "field_refresh": reports.get("field_refresh"),
            "field_refreshed_verify": reports.get("field_refreshed_verify"),
        },
    }


def render_delivery_markdown(report):
    lines = [
        "# Delivery Gate Report",
        "",
        f"- Status: {report.get('status')}",
        f"- Decision: {report.get('decision')}",
        "",
        "## Blockers",
    ]
    blockers = report.get("blockers") or []
    if blockers:
        for row in blockers:
            lines.append(f"- {row.get('code')}: {row.get('message')}")
            if row.get("detail") is not None:
                lines.append(f"  - Detail: {json.dumps(row.get('detail'), ensure_ascii=False)}")
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings"])
    warnings = report.get("warnings") or []
    if warnings:
        for row in warnings:
            lines.append(f"- {row.get('code')}: {row.get('message')}")
            if row.get("detail") is not None:
                lines.append(f"  - Detail: {json.dumps(row.get('detail'), ensure_ascii=False)}")
    else:
        lines.append("- None")
    lines.extend(["", "## Artifacts"])
    for key, value in (report.get("artifacts") or {}).items():
        if value:
            lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evaluate whether a template-fidelity pipeline report is safe to deliver.")
    parser.add_argument("pipeline_json")
    parser.add_argument("--output", help="Write delivery gate JSON report.")
    parser.add_argument("--markdown-output", help="Write delivery gate Markdown report.")
    parser.add_argument("--allow-missing-fonts", action="store_true", help="Treat missing fonts as warnings instead of blockers.")
    parser.add_argument("--allow-refresh-core-drift", action="store_true", help="Treat post-refresh core part drift as a warning instead of a blocker.")
    parser.add_argument("--require-pdf", action="store_true", help="Block delivery unless the pipeline produced a PDF.")
    parser.add_argument("--require-visual-compare", action="store_true", help="Block delivery unless the pipeline includes visual comparison results.")
    parser.add_argument("--require-actual-field-refresh", action="store_true", help="Block delivery unless field refresh evidence proves actual field-result recalculation.")
    parser.add_argument("--allow-review-exit-zero", action="store_true", help="Return 0 for needs_review instead of 1.")
    args = parser.parse_args()

    summary = read_json(args.pipeline_json)
    options = default_options(
        allow_missing_fonts=args.allow_missing_fonts,
        allow_refresh_core_drift=args.allow_refresh_core_drift,
        require_pdf=args.require_pdf,
        require_visual_compare=args.require_visual_compare,
        require_actual_field_refresh=args.require_actual_field_refresh,
    )
    report = evaluate_delivery(summary, options)
    report["source"] = str(Path(args.pipeline_json).expanduser())

    if args.output:
        Path(args.output).expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown_output:
        Path(args.markdown_output).expanduser().write_text(render_delivery_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["status"] == "ready":
        return 0
    if report["status"] == "needs_review":
        return 0 if args.allow_review_exit_zero else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
