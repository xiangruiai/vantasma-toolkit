export interface ProjectIdentityRecord {
  id: string;
  name: string;
  workspacePath?: string | null;
  issueCount?: number;
  createdAt?: string;
}

export interface CodexProjectIdentity {
  id: string;
  name: string;
}

export interface ProjectIdentityResolver {
  canonicalProjectId(projectId: string): string | null;
  isCanonicalPersistedProject(projectId: string): boolean;
  hasCodexProject(projectId: string): boolean;
  workspacePathFor(projectId: string): string | null;
}

export function createProjectIdentityResolver(options?: {
  persistedProjects?: ProjectIdentityRecord[];
  codexProjects?: CodexProjectIdentity[];
  workspacePaths?: Record<string, string>;
  currentCodexProjectId?: string | null;
  currentWorkspacePath?: string | null;
}): ProjectIdentityResolver;
