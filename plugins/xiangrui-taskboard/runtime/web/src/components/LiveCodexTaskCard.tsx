import type { RunningCodexThread } from "../types";
import { LinearIcon } from "./LinearIcon";

interface LiveCodexTaskCardProps {
  thread: RunningCodexThread;
  onOpen: (thread: RunningCodexThread) => void;
}

export function LiveCodexTaskCard({ thread, onOpen }: LiveCodexTaskCardProps) {
  return (
    <article
      className="task-card live-codex-task"
      aria-labelledby={`live-codex-task-${thread.threadId}-title`}
      data-live-thread-id={thread.threadId}
    >
      <button
        className="task-card-open"
        type="button"
        aria-label={`查看正在执行的任务：${thread.title}`}
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
          未关联议题
        </span>
      </div>
    </article>
  );
}
