import { LinearIcon } from "./LinearIcon";

export interface ProjectNavigatorProject {
  id: string;
  name: string;
  workspacePath: string | null;
  issueCount: number;
  inProgressCount: number;
  runningConversationCount: number;
  doneCount: number;
  inCodex: boolean;
  persisted: boolean;
}

interface ProjectNavigatorProps {
  projects: ProjectNavigatorProject[];
  selectedProjectId: string;
  openingProjectId: string | null;
  onCreate: () => void;
  onSelect: (project: ProjectNavigatorProject) => void;
}

export function ProjectNavigator({
  projects,
  selectedProjectId,
  openingProjectId,
  onCreate,
  onSelect,
}: ProjectNavigatorProps) {
  const groups = [
    {
      id: "running",
      label: "正在执行",
      projects: projects.filter((project) => project.inProgressCount > 0),
    },
    {
      id: "with-issues",
      label: "已有议题",
      projects: projects.filter((project) => (
        project.issueCount > 0
        && project.inProgressCount === 0
        && project.runningConversationCount === 0
      )),
    },
    {
      id: "running-conversations",
      label: "有运行中对话",
      projects: projects.filter((project) => (
        project.inProgressCount === 0 && project.runningConversationCount > 0
      )),
    },
    {
      id: "empty-projects",
      label: "已启用，暂无议题",
      projects: projects.filter((project) => (
        project.persisted && project.issueCount === 0 && project.inProgressCount === 0 && project.runningConversationCount === 0
      )),
    },
    {
      id: "untracked-projects",
      label: "未启用任务面板",
      projects: projects.filter((project) => !project.persisted && project.inProgressCount === 0 && project.runningConversationCount === 0),
    },
  ];

  return (
    <aside className="project-navigator" aria-label="项目导航">
      <header className="project-navigator-header">
        <span className="project-navigator-heading">
          <LinearIcon name="project" />
          <strong>项目</strong>
          <span>{projects.length}</span>
        </span>
        <button
          type="button"
          className="icon-button project-navigator-create"
          aria-label="在当前项目新建任务"
          title="新建任务"
          onClick={onCreate}
        >
          <LinearIcon name="plus" />
        </button>
      </header>

      <div className="project-navigator-scroll">
        {groups.map((group) => group.projects.length > 0 && (
          <section className="project-navigator-group" key={group.id}>
            <div className="project-navigator-group-title">
              <span>{group.label}</span>
              <span>{group.projects.length}</span>
            </div>
            <div className="project-navigator-items">
              {group.projects.map((project) => {
                const isActive = project.id === selectedProjectId;
                const isOpening = project.id === openingProjectId;
                const completionPercent = project.issueCount > 0
                  ? Math.round((project.doneCount / project.issueCount) * 100)
                  : 0;
                const progressSummary = !project.persisted
                  ? project.runningConversationCount > 0
                    ? `${project.runningConversationCount} 个运行中对话 · 点击启用任务面板`
                    : "未启用任务面板 · 点击启用"
                  : project.inProgressCount > 0
                    ? project.issueCount > 0
                      ? `${project.inProgressCount} 项执行中 · 已完成 ${project.doneCount}/${project.issueCount}`
                      : `${project.inProgressCount} 项执行中 · 暂无持久议题`
                    : project.runningConversationCount > 0
                      ? project.issueCount > 0
                        ? `${project.runningConversationCount} 个运行中对话 · ${project.issueCount} 个议题`
                        : `${project.runningConversationCount} 个运行中对话 · 暂无议题`
                    : project.issueCount > 0
                      ? `${project.issueCount} 个议题 · 已完成 ${project.doneCount}/${project.issueCount}`
                      : "任务面板已启用 · 暂无议题";
                return (
                  <button
                    type="button"
                    key={project.id}
                    className={`project-navigator-item${isActive ? " is-active" : ""}${project.inProgressCount > 0 ? " is-running" : ""}${project.runningConversationCount > 0 ? " has-running-conversations" : ""}`}
                    aria-current={isActive ? "page" : undefined}
                    disabled={openingProjectId !== null}
                    onClick={() => {
                      if (!isActive) onSelect(project);
                    }}
                    title={`打开 ${project.name} 看板 · ${progressSummary}`}
                  >
                    <span className="project-navigator-avatar" aria-hidden="true">
                      {project.name.slice(0, 1).toUpperCase()}
                    </span>
                    <span className="project-navigator-copy">
                      <strong>{project.name}</strong>
                      <span>{progressSummary}</span>
                      {project.issueCount > 0 && (
                        <span
                          className="project-navigator-progress"
                          role="progressbar"
                          aria-label={`${project.name} 已完成 ${project.doneCount}/${project.issueCount}`}
                          aria-valuemin={0}
                          aria-valuemax={project.issueCount}
                          aria-valuenow={project.doneCount}
                        >
                          <i style={{ width: `${completionPercent}%` }} />
                        </span>
                      )}
                    </span>
                    <span className="project-navigator-action" aria-hidden="true">
                      {isOpening ? "打开中" : isActive ? <LinearIcon name="check" /> : <LinearIcon name="chevronRight" />}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </aside>
  );
}
