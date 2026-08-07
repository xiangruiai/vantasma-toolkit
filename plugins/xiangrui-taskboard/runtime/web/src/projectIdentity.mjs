function normalizedWorkspacePath(value) {
  if (typeof value !== "string") return null;
  const normalized = value.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized || null;
}

function selectCanonicalProject(projects, workspacePath) {
  if (projects.length === 1) return projects[0];

  const explicitlyMapped = projects.filter(
    (project) => normalizedWorkspacePath(project.workspacePath) === workspacePath,
  );
  if (explicitlyMapped.length === 1) return explicitlyMapped[0];

  const populated = projects.filter((project) => Number(project.issueCount) > 0);
  if (explicitlyMapped.length === 0 && populated.length === 1) return populated[0];
  return null;
}

export function createProjectIdentityResolver({
  persistedProjects = [],
  codexProjects = [],
  workspacePaths = {},
  currentCodexProjectId = null,
  currentWorkspacePath = null,
} = {}) {
  const persistedById = new Map(persistedProjects.map((project) => [project.id, project]));

  function workspacePathForId(projectId) {
    const configuredPath = normalizedWorkspacePath(workspacePaths[projectId]);
    if (configuredPath) return configuredPath;
    const persistedPath = normalizedWorkspacePath(persistedById.get(projectId)?.workspacePath);
    if (persistedPath) return persistedPath;
    if (projectId === currentCodexProjectId) {
      return normalizedWorkspacePath(currentWorkspacePath);
    }
    return null;
  }

  const persistedByWorkspace = new Map();
  for (const project of persistedProjects) {
    const workspacePath = workspacePathForId(project.id);
    if (!workspacePath) continue;
    const group = persistedByWorkspace.get(workspacePath) ?? [];
    group.push(project);
    persistedByWorkspace.set(workspacePath, group);
  }

  const canonicalByWorkspace = new Map();
  for (const [workspacePath, projects] of persistedByWorkspace) {
    const canonical = selectCanonicalProject(projects, workspacePath);
    if (canonical) canonicalByWorkspace.set(workspacePath, canonical);
  }

  function canonicalProjectId(projectId) {
    if (typeof projectId !== "string" || !projectId) return null;
    const workspacePath = workspacePathForId(projectId);
    const canonical = workspacePath ? canonicalByWorkspace.get(workspacePath) : null;
    return canonical?.id ?? projectId;
  }

  const canonicalCodexProjectIds = new Set(
    codexProjects.flatMap((project) => {
      const projectId = canonicalProjectId(project?.id);
      return projectId ? [projectId] : [];
    }),
  );

  return {
    canonicalProjectId,
    isCanonicalPersistedProject(projectId) {
      return persistedById.has(projectId) && canonicalProjectId(projectId) === projectId;
    },
    hasCodexProject(projectId) {
      const canonicalId = canonicalProjectId(projectId);
      return Boolean(canonicalId && canonicalCodexProjectIds.has(canonicalId));
    },
    workspacePathFor(projectId) {
      const canonicalId = canonicalProjectId(projectId);
      return canonicalId
        ? workspacePathForId(canonicalId) ?? workspacePathForId(projectId)
        : workspacePathForId(projectId);
    },
  };
}
