export function prepareCodexExecutionDraft(draft) {
  return {
    ...draft,
    status: "todo",
    assigneeTarget: "codex-agent",
  };
}

export function resolveCodexExecutionWorkspace(task, availableContexts, fallbackPaths) {
  const boundContext = task.developmentContext;
  const boundWorktree = boundContext?.type === "worktree"
    ? boundContext
    : boundContext?.type === "branch"
      ? availableContexts.find((context) => (
        context.type === "worktree" && context.branch === boundContext.branch
      ))
      : null;
  const candidates = [boundWorktree?.path, ...fallbackPaths];
  return candidates
    .map((candidate) => candidate?.trim())
    .find(Boolean);
}
