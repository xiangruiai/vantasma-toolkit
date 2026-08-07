import type { RunningCodexThread, Task } from "../types";
import { LinearIcon, LinearStatusIcon } from "./LinearIcon";

interface RelatedConversationsProps {
  tasks: Task[];
  runningThreads: RunningCodexThread[];
  onOpenIssue: (task: Task) => void;
  onOpenThread: (threadId: string) => void;
}

export function RelatedConversations({
  tasks,
  runningThreads,
  onOpenIssue,
  onOpenThread,
}: RelatedConversationsProps) {
  const conversationTasks = tasks.filter((task) => task.threadId);
  const total = conversationTasks.length + runningThreads.length;

  return (
    <section className="related-conversations-view">
      <header className="related-conversations-header">
        <div>
          <span className="related-conversations-eyebrow">项目工作区</span>
          <h2>相关对话</h2>
          <p>这里汇总已经和 Codex 对话关联的议题。打开对话后，顶部仍可一键返回看板。</p>
        </div>
        <span className="related-conversations-count">{total}</span>
      </header>

      {total === 0 ? (
        <div className="related-conversations-empty">
          <LinearIcon name="conversation" />
          <strong>还没有相关对话</strong>
          <span>从议题中启动或关联 Codex 对话后，会集中显示在这里。</span>
        </div>
      ) : (
        <div className="related-conversations-sections">
          {conversationTasks.length > 0 && (
            <section className="related-conversations-group" aria-labelledby="linked-conversations-title">
              <header className="related-conversations-group-header">
                <strong id="linked-conversations-title">已关联议题</strong>
                <span>{conversationTasks.length}</span>
              </header>
              <div className="related-conversations-list">
                {conversationTasks.map((task) => (
                  <article className="related-conversation-row" key={task.id}>
                    <div className="related-conversation-status">
                      <LinearStatusIcon status={task.status} />
                    </div>
                    <button
                      type="button"
                      className="related-conversation-issue"
                      onClick={() => onOpenIssue(task)}
                    >
                      <span>{task.identifier}</span>
                      <strong>{task.title}</strong>
                    </button>
                    <button
                      type="button"
                      className="related-conversation-open"
                      onClick={() => onOpenThread(task.threadId!)}
                    >
                      <LinearIcon name="conversation" />
                      打开对话
                    </button>
                  </article>
                ))}
              </div>
            </section>
          )}

          {runningThreads.length > 0 && (
            <section className="related-conversations-group" aria-labelledby="running-conversations-title">
              <header className="related-conversations-group-header">
                <span className="running-conversation-indicator" aria-hidden="true" />
                <strong id="running-conversations-title">运行中的未关联对话</strong>
                <span>{runningThreads.length}</span>
              </header>
              <p className="related-conversations-group-note">
                这些是 Codex 对话，不是任务面板议题，不会计入“进行中”任务。
              </p>
              <div className="related-conversations-list">
                {runningThreads.map((thread) => (
                  <article className="related-conversation-row is-running" key={thread.threadId}>
                    <div className="related-conversation-status">
                      <LinearIcon name="conversation" />
                    </div>
                    <div className="related-conversation-summary">
                      <span>Codex 正在执行</span>
                      <strong>{thread.title}</strong>
                    </div>
                    <button
                      type="button"
                      className="related-conversation-open"
                      onClick={() => onOpenThread(thread.threadId)}
                    >
                      <LinearIcon name="conversation" />
                      打开对话
                    </button>
                  </article>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </section>
  );
}
