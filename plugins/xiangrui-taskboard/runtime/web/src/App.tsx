import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  isAutomationModel,
  isAutomationReasoningEffort,
  isSupportedModelEffort,
  type AutomationModel,
  type AutomationReasoningEffort,
} from "../../shared/taskboard-automation-options.mjs";
import {
  prepareCodexExecutionDraft,
  resolveCodexExecutionWorkspace,
} from "../../shared/direct-goal-dispatch.mjs";
import {
  ApiError,
  addTaskRelation,
  archiveTask as archiveTaskRequest,
  createProject as createProjectRequest,
  createTask as createTaskRequest,
  getTaskboardRevision,
  getWorkflowWorkspace,
  getTaskboardMetadata,
  listDevelopmentContexts,
  listDeviceWorkspaces,
  listProjects,
  listTasks,
  moveTask as moveTaskRequest,
  removeTaskRelation,
  restoreTask as restoreTaskRequest,
  setCurrentUserActor,
  uploadAttachment,
  updateTask as updateTaskRequest,
} from "./api";
import {
  actorForAssigneeTarget,
  assigneeTargetForActor,
} from "./actors";
import { reloadIfTaskboardBuildStale } from "./build-recovery";
import { BoardColumn, STATUS_DETAILS } from "./components/BoardColumn";
import { AiChat } from "./components/AiChat";
import { BlockTaskDialog } from "./components/BlockTaskDialog";
import {
  resolveInlineMediaMarkdown,
  type PendingInlineImage,
} from "./components/InlineMediaComposer";
import { LinearIcon, LinearStatusIcon } from "./components/LinearIcon";
import { ProjectNavigator } from "./components/ProjectNavigator";
import { ProjectAutomationMenu } from "./components/ProjectAutomationMenu";
import { RelatedConversations } from "./components/RelatedConversations";
import { TaskContextMenu } from "./components/TaskContextMenu";
import { TaskDetail } from "./components/TaskDetail";
import { TaskEditor } from "./components/TaskEditor";
import { TaskFilterMenu } from "./components/TaskFilterMenu";
import { buildIssueUrl, readIssueIdentifier } from "./issueRoute";
import { DEFAULT_LABELS } from "./labels";
import { createProjectIdentityResolver } from "./projectIdentity.mjs";
import {
  EMPTY_TASK_FILTERS,
  matchesTaskFilters,
  matchesTaskSearch,
  readTaskFilters,
  taskFilterCount,
  writeTaskFilters,
} from "./taskFilters";
import {
  TASK_STATUSES,
  type ActorIdentity,
  type BlockingDraft,
  type DevelopmentScan,
  type HostContext,
  type IssueRelationType,
  type Project,
  type RunningCodexThread,
  type Task,
  type TaskboardMetadata,
  type TaskDraft,
  type TaskStatus,
  type WorkflowOption,
} from "./types";
import {
  DEFAULT_WORKFLOW_OPTIONS,
  readLegacyWorkflowWorkspace,
  workflowOptionsFromWorkspace,
} from "./workflowStore";
// The poller stays in ESM JavaScript so its lifecycle can be tested directly with node:test.
// @ts-expect-error The module's option contract is enforced by its focused node tests.
import { createRevisionPoller, getRevisionPollingInterval } from "./revisionPolling.mjs";

type ConnectionState = "connecting" | "live" | "reconnecting";
type Theme = "light" | "dark";
type BoardView = "issues" | "workflow";
type WorkspacePane = "board" | "issue" | "conversations";
const SHOW_WORKFLOW_BOARD_ENTRY = false;

const WorkflowBoard = lazy(() => import("./components/WorkflowBoard").then((module) => ({
  default: module.WorkflowBoard,
})));

interface EditorState {
  task: Task | null;
  status: TaskStatus;
}

interface ContextMenuState {
  taskId: string;
  x: number;
  y: number;
}

interface BlockingRequest {
  task: Task;
  resolve: (blocking: BlockingDraft | null) => void;
}

interface ProjectChoice {
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

interface UndoOperation {
  id: number;
  message: string;
  undo: () => Promise<void>;
}

interface UndoNotice {
  id: number;
  message: string;
}

type ProjectAutomationStatus = "ACTIVE" | "PAUSED";
type AutomationQuotaState = "available" | "blocked" | "unknown" | "unavailable";
type AutomationIntervalMinutes = 5 | 10 | 15 | 30 | 60;

interface AutomationQuotaStatus {
  state: AutomationQuotaState;
  checkedAt: number;
  resetsAt?: number;
  reason?: "api-key";
}

interface ProjectAutomationRecord {
  automationId?: string;
  codexProjectId: string;
  status: ProjectAutomationStatus;
  enabledByUser: boolean;
  quotaAware: boolean;
  quota?: AutomationQuotaStatus;
  intervalMinutes: AutomationIntervalMinutes;
  model: AutomationModel;
  reasoningEffort: AutomationReasoningEffort;
}

type ProjectAutomations = Record<string, ProjectAutomationRecord>;

interface AutomationHostItem {
  id: string;
  status: ProjectAutomationStatus;
  model: AutomationModel;
  reasoningEffort: AutomationReasoningEffort;
  rrule: string;
}

interface AutomationHostResponse {
  requestId: string;
  ok: boolean;
  item?: AutomationHostItem;
  items?: AutomationHostItem[];
  quota?: AutomationQuotaStatus;
  policy?: {
    automationId?: string;
    enabledByUser: boolean;
    quotaAware: boolean;
    intervalMinutes: AutomationIntervalMinutes;
    model: AutomationModel;
    reasoningEffort: AutomationReasoningEffort;
  };
  error?: string;
}

interface PendingAutomationRequest {
  resolve: (response: AutomationHostResponse) => void;
  reject: (error: Error) => void;
  timeoutId: number;
}

const DEFAULT_USER_ACTOR: ActorIdentity = {
  type: "user",
  id: "local-user",
  name: "本地用户",
  avatarUrl: null,
};

const LAST_PROJECT_KEY = "taskboard.lastProjectId";
const FAVORITE_PROJECTS_KEY = "taskboard.favoriteProjectIds";
const DEVICE_WORKSPACE_PATHS_KEY = "taskboard.deviceWorkspacePaths.v1";
const PROJECT_AUTOMATIONS_KEY = "taskboard.projectAutomations.v1";
const DEFAULT_AUTOMATION_OPTIONS = {
  enabledByUser: false,
  quotaAware: false,
  intervalMinutes: 5,
  model: "gpt-5.5",
  reasoningEffort: "high",
} as const;

const EVENT_NAMES = [
  "task.created",
  "task.updated",
  "task.moved",
  "task.archived",
  "task.restored",
  "task.relation.updated",
  "comment.created",
  "comment.updated",
  "comment.deleted",
  "attachment.created",
  "attachment.deleted",
  "project.created",
  "project.updated",
  "workflow.updated",
] as const;

function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark";
}

function getInitialTheme(): Theme {
  const fromQuery = new URLSearchParams(window.location.search).get("theme");
  if (isTheme(fromQuery)) return fromQuery;
  const stored = window.localStorage.getItem("taskboard.theme");
  if (isTheme(stored)) return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readFavoriteProjectIds(): Set<string> {
  try {
    const value = JSON.parse(window.localStorage.getItem(FAVORITE_PROJECTS_KEY) ?? "[]");
    return new Set(Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
  } catch {
    return new Set();
  }
}

function readDeviceWorkspacePaths(): Record<string, string> {
  try {
    const value = JSON.parse(window.localStorage.getItem(DEVICE_WORKSPACE_PATHS_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => (
      typeof entry[1] === "string" && entry[1].trim().length > 0
    )));
  } catch {
    return {};
  }
}

function readProjectAutomations(): ProjectAutomations {
  try {
    const value = JSON.parse(window.localStorage.getItem(PROJECT_AUTOMATIONS_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    const result: ProjectAutomations = {};
    for (const [projectId, record] of Object.entries(value)) {
      if (!record || typeof record !== "object" || Array.isArray(record)) continue;
      const candidate = record as Partial<ProjectAutomationRecord>;
      const model = candidate.model ?? "gpt-5.5";
      const reasoningEffort = candidate.reasoningEffort ?? "high";
      const enabledByUser = candidate.enabledByUser ?? candidate.status === "ACTIVE";
      const quotaAware = candidate.quotaAware ?? false;
      if (
        (candidate.automationId !== undefined && typeof candidate.automationId !== "string")
        || typeof candidate.codexProjectId !== "string"
        || (candidate.status !== "ACTIVE" && candidate.status !== "PAUSED")
        || !isAutomationIntervalMinutes(candidate.intervalMinutes ?? 5)
        || !isAutomationModel(model)
        || !isAutomationReasoningEffort(reasoningEffort)
        || !isSupportedModelEffort(model, reasoningEffort)
        || (candidate.status === "ACTIVE" && !candidate.automationId)
        || typeof enabledByUser !== "boolean"
        || typeof quotaAware !== "boolean"
      ) continue;
      const quota = isAutomationQuotaStatus(candidate.quota) ? candidate.quota : undefined;
      result[projectId] = {
        automationId: candidate.automationId,
        codexProjectId: candidate.codexProjectId,
        status: candidate.status,
        enabledByUser,
        quotaAware,
        ...(quota ? { quota } : {}),
        intervalMinutes: candidate.intervalMinutes ?? 5,
        model,
        reasoningEffort,
      };
    }
    return result;
  } catch {
    return {};
  }
}

function isAutomationQuotaStatus(value: unknown): value is AutomationQuotaStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Partial<AutomationQuotaStatus>;
  return (
    (candidate.state === "available"
      || candidate.state === "blocked"
      || candidate.state === "unknown"
      || candidate.state === "unavailable")
    && Number.isFinite(candidate.checkedAt)
    && (candidate.resetsAt === undefined || Number.isFinite(candidate.resetsAt))
    && (candidate.reason === undefined || candidate.reason === "api-key")
  );
}

function isAutomationHostPolicy(
  value: AutomationHostResponse["policy"] | undefined,
): value is NonNullable<AutomationHostResponse["policy"]> {
  return Boolean(
    value
    && (value.automationId === undefined || typeof value.automationId === "string")
    && typeof value.enabledByUser === "boolean"
    && typeof value.quotaAware === "boolean"
    && isAutomationIntervalMinutes(value.intervalMinutes)
    && isAutomationModel(value.model)
    && isAutomationReasoningEffort(value.reasoningEffort)
    && isSupportedModelEffort(value.model, value.reasoningEffort),
  );
}

function isAutomationIntervalMinutes(value: unknown): value is AutomationIntervalMinutes {
  return value === 5 || value === 10 || value === 15 || value === 30 || value === 60;
}

function intervalMinutesFromRrule(value: string): AutomationIntervalMinutes | null {
  const match = /^RRULE:FREQ=MINUTELY;INTERVAL=(5|10|15|30|60)$/.exec(value);
  return match ? Number(match[1]) as AutomationIntervalMinutes : null;
}

function workspaceName(path?: string): string | null {
  if (!path) return null;
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? path;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "加载议题时出现问题。";
}

function isAutomationHostItem(value: unknown): value is AutomationHostItem {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Partial<AutomationHostItem>;
  return (
    typeof item.id === "string"
    && (item.status === "ACTIVE" || item.status === "PAUSED")
    && isAutomationModel(item.model)
    && isAutomationReasoningEffort(item.reasoningEffort)
    && isSupportedModelEffort(item.model, item.reasoningEffort)
    && typeof item.rrule === "string"
    && intervalMinutesFromRrule(item.rrule) !== null
  );
}

function isLocalTaskboardOrigin(origin: string): boolean {
  try {
    const { protocol, hostname } = new URL(origin);
    return (protocol === "http:" || protocol === "https:")
      && (hostname === "127.0.0.1" || hostname === "localhost");
  } catch {
    return false;
  }
}

function normalizedWorkspacePath(value?: string | null): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  return trimmed.replace(/[\\/]+$/, "");
}

function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort(
    (left, right) => left.sortOrder - right.sortOrder || left.createdAt.localeCompare(right.createdAt),
  );
}

function taskToDraft(task: Task): TaskDraft {
  return {
    title: task.title,
    description: task.description,
    status: task.status,
    priority: task.priority,
    labels: task.labels,
    workflowId: task.workflowId,
    developmentContext: task.developmentContext,
    dueDate: task.dueDate,
    recurrence: task.recurrence,
  };
}

interface LocalRealtimeSyncProps {
  selectedProjectId: string;
  detailTaskId: string | null;
  refreshProjectList: () => Promise<void>;
  refreshTasks: (
    projectId: string,
    options?: { quiet?: boolean; signal?: AbortSignal },
  ) => Promise<void>;
  refreshWorkflowOptions: (projectId: string, signal?: AbortSignal) => Promise<void>;
  setConnection: Dispatch<SetStateAction<ConnectionState>>;
  setCommentsRevision: Dispatch<SetStateAction<number>>;
  setAttachmentsRevision: Dispatch<SetStateAction<number>>;
}

function LocalRealtimeSync({
  selectedProjectId,
  detailTaskId,
  refreshProjectList,
  refreshTasks,
  refreshWorkflowOptions,
  setConnection,
  setCommentsRevision,
  setAttachmentsRevision,
}: LocalRealtimeSyncProps) {
  useEffect(() => {
    const source = new EventSource("/api/events");
    let refreshTimer: number | undefined;
    let refreshProjectsPending = false;
    let refreshTasksPending = false;

    const scheduleRefresh = (options: { projects?: boolean; tasks?: boolean }) => {
      refreshProjectsPending ||= options.projects === true;
      refreshTasksPending ||= options.tasks === true;
      window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(() => {
        if (refreshProjectsPending) void refreshProjectList();
        if (refreshTasksPending && selectedProjectId) {
          void refreshTasks(selectedProjectId, { quiet: true });
        }
        refreshProjectsPending = false;
        refreshTasksPending = false;
      }, 120);
    };

    const handleEvent = (event: Event) => {
      const message = event as MessageEvent<string>;
      let payload: { projectId?: string; taskId?: string } = {};
      try {
        payload = JSON.parse(message.data) as { projectId?: string; taskId?: string };
      } catch {
        // A malformed event should not interrupt later updates.
      }
      const affectsSelectedProject = Boolean(selectedProjectId)
        && (!payload.projectId || payload.projectId === selectedProjectId);
      if (event.type === "project.created" || event.type === "project.updated") {
        scheduleRefresh({ projects: true });
        return;
      }
      if (event.type.startsWith("task.")) {
        scheduleRefresh({ projects: true, tasks: affectsSelectedProject });
        return;
      }
      if (!affectsSelectedProject) return;
      if (event.type === "workflow.updated") {
        if (selectedProjectId) void refreshWorkflowOptions(selectedProjectId);
        return;
      }
      if (event.type.startsWith("comment.")) {
        if (!detailTaskId || !payload.taskId || payload.taskId === detailTaskId) {
          setCommentsRevision((current) => current + 1);
        }
        scheduleRefresh({ tasks: true });
        return;
      }
      if (event.type.startsWith("attachment.")) {
        if (!detailTaskId || !payload.taskId || payload.taskId === detailTaskId) {
          setAttachmentsRevision((current) => current + 1);
          setCommentsRevision((current) => current + 1);
        }
      }
    };

    EVENT_NAMES.forEach((name) => source.addEventListener(name, handleEvent));
    source.onopen = () => {
      setConnection("live");
      scheduleRefresh({ projects: true, tasks: Boolean(selectedProjectId) });
      if (selectedProjectId) void refreshWorkflowOptions(selectedProjectId);
      if (detailTaskId) {
        setCommentsRevision((current) => current + 1);
        setAttachmentsRevision((current) => current + 1);
      }
    };
    source.onerror = () => setConnection("reconnecting");

    return () => {
      window.clearTimeout(refreshTimer);
      EVENT_NAMES.forEach((name) => source.removeEventListener(name, handleEvent));
      source.close();
    };
  }, [
    detailTaskId,
    refreshProjectList,
    refreshTasks,
    refreshWorkflowOptions,
    selectedProjectId,
    setAttachmentsRevision,
    setCommentsRevision,
    setConnection,
  ]);

  return null;
}

export function App() {
  const query = useMemo(() => new URLSearchParams(window.location.search), []);
  const embedded = query.get("host") === "codex";
  const undoShortcut = navigator.userAgent.includes("Macintosh") ? "⌘Z" : "Ctrl+Z";
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [hostContext, setHostContext] = useState<HostContext | null>(null);
  const [developmentScan, setDevelopmentScan] = useState<DevelopmentScan>({ workspacePath: null, contexts: [] });
  const [developmentScanLoading, setDevelopmentScanLoading] = useState(false);
  const [manageTaskboardSkillPath, setManageTaskboardSkillPath] = useState("");
  const [taskboardMetadata, setTaskboardMetadata] = useState<TaskboardMetadata | null>(null);
  const [localAiChatAvailable, setLocalAiChatAvailable] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [hasLoadedTasks, setHasLoadedTasks] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState(readTaskFilters);
  const [boardView, setBoardView] = useState<BoardView>("issues");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [detailTaskIdentifier, setDetailTaskIdentifier] = useState<string | null>(
    () => readIssueIdentifier(window.location.search),
  );
  const [workspacePane, setWorkspacePane] = useState<WorkspacePane>(
    () => readIssueIdentifier(window.location.search) ? "issue" : "board",
  );
  const [latestActivityTarget, setLatestActivityTarget] = useState<string | null>(null);
  const [projectNavigatorOpen, setProjectNavigatorOpen] = useState(true);
  const [commentsRevision, setCommentsRevision] = useState(0);
  const [attachmentsRevision, setAttachmentsRevision] = useState(0);
  const [workflowRevision, setWorkflowRevision] = useState(0);
  const [workflowOptions, setWorkflowOptions] = useState<WorkflowOption[]>(DEFAULT_WORKFLOW_OPTIONS);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [blockingRequest, setBlockingRequest] = useState<BlockingRequest | null>(null);
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);
  const [draggedTaskHeight, setDraggedTaskHeight] = useState(0);
  const [dropTarget, setDropTarget] = useState<TaskStatus | null>(null);
  const [movingTaskId, setMovingTaskId] = useState<string | null>(null);
  const [settlingTaskId, setSettlingTaskId] = useState<string | null>(null);
  const [openingProjectId, setOpeningProjectId] = useState<string | null>(null);
  const [openingThreadTaskId, setOpeningThreadTaskId] = useState<string | null>(null);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [favoriteProjectIds, setFavoriteProjectIds] = useState(readFavoriteProjectIds);
  const [deviceWorkspacePaths, setDeviceWorkspacePaths] = useState(readDeviceWorkspacePaths);
  const [projectAutomations, setProjectAutomations] = useState(readProjectAutomations);
  const [automationPending, setAutomationPending] = useState(false);
  const [automationError, setAutomationError] = useState<string | null>(null);
  const [announcement, setAnnouncementValue] = useState("");
  const [undoNotice, setUndoNotice] = useState<UndoNotice | null>(null);
  const tasksRequestRef = useRef(0);
  const tasksRef = useRef<Task[]>([]);
  const undoSequenceRef = useRef(0);
  const undoStackRef = useRef<UndoOperation[]>([]);
  const undoInFlightRef = useRef(false);
  const dragRegionRef = useRef<HTMLDivElement>(null);
  const selectedProjectIdRef = useRef(selectedProjectId);
  selectedProjectIdRef.current = selectedProjectId;

  const revisionPollingInterval = getRevisionPollingInterval(taskboardMetadata);
  const pendingAutomationRequestsRef = useRef(new Map<string, PendingAutomationRequest>());
  const automationRequestInFlightRef = useRef(false);
  const projectAutomationsRef = useRef(projectAutomations);
  const buildCheckInFlightRef = useRef(false);
  const lastBuildCheckAtRef = useRef(0);

  const setAnnouncement = useCallback((message: string) => {
    setUndoNotice(null);
    setAnnouncementValue(message);
  }, []);

  const rememberDeviceWorkspacePath = useCallback((projectId: string, workspacePath: string) => {
    const normalizedPath = workspacePath.trim();
    setDeviceWorkspacePaths((current) => {
      if (current[projectId] === normalizedPath || (!normalizedPath && !(projectId in current))) {
        return current;
      }
      const next = { ...current };
      if (normalizedPath) next[projectId] = normalizedPath;
      else delete next[projectId];
      window.localStorage.setItem(DEVICE_WORKSPACE_PATHS_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const identityResolver = useMemo(() => createProjectIdentityResolver({
    persistedProjects: projects,
    codexProjects: hostContext?.projects ?? [],
    workspacePaths: deviceWorkspacePaths,
    currentCodexProjectId: hostContext?.projectId ?? null,
    currentWorkspacePath: hostContext?.workspacePath ?? null,
  }), [
    deviceWorkspacePaths,
    hostContext?.projectId,
    hostContext?.projects,
    hostContext?.workspacePath,
    projects,
  ]);

  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? null;
  const currentUser = hostContext?.user ?? DEFAULT_USER_ACTOR;
  const selectedDeviceWorkspacePath = deviceWorkspacePaths[selectedProjectId];
  const selectedProjectAutomation = projectAutomations[selectedProjectId];
  const automationProjectContext = useMemo(() => {
    if (!embedded || window.parent === window) {
      return { unavailableReason: "仅可在 Codex App 中使用" };
    }
    if (!isLocalTaskboardOrigin(window.location.origin)) {
      return { unavailableReason: "仅本地任务面板可用" };
    }
    if (!selectedProject) return { unavailableReason: "请先选择项目" };

    const directCodexProject = hostContext?.projects?.some(
      (project) => project.id === selectedProject.id,
    );
    const workspacePath = deviceWorkspacePaths[selectedProject.id]
      ?? selectedProject.workspacePath
      ?? (
        directCodexProject && hostContext?.projectId === selectedProject.id
          ? hostContext.workspacePath
          : undefined
      );
    const normalizedSelectedWorkspace = normalizedWorkspacePath(workspacePath);
    const currentHostProjectMatchesWorkspace = Boolean(
      hostContext?.projectId
      && normalizedSelectedWorkspace
      && normalizedWorkspacePath(hostContext.workspacePath) === normalizedSelectedWorkspace,
    );
    const mappedCodexProject = hostContext?.projects?.find(
      (project) => normalizedWorkspacePath(deviceWorkspacePaths[project.id]) === normalizedSelectedWorkspace,
    );
    const codexProjectId = currentHostProjectMatchesWorkspace
      ? hostContext?.projectId
      : directCodexProject
        ? selectedProject.id
        : mappedCodexProject?.id;

    if (!workspacePath || !codexProjectId) {
      return { unavailableReason: "请先在 Codex 中添加并映射该项目目录" };
    }
    if (!manageTaskboardSkillPath) {
      return { unavailableReason: "任务面板还没有读取到 Skill 路径" };
    }
    return { workspacePath, codexProjectId, unavailableReason: null };
  }, [
    deviceWorkspacePaths,
    embedded,
    hostContext,
    manageTaskboardSkillPath,
    selectedProject,
  ]);
  const detailTask = detailTaskIdentifier
    ? tasks.find((task) => task.identifier === detailTaskIdentifier) ?? null
    : null;
  const detailTaskId = detailTask?.id ?? null;
  const persistedThreadIds = useMemo(
    () => new Set(tasks.flatMap((task) => task.threadId ? [task.threadId] : [])),
    [tasks],
  );
  const contextMenuTask = contextMenu
    ? tasks.find((task) => task.id === contextMenu.taskId) ?? null
    : null;
  const availableLabels = useMemo(
    () => [...new Set([
      ...DEFAULT_LABELS.map((label) => label.name),
      ...tasks.flatMap((task) => task.labels),
    ])],
    [tasks],
  );
  const projectChoices = useMemo<ProjectChoice[]>(() => {
    const persistedById = new Map(projects.map((project) => [project.id, project]));
    const liveConversationCountByProject = new Map<string, number>();
    for (const thread of hostContext?.runningThreads ?? []) {
      if (thread.linkedTaskId || persistedThreadIds.has(thread.threadId)) continue;
      const projectId = identityResolver.canonicalProjectId(thread.projectId) ?? thread.projectId;
      liveConversationCountByProject.set(
        projectId,
        (liveConversationCountByProject.get(projectId) ?? 0) + 1,
      );
    }
    const seen = new Set<string>();
    const choices: ProjectChoice[] = [];
    for (const project of hostContext?.projects ?? []) {
      if (!project.id || !project.name) continue;
      const projectId = identityResolver.canonicalProjectId(project.id) ?? project.id;
      if (seen.has(projectId)) continue;
      const persistedProject = persistedById.get(projectId);
      seen.add(projectId);
      choices.push({
        id: projectId,
        name: persistedProject?.name ?? project.name,
        workspacePath: identityResolver.workspacePathFor(projectId),
        issueCount: persistedProject?.issueCount ?? 0,
        inProgressCount: persistedProject?.inProgressCount ?? 0,
        runningConversationCount: liveConversationCountByProject.get(projectId) ?? 0,
        doneCount: persistedProject?.doneCount ?? 0,
        inCodex: true,
        persisted: Boolean(persistedProject),
      });
    }
    for (const project of projects) {
      if (!identityResolver.isCanonicalPersistedProject(project.id)) continue;
      if (seen.has(project.id)) continue;
      choices.push({
        id: project.id,
        name: project.name,
        workspacePath: identityResolver.workspacePathFor(project.id),
        issueCount: project.issueCount,
        inProgressCount: project.inProgressCount,
        runningConversationCount: liveConversationCountByProject.get(project.id) ?? 0,
        doneCount: project.doneCount,
        inCodex: identityResolver.hasCodexProject(project.id),
        persisted: true,
      });
    }
    return choices.sort((left, right) => (
      Number(favoriteProjectIds.has(right.id)) - Number(favoriteProjectIds.has(left.id))
    ));
  }, [
    favoriteProjectIds,
    hostContext?.projects,
    hostContext?.runningThreads,
    identityResolver,
    persistedThreadIds,
    projects,
  ]);
  const projectsWithIssues = useMemo(
    () => projectChoices.filter((project) => (
      project.issueCount > 0 || project.runningConversationCount > 0
    )),
    [projectChoices],
  );
  const projectsWithoutIssues = useMemo(
    () => projectChoices.filter((project) => (
      project.issueCount === 0 && project.runningConversationCount === 0
    )),
    [projectChoices],
  );
  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  const writeProjectAutomation = useCallback((
    projectId: string,
    record: ProjectAutomationRecord | null | undefined,
  ) => {
    setProjectAutomations((current) => {
      if (
        record
        && current[projectId]?.automationId === record.automationId
        && current[projectId]?.codexProjectId === record.codexProjectId
        && current[projectId]?.status === record.status
        && current[projectId]?.enabledByUser === record.enabledByUser
        && current[projectId]?.quotaAware === record.quotaAware
        && JSON.stringify(current[projectId]?.quota) === JSON.stringify(record.quota)
        && current[projectId]?.intervalMinutes === record.intervalMinutes
        && current[projectId]?.model === record.model
        && current[projectId]?.reasoningEffort === record.reasoningEffort
      ) {
        return current;
      }
      const next = { ...current };
      if (record) next[projectId] = record;
      else delete next[projectId];
      projectAutomationsRef.current = next;
      window.localStorage.setItem(PROJECT_AUTOMATIONS_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const sendAutomationRequest = useCallback((
    operation: "ensure-active" | "pause" | "list" | "apply-policy",
    options: Pick<
      ProjectAutomationRecord,
      "enabledByUser" | "quotaAware" | "intervalMinutes" | "model" | "reasoningEffort"
    >,
    automationId?: string,
  ) => {
    if (
      !selectedProject
      || !automationProjectContext.codexProjectId
      || !automationProjectContext.workspacePath
    ) {
      return Promise.reject(new Error(
        automationProjectContext.unavailableReason ?? "无法读取项目自动化信息",
      ));
    }
    const requestId = window.crypto.randomUUID();
    const response = new Promise<AutomationHostResponse>((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        pendingAutomationRequestsRef.current.delete(requestId);
        reject(new Error("Codex 自动化没有响应，请稍后重试"));
      }, 10_000);
      pendingAutomationRequestsRef.current.set(requestId, { resolve, reject, timeoutId });
    });
    window.parent.postMessage({
      type: "taskboard:automation-request",
      payload: {
        requestId,
        operation,
        taskboardProjectId: selectedProjectId,
        codexProjectId: automationProjectContext.codexProjectId,
        projectName: selectedProject.name,
        workspacePath: automationProjectContext.workspacePath,
        skillPath: manageTaskboardSkillPath,
        ...(automationId ? { automationId } : {}),
        enabledByUser: options.enabledByUser,
        quotaAware: options.quotaAware,
        intervalMinutes: options.intervalMinutes,
        model: options.model,
        reasoningEffort: options.reasoningEffort,
      },
    }, "*");
    return response;
  }, [
    automationProjectContext,
    manageTaskboardSkillPath,
    selectedProject,
    selectedProjectId,
  ]);

  const reconcileProjectAutomation = useCallback(async () => {
    if (automationProjectContext.unavailableReason) {
      setAutomationError(null);
      return;
    }
    if (!selectedProjectId || !automationProjectContext.codexProjectId || automationRequestInFlightRef.current) return;
    const stored = projectAutomationsRef.current[selectedProjectId];
    automationRequestInFlightRef.current = true;
    setAutomationPending(true);
    setAutomationError(null);
    try {
      const options = stored ?? {
        status: "PAUSED" as const,
        ...DEFAULT_AUTOMATION_OPTIONS,
      };
      const response = await sendAutomationRequest(
        stored ? "apply-policy" : "list",
        options,
        stored?.automationId,
      );
      const items = Array.isArray(response.items)
        ? response.items.filter(isAutomationHostItem)
        : [];
      if (!stored) {
        const policy = isAutomationHostPolicy(response.policy) ? response.policy : null;
        if (!policy) return;
        const item = items.find((candidate) => candidate.id === policy.automationId)
          ?? (items.length === 1 ? items[0] : undefined);
        writeProjectAutomation(selectedProjectId, {
          automationId: item?.id ?? policy.automationId,
          codexProjectId: automationProjectContext.codexProjectId,
          status: item?.status ?? "PAUSED",
          enabledByUser: policy.enabledByUser,
          quotaAware: policy.quotaAware,
          intervalMinutes: policy.intervalMinutes,
          model: policy.model,
          reasoningEffort: policy.reasoningEffort,
        });
        return;
      }
      const item = (isAutomationHostItem(response.item) ? response.item : undefined)
        ?? items.find((item) => item.id === stored?.automationId)
        ?? (items.length === 1 ? items[0] : undefined);
      if (!item) {
        if (stored) {
          writeProjectAutomation(selectedProjectId, {
            ...stored,
            automationId: undefined,
            status: "PAUSED",
            ...(response.quota ? { quota: response.quota } : {}),
          });
        }
        return;
      }
      const intervalMinutes = intervalMinutesFromRrule(item.rrule);
      if (!intervalMinutes) return;
      writeProjectAutomation(selectedProjectId, {
        automationId: item.id,
        codexProjectId: automationProjectContext.codexProjectId,
        status: item.status,
        enabledByUser: stored.enabledByUser,
        quotaAware: stored.quotaAware,
        ...(response.quota ? { quota: response.quota } : {}),
        intervalMinutes,
        model: item.model,
        reasoningEffort: item.reasoningEffort,
      });
    } catch (error) {
      setAutomationError(error instanceof Error ? error.message : "无法读取自动化状态");
    } finally {
      automationRequestInFlightRef.current = false;
      setAutomationPending(false);
    }
  }, [
    automationProjectContext,
    selectedProjectId,
    sendAutomationRequest,
    writeProjectAutomation,
  ]);

  const saveProjectAutomation = useCallback(async (options: {
    enabledByUser: boolean;
    quotaAware: boolean;
    intervalMinutes: AutomationIntervalMinutes;
    model: AutomationModel;
    reasoningEffort: AutomationReasoningEffort;
  }) => {
    const stored = projectAutomations[selectedProjectId];
    if (
      !selectedProjectId
      || automationProjectContext.unavailableReason
      || !automationProjectContext.codexProjectId
      || automationRequestInFlightRef.current
    ) return;
    const previousRecord = stored;
    automationRequestInFlightRef.current = true;
    setAutomationPending(true);
    setAutomationError(null);
    try {
      const response = await sendAutomationRequest("apply-policy", options, stored?.automationId);
      const item = isAutomationHostItem(response.item) ? response.item : undefined;
      writeProjectAutomation(selectedProjectId, {
        automationId: item?.id,
        codexProjectId: automationProjectContext.codexProjectId,
        status: item?.status ?? "PAUSED",
        enabledByUser: options.enabledByUser,
        quotaAware: options.quotaAware,
        ...(response.quota ? { quota: response.quota } : {}),
        intervalMinutes: options.intervalMinutes,
        model: options.model,
        reasoningEffort: options.reasoningEffort,
      });
    } catch (error) {
      writeProjectAutomation(selectedProjectId, previousRecord);
      setAutomationError(error instanceof Error ? error.message : "无法更新自动化");
    } finally {
      automationRequestInFlightRef.current = false;
      setAutomationPending(false);
    }
  }, [
    automationProjectContext,
    projectAutomations,
    selectedProjectId,
    sendAutomationRequest,
    writeProjectAutomation,
  ]);

  function openTaskDetail(task: Pick<Task, "identifier" | "projectId">) {
    closeContextMenu();
    setProjectMenuOpen(false);
    setLatestActivityTarget(
      workspacePane === "board" && boardView === "issues" ? task.identifier : null,
    );
    setDetailTaskIdentifier(task.identifier);
    setWorkspacePane("issue");
    const currentIssue = readIssueIdentifier(window.location.search);
    const boardUrl = buildIssueUrl(window.location.href, task.projectId, null);
    if (!currentIssue) {
      window.history.replaceState(window.history.state, "", boardUrl);
    }
    const detailUrl = buildIssueUrl(
      currentIssue ? window.location.href : boardUrl.href,
      task.projectId,
      task.identifier,
    );
    window.history.pushState(window.history.state, "", detailUrl);
  }

  function closeTaskDetail() {
    setLatestActivityTarget(null);
    setWorkspacePane("board");
    const url = buildIssueUrl(window.location.href, selectedProjectId || null, null);
    window.history.replaceState(window.history.state, "", url);
  }

  function selectWorkspacePane(pane: WorkspacePane) {
    if (pane === "issue" && !detailTaskIdentifier) return;
    setWorkspacePane(pane);
    const issueIdentifier = pane === "issue" ? detailTaskIdentifier : null;
    const url = buildIssueUrl(window.location.href, selectedProjectId || null, issueIdentifier);
    window.history.replaceState(window.history.state, "", url);
  }

  function handleBoardTabClick() {
    const isCurrentBoard = workspacePane === "board" && boardView === "issues";
    if (isCurrentBoard) {
      setProjectNavigatorOpen((current) => !current);
      return;
    }
    selectBoardView("issues");
    selectWorkspacePane("board");
  }

  useEffect(() => {
    function syncRouteFromLocation() {
      const url = new URL(window.location.href);
      const routeProjectId = url.searchParams.get("project") ?? "";
      const routeIssueIdentifier = readIssueIdentifier(url.search);
      setDetailTaskIdentifier(routeIssueIdentifier);
      setWorkspacePane(routeIssueIdentifier ? "issue" : "board");
      if (routeProjectId === selectedProjectId) return;
      setBoardView("issues");
      setSelectedProjectId(routeProjectId);
      if (routeProjectId) window.localStorage.setItem(LAST_PROJECT_KEY, routeProjectId);
      else window.localStorage.removeItem(LAST_PROJECT_KEY);
    }

    window.addEventListener("popstate", syncRouteFromLocation);
    return () => window.removeEventListener("popstate", syncRouteFromLocation);
  }, [selectedProjectId]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.embedded = String(embedded);
    document.documentElement.style.colorScheme = theme;
    if (!embedded) window.localStorage.setItem("taskboard.theme", theme);
  }, [embedded, theme]);

  useEffect(() => {
    writeTaskFilters(filters);
  }, [filters]);

  useEffect(() => {
    tasksRef.current = tasks;
  }, [tasks]);

  useEffect(() => {
    if (!projectMenuOpen) return;
    function closeProjectMenu(event: PointerEvent) {
      const target = event.target as HTMLElement;
      if (!target.closest("[data-project-switcher]")) setProjectMenuOpen(false);
    }
    function closeProjectMenuWithEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setProjectMenuOpen(false);
    }
    document.addEventListener("pointerdown", closeProjectMenu);
    window.addEventListener("keydown", closeProjectMenuWithEscape);
    return () => {
      document.removeEventListener("pointerdown", closeProjectMenu);
      window.removeEventListener("keydown", closeProjectMenuWithEscape);
    };
  }, [projectMenuOpen]);

  useEffect(() => {
    setAutomationError(null);
    void reconcileProjectAutomation();
  }, [selectedProjectId, reconcileProjectAutomation]);

  useEffect(() => {
    if (!embedded || window.parent === window) return;

    function receiveHostMessage(event: MessageEvent) {
      if (event.source !== window.parent || !event.data || typeof event.data !== "object") return;
      const message = event.data as { type?: string; payload?: unknown; theme?: unknown };

      if (message.type === "taskboard:automation-response" && message.payload) {
        const payload = message.payload as Partial<AutomationHostResponse>;
        if (typeof payload.requestId !== "string") return;
        const pending = pendingAutomationRequestsRef.current.get(payload.requestId);
        if (!pending) return;
        window.clearTimeout(pending.timeoutId);
        pendingAutomationRequestsRef.current.delete(payload.requestId);
        if (payload.ok) pending.resolve(payload as AutomationHostResponse);
        else pending.reject(new Error(
          typeof payload.error === "string" ? payload.error : "Codex 无法更新自动化",
        ));
        return;
      }

      if (message.type === "taskboard:theme" && isTheme(message.theme)) {
        setTheme(message.theme);
        return;
      }

      if (message.type === "taskboard:thread-prepared") {
        setOpeningThreadTaskId(null);
        return;
      }

      if (message.type === "taskboard:thread-create-error" && message.payload) {
        const payload = message.payload as { taskId?: unknown; error?: unknown };
        setOpeningThreadTaskId(null);
        setActionError(typeof payload.error === "string" ? payload.error : "无法在 Codex 中创建对话。");
        return;
      }

      if (message.type !== "taskboard:host-context" || !message.payload) return;
      const now = Date.now();
      if (!buildCheckInFlightRef.current && now - lastBuildCheckAtRef.current >= 5_000) {
        buildCheckInFlightRef.current = true;
        lastBuildCheckAtRef.current = now;
        void reloadIfTaskboardBuildStale()
          .catch(() => false)
          .finally(() => { buildCheckInFlightRef.current = false; });
      }
      const payload = message.payload as HostContext;
      setHostContext(payload);
      setCurrentUserActor(payload.user);
      if (isTheme(payload.theme)) setTheme(payload.theme);
    }

    window.addEventListener("message", receiveHostMessage);
    window.parent.postMessage({ type: "taskboard:ready" }, "*");
    return () => {
      window.removeEventListener("message", receiveHostMessage);
      for (const pending of pendingAutomationRequestsRef.current.values()) {
        window.clearTimeout(pending.timeoutId);
      }
      pendingAutomationRequestsRef.current.clear();
    };
  }, [embedded]);

  useEffect(() => {
    if (!embedded || window.parent === window || !hostContext?.threadId) return;
    const linkedTask = tasks.find((task) => task.threadId === hostContext.threadId);
    if (!linkedTask) return;
    window.parent.postMessage({
      type: "taskboard:linked-task",
      payload: {
        threadId: hostContext.threadId,
        taskId: linkedTask.id,
        projectId: linkedTask.projectId,
        identifier: linkedTask.identifier,
        title: linkedTask.title,
      },
    }, "*");
  }, [embedded, hostContext?.threadId, tasks]);

  useLayoutEffect(() => {
    if (!embedded || window.parent === window || !dragRegionRef.current) return;
    const region = dragRegionRef.current;
    const publish = () => {
      const rect = region.getBoundingClientRect();
      window.parent.postMessage({
        type: "taskboard:drag-region",
        payload: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      }, "*");
    };
    const observer = new ResizeObserver(publish);
    observer.observe(region);
    window.addEventListener("resize", publish);
    publish();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", publish);
      window.parent.postMessage({ type: "taskboard:drag-region", payload: null }, "*");
    };
  }, [detailTaskId, embedded, selectedProjectId]);

  const loadProjectList = useCallback(async (signal?: AbortSignal) => {
    setProjectsLoading(true);
    setLoadError(null);
    try {
      const [nextProjects, metadata, workspaces] = await Promise.all([
        listProjects(signal),
        getTaskboardMetadata(signal),
        listDeviceWorkspaces(signal),
      ]);
      const mergedWorkspacePaths = { ...readDeviceWorkspacePaths(), ...workspaces };
      const identityResolver = createProjectIdentityResolver({
        persistedProjects: nextProjects,
        workspacePaths: mergedWorkspacePaths,
      });
      setTaskboardMetadata((current) => (
        current
        && current.mode === metadata.mode
        && current.realtime?.transport === metadata.realtime?.transport
        && current.realtime?.intervalMs === metadata.realtime?.intervalMs
        && current.manageTaskboardSkillPath === metadata.manageTaskboardSkillPath
        && current.localCapabilities?.available === metadata.localCapabilities?.available
          ? current
          : metadata
      ));
      setManageTaskboardSkillPath(metadata.manageTaskboardSkillPath ?? "");
      setLocalAiChatAvailable(metadata.capabilities?.localAiChat === true);
      setDeviceWorkspacePaths((current) => {
        const next = { ...current, ...workspaces };
        if (JSON.stringify(next) === JSON.stringify(current)) return current;
        window.localStorage.setItem(DEVICE_WORKSPACE_PATHS_KEY, JSON.stringify(next));
        return next;
      });
      setProjects(nextProjects);
      setSelectedProjectId((current) => {
        const fromQuery = new URLSearchParams(window.location.search).get("project");
        const remembered = window.localStorage.getItem(LAST_PROJECT_KEY);
        const canonicalPersistedId = (candidateId: string | null) => {
          if (!candidateId) return null;
          const canonicalId = identityResolver.canonicalProjectId(candidateId);
          return canonicalId && nextProjects.some((project) => project.id === canonicalId)
            ? canonicalId
            : null;
        };
        const selectedId = canonicalPersistedId(fromQuery)
          ?? canonicalPersistedId(current)
          ?? canonicalPersistedId(remembered);
        if (selectedId) {
          window.localStorage.setItem(LAST_PROJECT_KEY, selectedId);
          const url = buildIssueUrl(window.location.href, selectedId, readIssueIdentifier(window.location.search));
          window.history.replaceState(null, "", url);
          return selectedId;
        }
        return "";
      });
    } catch (error) {
      if ((error as Error).name !== "AbortError") setLoadError(errorMessage(error));
    } finally {
      setProjectsLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadProjectList(controller.signal);
    return () => controller.abort();
  }, [loadProjectList]);

  const refreshProjectList = useCallback(async () => {
    try {
      setProjects(await listProjects());
    } catch (error) {
      setLoadError(errorMessage(error));
    }
  }, []);

  const refreshTasks = useCallback(async (
    projectId: string,
    options: { quiet?: boolean; signal?: AbortSignal } = {},
  ) => {
    const requestId = ++tasksRequestRef.current;
    if (!options.quiet) setTasksLoading(true);
    setLoadError(null);
    try {
      const nextTasks = await listTasks(projectId, options.signal);
      if (requestId !== tasksRequestRef.current) return;
      setTasks(sortTasks(nextTasks));
      setHasLoadedTasks(true);
    } catch (error) {
      if ((error as Error).name !== "AbortError" && requestId === tasksRequestRef.current) {
        setLoadError(errorMessage(error));
      }
    } finally {
      if (!options.quiet && requestId === tasksRequestRef.current) setTasksLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setTasks([]);
      setHasLoadedTasks(false);
      return;
    }
    setHasLoadedTasks(false);
    const controller = new AbortController();
    void refreshTasks(selectedProjectId, { signal: controller.signal });
    return () => controller.abort();
  }, [refreshTasks, selectedProjectId]);

  const refreshWorkflowOptions = useCallback(async (projectId: string, signal?: AbortSignal) => {
    const record = await getWorkflowWorkspace<unknown>(projectId, signal);
    if (!signal?.aborted) setWorkflowOptions(workflowOptionsFromWorkspace(record.workspace));
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setWorkflowOptions(DEFAULT_WORKFLOW_OPTIONS);
      return;
    }
    setWorkflowOptions(workflowOptionsFromWorkspace(readLegacyWorkflowWorkspace(selectedProjectId)));
    const controller = new AbortController();
    void refreshWorkflowOptions(selectedProjectId, controller.signal).catch((error) => {
      if ((error as Error).name !== "AbortError") {
        setWorkflowOptions(workflowOptionsFromWorkspace(readLegacyWorkflowWorkspace(selectedProjectId)));
      }
    });
    return () => controller.abort();
  }, [refreshWorkflowOptions, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      setDevelopmentScan({ workspacePath: null, contexts: [] });
      return;
    }
    const controller = new AbortController();
    const codexProjectId = selectedProjectId === "local" ? hostContext?.projectId : selectedProjectId;
    const codexThreadId = hostContext?.threadId ?? detailTask?.threadId ?? undefined;
    setDevelopmentScan({ workspacePath: selectedDeviceWorkspacePath ?? null, contexts: [] });
    setDevelopmentScanLoading(true);
    void listDevelopmentContexts(
      selectedProjectId,
      codexProjectId,
      codexThreadId,
      controller.signal,
      selectedDeviceWorkspacePath,
    )
      .then((scan) => {
        setDevelopmentScan(scan);
        if (scan.workspacePath) rememberDeviceWorkspacePath(selectedProjectId, scan.workspacePath);
      })
      .catch((error) => {
        if ((error as Error).name !== "AbortError") {
          setDevelopmentScan({ workspacePath: selectedDeviceWorkspacePath ?? null, contexts: [] });
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDevelopmentScanLoading(false);
      });
    return () => controller.abort();
  }, [
    detailTask?.threadId,
    hostContext?.projectId,
    hostContext?.threadId,
    rememberDeviceWorkspacePath,
    selectedProjectId,
    selectedDeviceWorkspacePath,
  ]);

  useEffect(() => {
    if (revisionPollingInterval === null) return;
    const controller = new AbortController();
    setConnection("connecting");
    const poller = createRevisionPoller({
      intervalMs: revisionPollingInterval,
      fetchRevision: async (since: number) => {
        try {
          const result = await getTaskboardRevision(since, controller.signal);
          setConnection("live");
          return result;
        } catch (error) {
          if (!controller.signal.aborted) setConnection("reconnecting");
          throw error;
        }
      },
      onInvalidate: () => {
        void refreshProjectList();
        const projectId = selectedProjectIdRef.current;
        if (projectId) {
          void refreshTasks(projectId, { quiet: true });
          void refreshWorkflowOptions(projectId).catch(() => {});
        }
        setWorkflowRevision((current) => current + 1);
        setCommentsRevision((current) => current + 1);
        setAttachmentsRevision((current) => current + 1);
      },
    });
    poller.start();
    return () => {
      controller.abort();
      poller.stop();
    };
  }, [
    revisionPollingInterval,
    refreshProjectList,
    refreshTasks,
    refreshWorkflowOptions,
  ]);

  function pushUndo(message: string, undo: () => Promise<void>, showNotice = true) {
    const operation = { id: ++undoSequenceRef.current, message, undo };
    undoStackRef.current = [...undoStackRef.current.slice(-19), operation];
    setAnnouncementValue("");
    setUndoNotice(showNotice ? { id: operation.id, message } : null);
  }

  async function performUndo() {
    if (undoInFlightRef.current) return;
    const operation = undoStackRef.current.at(-1);
    if (!operation) return;
    undoStackRef.current = undoStackRef.current.slice(0, -1);
    undoInFlightRef.current = true;
    setUndoNotice(null);
    setProjectMenuOpen(false);
    closeContextMenu();
    setActionError(null);
    try {
      await operation.undo();
    } catch (error) {
      setActionError(`无法撤回这次操作：${errorMessage(error)}`);
      if (selectedProjectId) void refreshTasks(selectedProjectId, { quiet: true });
    } finally {
      undoInFlightRef.current = false;
    }
  }

  async function restoreTaskDetails(
    snapshot: Task,
    changed: Task,
    assigneeTarget = assigneeTargetForActor(snapshot.assignee, currentUser),
  ) {
    const candidate = tasksRef.current.find((task) => task.id === changed.id);
    const current = candidate && candidate.version >= changed.version ? candidate : changed;
    const blocking = snapshot.status === "blocked" && snapshot.blocking
      ? {
          reason: snapshot.blocking.reason,
          unblockAction: snapshot.blocking.unblockAction,
        }
      : undefined;
    const restored = await updateTaskRequest(current, {
      ...taskToDraft(snapshot),
      ...(assigneeTarget ? { assigneeTarget } : {}),
      ...(blocking ? { blocking } : {}),
    });
    setTasks((tasks) => sortTasks(tasks.map((task) => task.id === restored.id ? restored : task)));
  }

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTyping = target?.matches("input, textarea, select, [contenteditable='true']");
      if (
        event.key.toLowerCase() === "z"
        && (event.metaKey || event.ctrlKey)
        && !event.shiftKey
        && !isTyping
        && !editor
      ) {
        event.preventDefault();
        void performUndo();
        return;
      }
      if (isTyping || contextMenu || projectMenuOpen) return;
      if (
        event.key.toLowerCase() === "c"
        && !event.metaKey
        && !event.ctrlKey
        && selectedProjectId
        && workspacePane === "board"
        && boardView === "issues"
      ) {
        event.preventDefault();
        setEditor({ task: null, status: "backlog" });
      }
      if (event.key === "/" && workspacePane === "board" && selectedProjectId && boardView === "issues") {
        event.preventDefault();
        document.getElementById("task-search")?.focus();
      }
      if (event.key === "Escape" && workspacePane !== "board") {
        closeTaskDetail();
      }
    }

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [boardView, contextMenu, editor, projectMenuOpen, selectedProjectId, workspacePane]);

  const filteredTasks = useMemo(() => {
    return tasks.filter(
      (task) => matchesTaskSearch(task, search) && matchesTaskFilters(task, filters),
    );
  }, [filters, search, tasks]);

  const activeFilterCount = taskFilterCount(filters);

  const tasksByStatus = useMemo(() => {
    return Object.fromEntries(
      TASK_STATUSES.map((status) => [status, filteredTasks.filter((task) => task.status === status)]),
    ) as Record<TaskStatus, Task[]>;
  }, [filteredTasks]);

  const liveRunningThreads = useMemo<RunningCodexThread[]>(() => {
    return (hostContext?.runningThreads ?? []).filter((thread) => (
      identityResolver.canonicalProjectId(thread.projectId) === selectedProjectId
      && !thread.linkedTaskId
      && !persistedThreadIds.has(thread.threadId)
    ));
  }, [hostContext?.runningThreads, identityResolver, persistedThreadIds, selectedProjectId]);

  const conversationTaskCount = useMemo(
    () => tasks.filter((task) => task.threadId).length + liveRunningThreads.length,
    [liveRunningThreads.length, tasks],
  );

  const orderedStatuses = useMemo(() => {
    const hasVisibleTask = (status: TaskStatus) => (
      tasksByStatus[status].length > 0
      || (status === "in_progress" && liveRunningThreads.length > 0)
    );
    return [
      ...TASK_STATUSES.filter(hasVisibleTask),
      ...TASK_STATUSES.filter((status) => !hasVisibleTask(status)),
    ];
  }, [liveRunningThreads.length, tasksByStatus]);

  function selectBoardView(view: BoardView) {
    closeContextMenu();
    setBoardView(view);
  }

  async function saveEditor(
    draft: TaskDraft,
    attachments: File[],
    inlineImages: PendingInlineImage[],
    intent: "save" | "execute",
  ) {
    if (!selectedProjectId || !editor) return;
    setActionError(null);
    try {
      const creating = editor.task === null;
      const preparedDraft = creating && intent === "execute"
        ? prepareCodexExecutionDraft(draft)
        : draft;
      const effectiveDraft: TaskDraft = preparedDraft.status === "blocked"
        ? preparedDraft
        : { ...preparedDraft, blocking: undefined };
      let saved = editor.task
        ? await updateTaskRequest(editor.task, effectiveDraft)
        : await createTaskRequest(selectedProjectId, effectiveDraft);
      if (creating) {
        setProjects((current) => current.map((project) => (
          project.id === selectedProjectId
            ? { ...project, issueCount: project.issueCount + 1 }
            : project
        )));
      }
      let uploadedAttachments = 0;
      let failedAttachments = 0;
      if (creating && (attachments.length > 0 || inlineImages.length > 0)) {
        const [results, inlineAttachments] = await Promise.all([
          Promise.allSettled(
            attachments.map((file) => uploadAttachment(saved.id, file)),
          ),
          Promise.all(
            inlineImages.map((image) => uploadAttachment(saved.id, image.file)),
          ),
        ]);
        uploadedAttachments = results.filter((result) => result.status === "fulfilled").length;
        failedAttachments = results.length - uploadedAttachments;
        if (inlineImages.length > 0) {
          const description = resolveInlineMediaMarkdown(
            effectiveDraft.description,
            inlineImages,
            inlineAttachments,
          );
          saved = await updateTaskRequest(saved, { ...effectiveDraft, description });
        }
      }
      setTasks((current) => sortTasks([
        ...current.filter((task) => task.id !== saved.id),
        saved,
      ]));
      setEditor(null);
      if (failedAttachments > 0) {
        setActionError(`${saved.identifier} 已创建，但有 ${failedAttachments} 个附件上传失败，可在详情页重试。`);
      }
      if (creating) {
        const totalUploaded = uploadedAttachments + inlineImages.length;
        const message = `${saved.identifier} 已创建${totalUploaded > 0 ? `，已上传 ${totalUploaded} 个附件` : ""}。`;
        if (intent === "execute") {
          setAnnouncement(`${saved.identifier} 已创建，正在交给 Codex。`);
          openTaskInThread(saved, { autoSubmit: true });
        } else {
          pushUndo(message, async () => {
            const candidate = tasksRef.current.find((task) => task.id === saved.id);
            const current = candidate && candidate.version >= saved.version ? candidate : saved;
            await archiveTaskRequest(current);
            setTasks((tasks) => tasks.filter((task) => task.id !== saved.id));
          });
        }
      } else if (editor.task) {
        const previous = editor.task;
        const previousAssigneeTarget = assigneeTargetForActor(previous.assignee, currentUser);
        if ((!draft.assigneeTarget || previousAssigneeTarget) && (
          previous.status !== "blocked" || previous.blocking !== null
        )) {
          pushUndo(
            `${saved.identifier} 已更新。`,
            () => restoreTaskDetails(previous, saved, previousAssigneeTarget),
          );
        }
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
        void refreshTasks(selectedProjectId, { quiet: true });
      }
      throw error;
    }
  }

  async function moveTask(
    task: Task,
    status: TaskStatus,
    beforeTaskId: string | null = null,
    silent = false,
  ) {
    if (movingTaskId) {
      setDropTarget(null);
      setDraggedTaskId(null);
      setDraggedTaskHeight(0);
      return;
    }

    const destination = tasks.filter((candidate) => candidate.status === status && candidate.id !== task.id);
    const insertionIndex = beforeTaskId
      ? destination.findIndex((candidate) => candidate.id === beforeTaskId)
      : destination.length;
    const targetIndex = insertionIndex < 0 ? destination.length : insertionIndex;
    const desiredOrder = [...destination];
    desiredOrder.splice(targetIndex, 0, task);
    const currentOrder = tasks.filter((candidate) => candidate.status === status);
    if (
      task.status === status
      && currentOrder.length === desiredOrder.length
      && currentOrder.every((candidate, index) => candidate.id === desiredOrder[index].id)
    ) {
      setDropTarget(null);
      setDraggedTaskId(null);
      setDraggedTaskHeight(0);
      return;
    }
    const blocking = task.status !== "blocked" && status === "blocked"
      ? await requestBlockingInfo(task)
      : undefined;
    if (blocking === null) {
      setDropTarget(null);
      setDraggedTaskId(null);
      setDraggedTaskHeight(0);
      return;
    }
    const previousTask = destination[targetIndex - 1] ?? null;
    const nextTask = destination[targetIndex] ?? null;
    const sortOrder = previousTask && nextTask
      ? (previousTask.sortOrder + nextTask.sortOrder) / 2
      : previousTask
        ? previousTask.sortOrder + 1024
        : nextTask
          ? nextTask.sortOrder - 1024
          : 1024;
    const previous = task;
    setActionError(null);
    setMovingTaskId(task.id);
    setTasks((current) => sortTasks(current.map((candidate) =>
      candidate.id === task.id ? { ...candidate, status, sortOrder } : candidate,
    )));

    try {
      const moved = await moveTaskRequest(task, status, sortOrder, undefined, blocking);
      setTasks((current) => sortTasks(current.map((candidate) =>
        candidate.id === moved.id ? moved : candidate,
      )));
      const message = task.status === status
        ? `${task.identifier} 排序已调整。`
        : `${task.identifier} 已移至${STATUS_DETAILS[status].label}。`;
      pushUndo(message, async () => {
        const candidate = tasksRef.current.find((current) => current.id === moved.id);
        const current = candidate && candidate.version >= moved.version ? candidate : moved;
        const previousBlocking = previous.status === "blocked" && previous.blocking
          ? {
              reason: previous.blocking.reason,
              unblockAction: previous.blocking.unblockAction,
            }
          : undefined;
        const restored = await moveTaskRequest(
          current,
          previous.status,
          previous.sortOrder,
          undefined,
          previousBlocking,
        );
        setTasks((tasks) => sortTasks(tasks.map((item) => item.id === restored.id ? restored : item)));
      }, !silent && (previous.status !== "blocked" || previous.blocking !== null));
    } catch (error) {
      setTasks((current) => sortTasks(current.map((candidate) =>
        candidate.id === previous.id ? previous : candidate,
      )));
      setActionError(error instanceof ApiError && error.code === "VERSION_CONFLICT"
        ? "此议题已在其他位置更新，任务面板已刷新。"
        : errorMessage(error));
      if (selectedProjectId) void refreshTasks(selectedProjectId, { quiet: true });
    } finally {
      setMovingTaskId(null);
      setDropTarget(null);
      setDraggedTaskId(null);
      setDraggedTaskHeight(0);
    }
  }

  function finishTaskDrop(destination: TaskStatus, taskId: string, beforeTaskId: string | null = null) {
    const task = tasks.find((candidate) => candidate.id === taskId);
    setDraggedTaskId(null);
    setDraggedTaskHeight(0);
    setDropTarget(null);
    if (!task) return;
    setSettlingTaskId(task.id);
    window.setTimeout(() => {
      setSettlingTaskId((current) => current === task.id ? null : current);
    }, 220);
    void moveTask(task, destination, beforeTaskId, true);
  }

  async function updateTaskProperties(task: Task, changes: Partial<TaskDraft>, message?: string): Promise<Task> {
    const previous = task;
    const { assigneeTarget, blocking, ...taskChanges } = changes;
    const optimisticAssignee = assigneeTarget
      ? actorForAssigneeTarget(assigneeTarget, currentUser)
      : task.assignee;
    setActionError(null);
    setTasks((current) => current.map((candidate) =>
      candidate.id === task.id
        ? {
            ...candidate,
            ...taskChanges,
            assignee: optimisticAssignee,
            ...(blocking ? {
              blocking: {
                ...blocking,
                recordedBy: currentUser,
                recordedAt: new Date().toISOString(),
              },
            } : {}),
          }
        : candidate,
    ));

    try {
      const updated = await updateTaskRequest(task, { ...taskToDraft(task), ...changes });
      setTasks((current) => sortTasks(current.map((candidate) =>
        candidate.id === updated.id ? updated : candidate,
      )));
      const previousAssigneeTarget = assigneeTargetForActor(previous.assignee, currentUser);
      if ((!assigneeTarget || previousAssigneeTarget) && (
        previous.status !== "blocked" || previous.blocking !== null
      )) {
        pushUndo(
          message ?? `${task.identifier} 已更新。`,
          () => restoreTaskDetails(previous, updated, previousAssigneeTarget),
        );
      }
      return updated;
    } catch (error) {
      setTasks((current) => sortTasks(current.map((candidate) =>
        candidate.id === previous.id ? previous : candidate,
      )));
      setActionError(error instanceof ApiError && error.code === "VERSION_CONFLICT"
        ? "该议题已在其他位置更新，看板已重新同步。"
        : errorMessage(error));
      if (selectedProjectId) void refreshTasks(selectedProjectId, { quiet: true });
      throw error;
    }
  }

  function requestBlockingInfo(task: Task): Promise<BlockingDraft | null> {
    return new Promise((resolve) => setBlockingRequest({ task, resolve }));
  }

  function settleBlockingRequest(blocking: BlockingDraft | null) {
    const pending = blockingRequest;
    setBlockingRequest(null);
    pending?.resolve(blocking);
  }

  async function changeTaskStatus(task: Task, status: TaskStatus): Promise<Task | null> {
    if (status === task.status) return task;
    const blocking = task.status !== "blocked" && status === "blocked"
      ? await requestBlockingInfo(task)
      : undefined;
    if (blocking === null) return null;
    return updateTaskProperties(task, {
      status,
      ...(blocking ? { blocking } : {}),
    }, `${task.identifier} 已移至${STATUS_DETAILS[status].label}。`);
  }

  async function mutateTaskRelation(
    action: "add" | "remove",
    task: Task,
    type: IssueRelationType,
    relatedTaskId: string,
  ) {
    setActionError(null);
    try {
      const result = action === "add"
        ? await addTaskRelation(task, type, relatedTaskId)
        : await removeTaskRelation(task, type, relatedTaskId);
      setTasks((current) => sortTasks(current.map((candidate) => {
        if (candidate.id === result.task.id) return result.task;
        if (candidate.id === result.relatedTask.id) return result.relatedTask;
        return candidate;
      })));
      if (selectedProjectId) void refreshTasks(selectedProjectId, { quiet: true });
      return result;
    } catch (error) {
      setActionError(error instanceof ApiError && error.code === "VERSION_CONFLICT"
        ? "该议题已在其他位置更新，看板已重新同步。"
        : errorMessage(error));
      if (selectedProjectId) void refreshTasks(selectedProjectId, { quiet: true });
      throw error;
    }
  }

  async function duplicateTask(task: Task) {
    setActionError(null);
    try {
      const duplicated = await createTaskRequest(task.projectId, {
        ...taskToDraft(task),
        assigneeTarget: assigneeTargetForActor(task.assignee, currentUser),
        developmentContext: null,
      });
      setTasks((current) => sortTasks([...current, duplicated]));
      pushUndo(`${duplicated.identifier} 副本已创建。`, async () => {
        const candidate = tasksRef.current.find((current) => current.id === duplicated.id);
        const current = candidate && candidate.version >= duplicated.version ? candidate : duplicated;
        await archiveTaskRequest(current);
        setTasks((tasks) => tasks.filter((item) => item.id !== duplicated.id));
      });
    } catch (error) {
      setActionError(errorMessage(error));
    }
  }

  async function archiveTask(task: Task) {
    setActionError(null);
    try {
      const archived = await archiveTaskRequest(task);
      setTasks((current) => current.filter((candidate) => candidate.id !== task.id));
      pushUndo(`${task.identifier} 已归档。`, async () => {
        const restored = await restoreTaskRequest(archived);
        setTasks((current) => sortTasks([
          ...current.filter((candidate) => candidate.id !== restored.id),
          restored,
        ]));
      });
    } catch (error) {
      setActionError(error instanceof ApiError && error.code === "VERSION_CONFLICT"
        ? "该议题已在其他位置更新，看板已重新同步。"
        : errorMessage(error));
      if (selectedProjectId) void refreshTasks(selectedProjectId, { quiet: true });
    }
  }

  async function copyText(text: string, message: string) {
    try {
      await navigator.clipboard.writeText(text);
      setAnnouncement(message);
    } catch {
      setActionError("无法写入剪贴板。");
    }
  }

  function openThread(threadId: string) {
    if (embedded && window.parent !== window) {
      const sourceTask = tasks.find((task) => task.threadId === threadId) ?? null;
      const runningThread = hostContext?.runningThreads?.find(
        (thread) => thread.threadId === threadId,
      ) ?? null;
      const runningProjectId = runningThread
        ? identityResolver.canonicalProjectId(runningThread.projectId) ?? runningThread.projectId
        : null;
      const returnProjectId = (
        sourceTask?.projectId ?? runningProjectId ?? selectedProjectId
      ) || undefined;
      const returnProjectName = sourceTask
        ? selectedProject?.name
        : projectChoices.find((project) => project.id === returnProjectId)?.name;
      window.parent.postMessage({
        type: "taskboard:open-thread",
        payload: {
          threadId,
          taskId: sourceTask?.id,
          projectId: returnProjectId,
          projectName: returnProjectName,
          identifier: sourceTask?.identifier,
          title: sourceTask?.title,
        },
      }, "*");
      return;
    }

    window.location.assign(`codex://threads/${encodeURIComponent(threadId.trim())}`);
  }

  function expandCodexSidebar() {
    if (!embedded || window.parent === window) return;
    window.parent.postMessage({ type: "taskboard:expand-sidebar" }, "*");
  }

  function openTaskInThread(
    task: Task,
    options?: { autoSubmit?: boolean; replyToCommentId?: string },
  ) {
    if (!manageTaskboardSkillPath) {
      setActionError("任务面板还没有读取到 manage-taskboard Skill 路径，请刷新后重试。");
      return;
    }
    const workspacePath = resolveCodexExecutionWorkspace(
      task,
      developmentScan.contexts,
      [
        selectedDeviceWorkspacePath,
        developmentScan.workspacePath,
        hostContext?.workspacePath,
      ],
    );
    const instruction = `e-taskboard Addressing the issues mentioned in ${task.identifier}${
      options?.replyToCommentId
        ? `; reply to comment ${options.replyToCommentId} when recording the result`
        : ""
    }`;
    const prompt = `[$manage-taskboard](${manageTaskboardSkillPath}) ${instruction}`;

    if (!embedded || window.parent === window) {
      if (options?.autoSubmit === true) {
        setActionError("评论已发布，但自动交给 Codex 只能在 Codex 内置任务面板中使用。");
        return;
      }
      const query = new URLSearchParams();
      if (workspacePath) query.set("path", workspacePath);
      query.set("prompt", prompt);
      window.location.assign(`codex://new?${query.toString().replace(/\+/g, "%20")}`);
      return;
    }
    if (openingThreadTaskId) return;
    const codexProject = hostContext?.projects?.find((project) => project.id === selectedProject?.id);
    setOpeningThreadTaskId(task.id);
    setActionError(null);
    window.parent.postMessage({
      type: "taskboard:create-thread",
      payload: {
        taskId: task.id,
        projectId: task.projectId,
        identifier: task.identifier,
        title: task.title,
        instruction,
        skillName: "manage-taskboard",
        skillDisplayName: "Manage Taskboard",
        skillPath: manageTaskboardSkillPath,
        codexProjectId: codexProject?.id ?? (selectedProject?.id === "local" ? hostContext?.projectId : selectedProject?.id),
        projectName: selectedProject?.name,
        workspacePath,
        workspaceLabel: task.developmentContext ? workspaceName(workspacePath) : undefined,
        autoSubmit: options?.autoSubmit === true,
      },
    }, "*");
  }

  function changeProject(projectId: string) {
    closeContextMenu();
    setProjectMenuOpen(false);
    setDetailTaskIdentifier(null);
    setWorkspacePane("board");
    setProjectNavigatorOpen(true);
    setBoardView("issues");
    setSelectedProjectId(projectId);
    window.localStorage.setItem(LAST_PROJECT_KEY, projectId);
    setSearch("");
    setFilters(EMPTY_TASK_FILTERS);
    setActionError(null);
    undoStackRef.current = [];
    setUndoNotice(null);
    const url = buildIssueUrl(window.location.href, projectId, null);
    window.history.replaceState(null, "", url);
  }

  function returnToProjectHome() {
    closeContextMenu();
    setProjectMenuOpen(false);
    setDetailTaskIdentifier(null);
    setWorkspacePane("board");
    setSelectedProjectId("");
    window.localStorage.removeItem(LAST_PROJECT_KEY);
    setSearch("");
    setFilters(EMPTY_TASK_FILTERS);
    setActionError(null);
    undoStackRef.current = [];
    setUndoNotice(null);
    const url = buildIssueUrl(window.location.href, null, null);
    window.history.replaceState(null, "", url);
    void loadProjectList();
  }

  function toggleFavoriteProject() {
    if (!selectedProjectId) return;
    const shouldFavorite = !favoriteProjectIds.has(selectedProjectId);
    setFavoriteProjectIds((current) => {
      const next = new Set(current);
      if (shouldFavorite) next.add(selectedProjectId);
      else next.delete(selectedProjectId);
      window.localStorage.setItem(FAVORITE_PROJECTS_KEY, JSON.stringify([...next]));
      return next;
    });
    setAnnouncement(`${selectedProject?.name ?? "项目"}${shouldFavorite ? "已收藏。" : "已取消收藏。"}`);
  }

  async function selectProject(choice: ProjectChoice) {
    if (openingProjectId) return;
    setOpeningProjectId(choice.id);
    setActionError(null);
    try {
      let project = projects.find((candidate) => candidate.id === choice.id) ?? null;
      if (!project) {
        try {
          project = await createProjectRequest({
            id: choice.id,
            name: choice.name,
            workspacePath: null,
          });
          setProjects((current) => [...current, project!]);
        } catch (error) {
          if (!(error instanceof ApiError) || error.code !== "PROJECT_EXISTS") throw error;
          const nextProjects = await listProjects();
          setProjects(nextProjects);
          project = nextProjects.find((candidate) => candidate.id === choice.id) ?? null;
          if (!project) throw error;
        }
      }
      changeProject(project.id);
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setOpeningProjectId(null);
    }
  }

  const contextName = workspaceName(hostContext?.workspacePath);
  const headerProjectName = selectedProject?.name ?? "任务面板";
  const appShellStyle = embedded
    ? { "--codex-titlebar-left-inset": `${hostContext?.titlebarLeftInset ?? 0}px` } as CSSProperties
    : undefined;

  return (
    <div className={`app-shell${embedded ? " embedded" : ""}`} style={appShellStyle}>
      {taskboardMetadata && taskboardMetadata.mode !== "cloud" && (
        <LocalRealtimeSync
          selectedProjectId={selectedProjectId}
          detailTaskId={detailTaskId}
          refreshProjectList={refreshProjectList}
          refreshTasks={refreshTasks}
          refreshWorkflowOptions={refreshWorkflowOptions}
          setConnection={setConnection}
          setCommentsRevision={setCommentsRevision}
          setAttachmentsRevision={setAttachmentsRevision}
        />
      )}
      {!embedded && (
        <aside className="app-nav" aria-label="任务面板导航">
          <div className="brand-row">
            <span className="brand-mark" aria-hidden="true"><LinearIcon name="project" /></span>
            <span>任务面板</span>
          </div>

          <nav className="primary-nav" aria-label="Views">
            <span className="nav-label">工作区</span>
            <button className="nav-item active" type="button" aria-current="page">
              <span className="nav-glyph" aria-hidden="true">
                <LinearIcon name="myIssues" />
              </span>
              议题
              <span className="nav-count">{tasks.length}</span>
            </button>
          </nav>

          <div className="project-nav">
            <span className="nav-label">项目</span>
            {projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className={`project-nav-item${selectedProjectId === project.id ? " active" : ""}`}
                onClick={() => changeProject(project.id)}
              >
                <span className="project-dot" aria-hidden="true" />
                <span>{project.name}</span>
              </button>
            ))}
          </div>

          <div className="nav-spacer" />
          <div className="nav-footer">
            <div className={`connection connection-${connection}`}>
              <span aria-hidden="true" />
              {connection === "live" ? "实时同步" : "正在重新连接…"}
            </div>
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              <span aria-hidden="true"><LinearIcon name={theme === "dark" ? "sun" : "moon"} /></span>
              {theme === "dark" ? "浅色模式" : "深色模式"}
            </button>
          </div>
        </aside>
      )}

      <main className="workspace">
        {selectedProjectId ? (
          <header className="workspace-header">
          <div className="workspace-title">
            <div className="workspace-kicker">
              {embedded && hostContext?.sidebarCollapsed && (
                <button
                  className="detail-back-button codex-sidebar-expand-button"
                  type="button"
                  aria-label="展开 Codex 侧边栏"
                  title="展开侧边栏"
                  onClick={expandCodexSidebar}
                >
                  <LinearIcon name="codexSidebarExpand" />
                </button>
              )}
              {selectedProjectId && (
                <button
                  className="detail-back-button project-home-button"
                  type="button"
                  aria-label="返回项目首页"
                  title="返回项目首页"
                  onClick={returnToProjectHome}
                >
                  <LinearIcon name="home" />
                  <span>首页</span>
                </button>
              )}
              {selectedProjectId && <span className="breadcrumb-chevron" aria-hidden="true"><LinearIcon name="chevronRight" /></span>}
              {selectedProjectId ? (
                <div className="header-project-switcher" data-project-switcher>
                  <button
                    className="header-project-button"
                    type="button"
                    aria-label="切换项目"
                    aria-haspopup="menu"
                    aria-expanded={projectMenuOpen}
                    onClick={() => setProjectMenuOpen((current) => !current)}
                  >
                    <span className="project-avatar" aria-hidden="true">
                      {headerProjectName.slice(0, 1).toUpperCase()}
                    </span>
                    <span className="project-name">{headerProjectName}</span>
                    <LinearIcon className="project-switcher-chevron" name="chevronDown" />
                  </button>
                  {projectMenuOpen && (
                    <div className="header-project-menu" role="menu" aria-label="项目">
                      <span>切换项目</span>
                      {projectChoices.map((project) => (
                        <button
                          type="button"
                          role="menuitemradio"
                          aria-checked={project.id === selectedProjectId}
                          disabled={openingProjectId !== null}
                          key={project.id}
                          onClick={() => {
                            if (project.id === selectedProjectId) setProjectMenuOpen(false);
                            else void selectProject(project);
                          }}
                        >
                          <span className="project-avatar" aria-hidden="true">{project.name.slice(0, 1).toUpperCase()}</span>
                          <span>{project.name}</span>
                          {favoriteProjectIds.has(project.id) && <span className="project-menu-favorite" aria-label="已收藏"><LinearIcon name="favorite" /></span>}
                          {project.id === selectedProjectId && <span className="project-menu-check" aria-hidden="true"><LinearIcon name="check" /></span>}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <>
                  <span className="project-avatar" aria-hidden="true">
                    {headerProjectName.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="project-name">{headerProjectName}</span>
                </>
              )}
              {!selectedProjectId && (
                <>
                  <span className="breadcrumb-chevron" aria-hidden="true"><LinearIcon name="chevronRight" /></span>
                  <strong>项目</strong>
                </>
              )}
              {selectedProjectId && (
                <button
                  className={`favorite-button${favoriteProjectIds.has(selectedProjectId) ? " active" : ""}`}
                  type="button"
                  aria-label={favoriteProjectIds.has(selectedProjectId) ? "取消收藏项目" : "收藏项目"}
                  aria-pressed={favoriteProjectIds.has(selectedProjectId)}
                  title={favoriteProjectIds.has(selectedProjectId) ? "取消收藏" : "收藏项目"}
                  onClick={toggleFavoriteProject}
                >
                  <LinearIcon className="favorite-icon" name="favorite" />
                </button>
              )}
              {selectedProjectId && embedded && contextName && <span className="codex-context">{contextName}</span>}
            </div>
          </div>

          <div ref={dragRegionRef} className="workspace-drag-region" aria-hidden="true" />

          <div className="header-actions">
            {selectedProjectId && (
              <ProjectAutomationMenu
                automation={selectedProjectAutomation}
                pending={automationPending}
                error={automationError}
                unavailableReason={automationProjectContext.unavailableReason}
                onOpen={() => void reconcileProjectAutomation()}
                onChange={(options) => void saveProjectAutomation(options)}
              />
            )}
            {selectedProjectId && workspacePane === "board" && boardView === "issues" && (
              <button
                className="icon-button header-create-button"
                type="button"
                onClick={() => setEditor({ task: null, status: "backlog" })}
                aria-label="新建议题"
                title="新建议题 (C)"
              >
                <LinearIcon name="plus" />
              </button>
            )}
          </div>
          </header>
        ) : (
          <div ref={dragRegionRef} className="home-window-drag-region" aria-hidden="true" />
        )}

        {selectedProjectId && <div className="board-toolbar workspace-toolbar">
          <div className="workspace-tabs" role="tablist" aria-label="项目工作区">
            <button
              className={`workspace-tab${workspacePane === "board" ? " active" : ""}`}
              type="button"
              role="tab"
              aria-selected={workspacePane === "board"}
              aria-expanded={projectNavigatorOpen}
              aria-label={workspacePane === "board"
                ? projectNavigatorOpen ? "看板，隐藏项目导航" : "看板，显示项目导航"
                : "返回看板"}
              title={workspacePane === "board"
                ? projectNavigatorOpen ? "隐藏项目导航" : "显示项目导航"
                : "返回看板"}
              onClick={handleBoardTabClick}
            >
              <LinearIcon name="panel" />
              看板
              {workspacePane === "board" && (
                <LinearIcon
                  className="workspace-tab-toggle"
                  name={projectNavigatorOpen ? "chevronLeft" : "chevronRight"}
                />
              )}
            </button>
            {detailTask && (
              <button
                className={`workspace-tab workspace-tab-issue${workspacePane === "issue" ? " active" : ""}`}
                type="button"
                role="tab"
                aria-selected={workspacePane === "issue"}
                onClick={() => selectWorkspacePane("issue")}
                title={`${detailTask.identifier} ${detailTask.title}`}
              >
                <LinearStatusIcon status={detailTask.status} />
                <span>{detailTask.identifier}</span>
                <strong>{detailTask.title}</strong>
              </button>
            )}
            <button
              className={`workspace-tab${workspacePane === "conversations" ? " active" : ""}`}
              type="button"
              role="tab"
              aria-selected={workspacePane === "conversations"}
              onClick={() => selectWorkspacePane("conversations")}
            >
              <LinearIcon name="conversation" />
              相关对话
              <span className="workspace-tab-count">{conversationTaskCount}</span>
            </button>
            {SHOW_WORKFLOW_BOARD_ENTRY && (
              <button
                className={`workspace-tab${workspacePane === "board" && boardView === "workflow" ? " active" : ""}`}
                type="button"
                role="tab"
                aria-selected={workspacePane === "board" && boardView === "workflow"}
                onClick={() => {
                  selectWorkspacePane("board");
                  selectBoardView("workflow");
                }}
              >
                节点模式
              </button>
            )}
          </div>
          {workspacePane === "board" && boardView === "issues" && <div className="toolbar-tools">
            <label className={`search-field${search ? " has-value" : ""}`} title="搜索议题 (/)" >
              <LinearIcon className="search-icon" name="search" />
              <span className="sr-only">搜索议题</span>
              <input
                id="task-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索议题…"
              />
              {!search && <kbd>/</kbd>}
            </label>
            <TaskFilterMenu
              tasks={tasks}
              search={search}
              labels={availableLabels}
              filters={filters}
              onChange={setFilters}
            />
            {(search || activeFilterCount > 0) && (
              <button
                className="clear-filter"
                type="button"
                aria-label="清除筛选"
                title="清除筛选"
                onClick={() => { setSearch(""); setFilters(EMPTY_TASK_FILTERS); }}
              >
                <LinearIcon name="close" />
              </button>
            )}
          </div>}
        </div>}

        {(loadError || actionError) && (
          <div className="error-banner" role="alert">
            <span className="error-mark" aria-hidden="true"><LinearIcon name="alert" /></span>
            <div><strong>任务面板需要处理</strong><p>{actionError ?? loadError}</p></div>
            <button
              type="button"
              onClick={() => {
                setActionError(null);
                if (selectedProjectId) void refreshTasks(selectedProjectId);
                else void loadProjectList();
              }}
            >
              重试
            </button>
          </div>
        )}

        {!selectedProjectId ? (
          <section className="project-home">
            <div className="project-home-heading">
              <span>任务面板</span>
              <h1>选择项目</h1>
              <p>从 Codex 项目开始，或继续使用之前保存的项目。</p>
            </div>
            {projectsLoading ? (
              <div className="project-grid project-grid-loading" aria-label="正在加载项目" aria-busy="true">
                <span /><span /><span />
              </div>
            ) : projectChoices.length > 0 ? (
              <div className="project-home-groups">
                {[
                  { id: "with-issues", title: "已有任务", projects: projectsWithIssues },
                  { id: "without-issues", title: "暂无任务", projects: projectsWithoutIssues },
                ].map((group) => (
                  <section className="project-home-group" key={group.id} aria-labelledby={`project-group-${group.id}`}>
                    <div className="project-group-heading">
                      <h2 id={`project-group-${group.id}`}>{group.title}</h2>
                      <span>{group.projects.length}</span>
                    </div>
                    {group.projects.length > 0 ? (
                      <div className="project-grid">
                        {group.projects.map((project) => (
                          <div className="project-card" key={project.id}>
                            <button
                              className="project-card-open"
                              type="button"
                              disabled={openingProjectId !== null}
                              onClick={() => void selectProject(project)}
                            >
                              <span className="project-card-avatar" aria-hidden="true">
                                {project.name.slice(0, 1).toUpperCase()}
                              </span>
                              <span className="project-card-copy">
                                <strong>{project.name}</strong>
                                <span>
                                  {project.inCodex ? "Codex 项目" : "已保存的项目"}
                                  {project.runningConversationCount > 0
                                    ? ` · ${project.runningConversationCount} 项执行中${project.issueCount > 0 ? ` · ${project.issueCount} 个议题` : ""}`
                                    : project.issueCount > 0
                                      ? ` · ${project.issueCount} 个议题`
                                    : project.persisted
                                      ? " · 任务面板已启用，暂无议题"
                                      : " · 未启用任务面板，点击启用"}
                                </span>
                              </span>
                              {favoriteProjectIds.has(project.id) && <span className="project-card-favorite" aria-label="已收藏"><LinearIcon name="favorite" /></span>}
                              <span className="project-card-action" aria-hidden="true">
                                {openingProjectId === project.id ? "正在打开…" : <LinearIcon name="chevronRight" />}
                              </span>
                            </button>
                            <label className="project-card-directory">
                              <LinearIcon name="folder" />
                              <input
                                key={project.workspacePath ?? ""}
                                type="text"
                                defaultValue={project.workspacePath ?? ""}
                                placeholder="设置此设备的项目目录"
                                aria-label={`${project.name} 在此设备上的项目目录`}
                                onBlur={(event) => rememberDeviceWorkspacePath(project.id, event.currentTarget.value)}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter") event.currentTarget.blur();
                                }}
                              />
                            </label>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="project-group-empty">暂无项目</p>
                    )}
                  </section>
                ))}
              </div>
            ) : (
              <div className="project-home-empty">
                <span className="empty-orbit" aria-hidden="true"><i /><i /></span>
                <h2>还没有项目</h2>
                <p>在 Codex 中创建项目后，再打开任务面板。</p>
              </div>
            )}
          </section>
        ) : (
          <div className={`project-workspace-shell${projectNavigatorOpen ? "" : " navigator-collapsed"}`}>
            <ProjectNavigator
              projects={projectChoices}
              selectedProjectId={selectedProjectId}
              openingProjectId={openingProjectId}
              onCreate={() => setEditor({ task: null, status: "backlog" })}
              onSelect={(project) => void selectProject(project)}
            />
            <div className="project-workspace-content">
        {workspacePane === "issue" && detailTask && selectedProject ? (
          <TaskDetail
            key={detailTask.id}
            task={detailTask}
            tasks={tasks}
            currentUser={currentUser}
            availableLabels={availableLabels}
            workflows={workflowOptions}
            developmentScan={developmentScan}
            developmentScanLoading={developmentScanLoading}
            commentsRevision={commentsRevision}
            attachmentsRevision={attachmentsRevision}
            scrollToLatestActivity={latestActivityTarget === detailTask.identifier}
            onUpdate={(current, changes) => updateTaskProperties(current, changes)}
            onStatusChange={changeTaskStatus}
            onOpenTask={openTaskDetail}
            onAddRelation={(current, type, relatedTaskId) => (
              mutateTaskRelation("add", current, type, relatedTaskId)
            )}
            onRemoveRelation={(current, type, relatedTaskId) => (
              mutateTaskRelation("remove", current, type, relatedTaskId)
            )}
            onOpenThread={openThread}
            onOpenInThread={openTaskInThread}
            openingThread={openingThreadTaskId === detailTask.id}
            onLatestActivityVisible={() => setLatestActivityTarget((current) => (
              current === detailTask.identifier ? null : current
            ))}
            onError={setActionError}
            onAnnounce={setAnnouncement}
          />
        ) : workspacePane === "conversations" ? (
          <RelatedConversations
            tasks={tasks}
            runningThreads={liveRunningThreads}
            onOpenIssue={openTaskDetail}
            onOpenThread={openThread}
          />
        ) : boardView === "workflow" ? (
          <Suspense fallback={<div className="workflow-board-loading">正在打开节点模式…</div>}>
            <WorkflowBoard
              key={selectedProject?.id ?? "local"}
              projectId={selectedProject?.id ?? "local"}
              projectName={selectedProject?.name ?? "当前项目"}
              workspacePath={
                selectedDeviceWorkspacePath
                ?? developmentScan.workspacePath
                ?? hostContext?.workspacePath
              }
              revision={workflowRevision}
              onWorkflowsChange={setWorkflowOptions}
            />
          </Suspense>
        ) : tasksLoading && !hasLoadedTasks ? (
          <div className="loading-board" aria-label="正在加载议题" aria-busy="true">
            {TASK_STATUSES.map((status) => (
              <div className="loading-column" key={status}>
                <span /><div /><div />
              </div>
            ))}
          </div>
        ) : (
          <div
            className={`board-scroll${tasks.length === 0 && liveRunningThreads.length === 0 ? " empty-project-board" : ""}`}
            aria-label="议题看板"
          >
            {tasks.length === 0 && liveRunningThreads.length === 0 && (
              <section className="empty-project-onboarding" aria-label="空项目说明">
                <span className="empty-project-onboarding-icon" aria-hidden="true">
                  <LinearIcon name="project" />
                </span>
                <span className="empty-project-onboarding-copy">
                  <strong>从现在开始追踪这个项目</strong>
                  <span>历史 Codex 对话不会自动归入待办或已完成，创建首个议题后开始记录进度。</span>
                </span>
                <button
                  className="button primary"
                  type="button"
                  onClick={() => setEditor({ task: null, status: "todo" })}
                >
                  <LinearIcon name="plus" />
                  新建第一个待办
                </button>
              </section>
            )}
            <div className="board">
              {orderedStatuses.map((status) => (
                <BoardColumn
                  key={status}
                  status={status}
                  statusIndex={TASK_STATUSES.indexOf(status)}
                  tasks={tasksByStatus[status]}
                  runningThreads={status === "in_progress" ? liveRunningThreads : []}
                  isDropTarget={dropTarget === status}
                  draggedTaskId={draggedTaskId}
                  draggedTaskHeight={draggedTaskHeight}
                  movingTaskId={movingTaskId}
                  settlingTaskId={settlingTaskId}
                  contextMenuTaskId={contextMenu?.taskId ?? null}
                  onCreate={(initialStatus) => setEditor({ task: null, status: initialStatus })}
                  onEdit={openTaskDetail}
                  onContextMenu={(task, position) => setContextMenu({ taskId: task.id, ...position })}
                  onMove={(task, destination) => void moveTask(task, destination)}
                  onDragStart={(task, height) => {
                    setDraggedTaskId(task.id);
                    setDraggedTaskHeight(height);
                    setDropTarget(task.status);
                  }}
                  onDragEnd={() => {
                    setDraggedTaskId(null);
                    setDraggedTaskHeight(0);
                    setDropTarget(null);
                  }}
                  onDragEnter={setDropTarget}
                  onDrop={finishTaskDrop}
                  onOpenThread={openThread}
                  onOpenRunningTask={openThread}
                />
              ))}
            </div>
          </div>
        )}
            </div>
          </div>
        )}
      </main>

      {editor && (
        <TaskEditor
          key={editor.task?.id ?? `new-${editor.status}`}
          task={editor.task}
          initialStatus={editor.status}
          labels={availableLabels}
          workflows={workflowOptions}
          currentUser={currentUser}
          developmentScan={developmentScan}
          developmentScanLoading={developmentScanLoading}
          canExecuteWithCodex={embedded && Boolean(manageTaskboardSkillPath)}
          onCancel={() => setEditor(null)}
          onSave={saveEditor}
        />
      )}

      {blockingRequest && (
        <BlockTaskDialog
          task={blockingRequest.task}
          onCancel={() => settleBlockingRequest(null)}
          onConfirm={settleBlockingRequest}
        />
      )}

      {contextMenu && contextMenuTask && (
        <TaskContextMenu
          task={contextMenuTask}
          position={{ x: contextMenu.x, y: contextMenu.y }}
          labels={availableLabels}
          onClose={closeContextMenu}
          onEdit={openTaskDetail}
          onStatusChange={(task, status) => void changeTaskStatus(task, status)}
          onPriorityChange={(task, nextPriority) => void updateTaskProperties(
            task,
            { priority: nextPriority },
            `${task.identifier} 优先级已更新。`,
          ).catch(() => {})}
          onLabelsChange={(task, labels) => void updateTaskProperties(
            task,
            { labels },
            `${task.identifier} 标签已更新。`,
          ).catch(() => {})}
          onDuplicate={(task) => void duplicateTask(task)}
          onCopy={(text, message) => void copyText(text, message)}
          onOpenInThread={openTaskInThread}
          onArchive={(task) => void archiveTask(task)}
        />
      )}

      <AiChat
        available={localAiChatAvailable}
        projectId={selectedProjectId || null}
        issueId={workspacePane === "issue" ? detailTaskId : null}
      />

      <div className="sr-only" role="status" aria-live="polite">{announcement}</div>
      {undoNotice && (
        <div
          className="toast undo-toast"
          role="status"
          onAnimationEnd={() => setUndoNotice((current) => current?.id === undoNotice.id ? null : current)}
        >
          <span className="toast-check" aria-hidden="true"><LinearIcon name="check" /></span>
          <span className="undo-toast-message">{undoNotice.message}</span>
          <button type="button" onClick={() => void performUndo()}>
            撤回 <kbd>{undoShortcut}</kbd>
          </button>
        </div>
      )}
      {announcement && (
        <div className="toast" role="status" onAnimationEnd={() => setAnnouncementValue("")}>
          <span aria-hidden="true"><LinearIcon name="check" /></span>{announcement}
        </div>
      )}
      {draggedTaskId && <div className="drag-hint" aria-hidden="true">拖到目标位置后松开</div>}
    </div>
  );
}
