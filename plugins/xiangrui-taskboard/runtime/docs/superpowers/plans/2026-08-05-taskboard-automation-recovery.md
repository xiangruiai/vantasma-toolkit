# Taskboard Automation Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 Codex 任务的安全认领、退出分流、异常中断回收、项目映射和自动化可见状态，并收起没有执行器的界面能力。

**Architecture:** 不新增运行队列表，继续复用议题状态、负责人、阻塞关系、`threadId` 和 Codex automation。自动化只认领明确交给 Codex 且未被阻塞的待办；Agent 正常退出时必须进入审核中、待办或已阻塞，异常退出只在确认关联 Codex 任务已停止后回收。界面继续使用现有 React 组件和 TaskboardSelect，以真实能力为准展示设置。

**Tech Stack:** React 19、TypeScript、Vite、Node.js ESM、taskctl、Codex automation、TaskboardSelect

---

## 项目规则说明

祥瑞已经明确要求把原目标完整跑完，并授权在当前 main 工作区继续。工作区包含其他并行 Taskboard 任务的未提交改动，不能切换到缺少这些改动的 worktree，也不能整文件提交业务代码。本计划先完成真实路径和构建、界面验证；按照根目录 `AGENTS.md`，祥瑞整体验收后再更新保护性测试和旧断言。

## 文件边界

- 修改：`shared/taskboard-automation.mjs`
  - 定义周期自动认领候选、异常回收和退出状态协议。
- 修改：`skills/manage-taskboard/SKILL.md`
  - 让即时交办与自动认领使用相同的退出规则。
- 修改：`web/src/App.tsx`
  - 通过当前 Codex 项目的真实目录补齐 Taskboard ID 与 Codex Project ID 映射。
- 修改：`web/src/components/ProjectAutomationMenu.tsx`
  - 显示真实自动化状态，并使用 TaskboardSelect 替换三个原生 select。
- 修改：`web/src/components/TaskDetail.tsx`
  - 隐藏没有执行器的工作流和重复入口，保留已有数据。
- 修改：`web/src/components/TaskEditor.tsx`
  - 隐藏没有执行器的工作流和重复入口，编辑时继续原样保存已有值。
- 修改：`web/src/components/AiChat.tsx`
  - 将独立 AI 入口明确命名为“面板助手”。
- 修改：`web/src/styles.css`
  - 让自动化菜单中的 TaskboardSelect 与现有紧凑布局一致。

### Task 1: 统一 Agent 认领和退出协议

**Files:**
- Modify: `shared/taskboard-automation.mjs:60-70`
- Modify: `skills/manage-taskboard/SKILL.md:20-33`

- [ ] **Step 1: 保留当前真实路径证据**

运行：

```bash
sed -n '55,75p' shared/taskboard-automation.mjs
sed -n '18,36p' skills/manage-taskboard/SKILL.md
```

预期：当前自动化只要求处理一个 `todo`，没有负责人、依赖、排序和中断回收规则；成功后进入 `in_review`，不会自动进入 `done`。

- [ ] **Step 2: 收紧自动认领候选**

将自动化 Prompt 的候选规则写成可直接执行的协议：

```text
只从 todo 中选择 assignee.type=agent 且 assignee.id=codex-agent 的议题。
blockedBy 中只要存在 status!=done 的依赖就跳过。
候选依次按 priority(urgent, high, medium, low, none)、dueDate(有日期优先且升序)、sortOrder、createdAt 排序。
每轮最多处理一条，认领前重新读取议题和全部评论，使用最新 version 移到 in_progress。
```

Prompt 必须明确不领取人类负责人议题，并在 version 冲突时立即跳过。

- [ ] **Step 3: 增加可验证的异常回收**

在认领新待办前加入：

```text
检查 Codex Agent 负责的 in_progress。
只有在 threadId 存在，并且 Codex 任务工具确认关联任务已经 failed 或 interrupted 时才能回收。
可安全重试的任务写明中断点并退回 todo；等待资料、决定或依赖的任务写明解除条件并移到 blocked。
禁止仅根据 updatedAt 判断任务停止，无法确认就保持不变。
若本轮完成回收，不再认领第二条议题。
```

- [ ] **Step 4: 统一正常退出规则**

在自动化 Prompt 和 Skill 中使用相同规则：

```text
完成且自检通过 -> comment add -> in_review
临时中断、重试即可 -> comment add -> todo
等待外部输入或依赖 -> comment add -> blocked
不再处理 -> 只有祥瑞可决定 canceled
Agent 永远不能自动进入 done
```

结果评论回答具体返工评论时继续使用现有 `--reply-to` 能力。

### Task 2: 修复项目映射和自动化状态

**Files:**
- Modify: `web/src/App.tsx:590-630`
- Modify: `web/src/components/ProjectAutomationMenu.tsx:1-285`
- Modify: `web/src/styles.css:1397-1443`

- [ ] **Step 1: 使用当前 Codex 工作区匹配 Taskboard 项目**

在 `App.tsx` 增加浏览器安全的路径规范化函数：

```tsx
function normalizedWorkspacePath(value?: string | null): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  return trimmed.replace(/[\\/]+$/, "");
}
```

计算 `workspacePath` 后，如果它与 `hostContext.workspacePath` 规范化后相同，优先使用 `hostContext.projectId` 作为 `codexProjectId`。其次才使用 Taskboard/Codex 同 ID 或设备保存的路径映射。这样 Taskboard 项目 ID 为 `xiangrui-taskboard`、Codex Project ID 为原生 UUID 时仍可启用自动化。

- [ ] **Step 2: 让入口显示真实状态**

在 `ProjectAutomationMenu.tsx` 生成两个标签：

```tsx
const unavailableLabel = unavailableReason?.includes("映射")
  ? "项目未映射"
  : unavailableReason
    ? "自动化不可用"
    : null;
const stateLabel = unavailableLabel
  ?? (!automation?.enabledByUser
    ? "未启用"
    : automation.quotaAware && quota?.state === "blocked"
      ? "额度不足，已暂停"
      : automation.quotaAware && quota?.state === "unavailable"
        ? "额度不可用"
        : automation.quotaAware && (!quota || quota.state === "unknown")
          ? "额度未知，已暂停"
          : status === "ACTIVE" ? "运行中" : "已暂停");
const triggerLabel = pending
  ? "正在更新"
  : status === "ACTIVE" && !unavailableLabel
    ? "自动认领"
    : stateLabel;
```

入口的文字、`aria-label` 和 `title` 都使用 `triggerLabel`，不再显示含义模糊的“无自动化”。即使不可用，菜单仍可打开查看具体原因；只有设置控件被禁用。

- [ ] **Step 3: 将三个原生 select 换成 TaskboardSelect**

导入 `TaskboardSelect`，把间隔、模型和推理强度改为：

```tsx
<TaskboardSelect
  ariaLabel="自动认领间隔"
  value={String(draft.intervalMinutes)}
  disabled={disabled}
  minMenuWidth={132}
  options={[5, 10, 15, 30, 60].map((minutes) => ({
    value: String(minutes),
    label: `${minutes} 分钟`,
  }))}
  onChange={(value) => submitChange({
    ...draft,
    intervalMinutes: Number(value) as IntervalMinutes,
  })}
/>
```

模型与推理强度使用同一组件和现有选项数据。CSS 只限定 `.project-automation-field .taskboard-select` 宽度以及 trigger 的紧凑高度，不新增另一套菜单样式。

### Task 3: 收起没有执行器的能力并区分 AI 入口

**Files:**
- Modify: `web/src/components/TaskDetail.tsx:1155-1241`
- Modify: `web/src/components/TaskEditor.tsx:340-416`
- Modify: `web/src/components/AiChat.tsx:585,2032-2078,2539-2542`

- [ ] **Step 1: 隐藏议题详情中的工作流和重复**

删除 `TaskDetail` 中工作流与重复的渲染块，同时删除只服务这些块的 `workflowAvailable` 与 `Recurrence` 类型导入。截止日期仍保留；清除截止日期继续把已有 `recurrence` 置空，避免留下无效组合。

- [ ] **Step 2: 隐藏新建和编辑窗口中的工作流和重复**

删除 `TaskEditor` 中工作流按钮、重复摘要、设置重复菜单入口与重复 popover。保留 `workflowId` 和 `recurrence` state 以及提交字段，使编辑旧议题时不会静默丢失已有数据；新议题仍保存 `workflowId=null`、`recurrence=null`。

`menu` 类型收窄为：

```tsx
useState<"labels" | "more" | "due" | null>(null)
```

更多菜单只保留“设置截止日期”。

- [ ] **Step 3: 将独立 AI Chat 命名为面板助手**

保持 API 和内部类型名不变，只改用户可见文案：

```text
AI 对话暂时不可用 -> 面板助手暂时不可用
Codex AI 对话 -> Taskboard 面板助手
关闭 AI 对话 -> 关闭面板助手
打开 AI 对话 -> 打开面板助手
AI 对话 -> 面板助手
```

这样“交给 Codex”表示执行议题，“自动认领”表示周期领取，“面板助手”表示独立查询与整理入口。

### Task 4: 验证真实路径并保留并行改动

**Files:**
- Verify all files listed above
- Do not commit dirty business files before review

- [ ] **Step 1: 检查修改范围和静态构建**

运行：

```bash
git diff --check
npm run typecheck
npm run build
```

预期：无 diff 格式错误，TypeScript 和 Vite 构建通过，运行中的 Codex 注入刷新成功。

- [ ] **Step 2: 验证自动化 Prompt**

直接调用 `buildTaskboardAutomationPrompt()` 生成 Prompt，确认文本包含：`Codex Agent`、未完成阻塞依赖、稳定排序、`failed`/`interrupted` 线程确认、`todo`/`blocked`/`in_review` 三种退出和禁止 `done`。

- [ ] **Step 3: 验证实际页面**

在本地 Taskboard 中检查：

```text
自动化入口不再出现“无自动化”
项目未映射时入口可打开并显示原因
自动化菜单有 3 个 combobox、0 个原生 select
议题详情没有“工作流”和“重复”属性
新建议题没有工作流与重复入口
独立入口的可访问名称为“打开面板助手”
```

只读检查即可，不开启自动化、不创建评论、不修改真实议题。

- [ ] **Step 4: 记录交付并进入整体验收**

重新读取 `XIANGRUITASK-2` 和全部评论，添加包含关键改动、验证结果与剩余风险的结果评论，再使用最新 version 将其移动到 `in_review`。不移动到 `done`，等待祥瑞最终验收。

- [ ] **Step 5: 保留业务文件的共享工作区状态**

运行：

```bash
git status --short
git diff --stat
```

工作区开始前已经有多个并行任务修改相同业务文件，因此本轮不整文件提交业务代码。设计与计划文档可以单独提交，不夹带其他改动。
