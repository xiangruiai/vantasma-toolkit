import type { Task } from "../types";
import { LinearIcon, LinearStatusIcon } from "./LinearIcon";

interface RelatedConversationsProps {
  tasks: Task[];
  onOpenIssue: (task: Task) => void;
  onOpenThread: (threadId: string) => void;
}
export function RelatedConversations({
  tasks,
  onOpenIssue,
  onOpenThread,
}: RelatedConversationsProps) {
  const conversationTasks = tasks.filter((task) => task.threadId);

  return (
    <section className="related-conversations-view">
      <header className="related-conversations-header">
        <div>
          <span className="related-conversations-eyebrow">项目工作区</span>
          <h2>相关对话</h2>
          <p>这里汇总已经和 Codex 对话关联的议题。打开对话后，顶部仍可一键返回看板。</p>
        </div>
        <span className="related-conversations-count">{conversationTasks.length}</span>
      </header>

      {conversationTasks.length === 0 ? (
        <div className="related-conversations-empty">
          <LinearIcon name="conversation" />
          <strong>还没有相关对话</strong>
          <span>从议题中启动或关联 Codex 对话后，会集中显示在这里。</span>
        </div>
      ) : (
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
      )}
    </section>
  );
}
