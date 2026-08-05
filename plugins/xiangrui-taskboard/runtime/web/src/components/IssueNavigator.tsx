import { TASK_STATUSES, type Task } from "../types";
import { STATUS_DETAILS } from "./BoardColumn";
import { LinearIcon, LinearStatusIcon } from "./LinearIcon";

interface IssueNavigatorProps {
  projectName: string;
  tasks: Task[];
  selectedTaskId: string | null;
  onCreate: () => void;
  onSelect: (task: Task) => void;
}

export function IssueNavigator({
  projectName,
  tasks,
  selectedTaskId,
  onCreate,
  onSelect,
}: IssueNavigatorProps) {
  return (
    <aside className="issue-navigator" aria-label="项目议题导航">
      <header className="issue-navigator-header">
        <div className="issue-navigator-title">
          <span className="issue-navigator-project-mark" aria-hidden="true">
            {projectName.slice(0, 1).toUpperCase()}
          </span>
          <span className="issue-navigator-project-copy">
            <small>项目</small>
            <strong>{projectName}</strong>
          </span>
          <span className="issue-navigator-total">{tasks.length}</span>
        </div>
        <button
          type="button"
          className="icon-button issue-navigator-add"
          onClick={onCreate}
          aria-label="新建议题"
          title="新建议题"
        >
          <LinearIcon name="plus" />
        </button>
      </header>

      <div className="issue-navigator-scroll">
        {TASK_STATUSES.map((status) => {
          const statusTasks = tasks.filter((task) => task.status === status);
          if (statusTasks.length === 0) return null;
          const details = STATUS_DETAILS[status];

          return (
            <section className="issue-navigator-group" key={status}>
              <div className="issue-navigator-group-title">
                <LinearStatusIcon status={status} />
                <span>{details.label}</span>
                <span className="issue-navigator-group-count">{statusTasks.length}</span>
              </div>
              <div className="issue-navigator-items">
                {statusTasks.map((task) => (
                  <button
                    type="button"
                    key={task.id}
                    className={`issue-navigator-item${selectedTaskId === task.id ? " is-active" : ""}`}
                    onClick={() => onSelect(task)}
                    title={`${task.identifier} ${task.title}`}
                  >
                    <span className="issue-navigator-identifier">{task.identifier}</span>
                    <span className="issue-navigator-item-title">{task.title}</span>
                  </button>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </aside>
  );
}
