import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const readSource = (relativePath) => readFile(new URL(relativePath, import.meta.url), "utf8");

const [appSource, editorSource, labelPickerSource] = await Promise.all([
  readSource("../web/src/App.tsx"),
  readSource("../web/src/components/TaskEditor.tsx"),
  readSource("../web/src/components/LabelPicker.tsx"),
]);

test("taskboard-facing prompts use natural Chinese copy", () => {
  assert.match(editorSource, /placeholder="议题标题"/);
  assert.match(editorSource, /placeholder="添加描述…"/);
  assert.match(labelPickerSource, /placeholder="添加标签…"/);

  assert.match(appSource, /加载议题时出现问题。/);
  assert.match(appSource, /此议题已在其他位置更新，任务面板已刷新。/);
  assert.match(appSource, /<strong>任务面板需要处理<\/strong>/);
  assert.match(appSource, />\s*重试\s*<\/button>/);
  assert.match(appSource, /aria-label="正在加载议题"/);
  assert.match(appSource, /aria-label="议题看板"/);
  assert.match(appSource, /aria-label="任务面板导航"/);

  const userFacingSources = `${appSource}\n${editorSource}\n${labelPickerSource}`;
  for (const englishPrompt of [
    "Issue title",
    "Add description…",
    "Add labels…",
    "Something went wrong while loading your issues.",
    "That issue changed elsewhere. The board has been refreshed.",
    "Taskboard needs attention",
    "Try again",
    "Loading issues",
    "Issue board",
    "Taskboard navigation",
  ]) {
    assert.doesNotMatch(userFacingSources, new RegExp(englishPrompt.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});
