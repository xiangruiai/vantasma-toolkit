import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  prepareCodexExecutionDraft,
  resolveCodexExecutionWorkspace,
} from "../shared/direct-goal-dispatch.mjs";

const appSource = await readFile(new URL("../web/src/App.tsx", import.meta.url), "utf8");
const apiSource = await readFile(new URL("../web/src/api.ts", import.meta.url), "utf8");
const editorSource = await readFile(
  new URL("../web/src/components/TaskEditor.tsx", import.meta.url),
  "utf8",
);
const detailSource = await readFile(
  new URL("../web/src/components/TaskDetail.tsx", import.meta.url),
  "utf8",
);
const taskCardSource = await readFile(
  new URL("../web/src/components/TaskCard.tsx", import.meta.url),
  "utf8",
);
const automationSource = await readFile(
  new URL("../shared/taskboard-automation.mjs", import.meta.url),
  "utf8",
);
const injectionSource = await readFile(
  new URL("../inject/codex-taskboard.user.js", import.meta.url),
  "utf8",
);

test("direct execution changes ownership and status without dropping issue metadata", () => {
  const developmentContext = {
    type: "worktree",
    path: "/workspace/project/.worktrees/direct-goal",
    branch: "codex/direct-goal",
  };
  const draft = {
    title: "Ship the direct goal",
    description: "Acceptance details",
    status: "backlog",
    priority: "high",
    labels: ["workflow"],
    workflowId: null,
    developmentContext,
    dueDate: "2026-08-08",
    recurrence: null,
  };

  assert.deepEqual(prepareCodexExecutionDraft(draft), {
    ...draft,
    status: "todo",
    assigneeTarget: "codex-agent",
  });
  assert.equal(prepareCodexExecutionDraft(draft).developmentContext, developmentContext);
  assert.equal(prepareCodexExecutionDraft(draft).dueDate, "2026-08-08");
});

test("a bound worktree or checked-out branch selects the exact Codex workspace", () => {
  const contexts = [
    { type: "branch", branch: "main" },
    {
      type: "worktree",
      path: "/workspace/project/.worktrees/feature",
      branch: "codex/feature",
    },
  ];

  assert.equal(resolveCodexExecutionWorkspace({
    developmentContext: {
      type: "worktree",
      path: " /workspace/project/.worktrees/explicit ",
      branch: "codex/explicit",
    },
  }, contexts, ["/workspace/project"]), "/workspace/project/.worktrees/explicit");

  assert.equal(resolveCodexExecutionWorkspace({
    developmentContext: { type: "branch", branch: "codex/feature" },
  }, contexts, ["/workspace/project"]), "/workspace/project/.worktrees/feature");

  assert.equal(resolveCodexExecutionWorkspace({
    developmentContext: { type: "branch", branch: "codex/not-checked-out" },
  }, contexts, [null, " /workspace/project "]), "/workspace/project");
});

test("the editor, API, handoff, and Codex host keep the execution metadata path connected", () => {
  assert.match(editorSource, /developmentContext,\s*dueDate: dueDate \|\| null/);
  assert.match(appSource, /prepareCodexExecutionDraft\(draft\)/);
  assert.match(appSource, /createTaskRequest\(selectedProjectId, effectiveDraft\)/);
  assert.match(appSource, /openTaskInThread\(saved, \{ autoSubmit: true \}\)/);
  assert.match(apiSource, /JSON\.stringify\(\{ projectId, \.\.\.draft/);
  assert.match(appSource, /resolveCodexExecutionWorkspace\(\s*task,\s*developmentScan\.contexts/);
  assert.match(appSource, /workspacePath,\s*workspaceLabel: task\.developmentContext/);
  assert.match(injectionSource, /type: "electron-set-active-workspace-root",\s*root: workspacePath/);
});

test("the issue property sidebar drives execution context and due-date automation", () => {
  assert.match(
    detailSource,
    /ariaLabel="开发上下文"[\s\S]*?saveTask\(\{[\s\S]*?developmentContext:[\s\S]*?}, "developmentContext"\)/,
  );
  assert.match(
    detailSource,
    /type="date"[\s\S]*?saveTask\(\{[\s\S]*?dueDate: event\.target\.value \|\| null[\s\S]*?}, "dueDate"\)/,
  );
  assert.match(appSource, /function updateTaskProperties[\s\S]*?updateTaskRequest\(task,/);
  assert.match(taskCardSource, /task\.dueDate[\s\S]*?className="due-date-chip"/);
  assert.match(automationSource, /priority（urgent、high、medium、low、none）、dueDate（有日期优先且升序）/);
});
