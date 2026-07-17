#!/usr/bin/env python3
import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def run_analysis(template, output):
    skill_dir = Path(__file__).resolve().parents[1]
    script = skill_dir / "scripts" / "analyze_template.py"
    cp = subprocess.run(
        [sys.executable, str(script), str(template), "--output", str(output)],
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"analyze_template.py failed: {cp.stderr or cp.stdout}")
    return read_json(output)


def count_stable_content_controls(controls):
    stable = []
    unstable = []
    for control in controls:
        binding = control.get("binding") or {}
        has_stable_key = bool(control.get("tag") or control.get("alias") or binding.get("xpath"))
        if has_stable_key:
            stable.append(control)
        else:
            unstable.append(control)
    return stable, unstable


def named_bookmarks(bookmarks):
    return [item for item in bookmarks if item.get("name") and not item.get("hidden") and not item.get("system")]


def system_bookmarks(bookmarks):
    return [item for item in bookmarks if item.get("system")]


def visible_sample_count(analysis):
    samples = analysis.get("first_text_samples") or []
    count = 0
    for text in samples:
        value = str(text).strip()
        if len(value) >= 4 and not value.isdigit():
            count += 1
    return count


def complex_counts(analysis):
    complex_structures = analysis.get("complex_structures") or {}
    counts = complex_structures.get("counts") or {}
    return {key: int(value) for key, value in counts.items() if isinstance(value, int) or str(value).isdigit()}


def complex_risk_count(counts):
    risk_keys = [
        "field_code_markers",
        "field_instruction_count",
        "equation_count",
        "embedded_object_count",
        "alt_chunk_count",
        "revision_count",
    ]
    return sum(int(counts.get(key) or 0) for key in risk_keys)


def classify(analysis, source_kind="docx"):
    if source_kind != "docx":
        return {
            "level": "L3",
            "level_name": "visual-imitation-only",
            "score": 20,
            "can_claim_100_percent": False,
            "claim": "Only visual imitation is possible without an editable DOCX template.",
            "blockers": ["Input is not an editable DOCX template."],
            "warnings": [],
            "recommended_route": {
                "mode": "ask_for_docx",
                "commands": [],
            },
            "upgrade_actions": ["Get the original editable DOCX template."],
        }

    placeholders = analysis.get("placeholders") or {}
    controls = analysis.get("content_controls") or []
    bookmarks = analysis.get("bookmarks") or []
    hyperlinks = analysis.get("hyperlinks") or []
    tables = analysis.get("tables") or {}
    fonts = analysis.get("fonts") or {}
    missing_fonts = fonts.get("missing_fonts") or []
    stable_controls, unstable_controls = count_stable_content_controls(controls)
    stable_bookmarks = named_bookmarks(bookmarks)
    sample_count = visible_sample_count(analysis)
    placeholder_count = sum(int(value) for value in placeholders.values())
    complex = complex_counts(analysis)
    complex_risk = complex_risk_count(complex)

    blockers = []
    warnings = []
    upgrade_actions = []

    if placeholder_count:
        level = "L1"
        level_name = "placeholder-strong-fidelity"
        score = 90
        mode = "render_pipeline"
        claim = "Strong field-level fidelity is possible after font and verification checks pass."
    elif stable_controls:
        level = "L2"
        level_name = "content-control-spec"
        score = 76
        mode = "render_pipeline --auto-content-controls"
        claim = "High fidelity is possible for tagged, aliased, or data-bound content controls after data mapping is confirmed."
        blockers.append("No explicit {{field}} placeholders; content-control mapping must be confirmed.")
    elif stable_bookmarks:
        level = "L2"
        level_name = "bookmark-spec"
        score = 68
        mode = "fill_by_spec"
        claim = "High fidelity is possible for named bookmarks after a template_spec.json is confirmed."
        blockers.append("No explicit {{field}} placeholders; bookmark spec must be confirmed.")
    elif sample_count:
        level = "L2"
        level_name = "format-sample-draft-spec"
        score = 42
        mode = "render_pipeline --draft-spec"
        claim = "This looks like a format sample, not a fully data-addressable template."
        blockers.append("No placeholders, tagged content controls, data bindings, or named bookmarks were found.")
        upgrade_actions.append("Add {{field}} placeholders, Word bookmarks, or content-control tag/alias values for required fields.")
        upgrade_actions.append("Provide a filled reference DOCX for long thesis body sections, figures, tables, and references.")
    else:
        level = "L2"
        level_name = "manual-spec-required"
        score = 32
        mode = "draft_spec then manual review"
        claim = "The DOCX is editable, but no reliable field API was detected."
        blockers.append("No reliable field locators were found.")
        upgrade_actions.append("Manually add placeholders, bookmarks, or tagged content controls before production rendering.")

    if missing_fonts:
        score = max(0, score - min(20, 6 + len(missing_fonts) * 2))
        blockers.append("Missing required fonts prevent a 100% fidelity claim.")
        upgrade_actions.append("Install authorized font files or document approved fallback fonts.")

    if unstable_controls and not stable_controls:
        warnings.append("Content controls exist but have no tag, alias, or dataBinding; do not auto-fill them as business fields.")
    elif unstable_controls:
        warnings.append("Some content controls have no stable tag, alias, or dataBinding and need manual review.")

    if system_bookmarks(bookmarks):
        warnings.append("System or tool-generated bookmarks were ignored as business fields.")

    table_count = tables.get("count") if isinstance(tables, dict) else 0
    if table_count:
        warnings.append("Tables require explicit table_loop specs before repeated rows can be generated safely.")

    if hyperlinks:
        warnings.append("Existing hyperlinks should be handled through hyperlink locators or insert_hyperlink specs.")

    if complex_risk:
        score = max(0, score - min(18, 6 + complex_risk // 10))
        blockers.append("Complex Word structures require explicit handling and visual/PDF verification before a 100% fidelity claim.")
        upgrade_actions.append("Review field codes, equations, tracked revisions, embedded objects, and generated tables of contents before production rendering.")
        warnings.append("Template contains complex Word structures such as field codes, equations, revisions, or embedded objects.")
    elif complex.get("drawing_count"):
        warnings.append("Drawings or pictures are present; replace them only through explicit image_fields or leave them untouched.")

    can_claim = level == "L1" and not missing_fonts and not complex_risk
    if level != "L1":
        can_claim = False
    score = max(0, min(100, score))

    commands = []
    skill_dir = shlex.quote(str(Path(__file__).resolve().parents[1]))
    if mode == "render_pipeline":
        commands.append(f"python3 {skill_dir}/scripts/render_pipeline.py --template TEMPLATE.docx --data DATA.json --output OUT.docx --pdf --compare-template-pdf")
    elif mode == "render_pipeline --auto-content-controls":
        commands.append(f"python3 {skill_dir}/scripts/render_pipeline.py --template TEMPLATE.docx --data DATA.json --output OUT.docx --auto-content-controls")
    elif mode == "fill_by_spec":
        commands.append(f"python3 {skill_dir}/scripts/fill_by_spec.py template_spec.json --data DATA.json --output OUT.docx --report OUT.render.json")
    elif mode == "render_pipeline --draft-spec":
        commands.append(f"python3 {skill_dir}/scripts/render_pipeline.py --template TEMPLATE.docx --data DATA.json --output OUT.docx --draft-spec")
    else:
        commands.append(f"python3 {skill_dir}/scripts/draft_spec.py TEMPLATE.docx --spec-output template.draft.spec.json --data-output template.draft.data.json --report template.draft.report.json --report-md template.draft.md")

    return {
        "level": level,
        "level_name": level_name,
        "score": score,
        "can_claim_100_percent": can_claim,
        "claim": claim,
        "blockers": blockers,
        "warnings": warnings,
        "recommended_route": {
            "mode": mode,
            "commands": commands,
        },
        "upgrade_actions": upgrade_actions,
    }


def build_assessment(template, analysis):
    controls = analysis.get("content_controls") or []
    stable_controls, unstable_controls = count_stable_content_controls(controls)
    bookmarks = analysis.get("bookmarks") or []
    hyperlinks = analysis.get("hyperlinks") or []
    tables = analysis.get("tables") or {}
    fonts = analysis.get("fonts") or {}
    complex = complex_counts(analysis)
    result = classify(analysis, source_kind="docx")
    result.update(
        {
            "template": str(Path(template).expanduser().resolve()),
            "signals": {
                "placeholder_count": sum(int(value) for value in (analysis.get("placeholders") or {}).values()),
                "placeholder_keys": sorted((analysis.get("placeholders") or {}).keys()),
                "stable_content_control_count": len(stable_controls),
                "unstable_content_control_count": len(unstable_controls),
                "named_bookmark_count": len(named_bookmarks(bookmarks)),
                "system_bookmark_count": len(system_bookmarks(bookmarks)),
                "hyperlink_count": len(hyperlinks),
                "table_count": tables.get("count") if isinstance(tables, dict) else None,
                "section_count": len(analysis.get("sections") or []),
                "complex_structures": complex,
                "complex_risk_count": complex_risk_count(complex),
                "missing_fonts": fonts.get("missing_fonts") or [],
                "required_fonts": fonts.get("required_fonts") or [],
                "visible_sample_count": visible_sample_count(analysis),
            },
        }
    )
    return result


def markdown_report(assessment):
    signals = assessment.get("signals") or {}
    lines = [
        "# Template Readiness Assessment",
        "",
        f"- Template: `{assessment.get('template')}`",
        f"- Level: `{assessment.get('level')}` / `{assessment.get('level_name')}`",
        f"- Score: `{assessment.get('score')}/100`",
        f"- Can claim 100% fidelity: `{assessment.get('can_claim_100_percent')}`",
        f"- Claim: {assessment.get('claim')}",
        "",
        "## Signals",
        "",
        f"- Placeholders: `{signals.get('placeholder_count')}`",
        f"- Stable content controls: `{signals.get('stable_content_control_count')}`",
        f"- Unstable content controls: `{signals.get('unstable_content_control_count')}`",
        f"- Named bookmarks: `{signals.get('named_bookmark_count')}`",
        f"- System bookmarks ignored: `{signals.get('system_bookmark_count')}`",
        f"- Tables: `{signals.get('table_count')}`",
        f"- Sections: `{signals.get('section_count')}`",
        f"- Complex risk count: `{signals.get('complex_risk_count')}`",
        f"- Missing fonts: `{', '.join(signals.get('missing_fonts') or []) or 'none'}`",
        "",
        "## Blockers",
        "",
    ]
    for item in assessment.get("blockers") or ["none"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Warnings", ""])
    for item in assessment.get("warnings") or ["none"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Recommended Route", ""])
    route = assessment.get("recommended_route") or {}
    lines.append(f"- Mode: `{route.get('mode')}`")
    for command in route.get("commands") or []:
        lines.append(f"- `{command}`")
    lines.extend(["", "## Upgrade Actions", ""])
    for item in assessment.get("upgrade_actions") or ["none"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Assess whether a DOCX template is ready for high-fidelity filling.")
    parser.add_argument("template")
    parser.add_argument("--analysis", help="Use an existing analyze_template.py JSON report.")
    parser.add_argument("--analysis-output", help="Where to write analyze_template.py output when --analysis is not provided.")
    parser.add_argument("--output", "-o", help="Write readiness JSON report.")
    parser.add_argument("--markdown-output", help="Write a Markdown readiness report.")
    args = parser.parse_args()

    template = Path(args.template).expanduser()
    if not template.exists():
        print(f"Template not found: {template}", file=sys.stderr)
        return 2
    if template.suffix.lower() != ".docx":
        assessment = classify({}, source_kind="other")
        assessment["template"] = str(template.resolve())
    else:
        if args.analysis:
            analysis = read_json(args.analysis)
        else:
            analysis_output = Path(args.analysis_output).expanduser() if args.analysis_output else template.with_suffix(".analysis.json")
            analysis = run_analysis(template, analysis_output)
        assessment = build_assessment(template, analysis)

    text = json.dumps(assessment, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    if args.markdown_output:
        Path(args.markdown_output).expanduser().write_text(markdown_report(assessment), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
