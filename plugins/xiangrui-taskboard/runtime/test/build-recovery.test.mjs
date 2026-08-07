import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { reloadIfTaskboardBuildStale } from "../web/src/build-recovery.ts";

test("an embedded taskboard reloads itself when the server has a newer web build", async () => {
  const replacements = [];
  const stale = await reloadIfTaskboardBuildStale({
    currentAssetUrls: [
      "http://127.0.0.1:47823/assets/index-old.js",
      "http://127.0.0.1:47823/assets/index-old.css",
    ],
    fetchImpl: async () => ({
      ok: true,
      text: async () => `
        <script type="module" src="/assets/index-new.js"></script>
        <link rel="stylesheet" href="/assets/index-new.css">
      `,
    }),
    locationRef: {
      href: "http://127.0.0.1:47823/?host=codex&project=dashi-taskboard",
      origin: "http://127.0.0.1:47823",
      replace: (url) => replacements.push(url),
    },
    now: () => 1_234_567,
  });

  assert.equal(stale, true);
  assert.equal(replacements.length, 1);
  const replacement = new URL(replacements[0]);
  assert.equal(replacement.searchParams.get("project"), "dashi-taskboard");
  assert.equal(replacement.searchParams.get("__codex_taskboard_refresh"), "build-qglj");
});

test("the current taskboard build remains mounted", async () => {
  let replacement = null;
  const stale = await reloadIfTaskboardBuildStale({
    currentAssetUrls: [
      "http://127.0.0.1:47823/assets/index-current.js",
      "http://127.0.0.1:47823/assets/index-current.css",
    ],
    fetchImpl: async () => ({
      ok: true,
      text: async () => `
        <link rel="stylesheet" href="/assets/index-current.css">
        <script type="module" src="/assets/index-current.js"></script>
      `,
    }),
    locationRef: {
      href: "http://127.0.0.1:47823/?host=codex",
      origin: "http://127.0.0.1:47823",
      replace: (url) => { replacement = url; },
    },
  });

  assert.equal(stale, false);
  assert.equal(replacement, null);
});

test("Codex host context checks for a stale embedded build before continuing", async () => {
  const appSource = await readFile(new URL("../web/src/App.tsx", import.meta.url), "utf8");
  assert.match(appSource, /import \{ reloadIfTaskboardBuildStale \} from "\.\/build-recovery"/);
  assert.match(
    appSource,
    /message\.type !== "taskboard:host-context"[\s\S]*?reloadIfTaskboardBuildStale\(\)/,
  );
});
