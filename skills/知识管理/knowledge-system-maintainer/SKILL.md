---
name: knowledge-system-maintainer
description: Use when a local Markdown or Obsidian knowledge system needs a health audit, anti-decay review, evidence-backed defect prioritization, recovery verification, or one controlled and reversible system improvement. Do not use for routine note cleanup, generic file organization, or automatic bulk repair.
---

# Knowledge System Maintainer

Answer two questions with evidence: “What is actually unhealthy?” and “What is the smallest safe system change?” Work with ordinary local files. Never assume private scripts, a fixed Vault layout, Git, plugins, or the instructor's machine.

## Choose a Mode

- **Audit**: read-only health check and prioritized report.
- **Improve**: one confirmed finding, one human-approved reversible change, same-case retest.

No existing audit evidence means Audit mode. Authorization to audit is not authorization to repair.

## Audit

1. Resolve the narrowest knowledge-system directory. Reject a whole home, Documents folder, disk, or unrelated parent. Read governing instructions. Exclude `.env`, credentials, keys, tokens, and unrelated personal files.
2. List **Available**, **Not observed**, and **Provided for this run**. Never pretend the learner has the instructor's tools.
3. Read [references/health-dimensions.md](references/health-dimensions.md). Preview which of the fixed six lanes can be checked: `找得到`, `读得懂`, `用得上`, `接得住`, `救得回`, `管得动`. Unavailable checks stay `灰：未检查`; do not install tools just to fill them.
4. Inspect read-only. For every signal keep **automatic evidence** separate from **human judgment**. Counts, age, size, missing tags, orphan status, and script output are signals, not defects.
5. Classify only from current evidence:
   - `绿`: directly checked and working for a real case;
   - `黄`: suspicious, stale, incomplete, or awaiting judgment;
   - `红`: proven loss/exposure risk, blocked work, wrong retrieval, contradiction, or repeated failure;
   - `灰`: unavailable or not checked.
6. Prioritize confirmed findings: `P0` active loss/exposure/destructive or core-system failure; `P1` repeated wrong result or major blockage; `P2` friction or non-blocking improvement; `P3` accepted exception or low-value debt. Never invent a precise health score.
7. Every yellow or red finding needs an evidence card: `检查动作`, `预期结果`, `实际结果`, `证据`, `人工判断`, `下一动作`, `完成标志`. Missing evidence becomes `灰` or `待确认`, never inference.

When saving a report, preview the target first, use [assets/SYSTEM-HEALTH-REPORT.template.md](assets/SYSTEM-HEALTH-REPORT.template.md), read it back, then run:

```bash
python3 <skill-dir>/scripts/health_report_check.py <report-path>
```

The checker validates structure, not truth.

## Improve

Read [references/improvement-routing.md](references/improvement-routing.md). Choose one confirmed, reproducible finding. Preserve the before input, expected result, observed result, evidence, relevant revision, and rollback.

Route to the smallest layer: current content, project instruction, memory, capability map, Skill, Hook, deterministic checker, or knowledge structure. Show the exact target, proposed change, effect, side effects, same-case retest, adjacent regression check, and rollback. Wait for approval. Change one control point only, rerun the same case, record the result, and roll back if it fails or regresses.

## Red Flags

- “Low score authorizes repair.”
- “Sync proves backup and recovery.”
- “Old, isolated, large, or rarely used means defective.”
- “Audit permission includes repair permission.”
- “More metrics make the audit more complete.”
- “An unavailable lane can be estimated.”

Any red flag means return to read-only evidence collection.

## Acceptance

Audit passes only with scoped evidence, all six lanes accounted for, prioritized findings, and at least one next action. Improve passes only when one approved change has before/after evidence, same-case retest, adjacent regression check, and a usable rollback.
