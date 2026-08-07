import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  diagnoseSidebarIntegration,
  installSidebarIntegration,
} from "../../scripts/taskboard.mjs";
import {
  TASKBOARD_RUNTIME_PATHS,
  findTaskboardRuntimeDrift,
} from "../../../../scripts/sync-xiangrui-taskboard.mjs";

const pluginRoot = path.resolve(new URL("../..", import.meta.url).pathname);

test("macOS setup installs a stable xiangrui Codex launcher and resident injector", async () => {
  const homeDir = await mkdtemp(path.join(os.tmpdir(), "xiangrui-taskboard-setup-"));
  const result = await installSidebarIntegration({
    homeDir,
    pluginRoot,
    nodePath: process.execPath,
    platform: "darwin",
    activateLaunchAgent: false,
  });

  assert.equal(result.ok, true);
  assert.equal(result.appPath, path.join(homeDir, "Applications", "xiangrui Codex.app"));
  assert.equal(
    await realpath(path.join(homeDir, ".local", "share", "xiangrui-taskboard", "current-plugin")),
    pluginRoot,
  );

  const executable = await readFile(
    path.join(result.appPath, "Contents", "MacOS", "xiangrui-codex"),
    "utf8",
  );
  assert.match(executable, /XIANGRUI_NODE=/);
  assert.match(executable, /current-plugin\/runtime\/scripts\/xiangrui-codex/);

  const infoPlist = await readFile(path.join(result.appPath, "Contents", "Info.plist"), "utf8");
  assert.match(infoPlist, /com\.xiangrui\.taskboard-codex/);
  assert.match(infoPlist, /xiangrui Codex/);

  const launchAgent = await readFile(result.launchAgentPath, "utf8");
  assert.match(launchAgent, /com\.xiangrui\.taskboard-injector/);
  assert.match(launchAgent, /<string>--supervise<\/string>/);
  assert.match(launchAgent, /<key>KeepAlive<\/key>\s*<true\/>/);
  assert.match(
    launchAgent,
    new RegExp(`${path.join(homeDir, ".local", "share", "xiangrui-taskboard")}<\\/string>`),
  );
});

test("doctor reports exact missing stages instead of a generic startup failure", async () => {
  const diagnosis = await diagnoseSidebarIntegration({
    platform: "darwin",
    nodeVersion: "22.5.0",
    codexAppExists: true,
    launcherInstalled: true,
    pluginLinkCurrent: true,
    serviceHealthy: false,
    cdpReachable: false,
    rendererAvailable: false,
    injectionReady: false,
  });

  assert.equal(diagnosis.ok, false);
  assert.deepEqual(diagnosis.issues.map((issue) => issue.code), ["CDP_NOT_RUNNING"]);
  assert.match(diagnosis.issues[0].action, /xiangrui Codex/);
});

test("the launcher waits for ordinary Codex to quit and verifies injection before success", async () => {
  const launcher = await readFile(path.join(pluginRoot, "runtime", "scripts", "xiangrui-codex"), "utf8");
  assert.match(launcher, /for attempt in \{1\.\.120\}/);
  assert.match(launcher, /codex-injector\.mjs --launch --open/);
  assert.doesNotMatch(launcher, /--watch/);
  assert.match(launcher, /任务面板已经进入 Codex 左侧边栏/);
});

test("public runtime sync detects missing and changed capabilities", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "xiangrui-taskboard-sync-"));
  const sourceRoot = path.join(root, "source");
  const runtimeRoot = path.join(root, "runtime");
  await mkdir(path.join(sourceRoot, "web", "src"), { recursive: true });
  await mkdir(path.join(runtimeRoot, "web", "src"), { recursive: true });
  await writeFile(path.join(sourceRoot, "web", "src", "App.tsx"), "new\n");
  await writeFile(path.join(runtimeRoot, "web", "src", "App.tsx"), "old\n");
  await writeFile(path.join(sourceRoot, "web", "src", "types.ts"), "types\n");

  const drift = await findTaskboardRuntimeDrift({
    sourceRoot,
    runtimeRoot,
    paths: ["web/src/App.tsx", "web/src/types.ts"],
  });

  assert.deepEqual(drift, [
    { path: "web/src/App.tsx", state: "changed" },
    { path: "web/src/types.ts", state: "missing" },
  ]);
  assert.ok(TASKBOARD_RUNTIME_PATHS.includes("inject/codex-taskboard.user.js"));
  assert.ok(TASKBOARD_RUNTIME_PATHS.includes("web/src/components/ProjectNavigator.tsx"));
  assert.ok(TASKBOARD_RUNTIME_PATHS.includes("web/src/projectIdentity.mjs"));
  assert.ok(TASKBOARD_RUNTIME_PATHS.includes("scripts/codex-injector.mjs"));
});

test("the public Skill owns setup, launch and diagnosis for first use", async () => {
  const skill = await readFile(path.join(pluginRoot, "skills", "xiangrui-taskboard", "SKILL.md"), "utf8");
  assert.match(skill, /taskboard\.mjs setup/);
  assert.match(skill, /taskboard\.mjs launch/);
  assert.match(skill, /taskboard\.mjs doctor/);
  assert.match(skill, /左侧边栏/);
});
