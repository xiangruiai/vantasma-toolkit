import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const readSource = (relativePath) => readFile(new URL(relativePath, import.meta.url), "utf8")
  .catch(() => "");

const [selectSource, detailSource, editorSource, styles] = await Promise.all([
  readSource("../web/src/components/TaskboardSelect.tsx"),
  readSource("../web/src/components/TaskDetail.tsx"),
  readSource("../web/src/components/TaskEditor.tsx"),
  readSource("../web/src/styles.css"),
]);

test("issue property selects use the Taskboard-native popover instead of browser menus", () => {
  assert.match(detailSource, /<TaskboardSelect/);
  assert.match(editorSource, /<TaskboardSelect/);
  assert.doesNotMatch(detailSource, /<select/);
  assert.doesNotMatch(editorSource, /<select/);
  assert.match(selectSource, /createPortal/);
  assert.match(selectSource, /role="listbox"/);
  assert.match(selectSource, /role="option"/);
  assert.match(selectSource, /aria-selected=/);
  assert.match(selectSource, /event\.key === "ArrowDown"/);
  assert.match(selectSource, /event\.key === "ArrowUp"/);
  assert.match(selectSource, /event\.key === "Escape"/);
  assert.match(
    selectSource,
    /event\.key === "Escape"[\s\S]*?event\.preventDefault\(\);[\s\S]*?event\.stopPropagation\(\);[\s\S]*?closeAndFocus\(\)/,
  );
  assert.match(
    selectSource,
    /useLayoutEffect\(\(\) => \{[\s\S]*?if \(!open \|\| activeIndex < 0\) return;[\s\S]*?optionRefs\.current\[activeIndex\]\?\.focus\(\{ preventScroll: true \}\)/,
  );
  assert.match(styles, /\.taskboard-select-menu \{[\s\S]*?background: var\(--surface-raised\)/);
  assert.match(styles, /\.taskboard-select-option\[aria-selected="true"\]/);
});
