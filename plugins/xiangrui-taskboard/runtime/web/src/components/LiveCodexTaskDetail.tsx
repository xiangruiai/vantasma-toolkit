import type { RunningCodexThread } from "../types";
import { LinearIcon, LinearStatusIcon } from "./LinearIcon";

interface LiveCodexTaskDetailProps {
  thread: RunningCodexThread;
  projectName: string;
  onOpenThread: (threadId: string) => void;
}

export function LiveCodexTaskDetail({
  thread,
  projectName,
  onOpenThread,
}: LiveCodexTaskDetailProps) {
  return (
    <section className="issue-detail live-codex-task-detail">
      <div className="issue-detail-scroll">
        <div className="live-codex-task-detail-layout">
          <main className="live-codex-task-detail-main">
            <div className="live-codex-task-detail-kicker">
              <span className="live-codex-task-indicator" aria-hidden="true" />
              Codex 实时任务
            </div>
            <h1>{thread.title}</h1>
            <p>
              这项任务来自 Codex 当前真实的执行状态。它会在执行期间显示在“进行中”，
              停止执行后自动从实时卡片中移除，不会猜测任务已经完成。
            </p>
            <button
              className="button primary live-codex-task-open-thread"
              type="button"
              onClick={() => onOpenThread(thread.threadId)}
            >
              <LinearIcon name="conversation" />
              打开 Codex 对话
            </button>
          </main>

          <aside className="live-codex-task-detail-properties" aria-label="实时任务属性">
            <h2>属性</h2>
            <div className="live-codex-task-detail-property">
              <span><LinearStatusIcon status="in_progress" /> 状态</span>
              <strong>进行中</strong>
            </div>
            <div className="live-codex-task-detail-property">
              <span><LinearIcon name="project" /> 项目</span>
              <strong>{projectName}</strong>
            </div>
            <div className="live-codex-task-detail-property">
              <span><LinearIcon name="conversation" /> 来源</span>
              <strong>Codex 实时状态</strong>
            </div>
            <div className="live-codex-task-detail-thread-id">
              <span>对话 ID</span>
              <code>{thread.threadId}</code>
            </div>
          </aside>
        </div>
      </div>
    </section>
  );
}
