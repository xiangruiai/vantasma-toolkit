import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AUTOMATION_MODELS,
  getAutomationModel,
  withAutomationModel,
  type AutomationModel,
  type AutomationReasoningEffort,
} from "../../../shared/taskboard-automation-options.mjs";
import { LinearIcon } from "./LinearIcon";
import { TaskboardSelect } from "./TaskboardSelect";

type AutomationStatus = "ACTIVE" | "PAUSED";
type AutomationQuotaState = "available" | "blocked" | "unknown" | "unavailable";
type IntervalMinutes = 5 | 10 | 15 | 30 | 60;

interface AutomationOptions {
  enabledByUser: boolean;
  quotaAware: boolean;
  intervalMinutes: IntervalMinutes;
  model: AutomationModel;
  reasoningEffort: AutomationReasoningEffort;
}

interface AutomationState extends AutomationOptions {
  status: AutomationStatus;
  quota?: {
    state: AutomationQuotaState;
    checkedAt: number;
    resetsAt?: number;
    reason?: "api-key";
  };
}

interface ProjectAutomationMenuProps {
  automation?: Partial<AutomationState>;
  pending: boolean;
  error: string | null;
  unavailableReason: string | null;
  onOpen: () => void;
  onChange: (options: AutomationOptions) => void;
}

const DEFAULT_OPTIONS: AutomationOptions = {
  enabledByUser: false,
  quotaAware: false,
  intervalMinutes: 5,
  model: "gpt-5.5",
  reasoningEffort: "high",
};

const EFFORT_LABELS: Record<AutomationReasoningEffort, string> = {
  low: "轻度",
  medium: "中",
  high: "高",
  xhigh: "极高 (xhigh)",
  max: "最高",
  ultra: "极高 (ultra)",
};

export function ProjectAutomationMenu({
  automation,
  pending,
  error,
  unavailableReason,
  onOpen,
  onChange,
}: ProjectAutomationMenuProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const wasPendingRef = useRef(pending);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0, ready: false });
  const [draft, setDraft] = useState<AutomationOptions>(DEFAULT_OPTIONS);
  const status = automation?.status ?? "PAUSED";
  const quota = automation?.quota;
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
            : status === "ACTIVE"
              ? "运行中"
              : "已暂停");
  const triggerLabel = pending
    ? "正在更新"
    : status === "ACTIVE" && !unavailableLabel
      ? "自动认领"
      : stateLabel;
  const active = status === "ACTIVE" && !unavailableLabel;
  const disabled = pending || Boolean(unavailableReason);

  useEffect(() => {
    if (!open) return;
    setDraft({ ...DEFAULT_OPTIONS, ...automation });
  }, [open]);

  useEffect(() => {
    if (wasPendingRef.current && !pending) {
      setDraft({ ...DEFAULT_OPTIONS, ...automation });
    }
    wasPendingRef.current = pending;
  }, [automation, pending]);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current || !menuRef.current) return;
    const trigger = triggerRef.current.getBoundingClientRect();
    const menu = menuRef.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(trigger.right - menu.width, window.innerWidth - menu.width - 8));
    const top = trigger.bottom + 8 + menu.height <= window.innerHeight
      ? trigger.bottom + 8
      : Math.max(8, trigger.top - menu.height - 8);
    setPosition({ left, top, ready: true });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function closeFromOutside(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node) && !triggerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function closeFromViewportChange() {
      setOpen(false);
    }
    function closeFromEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", closeFromOutside);
    document.addEventListener("keydown", closeFromEscape);
    window.addEventListener("resize", closeFromViewportChange);
    window.addEventListener("scroll", closeFromViewportChange, true);
    return () => {
      document.removeEventListener("pointerdown", closeFromOutside);
      document.removeEventListener("keydown", closeFromEscape);
      window.removeEventListener("resize", closeFromViewportChange);
      window.removeEventListener("scroll", closeFromViewportChange, true);
    };
  }, [open]);

  const submitChange = (next: AutomationOptions) => {
    if (disabled) return;
    setDraft(next);
    onChange(next);
  };

  const menu = open ? createPortal(
    <div
      ref={menuRef}
      className="project-automation-menu no-drag"
      role="dialog"
      aria-label="自动认领待办设置"
      style={{ left: position.left, top: position.top, visibility: position.ready ? "visible" : "hidden" }}
    >
      <div className="project-automation-menu-heading">
        <strong>自动认领待办</strong>
        <span className={status === "ACTIVE" ? "is-active" : "is-paused"}>
          {stateLabel}
        </span>
      </div>
      <div className="project-automation-switch">
        <span>自动认领开关</span>
        <button
          type="button"
          className={`board-setting-switch${draft.enabledByUser ? " is-on" : ""}`}
          role="switch"
          aria-checked={draft.enabledByUser}
          disabled={disabled}
          onClick={() => submitChange({
            ...draft,
            enabledByUser: !draft.enabledByUser,
          })}
        >
          <span aria-hidden="true" />
        </button>
      </div>
      <div className="project-automation-switch">
        <span>根据额度启用/关闭</span>
        <button
          type="button"
          className={`board-setting-switch${draft.quotaAware ? " is-on" : ""}`}
          role="switch"
          aria-checked={draft.quotaAware}
          disabled={disabled}
          onClick={() => submitChange({
            ...draft,
            quotaAware: !draft.quotaAware,
          })}
        >
          <span aria-hidden="true" />
        </button>
      </div>
      {draft.quotaAware && (
        <div className={`project-automation-quota is-${quota?.state ?? "unknown"}`}>
          {quota?.state === "available" && "当前额度可用"}
          {quota?.state === "blocked" && (
            quota.resetsAt
              ? `额度已用尽，预计 ${formatResetTime(quota.resetsAt)} 恢复`
              : "额度已用尽，自动认领已暂停"
          )}
          {quota?.state === "unavailable" && (
            quota.reason === "api-key"
              ? "API Key 模式不支持读取 Codex App 额度"
              : "当前账户无法读取额度"
          )}
          {(!quota || quota.state === "unknown") && "额度状态未知，自动认领已暂停"}
        </div>
      )}
      <div className="project-automation-field">
        <span>间隔</span>
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
      </div>
      <div className="project-automation-field">
        <span>模型</span>
        <TaskboardSelect
          ariaLabel="自动认领模型"
          value={draft.model}
          disabled={disabled}
          minMenuWidth={132}
          options={AUTOMATION_MODELS.map((model) => ({ value: model.slug, label: model.label }))}
          onChange={(value) => submitChange(withAutomationModel(draft, value as AutomationModel))}
        />
      </div>
      <div className="project-automation-field">
        <span>推理强度</span>
        <TaskboardSelect
          ariaLabel="自动认领推理强度"
          value={draft.reasoningEffort}
          disabled={disabled}
          minMenuWidth={132}
          options={getAutomationModel(draft.model).efforts.map((effort) => ({
            value: effort,
            label: EFFORT_LABELS[effort],
          }))}
          onChange={(value) => submitChange({
            ...draft,
            reasoningEffort: value as AutomationReasoningEffort,
          })}
        />
      </div>
      {unavailableReason && <p className="project-automation-note">{unavailableReason}</p>}
      {error && error !== unavailableReason && <p className="project-automation-error" role="alert">{error}</p>}
    </div>,
    document.body,
  ) : null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`project-automation-trigger no-drag ${active ? "is-active" : "is-paused"}`}
        aria-label={triggerLabel}
        aria-busy={pending}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={triggerLabel}
        onClick={() => {
          if (!open) {
            setPosition((current) => ({ ...current, ready: false }));
            onOpen();
          }
          setOpen((current) => !current);
        }}
      >
        <LinearIcon name={active ? "play" : "pause"} />
        <span>{triggerLabel}</span>
      </button>
      {menu}
    </>
  );
}

function formatResetTime(value: number) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1_000));
}
