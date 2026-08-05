#!/usr/bin/env node

import { closeSync, mkdirSync, openSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
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
