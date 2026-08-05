import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function source(path) {
  return readFile(new URL(`../${path}`, import.meta.url), "utf8");
}

test("blocked tasks use structured exact blocking information throughout the UI", async () => {
  const [types, api, app, card, detail, editor, dialog] = await Promise.all([
    source("web/src/types.ts"),
    source("web/src/api.ts"),
    source("web/src/App.tsx"),
    source("web/src/components/TaskCard.tsx"),
    source("web/src/components/TaskDetail.tsx"),
    source("web/src/components/TaskEditor.tsx"),
    source("web/src/components/BlockTaskDialog.tsx"),
  ]);

  assert.match(types, /export interface BlockingInfo/);
  assert.match(types, /blocking: BlockingInfo \| null/);
  assert.match(api, /blocking\?: BlockingDraft/);
  assert.match(app, /requestBlockingInfo/);
  assert.match(app, /moveTaskRequest\(task, status, sortOrder, undefined, blocking\)/);
  assert.match(card, /task\.blocking\?\.reason \?\? "未记录阻塞原因"/);
  assert.match(detail, /阻塞原因/);
  assert.match(detail, /需要你做/);
  assert.match(detail, /未记录阻塞原因/);
  assert.match(editor, /只写已经确认的事实/);
  assert.match(editor, /需要你做什么/);
  assert.match(dialog, /内容将原样保存/);
  assert.match(dialog, /记录填写人和时间/);
});

