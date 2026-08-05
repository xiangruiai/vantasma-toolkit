import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const skillSource = await readFile(
  new URL("../skills/manage-taskboard/SKILL.md", import.meta.url),
  "utf8",
);

test("the taskboard skill coordinates safe issue execution and review handoff", () => {
  assert.match(skillSource, /read the latest issue content and all comments/i);
  assert.match(skillSource, /completed work.*returned|returned.*completed work/i);
  assert.match(skillSource, /claim.*`todo`.*`in_progress`.*`--if-version`/is);
  assert.match(skillSource, /version conflict.*skip the issue.*do not implement/is);
  assert.match(skillSource, /bound worktree[^\n]*exact path/i);
  assert.match(skillSource, /bound branch[^\n]*existing worktree/i);
  assert.match(skillSource, /never silently execute against a different branch/i);
  assert.match(skillSource, /preserve `dueDate` during claims and handoffs/i);
  assert.match(skillSource, /automatic pickup order/i);

  assert.match(
    skillSource,
    /after implementation[^\n]*add a comment[^\n]*key changes[^\n]*verification[^\n]*result[^\n]*risks[^\n]*then move[^\n]*`in_review`/i,
  );
  assert.match(skillSource, /remain `in_progress` only while Codex is actively working/i);
  assert.match(skillSource, /temporarily interrupted[^\n]*move back to `todo`/i);
  assert.match(skillSource, /waiting for user input[^\n]*`blocked`/i);
  assert.match(skillSource, /never move to `canceled` unless the user explicitly decides/i);
  assert.match(skillSource, /confirmed failed or interrupted through Codex task\/thread state/i);
  assert.match(skillSource, /never infer termination from age alone/i);
});
