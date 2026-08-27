# Six Health Lanes

Use only the checks supported by the learner's current environment. Mark the rest `灰：未检查`.

## 1. Can knowledge be found?

Use two or three real questions from the learner's work. Check whether the expected note or source can be found and whether the result actually answers the question.

Broken links, orphan notes, tags, search exclusions, and metadata can explain a failure, but their counts do not prove one.

## 2. Can it be understood?

Check whether the learner and Agent can identify the authoritative source, understand names and metadata, and distinguish stable knowledge from temporary material.

Look for duplicate sources of truth, ambiguous names, unreadable metadata, missing provenance, or contradictory facts.

## 3. Can it be used?

Check one real workflow. Can the Agent select an available capability, follow the correct instructions, produce an output, and validate it?

Possible signals include a Skill that never triggers, a capability map that points to missing tools, an instruction that conflicts with actual behavior, or an output with no validation.

Do not repeat a Week3 Hook lesson. This lane judges the whole route from request to evidence.

## 4. Can work continue?

Check whether a new task or Agent can identify the correct project, stable rules, current verified result, next action, blocker, and evidence.

Signals include contradictory status files, completed work still listed as next, vague next actions, or claims with no current output.

## 5. Can important material be recovered?

Check whether the learner can explain and safely demonstrate how one important non-sensitive file would be restored after accidental loss or corruption.

Synchronization alone does not prove backup. Mark recovery `待确认` when no restore evidence exists.

## 6. Can the system be maintained safely?

Check whether rules, Skills, tools, and maintenance steps are still understandable; whether obvious secrets or private data are exposed; and whether high-risk actions require confirmation.

Do not open secret files to prove they are secret. File names, ignore rules, permissions, user testimony, or a controlled sample restore may be enough.

## Evidence Table

For every finding record:

| Field | Meaning |
|---|---|
| Check | What was actually inspected or attempted |
| Expected | What should happen for this learner |
| Observed | What happened now |
| Evidence | File, path, query, command, result, or screenshot |
| Judgment | Green, yellow, red, or gray |
| Human note | Why this matters or why the signal is acceptable |
