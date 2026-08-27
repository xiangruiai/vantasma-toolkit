# Improvement Routing

Choose the smallest layer that can prevent the confirmed failure from repeating.

| Failure type | Preferred layer | Example | Do not use when |
|---|---|---|---|
| Wrong or missing current content | Current note or project file | Correct an outdated source | The problem is a repeated process failure |
| Stable project behavior | Project `AGENTS.md` or equivalent instruction | Always validate this project's exports | It is only one task's temporary state |
| Personal preference or durable personal fact | Memory system | Preferred writing tone | It is project progress or an unverified inference |
| Agent chooses the wrong available ability | Capability map or routing note | Map “查 Vault” to the actual search route | The tool itself is broken |
| Repeatable multi-step method | Skill | Monthly course-material audit | One instruction or deterministic check is enough |
| Action must run at a lifecycle event | Hook | Validate frontmatter after a file edit | It still needs human judgment or is not event-driven |
| Exact invariant must be checked every time | Deterministic script or test | Required headings, broken file reference | The quality standard is subjective |
| Knowledge cannot be found or understood | Link, metadata, structure, or source-of-truth change | Link a project index to its authoritative plan | The failure is execution rather than retrieval |

## Eligibility Gate

Before changing the system, answer yes to all applicable questions:

- Is the failure directly observed?
- Can it be reproduced with a specific input or action?
- Does it matter to a real task or real risk?
- Is the proposed rule stable beyond this one example?
- Is this the smallest layer that can address the root cause?
- Can the change be tested with the same case?
- Can it be rolled back?
- Has a human approved this exact change?

If the answer is no, repair the immediate output or collect more evidence. Do not create a permanent rule.

## Change Card

```markdown
### Problem
- Before input:
- Expected:
- Observed:
- Evidence:

### Proposed change
- Target layer:
- Target file:
- Minimal change:
- Why this layer:
- Side effects:

### Verification
- Same-case retest:
- Regression check:
- Pass signal:
- Rollback:
- Human approval:
```
