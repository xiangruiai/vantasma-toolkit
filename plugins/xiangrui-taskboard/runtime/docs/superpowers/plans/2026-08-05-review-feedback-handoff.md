# Review Feedback Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让审核中的议题提交评论后可靠退回待办，并可选择立即创建和提交原生 Codex 返工任务。

**Architecture:** 复用 `TaskDetail` 已有的评论持久化、`onUpdate` 状态更新和 `onOpenInThread` 原生任务交办能力。先保存评论和附件，再将 `in_review` 更新为 `todo`，最后仅在“立即返工”路径中使用更新后的任务快照交给 Codex；任何后续失败都保留已经保存的评论。

**Tech Stack:** React 19、TypeScript、Vite、现有 Taskboard REST API、Codex App postMessage 注入桥

---

## 项目规则说明

仓库根目录 `AGENTS.md` 要求先证明并实现真实主路径，在祥瑞确认实际可用前不增加保护性测试或大规模兼容改造。该规则覆盖本技能默认的 TDD 顺序。因此本计划只修改一处业务组件，执行 TypeScript 与构建检查，并在真实界面验证操作链路；回归测试留到祥瑞确认后单独规划。

## 文件边界

- 修改：`web/src/components/TaskDetail.tsx`
  - 负责评论、附件、审核反馈状态流转以及交给 Codex 的先后顺序。
- 不修改：`web/src/api.ts`
  - 现有 `createComment()` 和任务 PATCH 已满足需求。
- 不修改：`web/src/App.tsx`
  - 现有 `updateTaskProperties()` 会使用任务 version 更新状态，`openTaskInThread()` 会把议题交给 `manage-taskboard` Skill 并支持自动提交。
- 不修改：server 与 database
  - 本路径不需要新接口或表字段。

### Task 1: 接通审核反馈与立即返工主路径

**Files:**
- Modify: `web/src/components/TaskDetail.tsx:404-477`
- Modify: `web/src/components/TaskDetail.tsx:935-1012`

- [ ] **Step 1: 记录改动前的真实路径证据**

确认以下调用链仍与设计一致：

```text
TaskDetail.submitComment()
  -> createComment(task.id, body)
  -> uploadCommentAttachment(...)
  -> 普通评论：结束
  -> handoff：onOpenInThread(currentTask, { autoSubmit: true })
```

运行：

```bash
sed -n '404,477p' web/src/components/TaskDetail.tsx
sed -n '1691,1740p' web/src/App.tsx
```

预期：评论持久化后没有状态更新；handoff 使用 `currentTask` 旧快照。

- [ ] **Step 2: 在评论成功后退回待办，并把新快照交给 Codex**

在 `submitComment()` 内，附件处理成功后加入以下顺序控制。实现时保留函数现有的上传失败和评论保留逻辑，只替换 handoff 前的分支：

```tsx
      const isReviewFeedback = currentTask.status === "in_review";
      let taskForHandoff = currentTask;
      if (isReviewFeedback) {
        const returnedTask = await saveTask({ status: "todo" }, "status");
        if (!returnedTask) {
          setCommentsError("评论已保留，但退回待办失败，请重试。");
          return;
        }
        taskForHandoff = returnedTask;
      }

      if (handoffToCodex) {
        onAnnounce(
          isReviewFeedback
            ? "修改意见已提交，正在交给 Codex。"
            : "评论已发布，正在交给 Codex。",
        );
        onOpenInThread(taskForHandoff, { autoSubmit: true });
      } else {
        onAnnounce(
          isReviewFeedback
            ? "修改意见已提交，议题已退回待办。"
            : uploaded.length + inlineAttachments.length > 0
              ? "评论和附件已发布。"
              : "评论已发布。",
        );
      }
```

关键约束：

```text
评论/附件失败       -> 保持 in_review，不交办
评论成功、状态失败   -> 评论保留，保持当前状态，不交办
评论成功、状态成功   -> 进入 todo
立即返工全部成功     -> 使用 returnedTask 创建 Codex 任务
Codex 创建失败       -> 评论保留，议题保持 todo，可再次交办
```

- [ ] **Step 3: 让审核状态的按钮准确描述副作用**

在组件渲染区定义状态标签：

```tsx
  const reviewing = currentTask.status === "in_review";
  const commentPlaceholder = reviewing ? "填写需要修改的内容…" : "留下评论…";
  const commentActionLabel = reviewing ? "提交修改意见" : "评论";
  const handoffActionLabel = reviewing ? "立即返工" : "评论并交给 Codex";
```

将编辑器 placeholder 与 ariaLabel 都设为 `commentPlaceholder`。主按钮文字改为：

```tsx
{submittingMode === "comment" ? "发布中…" : commentActionLabel}
```

次按钮文字改为：

```tsx
<span>{submittingMode === "handoff" || openingThread
  ? reviewing ? "正在返工…" : "正在交给 Codex…"
  : handoffActionLabel}</span>
```

快捷键 `⌘ Enter` 继续调用 `submitComment()`。在审核状态下，它与主按钮一致，表示提交修改意见并退回待办，不自动启动 Codex。

- [ ] **Step 4: 检查修改范围**

运行：

```bash
git diff --check -- web/src/components/TaskDetail.tsx
git diff -- web/src/components/TaskDetail.tsx
```

预期：只有评论提交顺序、审核状态文案和对应的可访问性标签发生变化；没有 API、数据库或无关样式改动。

### Task 2: 构建并证明真实界面路径

**Files:**
- Verify: `web/src/components/TaskDetail.tsx`
- Generated at runtime: Vite web bundle and Codex injector refresh

- [ ] **Step 1: 执行静态检查和构建**

运行：

```bash
npm run typecheck
npm run build
```

预期：TypeScript 无错误，Vite 构建完成，运行中的 Codex 注入器被刷新。

- [ ] **Step 2: 验证“提交修改意见”路径**

在真实 Taskboard 中打开一条 `in_review` 议题，输入唯一评论 `返工闭环验证：仅退回待办`，点击“提交修改意见”。

预期可观察结果：

```text
评论列表出现该评论
议题状态从“审核中”变为“待办”
没有新建 Codex 任务
界面播报“修改意见已提交，议题已退回待办”
```

- [ ] **Step 3: 验证“立即返工”路径**

将同一测试议题重新置为 `in_review`，输入唯一评论 `返工闭环验证：立即交给 Codex`，点击“立即返工”。

预期可观察结果：

```text
评论列表出现该评论
议题先进入“待办”
Codex 创建并自动提交一个原生任务
新任务通过 manage-taskboard 读取议题与全部评论
Agent 使用最新 version 把议题认领为“进行中”
```

- [ ] **Step 4: 向祥瑞交付验证证据并等待确认**

提供实际界面结果、测试议题编号和任何失败点。祥瑞确认后，再为该主路径补充精确回归测试，并分别规划自动认领安全、状态文案和未完成能力收口。

- [ ] **Step 5: 保留工作区并等待提交决定**

`web/src/components/TaskDetail.tsx` 在本计划开始前已经包含其他已授权功能的未提交改动，不能安全地把整份文件冒充为本次独立变更提交。完成验证后先查看：

```bash
git diff -- web/src/components/TaskDetail.tsx
git status --short
```

预期：业务修改继续保留在工作区，不自动提交、不覆盖已有改动。向祥瑞报告文件现状，再决定与前序功能一起提交还是后续拆分。
