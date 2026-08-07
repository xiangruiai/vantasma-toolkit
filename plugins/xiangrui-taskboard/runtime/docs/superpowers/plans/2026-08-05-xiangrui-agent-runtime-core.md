# 祥瑞 Agent Runtime Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有「祥瑞」看板中完成 Codex、Claude Code、OpenClaw 三种本地 Agent 的注册、分配、执行、实时状态和提交审核闭环。

**Architecture:** 现有 Node Server 作为 Control Plane，新增独立 Node Runtime Daemon，由 Daemon 主动通过认证 WebSocket 连接 Server。Daemon 通过统一 Adapter 启动本地 CLI，Run 和 Run Event 由现有 SQLite 保存，UI 继续使用现有 SSE 接收变更提示。

**Tech Stack:** Node.js 22、原生 HTTP Server、`ws`、SQLite、React 19、TypeScript、现有 SSE、Codex CLI、Claude Code CLI、OpenClaw CLI。

---

## 0. 仓库规则与执行边界

本计划以已批准的设计为准：

- `docs/superpowers/specs/2026-08-05-xiangrui-multi-agent-platform-design.md`

仓库 `AGENTS.md` 明确要求先打通真实操作路径，并且在祥瑞确认前不扩张保护性测试。它高于 `writing-plans` Skill 的通用 TDD 约定，因此本计划不预先新增 mutation、regression 或兼容性测试。每个主路径完成后先在真实产品中验证，交给祥瑞确认；只有祥瑞明确要求或报告具体失败时，再补 targeted regression。

当前主工作区存在大量非本功能的未提交修改。执行者必须：

1. 不覆盖、不暂存、不提交这些已有修改。
2. 每次提交前检查 `git diff --cached --name-only`，只允许出现当前子任务列出的文件。
3. 如果目标文件存在重叠修改，先停止写入并把冲突文件报告给主对话，由主对话决定顺序。

## 1. 已证明的真实操作路径

当前任务路径：

```text
TaskEditor.tsx
  → web/src/api.ts POST /api/tasks
  → server/app.mjs
  → server/database.mjs SQLite
  → EventHub SSE
  → React UI 可见任务
```

当前 Codex AI Chat 路径：

```text
AiChat.tsx
  → POST /api/local/ai/threads/:id/turns
  → AiChatService.startTurn()
  → spawnCodexTurn()
  → ai_chat_runs / ai_chat_events
  → thread SSE
  → AiChat UI 可见输出
```

Phase 1 要新增的路径：

```text
TaskDetail.tsx 选择 Agent 并点击执行
  → POST /api/tasks/:id/runs
  → AgentControlService 创建 queued Run，并把任务移到 in_progress
  → RuntimeGateway 通过 WebSocket 分配 Run
  → Runtime Daemon 选择 Agent Adapter 并启动 CLI
  → run.event 消息写入 run_events，并通过现有 SSE 通知 UI
  → run.complete 写结果评论，把任务移到 in_review
  → TaskDetail 显示结果和 Run 历史
```

## 2. 文件结构锁定

### 新建文件

- `shared/agent-runtime.mjs`：跨 Server、Daemon 使用的状态、权限、消息类型和校验函数。
- `shared/agent-runtime.d.mts`：共享运行时契约的 TypeScript 声明。
- `server/agent-control.mjs`：Agent、Runtime、Run 的业务服务，不处理 HTTP 细节。
- `server/runtime-gateway.mjs`：WebSocket 鉴权、连接表、分配和事件接收。
- `runtime/config.mjs`：Daemon 配置创建、读取和权限设置。
- `runtime/client.mjs`：Daemon WebSocket 客户端、重连和消息发送。
- `runtime/process-runner.mjs`：统一子进程生命周期、JSONL 读取、中断和退出归一化。
- `runtime/adapter-registry.mjs`：Adapter 注册、检测和 provider 路由。
- `runtime/adapters/codex.mjs`：Codex CLI Adapter。
- `runtime/adapters/claude-code.mjs`：Claude Code CLI Adapter。
- `runtime/adapters/openclaw.mjs`：OpenClaw CLI Adapter。
- `runtime/index.mjs`：`setup`、`start`、`status` 命令入口。
- `web/src/components/AgentRunPanel.tsx`：任务内 Agent 选择、执行控制和 Run 历史。
- `web/src/components/AgentRuntimeSettings.tsx`：Agent 与 Runtime 的最小管理页面。

### 修改文件

- `package.json`：增加 `ws` 和 Runtime scripts。
- `package-lock.json`：锁定 `ws`。
- `server/database.mjs`：新增 Agent、Runtime、Run、Run Event 表与方法。
- `server/app.mjs`：新增 REST API、Runtime WebSocket upgrade 和 SSE 事件。
- `server/index.mjs`：Server 关闭时关闭 Runtime Gateway。
- `web/src/types.ts`：新增 Agent、Runtime、Run、RunEvent 类型。
- `web/src/api.ts`：新增 Agent、Runtime、Run API。
- `web/src/actors.ts`：将动态 Agent 转为任务 Actor，同时保留旧 Codex Actor 兼容入口。
- `web/src/components/TaskDetail.tsx`：接入 AgentRunPanel 和动态负责人。
- `web/src/components/TaskEditor.tsx`：新建任务时支持动态 Agent。
- `web/src/App.tsx`：加载 Agent/Runtime 数据并传给任务组件。
- `web/src/styles.css`：Run Panel 和 Runtime Settings 样式。

### Phase 1 不修改

- `cloud/`：Cloud Runtime 在 Phase 5 独立实现。
- `server/ai-chat.mjs` 与 `web/src/components/AiChat.tsx`：现有 Codex Chat 保持原路径，Phase 2 再迁移到统一 Conversation。
- Squad、Autopilot 和 Skill 数据模型：各自在后续计划实现。

## 3. Runtime 协议

所有 WebSocket 消息都是单个 JSON object。每条消息必须有 `type`。

Daemon 发往 Server：

```js
export const RUNTIME_CLIENT_MESSAGES = {
  hello: "runtime.hello",
  heartbeat: "runtime.heartbeat",
  event: "run.event",
  complete: "run.complete",
  failed: "run.failed",
};
```

Server 发往 Daemon：

```js
export const RUNTIME_SERVER_MESSAGES = {
  welcome: "runtime.welcome",
  assign: "run.assign",
  input: "run.input",
  interrupt: "run.interrupt",
};
```

Run Assignment 的固定形状：

```js
{
  type: "run.assign",
  run: {
    id: "uuid",
    taskId: "uuid",
    provider: "codex",
    workspacePath: "/absolute/path",
    permissionProfile: "workspace-write",
    instruction: "完整任务和验收标准",
    sessionId: null,
    model: null
  }
}
```

## Task 1: 共享 Runtime 契约

**Files:**

- Create: `shared/agent-runtime.mjs`
- Create: `shared/agent-runtime.d.mts`

- [ ] **Step 1: 定义固定状态和 provider**

在 `shared/agent-runtime.mjs` 写入：

```js
export const AGENT_PROVIDERS = ["codex", "claude-code", "openclaw"];
export const RUN_STATUSES = [
  "queued",
  "starting",
  "running",
  "waiting_input",
  "completed",
  "failed",
  "interrupted",
  "orphaned",
];
export const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "interrupted",
  "orphaned",
]);
export const PERMISSION_PROFILES = [
  "read-only",
  "workspace-write",
  "danger-full-access",
];

export function isAgentProvider(value) {
  return AGENT_PROVIDERS.includes(value);
}

export function isRunStatus(value) {
  return RUN_STATUSES.includes(value);
}

export function isPermissionProfile(value) {
  return PERMISSION_PROFILES.includes(value);
}
```

- [ ] **Step 2: 定义消息校验函数**

在同一文件追加：

```js
export function parseRuntimeMessage(raw) {
  let value;
  try {
    value = typeof raw === "string" ? JSON.parse(raw) : JSON.parse(raw.toString("utf8"));
  } catch {
    throw new Error("Runtime message must be valid JSON");
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Runtime message must be an object");
  }
  if (typeof value.type !== "string" || value.type.length === 0) {
    throw new Error("Runtime message type is required");
  }
  return value;
}
```

- [ ] **Step 3: 写 TypeScript declaration**

`shared/agent-runtime.d.mts` 必须导出与 JavaScript 同名的 union 和函数声明：

```ts
export type AgentProvider = "codex" | "claude-code" | "openclaw";
export type RunStatus =
  | "queued" | "starting" | "running" | "waiting_input"
  | "completed" | "failed" | "interrupted" | "orphaned";
export type PermissionProfile = "read-only" | "workspace-write" | "danger-full-access";

export const AGENT_PROVIDERS: AgentProvider[];
export const RUN_STATUSES: RunStatus[];
export const TERMINAL_RUN_STATUSES: Set<RunStatus>;
export const PERMISSION_PROFILES: PermissionProfile[];
export function isAgentProvider(value: unknown): value is AgentProvider;
export function isRunStatus(value: unknown): value is RunStatus;
export function isPermissionProfile(value: unknown): value is PermissionProfile;
export function parseRuntimeMessage(raw: string | Buffer): Record<string, unknown> & { type: string };
```

- [ ] **Step 4: 验证模块可导入**

Run:

```bash
node --input-type=module -e 'import { RUN_STATUSES, parseRuntimeMessage } from "./shared/agent-runtime.mjs"; console.log(RUN_STATUSES.length, parseRuntimeMessage("{\"type\":\"runtime.hello\"}").type)'
```

Expected: `8 runtime.hello`

- [ ] **Step 5: Commit**

```bash
git add shared/agent-runtime.mjs shared/agent-runtime.d.mts
git commit -m "feat: define agent runtime contracts"
```

## Task 2: Agent、Runtime、Run 持久化

**Files:**

- Modify: `server/database.mjs`

- [ ] **Step 1: 在现有初始化事务中追加四张表**

使用以下字段，不修改旧表：

```sql
CREATE TABLE IF NOT EXISTS runtimes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  device_id TEXT NOT NULL UNIQUE,
  token_hash TEXT NOT NULL,
  version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('offline', 'online')),
  capabilities TEXT NOT NULL DEFAULT '{}',
  workspace_allowlist TEXT NOT NULL DEFAULT '[]',
  last_heartbeat_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('codex', 'claude-code', 'openclaw')),
  avatar_url TEXT,
  description TEXT NOT NULL DEFAULT '',
  default_runtime_id TEXT,
  default_permission_profile TEXT NOT NULL CHECK (
    default_permission_profile IN ('read-only', 'workspace-write', 'danger-full-access')
  ),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (default_runtime_id) REFERENCES runtimes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  runtime_id TEXT REFERENCES runtimes(id) ON DELETE SET NULL,
  parent_run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN (
    'queued', 'starting', 'running', 'waiting_input',
    'completed', 'failed', 'interrupted', 'orphaned'
  )),
  permission_profile TEXT NOT NULL CHECK (
    permission_profile IN ('read-only', 'workspace-write', 'danger-full-access')
  ),
  workspace_path TEXT NOT NULL,
  instruction_snapshot TEXT NOT NULL,
  task_version_snapshot INTEGER NOT NULL,
  session_id TEXT,
  model TEXT,
  exit_code INTEGER,
  error_code TEXT,
  error_message TEXT,
  token_usage TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_run_events (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL,
  type TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'activity', 'error', 'system')),
  content TEXT NOT NULL,
  data TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (run_id, sequence)
);
```

SQLite 不能在建表时引用尚未创建的表，因此初始化顺序必须是 `runtimes`、`agents`、`agent_runs`、`agent_run_events`。

- [ ] **Step 2: 添加 row mapper**

新增 `agentFromRow`、`runtimeFromRow`、`agentRunFromRow`、`agentRunEventFromRow`。JSON 字段使用现有安全解析方式，没有值时返回空 object 或 array，不把 JSON 字符串直接暴露给 UI。

- [ ] **Step 3: 添加 Agent CRUD 方法**

实现：

```js
listAgents()
getAgent(id)
createAgent(input)
updateAgent(id, input)
```

创建和更新时由 Server 生成时间戳；`name`、`provider` 和 permission 已在 HTTP 边界校验。

- [ ] **Step 4: 添加 Runtime 方法**

实现：

```js
registerRuntime(input)
getRuntime(id)
getRuntimeByDeviceId(deviceId)
listRuntimes()
authenticateRuntime(id, tokenHash)
markRuntimeOnline(id, input)
markRuntimeOffline(id)
touchRuntimeHeartbeat(id, capabilities)
```

`token_hash` 永不从 mapper 返回。

- [ ] **Step 5: 添加 Run 与 Event 方法**

实现：

```js
createAgentRunAndAssignTask(input)
getAgentRun(id)
listTaskAgentRuns(taskId)
listQueuedAgentRuns(runtimeId)
assignAgentRunAndStartTask(id, runtimeId)
transitionAgentRun(id, fromStatuses, nextStatus, patch)
appendAgentRunEvent(runId, input)
listAgentRunEvents(runId)
completeAgentRunAndMoveTask(id, result)
failAgentRunAndMoveTask(id, failure)
```

`createAgentRunAndAssignTask` 在一个 `BEGIN IMMEDIATE` 中校验 task version、创建 queued Run 并更新负责人，但保持 Task 为 `todo`。`assignAgentRunAndStartTask` 在一个事务中把 queued Run 绑定 Runtime，并把 Task 移到 `in_progress`。完成和失败方法在各自单一事务中同时更新 Run、Task 和结果评论。`appendAgentRunEvent` 在 `BEGIN IMMEDIATE` 内计算 `MAX(sequence) + 1`，保证同一 Run 事件顺序稳定。

- [ ] **Step 6: 用临时数据库验证新增对象**

Run 一个不写仓库文件的 Node inline script：

```bash
node --input-type=module -e '
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { TaskboardDatabase } from "./server/database.mjs";
const dir = mkdtempSync(path.join(tmpdir(), "xiangrui-runtime-"));
const db = new TaskboardDatabase(path.join(dir, "taskboard.sqlite"));
const agent = db.createAgent({ name: "Codex", provider: "codex", avatarUrl: null, description: "", defaultRuntimeId: null, defaultPermissionProfile: "workspace-write" });
console.log(agent.name, db.listAgents().length);
db.close();
'
```

Expected: `Codex 1`

- [ ] **Step 7: Commit**

```bash
git add server/database.mjs
git commit -m "feat: persist agents runtimes and runs"
```

## Task 3: Agent Control Service 与 REST API

**Files:**

- Create: `server/agent-control.mjs`
- Modify: `server/app.mjs`

- [ ] **Step 1: 创建 AgentControlService**

服务构造函数接收 `database`、`events`、`runtimeGateway` 和 `processEnv`。实现：

```js
export class AgentControlService {
  constructor({ database, events, processEnv = process.env }) {
    this.database = database;
    this.events = events;
    this.processEnv = processEnv;
    this.runtimeGateway = null;
  }

  attachRuntimeGateway(runtimeGateway) {
    this.runtimeGateway = runtimeGateway;
  }

  listAgents() { return this.database.listAgents(); }
  listRuntimes() { return this.database.listRuntimes(); }
  listTaskRuns(taskId) { return this.database.listTaskAgentRuns(taskId); }
}
```

- [ ] **Step 2: 实现 registerRuntime**

只允许 loopback HTTP 调用注册。用 `randomBytes(32).toString("base64url")` 生成 raw token，用 `createHash("sha256")` 保存 hash。返回 raw token 仅一次：

```js
return {
  runtime: this.database.registerRuntime({ ...input, tokenHash: sha256(token) }),
  token,
};
```

- [ ] **Step 3: 实现 createRun 原子入口**

输入固定为：

```js
{
  taskId,
  taskVersion,
  agentId,
  permissionProfile,
  dangerFullAccessConfirmed,
}
```

校验顺序：任务存在且未归档、version 一致、Agent 启用、project 有 workspace、danger 权限逐次确认。Control Plane 从任务标题、描述、验收信息、评论和开发上下文生成 `instruction_snapshot`，不接收客户端复制的第二份 instruction。调用 `createAgentRunAndAssignTask` 创建 queued Run并把任务负责人改为 Agent Actor；任务保持 `todo`。只有 Gateway 成功把 Run 发给在线 Runtime 后，才调用 `assignAgentRunAndStartTask` 把任务移动到 `in_progress`。成功后 `events.emit("agent.run.created", { run, task })`。

- [ ] **Step 4: 实现 completeRun 和 failRun**

`completeRun` 调用 `completeAgentRunAndMoveTask`，并且必须：

1. 把 Run 从 `starting/running/waiting_input` 移到 `completed`。
2. 由 Control Plane 创建 `authorType: agent` 的结果评论。
3. 把任务移动到 `in_review`。
4. 发出 `agent.run.completed`。

`failRun` 调用 `failAgentRunAndMoveTask`，并根据 error kind：

- `missing_dependency`、`workspace_denied`、`needs_input` → Task `blocked`
- `process_error`、`interrupted` → Task `todo`
- Run 始终保存原 error code 和 message

- [ ] **Step 5: 在 server/app.mjs 添加 parse 函数**

新增精确 body allowlist，不接受多余字段：

```js
parseAgentCreate(body)
parseAgentPatch(body)
parseRuntimeRegistration(body)
parseAgentRunCreate(body)
parseAgentRunInput(body)
```

- [ ] **Step 6: 添加 REST routes**

新增：

```text
GET    /api/agents
POST   /api/agents
PATCH  /api/agents/:id
GET    /api/runtimes
POST   /api/runtimes/register
GET    /api/tasks/:taskId/runs
POST   /api/tasks/:taskId/runs
GET    /api/runs/:id
GET    /api/runs/:id/events
POST   /api/runs/:id/input
POST   /api/runs/:id/interrupt
```

`/api/runtimes/register` 强制 `assertLoopbackRequest`。Cloud Phase 5 另行设计注册授权。

- [ ] **Step 7: 启动 Server 并验证 Agent CRUD**

Run:

```bash
CODEX_TASKBOARD_PORT=47824 CODEX_TASKBOARD_DATA_DIR="$(mktemp -d)" npm start
```

在另一个终端创建 Agent：

```bash
curl -sS -X POST http://127.0.0.1:47824/api/agents \
  -H 'content-type: application/json' \
  -d '{"name":"Codex 主力","provider":"codex","defaultPermissionProfile":"workspace-write"}'
```

Expected: HTTP 201，response 的 Agent name 为 `Codex 主力`，且没有 credential 字段。

- [ ] **Step 8: Commit**

```bash
git add server/agent-control.mjs server/app.mjs
git commit -m "feat: add agent control api"
```

## Task 4: Runtime Gateway 与 Daemon 连接

**Files:**

- Modify: `package.json`
- Modify: `package-lock.json`
- Create: `server/runtime-gateway.mjs`
- Create: `runtime/config.mjs`
- Create: `runtime/client.mjs`
- Create: `runtime/index.mjs`
- Modify: `server/app.mjs`
- Modify: `server/index.mjs`

- [ ] **Step 1: 安装 WebSocket 依赖并添加 scripts**

Run:

```bash
npm install ws@8
```

`package.json` scripts 增加：

```json
"runtime:setup": "node runtime/index.mjs setup",
"runtime:start": "node runtime/index.mjs start",
"runtime:status": "node runtime/index.mjs status"
```

- [ ] **Step 2: 实现 RuntimeGateway**

使用 `WebSocketServer({ noServer: true })`。只接受 `/api/runtime/connect` upgrade。Header 必须有：

```text
Authorization: Bearer <runtime-token>
X-Xiangrui-Runtime-Id: <runtime-id>
```

Server 对 token 做 SHA-256 后与数据库 hash 比较。连接成功后保存 `Map<runtimeId, socket>`，标记 online，并发送 `runtime.welcome`。

- [ ] **Step 3: 接收心跳、事件和完成消息**

每种 message 都通过 `parseRuntimeMessage`。Gateway 只负责 transport，把业务动作调用到 `AgentControlService`。socket close 时标记 Runtime offline，并把该设备仍处于 `starting/running` 的 Run 标为 `orphaned`，不自动重跑。

- [ ] **Step 4: 实现分配和中断**

Gateway 暴露：

```js
assignRun(runtimeId, assignment)
sendRunInput(runtimeId, runId, input)
interruptRun(runtimeId, runId)
close()
```

`assignRun` 只在 socket OPEN 时发送；未连接时 Run 保持 queued。

- [ ] **Step 5: 实现 Daemon 配置**

默认配置路径：

```text
.data/xiangrui-runtime.json
```

`setup` 调用 loopback 注册 API，保存 `serverUrl`、`runtimeId`、`token`、`name` 和 `workspaceAllowlist`，文件 mode 固定 `0600`。命令输出只打印 runtime id 和 config path，不打印 token。

- [ ] **Step 6: 实现 WebSocket Client**

Daemon 使用全局 WebSocket，连接 `http` 转 `ws`、`https` 转 `wss`。断线重连延迟固定为：1s、2s、4s、8s、15s，上限 15s，并加 0 到 500ms 抖动。连接后发送 provider detection 和 workspace allowlist。

- [ ] **Step 7: 连接到 app 生命周期**

`createTaskboardServer()` 创建 `AgentControlService` 和 `RuntimeGateway`，互相 attach。`app.close()` 先关闭 Gateway，再关闭 HTTP Server 和 database。

- [ ] **Step 8: 验证真实连接**

Server 使用 47824，执行：

```bash
npm run runtime:setup -- --server http://127.0.0.1:47824 --name "MacBook-Pro" --workspace "$HOME/Projects"
npm run runtime:start
```

Expected: `GET /api/runtimes` 返回一个 `online` Runtime，15 秒内 `lastHeartbeatAt` 更新。

- [ ] **Step 9: Commit**

```bash
git add package.json package-lock.json server/runtime-gateway.mjs server/agent-control.mjs server/app.mjs server/index.mjs runtime/config.mjs runtime/client.mjs runtime/index.mjs
git commit -m "feat: connect local agent runtime"
```

## Task 5: 统一 Adapter 与进程执行器

**Files:**

- Create: `runtime/process-runner.mjs`
- Create: `runtime/adapter-registry.mjs`
- Modify: `runtime/index.mjs`

- [ ] **Step 1: 定义 Adapter interface 约定**

每个 Adapter 导出：

```js
{
  provider,
  async detect({ env }),
  buildInvocation(run),
  parseStdoutLine(line),
  parseStderrLine(line),
  normalizeExit({ code, signal, stderr, lastEvent })
}
```

- [ ] **Step 2: 实现 process runner**

`runAgentProcess({ invocation, adapter, emit, signal })` 使用 `spawn`：

```js
spawn(invocation.command, invocation.args, {
  cwd: invocation.cwd,
  env: invocation.env,
  detached: true,
  stdio: ["pipe", "pipe", "pipe"],
});
```

stdout 按行读取，单行上限 1 MiB；stderr 累计上限 64 KiB。每个解析事件立刻调用 `emit`。中断时先向 process group 发 `SIGTERM`，1 秒后仍未退出再发 `SIGKILL`。

- [ ] **Step 3: 实现 Adapter Registry**

```js
export function createAdapterRegistry(adapters) {
  const byProvider = new Map(adapters.map((adapter) => [adapter.provider, adapter]));
  return {
    providers: () => [...byProvider.keys()],
    get(provider) {
      const adapter = byProvider.get(provider);
      if (!adapter) throw new Error(`Unsupported agent provider '${provider}'`);
      return adapter;
    },
  };
}
```

- [ ] **Step 4: 把 run.assign 接到执行器**

Daemon 收到 assignment 后：校验 workspace 在 allowlist、选择 Adapter、发送 `starting`、启动进程、发送事件，退出后只发送一个 `run.complete` 或 `run.failed` terminal message。

- [ ] **Step 5: Commit**

```bash
git add runtime/process-runner.mjs runtime/adapter-registry.mjs runtime/index.mjs
git commit -m "feat: add agent adapter runtime"
```

## Task 6: Codex Adapter 与第一条完整主路径

**Files:**

- Create: `runtime/adapters/codex.mjs`
- Modify: `runtime/index.mjs`
- Modify: `server/agent-control.mjs`

- [ ] **Step 1: 实现 Codex detect**

使用 `codex --version`，成功时返回版本字符串和 `available: true`，ENOENT 返回 `available: false`。不使用 `which` 或 `--help`。

- [ ] **Step 2: 构建 Codex invocation**

```js
const args = [
  "exec",
  "--json",
  "--color", "never",
  "-C", run.workspacePath,
  "-s", run.permissionProfile === "read-only" ? "read-only" : run.permissionProfile,
];
if (run.model) args.push("-m", run.model);
args.push("-");
return {
  command: "codex",
  args,
  cwd: run.workspacePath,
  env: process.env,
  stdin: run.instruction,
};
```

`danger-full-access` 只在 createRun 已收到逐次确认时允许。

- [ ] **Step 3: 归一化 Codex JSONL**

复用 `server/ai-chat-process.mjs` 已验证的事件语义：

- `thread.started` → session id
- `item.* agent_message` → assistant event
- `item.* command_execution` → activity event
- `item.* file_change` → activity event with files
- `item.* mcp_tool_call` → activity or error
- `turn.completed` → usage and terminal hint
- `turn.failed`、`error` → error event

Runtime Adapter 不能导入 Database 或 Server Service。

- [ ] **Step 4: 完成 Control Plane 分配**

`AgentControlService.createRun()` 在事务完成后选择：

1. Agent 的 default Runtime 且 online、provider available、workspace allowed。
2. 否则第一个满足条件的 online Runtime。
3. 没有 Runtime 时 Run 保持 queued，Task 保持 `todo`，不移动到 `in_progress`。

只有 `assignRun` 成功后才把 Run 改成 `starting` 并把 Task 移到 `in_progress`。

- [ ] **Step 5: 验证 Codex 真实路径**

在真实 UI 创建一条任务，内容为：

```text
读取当前 workspace 的 package.json，只返回 name 字段，不编辑文件、不执行外部操作。
验收标准：结果评论必须包含 codex-taskboard。
```

选择 Codex Agent，点击执行。观察：

1. Runtime online。
2. Run `queued → starting → running → completed`。
3. 实时出现至少一条 assistant 或 activity event。
4. 结果评论包含 `codex-taskboard`。
5. 任务进入 `in_review`。

这是项目规定的主路径验收，不是回归测试。

- [ ] **Step 6: Commit**

```bash
git add runtime/adapters/codex.mjs runtime/index.mjs server/agent-control.mjs
git commit -m "feat: run Codex tasks through local runtime"
```

## Task 7: 前端 Agent、Runtime 与 Run 类型和 API

**Files:**

- Modify: `web/src/types.ts`
- Modify: `web/src/api.ts`
- Modify: `web/src/actors.ts`

- [ ] **Step 1: 新增前端类型**

```ts
export type AgentProvider = "codex" | "claude-code" | "openclaw";
export type PermissionProfile = "read-only" | "workspace-write" | "danger-full-access";
export type AgentRunStatus =
  | "queued" | "starting" | "running" | "waiting_input"
  | "completed" | "failed" | "interrupted" | "orphaned";

export interface Agent {
  id: string;
  name: string;
  provider: AgentProvider;
  avatarUrl: string | null;
  description: string;
  defaultRuntimeId: string | null;
  defaultPermissionProfile: PermissionProfile;
  enabled: boolean;
}

export interface Runtime {
  id: string;
  name: string;
  deviceId: string;
  version: string;
  status: "online" | "offline";
  capabilities: Record<string, { available: boolean; version?: string }>;
  workspaceAllowlist: string[];
  lastHeartbeatAt: string | null;
}

export interface AgentRun {
  id: string;
  taskId: string;
  agentId: string;
  runtimeId: string | null;
  status: AgentRunStatus;
  permissionProfile: PermissionProfile;
  workspacePath: string;
  errorCode: string | null;
  errorMessage: string | null;
  tokenUsage: Record<string, number> | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}
```

- [ ] **Step 2: 新增 API functions**

实现 `listAgents`、`createAgent`、`updateAgent`、`listRuntimes`、`listTaskRuns`、`createAgentRun`、`getRunEvents`、`interruptAgentRun`。全部使用现有 `request<T>()`，不另写 fetch wrapper。

- [ ] **Step 3: 保留旧负责人兼容并支持动态 Agent**

`AssigneeTarget` 保持现状。`TaskDraft` 新增 `assigneeAgentId?: string`。`actorForAgent(agent)` 返回：

```ts
{
  type: "agent",
  id: agent.id,
  name: agent.name,
  avatarUrl: agent.avatarUrl,
}
```

`assigneeTargetForActor` 只处理旧 current-user 和 codex-agent；动态 Agent 由 `assigneeAgentId` 单独发送，避免破坏旧 CLI。

- [ ] **Step 4: Typecheck**

Run:

```bash
npm run typecheck
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/api.ts web/src/actors.ts
git commit -m "feat: expose agent runtime types to web"
```

## Task 8: Agent 管理、动态负责人和 Run Panel

**Files:**

- Create: `web/src/components/AgentRunPanel.tsx`
- Create: `web/src/components/AgentRuntimeSettings.tsx`
- Modify: `web/src/components/TaskDetail.tsx`
- Modify: `web/src/components/TaskEditor.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Modify: `server/app.mjs`

- [ ] **Step 1: Server 支持 assigneeAgentId**

`parseTaskCreate` 和 `parseTaskPatch` 接受 `assigneeAgentId`，但禁止与 `assigneeTarget` 同时出现。Server 从 database 读取 enabled Agent，并生成可信 Actor，不接受客户端传 name 或 avatar。

- [ ] **Step 2: App 加载 Agent 和 Runtime**

App 在项目数据加载后并行调用 `listAgents()` 和 `listRuntimes()`。local capability 不可用时返回空列表，现有任务看板继续工作。

- [ ] **Step 3: 动态负责人选择**

TaskEditor 和 TaskDetail 的负责人选项由：当前 assignee、当前用户、旧 Codex Actor、enabled Agents 去重组成。选择动态 Agent 时写 `assigneeAgentId`。

- [ ] **Step 4: 实现 AgentRunPanel**

Panel 显示：

- Agent 下拉
- permission profile
- 立即执行按钮
- 当前 Run status、Runtime、开始时间、token
- 实时事件列表
- 中断按钮
- 历史 Run 列表

创建 Run 时 body 固定包含当前 `task.version`。danger 权限必须弹出逐次确认。

- [ ] **Step 5: 实现最小 AgentRuntimeSettings**

Settings 能创建 Agent、启停 Agent、选择 provider/default Runtime/default permission，并只读显示 Runtime online、providers 和 last heartbeat。Phase 1 不做远程设备授权。

- [ ] **Step 6: 接入现有 SSE**

现有 `TaskEvent` 增加可选 `run` 和 `runtime`。收到 `agent.run.*` 或 `runtime.*` 时刷新当前 Task Run 和 Runtime list，不新增第二条 realtime 连接。

- [ ] **Step 7: 构建并打开真实 UI**

Run:

```bash
npm run typecheck
npm run build
```

Expected: TypeScript 和 Vite build PASS。实际 UI 中能看到三类 Agent provider、Runtime online 和 Run Panel。

- [ ] **Step 8: Commit**

```bash
git add server/app.mjs web/src/types.ts web/src/api.ts web/src/actors.ts web/src/components/AgentRunPanel.tsx web/src/components/AgentRuntimeSettings.tsx web/src/components/TaskDetail.tsx web/src/components/TaskEditor.tsx web/src/App.tsx web/src/styles.css
git commit -m "feat: manage agents and runs in taskboard"
```

## Task 9: Claude Code Adapter

**Files:**

- Create: `runtime/adapters/claude-code.mjs`
- Modify: `runtime/index.mjs`

官方参考：`https://docs.anthropic.com/en/docs/claude-code/cli-usage`

- [ ] **Step 1: 实现 detect**

执行 `claude --version`，保存可用状态和版本，不解析或修改 Claude 配置。

- [ ] **Step 2: 构建 Claude invocation**

基础参数：

```js
const args = [
  "-p",
  "--input-format", "stream-json",
  "--output-format", "stream-json",
  "--verbose",
];
```

权限映射：

- `read-only` → `--permission-mode plan`
- `workspace-write` → `--permission-mode acceptEdits`
- `danger-full-access` → `--dangerously-skip-permissions`

新会话向 stdin 写一行 user message JSONL。`session_id` 保存到 Run；有 session id 时增加 `--resume <id>`。

- [ ] **Step 3: 归一化 stream-json**

至少处理：system/session id、assistant text、tool use、tool result、result、error 和 usage。未知事件保留为 `activity`，但 payload 大小受共享限制。

- [ ] **Step 4: 验证 Claude 真实路径**

创建与 Codex 相同的只读任务，选择 Claude Code。观察 Run 完成、结果评论包含 `codex-taskboard`、任务进入 `in_review`。

- [ ] **Step 5: Commit**

```bash
git add runtime/adapters/claude-code.mjs runtime/index.mjs
git commit -m "feat: run Claude Code tasks through local runtime"
```

## Task 10: OpenClaw Adapter

**Files:**

- Create: `runtime/adapters/openclaw.mjs`
- Modify: `runtime/index.mjs`

官方参考：`https://docs.openclaw.ai/cli/agent`

- [ ] **Step 1: 实现 detect**

执行 `openclaw --version`，保存可用状态和版本。

- [ ] **Step 2: 构建 OpenClaw invocation**

使用当前本机 OpenClaw 2026.5.5 已验证兼容的 Agent 入口：

```js
{
  command: "openclaw",
  args: [
    "agent",
    "--agent", "main",
    "--message-file", "-",
    "--json",
    "--local",
    "--timeout", "0",
  ],
  cwd: run.workspacePath,
  env: process.env,
  stdin: run.instruction,
}
```

Phase 1 不使用 `--deliver`，禁止把执行结果投递到飞书或其他外部 channel。

- [ ] **Step 3: 归一化 JSON envelope**

解析 `status`、`payloads`、`usage`、`model`、`provider`、`error.message` 和 `error.kind`。OpenClaw 当前 headless envelope 在进程结束时输出，因此 UI 先显示 process running，完成后一次写入 assistant/result/usage events，不伪造不存在的逐工具实时流。

- [ ] **Step 4: 验证 OpenClaw 真实路径**

创建同样的只读任务，选择 OpenClaw。观察 Run 完成、没有外部 delivery、结果评论包含 `codex-taskboard`、任务进入 `in_review`。

- [ ] **Step 5: Commit**

```bash
git add runtime/adapters/openclaw.mjs runtime/index.mjs
git commit -m "feat: run OpenClaw tasks through local runtime"
```

## Task 11: 三端联合验收与交付

**Files:**

- Modify: `README.md`

- [ ] **Step 1: 写本地启动说明**

README 只增加以下真实命令：

```bash
npm start
npm run runtime:setup -- --server http://127.0.0.1:47823 --name "MacBook-Pro" --workspace /absolute/workspace/root
npm run runtime:start
npm run runtime:status
```

说明 Runtime config 含 token，不应提交到 Git；默认 `.data/` 已被忽略。

- [ ] **Step 2: 检查三端 capability**

Settings 中必须同时显示：

- Codex available，版本可见
- Claude Code available，版本可见
- OpenClaw available，版本可见

- [ ] **Step 3: 分别执行三条真实任务**

三条任务使用相同只读验收要求，但分别绑定三种 Agent。每条都必须出现：

```text
todo → in_progress → in_review
queued → starting → running → completed
```

每条都有 agent-authored 结果评论和 Runtime 记录。

- [ ] **Step 4: 验证中断路径**

创建一条需要持续运行的安全只读任务，在 running 状态点击中断。观察 Run `interrupted`，Task 返回 `todo`，进程不再存活。

- [ ] **Step 5: 运行已有静态检查**

Run:

```bash
npm run typecheck
npm run build
```

Expected: PASS。不新增 regression test，等待祥瑞对真实路径确认。

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: explain local agent runtime"
```

- [ ] **Step 7: 交给祥瑞验收**

交付以下入口和证据：

1. Agent Settings 页面。
2. Runtime online 状态。
3. 三条进入 `in_review` 的任务。
4. 每条任务的 Run event、结果评论、耗时和 token。
5. 中断任务的可见结果。

祥瑞确认 Phase 1 后，再分别进入 Phase 2 Conversation、Phase 3 Squad、Phase 4 Autopilot、Phase 4 Skills、Phase 5 Remote Runtime 的独立计划。

## 子对话拆分与依赖

执行时按以下子对话拆分：

| 子对话 | 负责范围 | 依赖 | 可并行时机 |
| --- | --- | --- | --- |
| Runtime Control Plane | Task 1 到 Task 4 | 无 | 立即开始 |
| Codex Adapter | Task 5、Task 6 | Task 1 契约 | 契约完成后 |
| Agent UI | Task 7、Task 8 | Task 3 API shape | API shape 锁定后 |
| Claude + OpenClaw Adapters | Task 9、Task 10 | Task 5 Adapter interface | interface 锁定后 |
| 联合验收 | Task 11 | 全部 | 最后 |

主对话负责合并顺序、真实路径验证和向祥瑞交付。任何子对话如果发现 plan 与当前未提交改动冲突，必须停止写入并报告，不自行覆盖或回滚。
