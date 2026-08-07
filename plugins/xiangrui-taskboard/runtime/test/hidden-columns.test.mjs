import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const appSource = await readFile(new URL("../web/src/App.tsx", import.meta.url), "utf8");
const settingsSource = await readFile(new URL("../web/src/components/BoardSettingsMenu.tsx", import.meta.url), "utf8");
const boardColumnSource = await readFile(new URL("../web/src/components/BoardColumn.tsx", import.meta.url), "utf8");
const iconSource = await readFile(new URL("../web/src/components/LinearIcon.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../web/src/styles.css", import.meta.url), "utf8");

test("statuses with work come first while every workflow status remains on the board", () => {
  assert.match(appSource, /const orderedStatuses = useMemo\(\(\) => \{[\s\S]*?const hasVisibleTask/);
  assert.match(appSource, /\.\.\.TASK_STATUSES\.filter\(hasVisibleTask\)/);
  assert.match(appSource, /\.\.\.TASK_STATUSES\.filter\(\(status\) => !hasVisibleTask\(status\)\)/);
  assert.match(appSource, /orderedStatuses\.map\(\(status\) =>/);
  assert.match(appSource, /statusIndex=\{TASK_STATUSES\.indexOf\(status\)\}/);
  assert.doesNotMatch(appSource, /<HiddenColumns|hiddenStatuses|visibleStatuses/);
});

test("the active product no longer persists empty-column visibility state", () => {
  assert.doesNotMatch(appSource, /SHOW_EMPTY_COLUMNS_KEY|showEmptyColumns|readShowEmptyColumns/);
  assert.doesNotMatch(appSource, /<BoardSettingsMenu/);
});

test("columns have no manual hide action and remain full-height drop targets", () => {
  assert.doesNotMatch(appSource, /COLUMN_VISIBILITY_KEY|columnVisibility|updateColumnVisibility/);
  assert.doesNotMatch(boardColumnSource, /onHide|ColumnVisibilityMenu|隐藏列/);
  assert.match(boardColumnSource, /onDrop=\{handleDrop\}/);
  assert.match(styles, /\.board-column\s*\{[\s\S]*?min-height:\s*0;/);
});

test("each visible status accepts ordered task drops directly", () => {
  assert.match(boardColumnSource, /application\/x-taskboard-task/);
  assert.match(boardColumnSource, /onDrop\(status, taskId, findDropBefore/);
  assert.match(appSource, /onDrop=\{finishTaskDrop\}/);
});

test("display options uses the centralized Linear sliders asset", () => {
  assert.match(settingsSource, /<LinearIcon name="displayOptions" \/>/);
  assert.doesNotMatch(settingsSource, /<svg/);
  assert.match(iconSource, /displayOptions: \{/);
  assert.match(iconSource, /M7 2\.5C8\.11933 2\.5/);
  assert.match(styles, /\.board-settings-menu/);
  assert.match(styles, /\.board-setting-switch\.is-on/);
});

test("settings focus enters the portal and returns to the trigger on Escape", () => {
  assert.match(settingsSource, /requestAnimationFrame\(\(\) => menuRef\.current\?\.querySelector<HTMLButtonElement>\("\[role='switch'\]"\)\?\.focus\(\)\)/);
  assert.match(settingsSource, /event\.key === "Escape"[\s\S]*?triggerRef\.current\?\.focus\(\)/);
  assert.match(settingsSource, /event\.key === "Tab"[\s\S]*?event\.preventDefault\(\)/);
});
