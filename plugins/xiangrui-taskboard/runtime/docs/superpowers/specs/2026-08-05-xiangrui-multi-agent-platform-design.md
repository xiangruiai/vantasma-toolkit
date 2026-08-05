# 祥瑞本地多 Agent 管理平台设计

日期：2026-08-05

状态：整体设计已获祥瑞口头批准，等待书面 spec 评审

产品名称：祥瑞

当前仓库目录：`xiangrui-taskboard`

## 1. 背景与目标

祥瑞现有看板已经具备成熟的项目导航、任务状态、审核返工、评论附件、任务关系、Codex 对话关联、branch/worktree、本地协作与云端协作能力。现有缺口不是再做一个看板，而是缺少一套统一管理本地 Agent 的执行内核。

本项目将在现有看板基础上，自主实现轻量 Agent Orchestration，使「祥瑞」成为所有本地 Agent 的统一管理与交互平台。最终支持 Codex、Claude Code、OpenClaw 以及未来可扩展的 CLI Agent，并完整覆盖 Agent、Runtime、Run、对话、Squad、Autopilot、Skills 和远程 Runtime 能力。

本项目不复制 Multica 的源码、界面、品牌或受其许可证约束的实现。可以学习通用产品概念，但所有数据模型、协议、交互和代码均在「祥瑞」中独立设计和实现。

## 2. 成功标准

完整平台应满足以下结果：

1. 祥瑞可以在任务中选择 Codex、Claude Code、OpenClaw、其他 Agent 或 Squad。
2. Agent 能自动领取 Run，在指定 workspace、branch 或 worktree 中执行任务。
3. 看板能实时展示执行状态、输出、工具事件、token、产物、失败原因和最后心跳。
4. 祥瑞能在任务或独立对话中与 Agent 多轮交互，支持评论、`@Agent`、追问、暂停、中断、继续和返工。
5. Agent 能组成 Squad，由 Leader 根据任务内容选择成员、拆分子任务并汇总结果。
6. Autopilot 能通过 Cron、Webhook 或手动触发创建任务并分配给 Agent 或 Squad。
7. Skills 能导入、版本化、绑定、运行时注入和记录使用效果。
8. 本地和云端看板能连接一台或多台 Runtime，同时保持清晰的设备、权限和 workspace 边界。
9. 看板任务始终是唯一事实来源，Agent 不维护第二套任务状态。
10. Agent 只能把完成的任务提交到 `in_review`，只有祥瑞能将其移动到 `done`。

## 3. 已验证的现有操作路径

### 3.1 创建与更新任务

现有入口是 `web/src/components/TaskEditor.tsx`。前端通过 `web/src/api.ts` 调用 `POST /api/tasks` 或任务更新 API，后端由 `server/app.mjs` 处理请求，并由 `server/database.mjs` 写入 SQLite。任务、评论和附件变更通过现有事件与刷新机制回到 React UI。

### 3.2 交给 Codex

现有 `web/src/components/TaskDetail.tsx` 和 `web/src/App.tsx` 能从任务打开原生 Codex 对话。注入层位于 `inject/codex-taskboard.user.js`、`scripts/codex-injector-runtime.mjs` 和 `scripts/codex-injector.mjs`，负责向 Codex 创建并打开任务。

这条路径证明看板已经可以把真实任务交给一个 Agent，但当前执行仍由宿主对话承担，没有统一的 Agent Registry、Run 生命周期、实时事件、Daemon、其他 Agent 适配器和故障恢复。

## 4. 总体架构

采用「祥瑞 Control Plane + 轻量 Runtime Daemon + 可插拔 Agent Adapter」架构。

```text
祥瑞 Web UI
    ↓ HTTP API / SSE
祥瑞 Control Plane
    ↓ 认证的 Runtime 连接
轻量 Runtime Daemon
    ↓ Agent Adapter
Codex / Claude Code / OpenClaw / 其他 CLI Agent
```

### 4.1 祥瑞 Web UI

继续使用现有 React 看板作为唯一入口，新增：

- Agent 与 Squad 负责人选择
- Run 状态和实时执行面板
- 对话与 `@Agent`
- Runtime 管理
- Agent 管理
- Squad 管理
- Autopilot 管理
- Skills 管理
- token、耗时、失败和产物展示

### 4.2 祥瑞 Control Plane

继续运行在现有 Node Server 中，职责包括：

- Agent、Runtime、Run、Conversation、Squad、Autopilot 和 Skill 的业务状态
- Run 排队、认领、状态机和审计事件
- Task 与 Run 的关联
- Agent 或 Squad 路由
- Runtime 身份认证和心跳
- 向 UI 推送事件
- 本地 SQLite 与 Cloud D1 数据适配

Control Plane 不直接启动 Agent CLI，避免看板服务与执行进程耦合。

### 4.3 轻量 Runtime Daemon

Daemon 使用与仓库一致的 Node.js 22 运行时，作为独立本地进程。第一版由 Daemon 主动连接 Control Plane，不公开监听端口。

职责包括：

- 上报设备、版本、在线状态和 Agent CLI 能力
- 领取分配给本设备的 Run
- 校验 workspace allowlist
- 准备 repo、branch、worktree、环境和 Skills
- 启动、监控、中断和回收 Agent 子进程
- 流式上报 stdout、stderr、结构化事件、token 和心跳
- 在重启后识别未完成 Run，但不自动重复具有外部副作用的执行

### 4.4 Agent Adapter

每个 Agent Adapter 实现统一接口：

```ts
interface AgentAdapter {
  detect(): Promise<AgentCapability>;
  prepare(input: RunPreparation): Promise<PreparedRun>;
  start(input: PreparedRun, emit: RunEventEmitter): Promise<AgentProcess>;
  sendInput(process: AgentProcess, message: RunInput): Promise<void>;
  interrupt(process: AgentProcess): Promise<void>;
  normalizeExit(result: AgentExit): NormalizedRunResult;
}
```

首批适配器为：

1. Codex
2. Claude Code
3. OpenClaw

以后接入 OpenCode、Cursor Agent 或其他 CLI 时，只新增 Adapter，不修改 Run Core。

## 5. 核心数据模型

现有 `projects`、`tasks`、`comments`、`attachments` 和任务关系保持不变。新增模型采用追加式迁移，不重建旧表。

### 5.1 agents

- `id`
- `name`
- `provider`
- `avatar`
- `description`
- `default_runtime_id`
- `default_permission_profile`
- `status`
- `created_at`
- `updated_at`

### 5.2 runtimes

- `id`
- `name`
- `device_id`
- `version`
- `status`
- `last_heartbeat_at`
- `workspace_allowlist`
- `capabilities`
- `created_at`
- `updated_at`

Runtime token 只保存不可逆摘要。Agent 的 API Key 或登录凭据不进入祥瑞数据库。

### 5.3 runs

- `id`
- `task_id`
- `agent_id`
- `squad_id`
- `runtime_id`
- `conversation_id`
- `parent_run_id`
- `status`
- `permission_profile`
- `workspace_path`
- `development_context`
- `instruction_snapshot`
- `task_version_snapshot`
- `started_at`
- `finished_at`
- `exit_code`
- `error_code`
- `error_message`
- `token_usage`
- `created_at`
- `updated_at`

Run 状态固定为：

- `queued`
- `starting`
- `running`
- `waiting_input`
- `completed`
- `failed`
- `interrupted`
- `orphaned`

### 5.4 run_events

Run Event 只追加，不覆盖历史：

- `id`
- `run_id`
- `sequence`
- `type`
- `payload`
- `created_at`

事件类型包括状态、日志、工具调用、评论、产物、token、心跳、用户输入和错误。

### 5.5 conversations 与 messages

Conversation 可以独立存在，也可以绑定 Task 或 Run。Message 支持人、Agent、系统消息、附件和回复关系。把一段对话转为任务时，新任务引用原 Conversation，不复制另一套上下文。

### 5.6 squads

Squad 包含 Leader、成员和路由规则。Leader 创建的子工作使用真实子任务和子 Run 表达，并通过现有任务关系记录依赖，不在 Run payload 中维护隐藏任务列表。

### 5.7 autopilots

Autopilot 包含触发器、目标模板、验收模板、目标项目、负责人、启停状态和运行历史。每次触发都创建真实 Task，再进入标准 Run 流程。

### 5.8 skills

Skill 保存来源、版本、内容摘要、目录、兼容 Agent、状态和统计。Skill Binding 把 Skill 绑定到 Agent、Squad 或 Project。运行时只注入当前 Run 实际需要的 Skills，并记录注入版本。

## 6. 核心 API 与事件

### 6.1 Agent 与 Runtime

- `GET /api/agents`
- `POST /api/agents`
- `PATCH /api/agents/:id`
- `GET /api/runtimes`
- `POST /api/runtimes/register`
- `POST /api/runtimes/:id/heartbeat`

Daemon 通过新增的认证 WebSocket endpoint `GET /api/runtime/connect` 领取命令并上报事件。连接由 Daemon 主动发起，断线后使用带抖动的指数退避重连。UI 继续通过现有 SSE 模式接收可见状态变化。

### 6.2 Run

- `GET /api/tasks/:taskId/runs`
- `POST /api/tasks/:taskId/runs`
- `GET /api/runs/:id`
- `POST /api/runs/:id/input`
- `POST /api/runs/:id/interrupt`
- `POST /api/runs/:id/retry`
- `GET /api/runs/:id/events`

创建 Run 时必须使用任务最新 version，避免基于过期任务执行。重试创建新 Run，并通过 `parent_run_id` 指向原 Run，不覆盖原日志。

### 6.3 对话、Squad、Autopilot 与 Skills

这些模块使用各自 CRUD API，但最终执行全部落到 `POST /api/tasks/:taskId/runs`，禁止新增旁路执行器。

## 7. 一条任务的真实操作路径

1. 祥瑞在 `TaskEditor` 创建任务，填写目标、验收标准、附件和开发上下文。
2. 在任务详情选择 Agent 或 Squad，并点击立即执行。
3. Web 调用创建 Run API，Server 原子写入 Run 和首条 queued event。
4. Control Plane 把 Run 分配给在线且满足 workspace 与 provider 条件的 Runtime。
5. Daemon 领取 Run，Adapter 启动对应 CLI。
6. Daemon 持续上报输出、事件、token 和心跳，UI 实时展示。
7. 祥瑞可以发送补充消息、暂停或中断。
8. Agent 成功退出后写结果评论和产物，Run 进入 `completed`，任务进入 `in_review`。
9. 祥瑞验收通过后把任务移动到 `done`；不通过则提交返工意见并创建新 Run。

可观察结果包括任务状态、Run 状态、Agent 状态、实时输出、结果评论、产物、token、耗时和关联对话。

## 8. 对话与 `@Agent`

### 8.1 任务内交互

任务评论默认仍只是记录。以下动作必须显式区分：

- 评论
- 评论并发送给当前 Run
- `@Agent` 创建新 Run
- 提交修改意见
- 立即返工

按钮文字必须准确预告是否会创建 Run、改变任务状态或中断当前执行。

### 8.2 独立对话

独立对话用于探索、研究和多轮沟通。对话可以：

- 绑定一个 Agent 或 Squad
- 关联项目与 workspace
- 转为真实任务
- 从消息创建子任务
- 查看每一轮对应的 Run

独立对话不绕过 Run Core。

## 9. Squad 与 Leader

1. 祥瑞把任务分配给 Squad。
2. 系统为 Leader 创建路由 Run。
3. Leader 读取任务、成员能力、在线 Runtime 和当前负载。
4. Leader选择一个成员直接执行，或创建多个真实子任务。
5. 子任务通过现有任务关系表达父子、阻塞和依赖。
6. 成员 Run 完成后，Leader 创建汇总 Run。
7. 总结果写入父任务并提交审核。

任何时候祥瑞都可以修改成员、接管路由、停止某个子 Run 或直接指定 Agent。

## 10. Autopilot

支持三类触发器：

- Cron
- Webhook
- 手动运行

触发器只负责创建任务，不直接启动隐藏进程。创建的任务带有来源、模板版本和 `autopilot_run_id`，再按标准分配与 Run 流程执行。

Autopilot 具有启用、暂停、失败暂停和停用状态。每次运行均可查看创建的任务、目标 Agent、最终状态和错误。

## 11. Skills

Skill Registry 首先支持本地目录导入，兼容现有 `SKILL.md` 约定。完整能力包括：

- 导入、更新、停用和删除绑定
- 版本与来源追踪
- Agent、Squad、Project 三级绑定
- 运行时按需注入
- 使用次数、成功率、失败反馈和最后使用时间
- 从成功 Run 提议沉淀 Skill，但必须由祥瑞确认后写入

Skill 不复制 Agent 私有凭据，不自动改写 Vault 或外部知识库。

## 12. 失败恢复

| 场景 | Run 结果 | Task 结果 | 恢复方式 |
| --- | --- | --- | --- |
| 没有在线 Runtime | 保持 `queued` | 保持 `todo` | Runtime 上线后领取 |
| Agent CLI 不存在 | `failed` | `blocked` | 安装或改派 Agent |
| workspace 不允许 | `failed` | `blocked` | 修改 Runtime allowlist |
| 可重试进程错误 | `failed` | 返回 `todo` | 人工或策略创建新 Run |
| 缺少资料 | `waiting_input` | `blocked` | 补充消息后继续或新 Run |
| 人工中断 | `interrupted` | 返回 `todo` | 明确点击继续或重试 |
| Daemon 失联 | `orphaned` | 保留当前可见状态 | 根据心跳与进程确认后人工恢复 |
| 成功完成 | `completed` | `in_review` | 祥瑞验收 |

系统不根据超时直接重跑可能有外部副作用的 Run，也不把失联 Run 自动标成完成。

## 13. 安全边界

1. Daemon 主动连接 Control Plane，不公开暴露执行端口。
2. Runtime 使用设备 token，Server 只保存 token 摘要。
3. Daemon 只访问配置的 workspace allowlist。
4. 每个 Run 明确 `read-only`、`workspace-write` 或 `danger-full-access`。
5. Agent 复用本机 CLI 登录状态，祥瑞数据库不保存 API Key。
6. 删除、部署、外部发送、付款和其他高风险副作用继续使用对应 Agent 的确认机制。
7. Runtime 日志在写入前执行 secrets redaction，原始 `.env` 和 credential 文件不作为附件上传。
8. Cloud 模式只把 Run 分配给显式注册的设备，不暗中回退到本地或双写数据。

## 14. 分阶段建设与子项目

最终功能范围不缩水，但按依赖拆为五个可独立验收的子项目。

### Phase 1：Agent Runtime 核心

- Agent Registry
- Runtime Daemon
- Runtime 注册、心跳和能力探测
- Run 数据模型、API、状态机和事件流
- Codex、Claude Code、OpenClaw Adapter
- 任务负责人选择与 Run 面板
- 启动、中断、实时输出和提交审核

验收结果：一条真实任务分别交给三个 Agent，均能从 `todo` 执行到 `in_review`。

### Phase 2：对话与任务交互

- 独立 Conversation 与 Message
- 任务内发送给 Agent
- `@Agent`
- 多轮追问、暂停、继续和换 Agent
- 对话转任务、消息转子任务

验收结果：祥瑞能在看板内完成一次多轮追问，并把结果转成可审核任务。

### Phase 3：Squad 与协作路由

- Squad、Leader 和成员管理
- Leader 路由 Run
- 子任务拆分、依赖和并行执行
- 结果汇总与人工接管

验收结果：一个 Squad 能把父任务拆给至少两个不同 Agent，并汇总到父任务审核。

### Phase 4：Autopilot 与 Skills

- Cron、Webhook、手动触发
- Autopilot 任务模板和运行历史
- Skill 导入、版本、绑定和运行时注入
- Skill 使用记录与沉淀建议

验收结果：一个定时 Autopilot 创建真实任务，调用绑定 Skill 完成并提交审核。

### Phase 5：远程 Runtime 与云端协作

- 多设备 Runtime
- Cloud Control Plane 连接
- 设备授权、撤销和 workspace 映射
- 远程执行状态与日志

验收结果：云看板把任务分配给指定本地设备执行，并完整回传结果。

## 15. 验证策略

遵循仓库 `AGENTS.md` 的直接路径规则：

1. 每个 Phase 实施前先证明实际入口、API、数据变化和可观察结果。
2. 只实现当前 Phase 的主路径。
3. 在实际运行的「祥瑞」中完成对应验收场景。
4. 主路径未经祥瑞确认前，不扩张防御性兼容、回归保护和假设性 fallback。
5. 祥瑞确认后，只有在明确要求或出现具体失败时，才补充 targeted regression。

设计层仍要求接口边界清晰、数据迁移可追溯、真实外部输入有必要校验、安全边界不被跳过。

## 16. 子对话与实施组织

设计文档确认后，通过 implementation plan 拆分为可独立推进的子任务。适合并行的子对话包括：

- Runtime Daemon 与协议
- Run 数据模型与 Control Plane API
- Codex Adapter
- Claude Code Adapter
- OpenClaw Adapter
- Agent、Runtime 与 Run UI
- Conversation 与消息交互
- Squad 路由
- Autopilot
- Skills
- Cloud Runtime 与安全边界

有数据依赖的任务按 Phase 顺序推进；相互独立的 Adapter 和 UI 组件在核心接口稳定后并行。所有子对话必须引用同一份 spec 和 plan，禁止自行扩张范围。

## 17. 非目标

- 不复制 Multica 源码、UI、品牌或数据模型。
- 不保留两个看板或两套任务事实来源。
- 不要求 Docker、PostgreSQL 或 pgvector 才能运行本地版本。
- 不在第一阶段同时解决多组织 SaaS、计费和公开市场。
- 不让 Agent 自动批准自己的交付。
- 不因为最终范围较大而在单个 Phase 内一次性实现全部模块。

## 18. 命名约定

正式产品名称统一为「祥瑞」。所有 UI、文档、目录和对外文案均使用「祥瑞」。
