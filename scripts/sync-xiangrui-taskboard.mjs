#!/usr/bin/env node

import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const toolkitRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const defaultRuntimeRoot = path.join(toolkitRoot, "plugins", "xiangrui-taskboard", "runtime");
const pluginManifestPath = path.join(
  toolkitRoot,
  "plugins",
  "xiangrui-taskboard",
  ".codex-plugin",
  "plugin.json",
);

const runtimeRoots = [
  "cli",
  "cloud",
  "docs",
  "inject",
  "server",
  "shared",
  "skills/manage-taskboard",
  "test",
  "web",
];

const runtimeFiles = [
  "scripts/codex-injector-runtime.mjs",
  "scripts/codex-injector.mjs",
  "scripts/codex-rate-limits.mjs",
  "scripts/dev.mjs",
  "scripts/migrate-to-cloud.mjs",
  "scripts/wrangler-cloud-adapter.mjs",
  "wrangler.jsonc",
];

export const TASKBOARD_RUNTIME_PATHS = Object.freeze([
  "inject/codex-taskboard.user.js",
  "scripts/codex-injector.mjs",
  "server/app.mjs",
  "server/database.mjs",
  "shared/direct-goal-dispatch.mjs",
  "web/src/App.tsx",
  "web/src/components/ProjectNavigator.tsx",
  "web/src/components/RelatedConversations.tsx",
  "web/src/components/TaskboardSelect.tsx",
  "web/src/projectIdentity.mjs",
]);

async function walkFiles(root, relativeRoot) {
  const absoluteRoot = path.join(root, relativeRoot);
  const entries = await readdir(absoluteRoot, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    if (entry.name === "node_modules" || entry.name === ".DS_Store") continue;
    const relativePath = path.posix.join(relativeRoot.split(path.sep).join(path.posix.sep), entry.name);
    if (entry.isDirectory()) files.push(...await walkFiles(root, relativePath));
    else if (entry.isFile()) files.push(relativePath);
  }
  return files;
}

export async function collectTaskboardRuntimePaths(sourceRoot) {
  const paths = [...runtimeFiles];
  for (const root of runtimeRoots) paths.push(...await walkFiles(sourceRoot, root));
  return [...new Set(paths)].sort();
}

async function contentHash(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

export async function findTaskboardRuntimeDrift({
  sourceRoot,
  runtimeRoot = defaultRuntimeRoot,
  paths,
}) {
  const drift = [];
  for (const relativePath of paths) {
    const sourcePath = path.join(sourceRoot, relativePath);
    const runtimePath = path.join(runtimeRoot, relativePath);
    let runtimeHash;
    try {
      runtimeHash = await contentHash(runtimePath);
    } catch (error) {
      if (error?.code === "ENOENT") {
        drift.push({ path: relativePath, state: "missing" });
        continue;
      }
      throw error;
    }
    if (runtimeHash !== await contentHash(sourcePath)) {
      drift.push({ path: relativePath, state: "changed" });
    }
  }
  return drift;
}

async function synchronizedPackage(sourceRoot) {
  const sourcePackage = JSON.parse(await readFile(path.join(sourceRoot, "package.json"), "utf8"));
  const pluginManifest = JSON.parse(await readFile(pluginManifestPath, "utf8"));
  return {
    ...sourcePackage,
    name: "xiangrui-taskboard-runtime",
    version: pluginManifest.version,
    private: true,
  };
}

async function packageDrift(sourceRoot, runtimeRoot) {
  const expected = synchronizedPackage(sourceRoot);
  const actual = JSON.parse(await readFile(path.join(runtimeRoot, "package.json"), "utf8"));
  return JSON.stringify(actual) === JSON.stringify(await expected)
    ? []
    : [{ path: "package.json", state: "changed" }];
}

export async function syncTaskboardRuntime({
  sourceRoot,
  runtimeRoot = defaultRuntimeRoot,
  paths,
}) {
  for (const relativePath of paths) {
    const sourcePath = path.join(sourceRoot, relativePath);
    const runtimePath = path.join(runtimeRoot, relativePath);
    await mkdir(path.dirname(runtimePath), { recursive: true });
    await copyFile(sourcePath, runtimePath);
    const sourceMode = (await stat(sourcePath)).mode & 0o777;
    if (sourceMode) await import("node:fs/promises").then(({ chmod }) => chmod(runtimePath, sourceMode));
  }
  await writeFile(
    path.join(runtimeRoot, "package.json"),
    `${JSON.stringify(await synchronizedPackage(sourceRoot), null, 2)}\n`,
  );
  return { copied: paths.length, runtimeRoot };
}

function parseArgs(argv) {
  const options = { sourceRoot: null, check: false, write: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--source") options.sourceRoot = path.resolve(argv[++index] || "");
    else if (argument === "--check") options.check = true;
    else if (argument === "--write") options.write = true;
    else throw new Error(`未知参数：${argument}`);
  }
  if (!options.sourceRoot) throw new Error("必须通过 --source 指定 dashi-taskboard 开发源目录");
  if (options.check === options.write) throw new Error("必须且只能选择 --check 或 --write");
  return options;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const paths = await collectTaskboardRuntimePaths(options.sourceRoot);
  if (options.write) {
    const result = await syncTaskboardRuntime({ sourceRoot: options.sourceRoot, paths });
    process.stdout.write(`${JSON.stringify({ ok: true, ...result })}\n`);
    return;
  }
  const drift = [
    ...await findTaskboardRuntimeDrift({ sourceRoot: options.sourceRoot, paths }),
    ...await packageDrift(options.sourceRoot, defaultRuntimeRoot),
  ];
  process.stdout.write(`${JSON.stringify({ ok: drift.length === 0, drift })}\n`);
  if (drift.length > 0) process.exitCode = 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
