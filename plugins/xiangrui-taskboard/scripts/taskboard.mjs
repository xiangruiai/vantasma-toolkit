#!/usr/bin/env node

import { closeSync, existsSync, mkdirSync, openSync } from "node:fs";
import {
  chmod,
  mkdir,
  realpath,
  rename,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const pluginRoot = path.resolve(path.dirname(scriptPath), "..");
const runtimeRoot = path.join(pluginRoot, "runtime");
const port = Number(process.env.CODEX_TASKBOARD_PORT || 47823);
const origin = `http://127.0.0.1:${port}`;
const dataRoot = path.resolve(
  process.env.XIANGRUI_TASKBOARD_DATA_DIR
    || path.join(os.homedir(), ".local", "share", "xiangrui-taskboard"),
);
const sidebarPort = 9231;
const sidebarLabel = "com.xiangrui.taskboard-injector";

function xmlEscape(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

function appInfoPlist() {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>xiangrui Codex</string>
  <key>CFBundleExecutable</key>
  <string>xiangrui-codex</string>
  <key>CFBundleIdentifier</key>
  <string>com.xiangrui.taskboard-codex</string>
  <key>CFBundleName</key>
  <string>xiangrui Codex</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.2.1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
</dict>
</plist>
`;
}

function appExecutable(nodePath, stablePluginRoot) {
  const launcherPath = path.join(stablePluginRoot, "runtime", "scripts", "xiangrui-codex");
  return `#!/bin/zsh
set -euo pipefail

readonly XIANGRUI_NODE=${shellQuote(nodePath)}
readonly XIANGRUI_LAUNCHER=${shellQuote(launcherPath)}

if [[ ! -x "$XIANGRUI_NODE" ]]; then
  /usr/bin/osascript -e 'display alert "xiangrui Codex 启动失败" message "安装时使用的 Node.js 已不存在，请在普通 Codex 中重新运行任务面板设置。" as critical'
  exit 1
fi

if [[ ! -x "$XIANGRUI_LAUNCHER" ]]; then
  /usr/bin/osascript -e 'display alert "xiangrui Codex 启动失败" message "任务面板插件已移动或更新，请在普通 Codex 中重新运行任务面板设置。" as critical'
  exit 1
fi

export XIANGRUI_NODE
exec "$XIANGRUI_LAUNCHER"
`;
}

function injectorLaunchAgent({ nodePath, stablePluginRoot, homeDir, taskboardDataRoot }) {
  const injectorPath = path.join(stablePluginRoot, "runtime", "scripts", "codex-injector.mjs");
  const runtimeRoot = path.join(stablePluginRoot, "runtime");
  const logPath = path.join(homeDir, "Library", "Logs", "xiangrui-taskboard-injector.log");
  const errorLogPath = path.join(homeDir, "Library", "Logs", "xiangrui-taskboard-injector.error.log");
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${sidebarLabel}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${xmlEscape(nodePath)}</string>
    <string>${xmlEscape(injectorPath)}</string>
    <string>--supervise</string>
    <string>--port</string>
    <string>${sidebarPort}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${xmlEscape(runtimeRoot)}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CODEX_TASKBOARD_HOST</key>
    <string>127.0.0.1</string>
    <key>CODEX_TASKBOARD_PORT</key>
    <string>${port}</string>
    <key>CODEX_TASKBOARD_DATA_DIR</key>
    <string>${xmlEscape(taskboardDataRoot)}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>5</integer>
  <key>StandardOutPath</key>
  <string>${xmlEscape(logPath)}</string>
  <key>StandardErrorPath</key>
  <string>${xmlEscape(errorLogPath)}</string>
</dict>
</plist>
`;
}

async function run(command, args) {
  const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const code = await new Promise((resolve) => child.once("exit", (value) => resolve(value ?? 1)));
  return { code, stdout, stderr };
}

async function activateInjectorLaunchAgent(launchAgentPath) {
  const domain = `gui/${process.getuid()}`;
  await run("/bin/launchctl", ["bootout", `${domain}/${sidebarLabel}`]);
  const bootstrap = await run("/bin/launchctl", ["bootstrap", domain, launchAgentPath]);
  if (bootstrap.code !== 0) {
    throw new Error(`无法启用任务面板常驻服务：${bootstrap.stderr.trim() || bootstrap.stdout.trim()}`);
  }
  const kickstart = await run("/bin/launchctl", ["kickstart", "-k", `${domain}/${sidebarLabel}`]);
  if (kickstart.code !== 0) {
    throw new Error(`任务面板常驻服务未能启动：${kickstart.stderr.trim() || kickstart.stdout.trim()}`);
  }
}

export async function installSidebarIntegration({
  homeDir = os.homedir(),
  pluginRoot: sourcePluginRoot = pluginRoot,
  nodePath = process.execPath,
  platform = process.platform,
  activateLaunchAgent = true,
} = {}) {
  if (platform !== "darwin") {
    return {
      ok: false,
      code: "UNSUPPORTED_PLATFORM",
      message: "Codex 左侧边栏一键集成目前支持 macOS；当前系统仍可使用浏览器版任务面板。",
    };
  }

  const stableRoot = path.join(homeDir, ".local", "share", "xiangrui-taskboard");
  const stablePluginRoot = path.join(stableRoot, "current-plugin");
  const nextPluginLink = `${stablePluginRoot}.next-${process.pid}-${Date.now()}`;
  const appPath = path.join(homeDir, "Applications", "xiangrui Codex.app");
  const contentsPath = path.join(appPath, "Contents");
  const executablePath = path.join(contentsPath, "MacOS", "xiangrui-codex");
  const launchAgentPath = path.join(
    homeDir,
    "Library",
    "LaunchAgents",
    `${sidebarLabel}.plist`,
  );

  await mkdir(stableRoot, { recursive: true, mode: 0o700 });
  await symlink(await realpath(sourcePluginRoot), nextPluginLink, "dir");
  await rename(nextPluginLink, stablePluginRoot);
  await mkdir(path.dirname(executablePath), { recursive: true });
  await mkdir(path.dirname(launchAgentPath), { recursive: true });
  await mkdir(path.join(homeDir, "Library", "Logs"), { recursive: true });
  await writeFile(path.join(contentsPath, "Info.plist"), appInfoPlist(), { mode: 0o644 });
  await writeFile(executablePath, appExecutable(nodePath, stablePluginRoot), { mode: 0o755 });
  await chmod(executablePath, 0o755);
  await writeFile(
    launchAgentPath,
    injectorLaunchAgent({
      nodePath,
      stablePluginRoot,
      homeDir,
      taskboardDataRoot: stableRoot,
    }),
    { mode: 0o644 },
  );
  if (activateLaunchAgent) await activateInjectorLaunchAgent(launchAgentPath);

  return {
    ok: true,
    appPath,
    launchAgentPath,
    pluginRoot: await realpath(stablePluginRoot),
    requiresRelaunch: true,
  };
}

export async function diagnoseSidebarIntegration(observed) {
  const issues = [];
  const [nodeMajor, nodeMinor] = observed.nodeVersion.split(".").map(Number);
  const nodeSupported = nodeMajor > 22 || (nodeMajor === 22 && nodeMinor >= 5);
  if (observed.platform !== "darwin") {
    issues.push({
      code: "UNSUPPORTED_PLATFORM",
      message: "当前系统不支持 Codex 左侧边栏一键集成。",
      action: "使用浏览器版任务面板。",
    });
  } else if (!nodeSupported) {
    issues.push({
      code: "NODE_TOO_OLD",
      message: `Node.js ${observed.nodeVersion} 低于任务面板要求。`,
      action: "升级到 Node.js 22.5 或更高版本后重新设置。",
    });
  } else if (!observed.codexAppExists) {
    issues.push({
      code: "CODEX_APP_MISSING",
      message: "没有找到 Codex 桌面应用。",
      action: "先把 Codex 安装到 /Applications，再重新设置任务面板。",
    });
  } else if (!observed.launcherInstalled) {
    issues.push({
      code: "LAUNCHER_NOT_INSTALLED",
      message: "xiangrui Codex 启动器尚未安装。",
      action: "运行 taskboard.mjs setup 安装侧栏启动器。",
    });
  } else if (!observed.pluginLinkCurrent) {
    issues.push({
      code: "PLUGIN_LINK_STALE",
      message: "侧栏启动器仍指向旧版或已移动的插件。",
      action: "重新运行 taskboard.mjs setup 更新稳定入口。",
    });
  } else if (!observed.cdpReachable) {
    issues.push({
      code: "CDP_NOT_RUNNING",
      message: `Codex 没有以本机调试端口 ${sidebarPort} 启动。`,
      action: "退出普通 Codex，并从“应用程序”里的 xiangrui Codex 重新打开。",
    });
  } else if (!observed.rendererAvailable) {
    issues.push({
      code: "CODEX_RENDERER_MISSING",
      message: "调试端口已启动，但 Codex 主界面还没有就绪。",
      action: "等待主界面加载后再次运行 doctor。",
    });
  } else if (!observed.serviceHealthy) {
    issues.push({
      code: "SERVICE_NOT_RUNNING",
      message: "任务面板本地服务当前没有响应。",
      action: "运行 taskboard.mjs start；若仍失败，查看任务面板日志。",
    });
  } else if (!observed.injectionReady) {
    issues.push({
      code: "INJECTION_MISSING",
      message: "Codex 主界面存在，但任务面板注入尚未生效。",
      action: "重新打开 xiangrui Codex；常驻服务会重新注入当前版本。",
    });
  }
  return { ok: issues.length === 0, observed, issues };
}

async function probeInjection(target) {
  if (!target?.webSocketDebuggerUrl || typeof WebSocket !== "function") return false;
  return new Promise((resolve) => {
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    const timer = setTimeout(() => {
      socket.close();
      resolve(false);
    }, 2_000);
    const settle = (value) => {
      clearTimeout(timer);
      socket.close();
      resolve(value);
    };
    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({
        id: 1,
        method: "Runtime.evaluate",
        params: {
          expression: "typeof window.__codexTaskboardInjection__?.refresh === 'function'",
          returnByValue: true,
        },
      }));
    });
    socket.addEventListener("message", (event) => {
      try {
        const message = JSON.parse(String(event.data));
        if (message.id === 1) settle(message.result?.result?.value === true);
      } catch {
        settle(false);
      }
    });
    socket.addEventListener("error", () => settle(false));
  });
}

async function collectSidebarObservation() {
  const homeDir = os.homedir();
  const stablePluginRoot = path.join(homeDir, ".local", "share", "xiangrui-taskboard", "current-plugin");
  const appPath = path.join(homeDir, "Applications", "xiangrui Codex.app");
  const launchAgentPath = path.join(homeDir, "Library", "LaunchAgents", `${sidebarLabel}.plist`);
  const codexAppExists = existsSync("/Applications/ChatGPT.app") || existsSync("/Applications/Codex.app");
  const launcherInstalled = existsSync(path.join(appPath, "Contents", "MacOS", "xiangrui-codex"))
    && existsSync(launchAgentPath);
  let pluginLinkCurrent = false;
  try {
    pluginLinkCurrent = await realpath(stablePluginRoot) === await realpath(pluginRoot);
  } catch {}

  let cdpReachable = false;
  let rendererAvailable = false;
  let injectionReady = false;
  try {
    const versionResponse = await fetch(`http://127.0.0.1:${sidebarPort}/json/version`, {
      signal: AbortSignal.timeout(1_500),
    });
    cdpReachable = versionResponse.ok;
    if (cdpReachable) {
      const targetsResponse = await fetch(`http://127.0.0.1:${sidebarPort}/json/list`, {
        signal: AbortSignal.timeout(1_500),
      });
      const targets = targetsResponse.ok ? await targetsResponse.json() : [];
      const target = targets.find((candidate) => (
        candidate.type === "page"
        && candidate.webSocketDebuggerUrl
        && !candidate.url?.includes("initialRoute=%2Fglobal-dictation")
        && !candidate.url?.includes("initialRoute=%2Favatar-overlay")
        && (candidate.url?.startsWith("app://") || candidate.title === "Codex")
      ));
      rendererAvailable = Boolean(target);
      injectionReady = target ? await probeInjection(target) : false;
    }
  } catch {}

  return {
    platform: process.platform,
    nodeVersion: process.versions.node,
    codexAppExists,
    launcherInstalled,
    pluginLinkCurrent,
    serviceHealthy: await isHealthy(),
    cdpReachable,
    rendererAvailable,
    injectionReady,
  };
}

function runtimeEnv() {
  return {
    ...process.env,
    CODEX_TASKBOARD_HOST: "127.0.0.1",
    CODEX_TASKBOARD_PORT: String(port),
    CODEX_TASKBOARD_DATA_DIR: dataRoot,
  };
}

async function isHealthy() {
  try {
    const response = await fetch(`${origin}/health`, { signal: AbortSignal.timeout(1_500) });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitUntilHealthy(timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isHealthy()) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`祥瑞任务面板未能在 ${origin} 启动`);
}

export async function ensureServer() {
  if (await isHealthy()) return { origin, started: false };

  await mkdir(dataRoot, { recursive: true });
  const logPath = path.join(dataRoot, "taskboard.log");
  const pidPath = path.join(dataRoot, "taskboard.pid");
  const logFd = openSync(logPath, "a");
  const child = spawn(process.execPath, [path.join(runtimeRoot, "server", "index.mjs")], {
    cwd: runtimeRoot,
    detached: true,
    env: runtimeEnv(),
    stdio: ["ignore", logFd, logFd],
  });
  child.unref();
  closeSync(logFd);
  await writeFile(pidPath, `${child.pid}\n`, { mode: 0o600 });
  await waitUntilHealthy();
  return { origin, started: true };
}

function openUrl(url) {
  let command;
  let args;
  if (process.platform === "darwin") {
    command = "/usr/bin/open";
    args = [url];
  } else if (process.platform === "win32") {
    command = "cmd";
    args = ["/c", "start", "", url];
  } else {
    command = "xdg-open";
    args = [url];
  }
  const child = spawn(command, args, { detached: true, stdio: "ignore" });
  child.unref();
}

function readPort(argv) {
  const index = argv.indexOf("--port");
  if (index === -1) return 9231;
  const value = Number(argv[index + 1]);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error("--port 必须是 1 到 65535 之间的整数");
  }
  return value;
}

async function inject(argv) {
  await ensureServer();
  const cdpPort = readPort(argv);
  const child = spawn(
    process.execPath,
    [path.join(runtimeRoot, "scripts", "codex-injector.mjs"), "--daemon", "--open", "--port", String(cdpPort)],
    { cwd: runtimeRoot, env: runtimeEnv(), stdio: "inherit" },
  );
  const exitCode = await new Promise((resolve) => child.once("exit", (code) => resolve(code ?? 1)));
  if (exitCode !== 0) process.exitCode = exitCode;
}

async function main() {
  mkdirSync(dataRoot, { recursive: true });
  const [command = "open", ...args] = process.argv.slice(2);

  if (command === "setup") {
    process.stdout.write(`${JSON.stringify(await installSidebarIntegration())}\n`);
    return;
  }

  if (command === "launch") {
    const setup = await installSidebarIntegration();
    if (!setup.ok) {
      await ensureServer();
      openUrl(origin);
      process.stdout.write(`${JSON.stringify({ ...setup, fallback: "browser", origin })}\n`);
      return;
    }
    const child = spawn("/usr/bin/open", ["-a", setup.appPath], {
      detached: true,
      stdio: "ignore",
    });
    child.unref();
    process.stdout.write(`${JSON.stringify({ ok: true, appPath: setup.appPath, launching: true })}\n`);
    return;
  }

  if (command === "doctor") {
    const diagnosis = await diagnoseSidebarIntegration(await collectSidebarObservation());
    process.stdout.write(`${JSON.stringify(diagnosis)}\n`);
    if (!diagnosis.ok) process.exitCode = 2;
    return;
  }

  if (command === "status") {
    process.stdout.write(`${JSON.stringify({ ok: await isHealthy(), origin, dataRoot })}\n`);
    return;
  }

  if (command === "start") {
    process.stdout.write(`${JSON.stringify({ ok: true, ...(await ensureServer()), dataRoot })}\n`);
    return;
  }

  if (command === "open") {
    await ensureServer();
    openUrl(origin);
    process.stdout.write(`${JSON.stringify({ ok: true, origin, dataRoot })}\n`);
    return;
  }

  if (command === "inject") {
    await inject(args);
    return;
  }

  throw new Error(`未知命令：${command}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
