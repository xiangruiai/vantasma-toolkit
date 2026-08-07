import type { RunningCodexThread } from "../types";
import { LinearIcon } from "./LinearIcon";

interface LiveCodexTaskCardProps {
  thread: RunningCodexThread;
  opening: boolean;
  onOpen: (thread: RunningCodexThread) => void;
}

export function LiveCodexTaskCard({ thread, opening, onOpen }: LiveCodexTaskCardProps) {
  return (
    <article
      className="task-card live-codex-task"
      aria-labelledby={`live-codex-task-${thread.threadId}-title`}
      data-live-thread-id={thread.threadId}
    >
      <button
        className="task-card-open"
        type="button"
        disabled={opening}
        aria-label={opening ? `正在打开任务详情：${thread.title}` : `打开任务详情：${thread.title}`}
        onClick={() => onOpen(thread)}
      />

      <div className="card-topline">
        <span className="live-codex-task-source">
          <span className="live-codex-task-indicator" aria-hidden="true" />
          Codex 正在执行
        </span>
        <span className="live-codex-task-realtime">实时</span>
      </div>

      <h3 id={`live-codex-task-${thread.threadId}-title`}>{thread.title}</h3>

      <div className="card-properties" aria-label="实时任务属性">
        <span className="live-codex-task-property">
          <LinearIcon name="conversation" />
          {opening ? "正在建立任务详情…" : "点击查看任务详情"}
        </span>
      </div>
    </article>
  );
}
