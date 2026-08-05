import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../api";
import {
  TASK_PRIORITIES,
  TASK_STATUSES,
  type ActorIdentity,
  type DevelopmentContext,
  type DevelopmentScan,
  type Recurrence,
  type Task,
  type TaskDraft,
  type TaskPriority,
  type TaskStatus,
  type WorkflowOption,
} from "../types";
import {
  CODEX_AGENT_ACTOR,
  actorKey,
  assigneeTargetForActor,
} from "../actors";
import { ActorAvatar } from "./ActorAvatar";
import { STATUS_DETAILS } from "./BoardColumn";
import { LabelPicker } from "./LabelPicker";
import { LinearIcon, LinearPriorityIcon, LinearStatusIcon } from "./LinearIcon";
import { TaskboardSelect } from "./TaskboardSelect";
import {
  fileKey,
  MAX_ATTACHMENT_SIZE,
  PendingAttachments,
} from "./PendingAttachments";
import {
  createInlineMediaSegments,
  InlineMediaComposer,
  inlineMediaImages,
  serializeInlineMedia,
  type InlineMediaSegment,
  type PendingInlineImage,
} from "./InlineMediaComposer";

const PRIORITY_LABELS: Record<TaskPriority, string> = {
  none: "无优先级",
  urgent: "紧急",
  high: "高",
  medium: "中",
  low: "低",
};

interface TaskEditorProps {
  task: Task | null;
  initialStatus: TaskStatus;
  labels: string[];
  workflows: WorkflowOption[];
  currentUser: ActorIdentity;
  developmentScan: DevelopmentScan;
  developmentScanLoading: boolean;
  canExecuteWithCodex: boolean;
  onCancel: () => void;
  onSave: (
    draft: TaskDraft,
    attachments: File[],
    inlineImages: PendingInlineImage[],
    intent: "save" | "execute",
  ) => Promise<void>;
}

function isoDate(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function dateFromNow(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return isoDate(date);
}

function endOfWeek(): string {
  const date = new Date();
  const daysUntilFriday = (5 - date.getDay() + 7) % 7;
  date.setDate(date.getDate() + daysUntilFriday);
  return isoDate(date);
}

function displayDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" })
    .format(new Date(`${value}T12:00:00`));
}

function contextValue(context: DevelopmentContext | null): string {
  return context ? JSON.stringify(context) : "";
}

function contextLabel(context: DevelopmentContext): string {
  if (context.type === "branch") return context.branch;
  const folder = context.path.split(/[\\/]/).filter(Boolean).at(-1) ?? context.path;
  return `${context.branch ?? "detached"} · ${folder}`;
}

export function TaskEditor({
  task,
  initialStatus,
  labels: availableLabels,
  currentUser,
  developmentScan,
  developmentScanLoading,
  canExecuteWithCodex,
  onCancel,
  onSave,
}: TaskEditorProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const attachmentInputRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState(task?.title ?? "");
  const [description, setDescription] = useState(task?.description ?? "");
  const [descriptionSegments, setDescriptionSegments] = useState<InlineMediaSegment[]>(
    () => createInlineMediaSegments(),
  );
  const [status, setStatus] = useState<TaskStatus>(task?.status ?? initialStatus);
  const [priority, setPriority] = useState<TaskPriority>(task?.priority ?? "none");
  const [assignee, setAssignee] = useState<ActorIdentity>(task?.assignee ?? currentUser);
  const [selectedLabels, setSelectedLabels] = useState<string[]>(task?.labels ?? []);
  const [workflowId, setWorkflowId] = useState(task?.workflowId ?? "");
  const [developmentContext, setDevelopmentContext] = useState<DevelopmentContext | null>(task?.developmentContext ?? null);
  const [dueDate, setDueDate] = useState(task?.dueDate ?? "");
  const [recurrence, setRecurrence] = useState<Recurrence | null>(task?.recurrence ?? null);
  const [blockedReason, setBlockedReason] = useState("");
  const [unblockAction, setUnblockAction] = useState("");
  const [menu, setMenu] = useState<"labels" | "more" | "due" | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [savingIntent, setSavingIntent] = useState<"save" | "execute" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<File[]>([]);
  const saving = savingIntent !== null;
  const needsBlockingInfo = status === "blocked" && task?.status !== "blocked";

  const developmentOptions = useMemo(() => {
    const options = [...developmentScan.contexts];
    if (developmentContext && !options.some((option) => contextValue(option) === contextValue(developmentContext))) {
      options.unshift(developmentContext);
    }
    return options;
  }, [developmentContext, developmentScan.contexts]);

  const assigneeOptions = [task?.assignee, currentUser, CODEX_AGENT_ACTOR]
    .filter((actor): actor is ActorIdentity => actor !== undefined)
    .filter((actor, index, actors) => (
      actors.findIndex((candidate) => actorKey(candidate) === actorKey(actor)) === index
    ));

  useEffect(() => {
    dialogRef.current?.showModal();
    titleRef.current?.focus();
    return () => {
      if (dialogRef.current?.open) dialogRef.current.close();
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const intent = !task
      && submitter instanceof HTMLButtonElement
      && submitter.value === "execute"
      ? "execute"
      : "save";
    const cleanTitle = title.trim();
    if (!cleanTitle) {
      setError("请为议题填写一个简短、明确的标题。");
      titleRef.current?.focus();
      return;
    }
    if (recurrence && !dueDate) {
      setError("重复议题需要先设置最早截止日期。");
      return;
    }
    if (needsBlockingInfo && (!blockedReason.trim() || !unblockAction.trim())) {
      setError("进入阻塞前，请填写准确的阻塞原因和需要你做的解除动作。");
      return;
    }

    setSavingIntent(intent);
    setError(null);
    try {
      const assigneeTarget = task && actorKey(assignee) === actorKey(task.assignee)
        ? undefined
        : assigneeTargetForActor(assignee, currentUser);
      const descriptionValue = task
        ? description.trim()
        : serializeInlineMedia(descriptionSegments).trim();
      await onSave({
        title: cleanTitle,
        description: descriptionValue,
        status,
        priority,
        labels: selectedLabels,
        ...(assigneeTarget ? { assigneeTarget } : {}),
        workflowId: workflowId || null,
        developmentContext,
        dueDate: dueDate || null,
        recurrence,
        ...(needsBlockingInfo ? {
          blocking: {
            reason: blockedReason.trim(),
            unblockAction: unblockAction.trim(),
          },
        } : {}),
      }, attachments, inlineMediaImages(descriptionSegments), intent);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "VERSION_CONFLICT") {
        setError("这个议题已在其他位置发生变更，请关闭并刷新后重试。");
      } else {
        setError(caught instanceof Error ? caught.message : "无法保存这个议题。");
      }
    } finally {
      setSavingIntent(null);
    }
  }

  function addAttachments(files: FileList | File[]) {
    const selected = Array.from(files);
    const oversized = selected.find((file) => file.size > MAX_ATTACHMENT_SIZE);
    if (oversized) {
      setAttachmentError(`“${oversized.name}” 超过 25 MB，无法上传。`);
      return;
    }
    setAttachmentError(null);
    setAttachments((current) => {
      const existing = new Set(current.map(fileKey));
      return [...current, ...selected.filter((file) => !existing.has(fileKey(file)))];
    });
  }

  function chooseDueDate(value: string) {
    setDueDate(value);
    setMenu(null);
  }

  return (
    <dialog
      ref={dialogRef}
      className={`task-dialog${expanded ? " is-expanded" : ""}`}
      aria-labelledby="task-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!saving) onCancel();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget && !saving) onCancel();
      }}
    >
      <form className="task-form" onSubmit={handleSubmit}>
        <header className="dialog-header">
          <div className="dialog-context">
            <strong id="task-dialog-title">{task ? task.identifier : "新建任务"}</strong>
          </div>
          <div className="dialog-header-actions">
            <button type="button" className="icon-button dialog-expand" aria-label={expanded ? "收起编辑器" : "展开编辑器"} onClick={() => setExpanded((current) => !current)}>
              <LinearIcon name="expand" />
            </button>
            <button type="button" className="icon-button dialog-close" onClick={onCancel} disabled={saving} aria-label="关闭编辑器">
              <LinearIcon name="close" />
            </button>
          </div>
        </header>

        <div className="form-body">
          <label className="composer-title">
            <span className="sr-only">标题</span>
            <input ref={titleRef} value={title} onChange={(event) => setTitle(event.target.value)} placeholder={task ? "议题标题" : "目标：要完成什么？"} maxLength={240} autoComplete="off" />
          </label>
          {task ? (
            <label className="composer-description">
              <span className="sr-only">描述</span>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="添加描述…" rows={5} />
            </label>
          ) : (
            <InlineMediaComposer
              className="composer-description inline-media-description"
              segments={descriptionSegments}
              placeholder="补充要求、验收标准和必要背景…"
              ariaLabel="描述"
              disabled={saving}
              imagePreviewLayout="strip"
              onChange={setDescriptionSegments}
              onError={setAttachmentError}
            />
          )}

          {!task && (
            <>
              <p className="task-goal-hint">
                <LinearIcon name="terminal" />
                标题是执行目标，Codex 会读取完整要求后开始工作。
              </p>
              <PendingAttachments
                files={attachments}
                disabled={saving}
                uploadLabel="保存后上传"
                ariaLabel="待上传附件"
                onRemove={(index) => setAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))}
              />
            </>
          )}

          {needsBlockingInfo && (
            <section className="editor-blocking-fields" aria-label="阻塞信息">
              <header>
                <span><LinearIcon name="alert" /></span>
                <div>
                  <strong>确认为什么不能继续</strong>
                  <p>系统不会根据评论或状态猜测，下面内容会原样记录。</p>
                </div>
              </header>
              <label>
                <span>阻塞原因</span>
                <textarea
                  value={blockedReason}
                  rows={2}
                  maxLength={4000}
                  placeholder="只写已经确认的事实，不要猜测"
                  onChange={(event) => setBlockedReason(event.target.value)}
                />
              </label>
              <label>
                <span>需要你做什么</span>
                <textarea
                  value={unblockAction}
                  rows={2}
                  maxLength={4000}
                  placeholder="写出一个明确、可执行的解除动作"
                  onChange={(event) => setUnblockAction(event.target.value)}
                />
              </label>
            </section>
          )}
        </div>

        <div className="task-form-dock">
          <div className="property-row">
            <div className="property-control property-status">
              <LinearStatusIcon status={status} className={`status-icon-${STATUS_DETAILS[status].tone}`} />
              <span className="sr-only">状态</span>
              <TaskboardSelect
                ariaLabel="状态"
                value={status}
                minMenuWidth={156}
                options={TASK_STATUSES.map((value) => ({
                  value,
                  label: STATUS_DETAILS[value].label,
                  icon: <LinearStatusIcon status={value} className={`status-icon-${STATUS_DETAILS[value].tone}`} />,
                }))}
                onChange={(nextStatus) => setStatus(nextStatus as TaskStatus)}
              />
            </div>
            <div className={`property-control property-priority priority-${priority}`}>
              <LinearPriorityIcon priority={priority} />
              <span className="sr-only">优先级</span>
              <TaskboardSelect
                ariaLabel="优先级"
                value={priority}
                minMenuWidth={148}
                options={TASK_PRIORITIES.map((nextPriority) => ({
                  value: nextPriority,
                  label: PRIORITY_LABELS[nextPriority],
                  icon: <LinearPriorityIcon priority={nextPriority} />,
                }))}
                onChange={(nextPriority) => setPriority(nextPriority as TaskPriority)}
              />
            </div>
            <div className="property-control property-assignee">
              <ActorAvatar actor={assignee} className="property-assignee-avatar" />
              <TaskboardSelect
                ariaLabel="负责人"
                value={actorKey(assignee)}
                minMenuWidth={188}
                options={assigneeOptions.map((actor) => ({
                  value: actorKey(actor),
                  label: actor.id === currentUser.id ? `${actor.name}（我）` : actor.name,
                  icon: <ActorAvatar actor={actor} className="taskboard-select-avatar" />,
                }))}
                onChange={(nextAssignee) => {
                  const selected = assigneeOptions.find((actor) => actorKey(actor) === nextAssignee);
                  if (selected) setAssignee(selected);
                }}
              />
            </div>
            <LabelPicker
              availableLabels={availableLabels}
              selectedLabels={selectedLabels}
              open={menu === "labels"}
              triggerClassName="property-control"
              showIcon
              onOpenChange={(open) => setMenu(open ? "labels" : null)}
              onChange={setSelectedLabels}
            />

            <div className="property-control property-development" title={developmentScan.workspacePath ?? undefined}>
              <LinearIcon name="branch" />
              <span className="sr-only">代码分支或 Worktree</span>
              <TaskboardSelect
                ariaLabel="代码分支或 Worktree"
                value={contextValue(developmentContext)}
                disabled={developmentScanLoading}
                minMenuWidth={224}
                options={[
                  { value: "", label: developmentScanLoading ? "正在扫描 Git…" : "分支 / Worktree" },
                  ...developmentOptions.filter((context) => context.type === "branch").map((context) => ({
                    value: contextValue(context),
                    label: contextLabel(context),
                    group: "代码分支",
                  })),
                  ...developmentOptions.filter((context) => context.type === "worktree").map((context) => ({
                    value: contextValue(context),
                    label: contextLabel(context),
                    group: "Worktree",
                  })),
                ]}
                onChange={(nextContext) => setDevelopmentContext(nextContext ? JSON.parse(nextContext) as DevelopmentContext : null)}
              />
            </div>

            {dueDate && <button className="property-control" type="button" onClick={() => setMenu("due")}><span>截止 {displayDate(dueDate)}</span></button>}
            <div className="composer-menu-anchor">
              <button className="property-control property-more" type="button" aria-label="更多属性" onClick={() => setMenu(menu === "more" ? null : "more")}><LinearIcon name="more" /></button>
              {menu === "more" && (
                <div className="composer-popover more-popover">
                  <button type="button" onClick={() => setMenu("due")}><span><LinearIcon name="calendarAdd" /></span><strong>设置截止日期</strong><kbd>⇧ D</kbd><b><LinearIcon name="chevronRight" /></b></button>
                </div>
              )}
              {menu === "due" && (
                <div className="composer-popover due-popover">
                  <label className="custom-date-row"><span>自定义…</span><input type="date" value={dueDate} onChange={(event) => chooseDueDate(event.target.value)} /></label>
                  <button type="button" onClick={() => chooseDueDate(dateFromNow(1))}><strong>明天</strong><span>{displayDate(dateFromNow(1))}</span></button>
                  <button type="button" onClick={() => chooseDueDate(endOfWeek())}><strong>本周结束</strong><span>{displayDate(endOfWeek())}</span></button>
                  <button type="button" onClick={() => chooseDueDate(dateFromNow(7))}><strong>一周后</strong><span>{displayDate(dateFromNow(7))}</span></button>
                  {dueDate && <button className="destructive-menu-row" type="button" onClick={() => { setDueDate(""); setRecurrence(null); setMenu(null); }}>清除截止日期</button>}
                </div>
              )}
            </div>
          </div>

          {attachmentError && <div className="form-error" role="alert">{attachmentError}</div>}
          {error && <div className="form-error" role="alert">{error}</div>}

          <footer className="dialog-footer">
            {!task && (
              <>
                <button className="composer-attach-icon" type="button" disabled={saving} onClick={() => attachmentInputRef.current?.click()} aria-label="上传附件">
                  <LinearIcon name="attachment" />{attachments.length > 0 && <span>{attachments.length}</span>}
                </button>
                <input ref={attachmentInputRef} type="file" multiple hidden onChange={(event) => { if (event.currentTarget.files) addAttachments(event.currentTarget.files); event.currentTarget.value = ""; }} />
              </>
            )}
            {task && <span aria-hidden="true" />}
            <div className="dialog-actions">
              {task && <span className="dialog-updated">编辑 {task.identifier}</span>}
              {task ? (
                <button className="button primary" type="submit" disabled={saving}>
                  {saving ? "正在保存…" : "保存更改"}
                </button>
              ) : (
                <>
                  <button className="button secondary" type="submit" name="taskAction" value="save" disabled={saving}>
                    {savingIntent === "save" ? "正在保存…" : "仅保存"}
                  </button>
                  <button
                    className="button primary task-execute-button"
                    type="submit"
                    name="taskAction"
                    value="execute"
                    disabled={saving || !canExecuteWithCodex}
                    title={canExecuteWithCodex ? "创建任务并立即交给 Codex" : "请在 Codex 内置任务面板中使用"}
                  >
                    <LinearIcon name="play" />
                    {savingIntent === "execute" ? "正在交给 Codex…" : "交给 Codex 执行"}
                  </button>
                </>
              )}
            </div>
          </footer>
        </div>
      </form>
    </dialog>
  );
}
