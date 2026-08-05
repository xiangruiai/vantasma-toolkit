export type DirectGoalDevelopmentContext =
  | { type: "branch"; branch: string }
  | { type: "worktree"; path: string; branch: string | null };

export function prepareCodexExecutionDraft<
  T extends { status: string; assigneeTarget?: string },
>(draft: T): T & { status: "todo"; assigneeTarget: "codex-agent" };

export function resolveCodexExecutionWorkspace(
  task: { developmentContext: DirectGoalDevelopmentContext | null },
  availableContexts: DirectGoalDevelopmentContext[],
  fallbackPaths: Array<string | null | undefined>,
): string | undefined;
