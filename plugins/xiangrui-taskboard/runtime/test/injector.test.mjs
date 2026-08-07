import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const source = await readFile(new URL("../scripts/codex-injector.mjs", import.meta.url), "utf8");
const runtimeSource = await readFile(
  new URL("../scripts/codex-injector-runtime.mjs", import.meta.url),
  "utf8",
);
const packageJson = JSON.parse(
  await readFile(new URL("../package.json", import.meta.url), "utf8"),
);
const readme = await readFile(new URL("../README.md", import.meta.url), "utf8");
const launcher = await readFile(
  new URL("../scripts/dashi-codex", import.meta.url),
  "utf8",
).catch(() => readFile(new URL("../scripts/xiangrui-codex", import.meta.url), "utf8"));
const injectorLaunchAgent = await readFile(
  new URL("../scripts/com.xiangrui.dashi-taskboard-injector.plist", import.meta.url),
  "utf8",
).catch(() => readFile(new URL("../../scripts/taskboard.mjs", import.meta.url), "utf8"));

test("the resident injector supervises the fixed local Taskboard service", () => {
  assert.match(source, /function createTaskboardSupervisor/);
  assert.match(source, /await isReachable\(taskboardHealthUrl\)/);
  assert.match(source, /ensureInFlight/);
  assert.match(source, /await supervisor\.ensure\(\)/);
  assert.match(source, /it will be restarted automatically/);
  assert.match(source, /AbortSignal\.timeout\(1_500\)/);
});

test("the CDP bridge accepts only service ensure and native Skill composer prefill actions", () => {
  assert.match(source, /const hostBindingName = "__codexTaskboardHostV1"/);
  assert.match(runtimeSource, /request\.action === "ensure"/);
  assert.match(runtimeSource, /request\.action === "prefill-task-composer"/);
  assert.match(runtimeSource, /request\.instruction\.length <= 1_024/);
  assert.match(runtimeSource, /request\.skillPath\.length <= 1_024/);
  assert.match(runtimeSource, /typeof request\.autoSubmit === "boolean"/);
  assert.match(source, /function prefillTaskComposerViaCdp/);
  assert.match(source, /cdp\.send\("Input\.insertText", \{ text: `\$\$\{skillName\}` \}\)/);
  assert.doesNotMatch(source, /Timed out while selecting the \$\{skillDisplayName\} Skill/);
  assert.match(source, /没有找到路径匹配的 \$\{skillDisplayName\} Skill/);
  assert.match(source, /data-composer-overlay-floating-ui/);
  assert.match(source, /button\[data-list-navigation-item="true"\]/);
  assert.match(source, /\[skill-mention-name\]/);
  assert.match(source, /skill-mention-path/);
  assert.match(source, /cdp\.send\("Input\.insertText", \{ text: instruction \}\)/);
  assert.match(source, /if \(!autoSubmit\) return \{ prefilled: true, submitted: false \}/);
  assert.match(source, /return \{ prefilled: true, submitted: true \}/);
  assert.match(source, /Runtime\.bindingCalled/);
  assert.match(runtimeSource, /params\.executionContextId/);
  assert.match(source, /hostResponse/);
  assert.match(source, /if \(keepAlive\) await installTaskboardHostBinding/);
  assert.match(source, /publishHostHeartbeat/);
  assert.match(source, /__codexTaskboardHostHeartbeatV1/);
});

test("foreground Taskboard handoff guards every native input and submits without a global Enter key", () => {
  assert.match(source, /async function exposeNativeTaskComposerViaCdp/);
  assert.match(source, /async function restoreNativeTaskComposerViaCdp/);
  assert.match(source, /data-codex-taskboard-native-handoff/);
  assert.match(
    source,
    /const taskboardOpen = document\.documentElement\.hasAttribute\("data-codex-taskboard-open"\)/,
  );
  assert.match(source, /if \(taskboardOpen\) node\.setAttribute\(hiddenAttribute, "true"\)/);
  assert.match(
    source,
    /await exposeNativeTaskComposerViaCdp[\s\S]*?try \{[\s\S]*?await prefillTaskComposerContentsViaCdp[\s\S]*?finally \{[\s\S]*?await restoreNativeTaskComposerViaCdp/,
  );
  assert.match(source, /async function focusTaskComposerForInputViaCdp/);
  assert.match(source, /data-codex-taskboard-native-hidden/);
  assert.match(source, /codex-taskboard-frame/);

  const skillQueryInsertion = source.indexOf('cdp.send("Input.insertText", { text: `$${skillName}` })');
  const instructionInsertion = source.indexOf('cdp.send("Input.insertText", { text: instruction })');
  assert.ok(skillQueryInsertion > 0, "the Skill query should still use native text input");
  assert.ok(instructionInsertion > 0, "the issue instruction should still use native text input");
  assert.match(
    source.slice(Math.max(0, skillQueryInsertion - 500), skillQueryInsertion),
    /await focusTaskComposerForInputViaCdp/,
  );
  assert.match(
    source.slice(Math.max(0, instructionInsertion - 500), instructionInsertion),
    /await focusTaskComposerForInputViaCdp/,
  );

  assert.doesNotMatch(source, /Input\.dispatchKeyEvent[\s\S]{0,400}?key: "Enter"/);
  assert.match(source, /button\[aria-label="发送"\]/);
  assert.match(source, /submit\.click\(\)/);
  assert.match(source, /const editorDeadline = Date\.now\(\) \+ 8_000/);
  assert.match(source, /const skillSelectionDeadline = Date\.now\(\) \+ 15_000/);
  assert.match(source, /const mentionDeadline = Date\.now\(\) \+ 5_000/);
  assert.match(source, /const instructionDeadline = Date\.now\(\) \+ 5_000/);
  const instructionDeadline = source.indexOf("const instructionDeadline = Date.now() + 5_000");
  assert.ok(
    instructionDeadline > 0 && instructionDeadline < instructionInsertion,
    "the instruction phase must be able to refocus and retry native input until its own deadline",
  );
  assert.match(
    source.slice(instructionDeadline, instructionInsertion),
    /while \(Date\.now\(\) < instructionDeadline\)[\s\S]*?await focusTaskComposerForInputViaCdp/,
  );
});

test("the CDP bridge exposes only the fixed Taskboard automation operations", () => {
  assert.match(source, /parseTaskboardAutomationHostRequest/);
  assert.match(source, /reconcileTaskboardAutomation/);
  assert.match(runtimeSource, /request\.action === "automation"/);
  assert.match(source, /function requestCodexAutomationViaCdp/);
  assert.match(source, /new Set\(\[\s*"list-automations",\s*"automation-create",\s*"automation-update",\s*\]\)/);
  assert.match(source, /bridge\.sendMessageFromView\(\{\s*type: "fetch",\s*requestId,/);
  assert.match(source, /method: "POST"/);
  assert.match(source, /vscode:\/\/codex\/\$\{method\}/);
  assert.match(source, /body: JSON\.stringify\(params\)/);
  assert.match(source, /message\.type !== "fetch-response"/);
  assert.match(source, /message\.responseType/);
  assert.match(source, /message\.status/);
  assert.match(source, /message\.bodyJsonString/);
  assert.doesNotMatch(source, /automation-delete/);
  assert.doesNotMatch(source, /automations\.toml/);
});

test("the package injection command remains resident for tab-triggered recovery", () => {
  assert.match(packageJson.scripts["codex:inject"], /--watch/);
  assert.match(packageJson.scripts["codex:daemon"], /--daemon --open/);
  assert.match(source, /function startResidentInjector/);
  assert.match(source, /const defaultCodexDebuggingPort = 9229/);
  assert.match(source, /port: defaultCodexDebuggingPort/);
  assert.match(source, /--startup-token/);
  assert.match(source, /__codexTaskboardHostStartupTokenV1/);
});

test("attach reconciles the renderer against a hashed current injection source", () => {
  assert.match(source, /createHash\("sha256"\)/);
  assert.match(source, /__CODEX_TASKBOARD_SOURCE_HASH__/);
  assert.match(source, /sourceHash: window\.__codexTaskboardInjection__\?\.sourceHash \|\| null/);
  assert.match(source, /const injectionScriptIdentifierName = "__CODEX_TASKBOARD_SCRIPT_IDENTIFIER__"/);
  assert.match(source, /scriptIdentifier: window\[\$\{JSON\.stringify\(injectionScriptIdentifierName\)\}\] \|\| null/);
  assert.match(source, /Page\.removeScriptToEvaluateOnNewDocument/);
  assert.match(source, /Page\.addScriptToEvaluateOnNewDocument/);
  assert.match(source, /reconcileInjectionRuntime/);
  assert.match(source, /expectedSourceHash/);
});

test("the injector ignores auxiliary Codex windows", () => {
  assert.match(source, /!target\.url\?\.includes\("initialRoute=%2Fglobal-dictation"\)/);
  assert.match(source, /!target\.url\?\.includes\("initialRoute=%2Favatar-overlay"\)/);
});

test("a completed web build refreshes an already-open Codex iframe", () => {
  assert.match(packageJson.scripts.build, /--refresh-if-running/);
  assert.match(packageJson.scripts["codex:refresh"], /--refresh/);
  assert.match(source, /async function refreshTaskboardFrames/);
  assert.match(source, /function codexDebuggingPorts/);
  assert.match(source, /--remote-debugging-port=/);
  assert.match(source, /taskboard\.reloadFrame\(\)/);
  assert.match(source, /__codex_taskboard_refresh/);
  assert.match(source, /await restartResidentInjectorForRefresh\(port\)/);
});

test("Codex launch commands disable Chromium local network access checks", () => {
  assert.match(source, /--disable-features=LocalNetworkAccessChecks/);
  assert.match(readme, /--disable-features=LocalNetworkAccessChecks/);
});

test("the canonical xiangrui Codex launcher detects the running app by bundle identity", () => {
  assert.match(launcher, /application id \"com\.openai\.codex\" is running/);
  assert.doesNotMatch(launcher, /pgrep/);
});

test("the persistent injector supervisor waits for Codex and recovers a missing resident", () => {
  assert.match(source, /--supervise/);
  assert.match(source, /async function superviseResidentInjector/);
  assert.match(source, /residentInjectorPids\(port\)\.length === 0/);
  assert.match(source, /startResidentInjector\(port, false, true\)/);
  assert.match(source, /stdio: \["ignore", "inherit", "inherit"\]/);
  assert.match(injectorLaunchAgent, /com\.xiangrui\.(?:dashi-taskboard|taskboard)-injector/);
  assert.match(injectorLaunchAgent, /KeepAlive[\s\S]{0,80}?<true\/>/);
  assert.match(injectorLaunchAgent, /--supervise/);
  assert.match(injectorLaunchAgent, /(?:dashi|xiangrui)-taskboard-injector\.log/);
  assert.match(injectorLaunchAgent, /(?:dashi|xiangrui)-taskboard-injector\.error\.log/);
});

test("the injector launch guard detects the running app by bundle identity", () => {
  assert.match(source, /application id \\"com\.openai\.codex\\" is running/);
  assert.doesNotMatch(source, /spawnSync\("\/usr\/bin\/pgrep"/);
});

test("the injected iframe follows the configured local service port", () => {
  assert.match(source, /const taskboardPageUrl = `\$\{taskboardOrigin\}\/\?host=codex`/);
  assert.match(source, /window\.__CODEX_TASKBOARD_URL__ = \$\{JSON\.stringify\(taskboardPageUrl\)\}/);
});
