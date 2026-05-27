import type {
  Activity, Attachment, BackgroundJob, Comment, Delivery, DriveComment, DriveItem, DriveList, DriveManifest, DrivePreview,
  DriveTreeNode, DriveUploadInit, Identity, KnowledgeAskRun, KnowledgeSearchHit, Meeting, MeetingInsight, MeetingUploadInit,
  Notification, Project, ProjectHealth, Reminder, Requirement, RequirementAcceptanceItem,
  RequirementAssignee, RequirementWorkspace, ScheduleEvent, StoredChatMessage, TaskPlan, UserOption, UserWorkload, WorkspaceItem,
} from "./types";

export function isDesktopRuntime(): boolean {
  try {
    return window.localStorage.getItem("yqgl_runtime") === "desktop";
  } catch {
    return false;
  }
}

function localClientToken(): string | null {
  try {
    return window.localStorage.getItem("yqgl_client_token");
  } catch {
    return null;
  }
}

function withCommon(init: RequestInit = {}): RequestInit {
  const headers = new Headers(init.headers || {});
  const token = localClientToken();
  if (token) headers.set("X-YQGL-Client-Token", token);
  return { ...init, credentials: "include", headers };
}

async function json<T>(input: string, init?: RequestInit): Promise<T> {
  const r = await fetch(input, withCommon(init));
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status} ${r.statusText}: ${text.slice(0, 200)}`);
  }
  return (await r.json()) as T;
}

export const api = {
  identify: (nickname: string) =>
    json<Identity>("/api/auth/identify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nickname }),
    }),
  me: () => json<Identity | null>("/api/auth/me"),
  listUsers: (search = "") => {
    const q = new URLSearchParams();
    if (search.trim()) q.set("search", search.trim());
    return json<UserOption[]>(`/api/users?${q.toString()}`);
  },
  updateMyStatus: (input: { availability_status: "free" | "busy" | "custom"; availability_text?: string | null }) =>
    json<UserOption>("/api/users/me/status", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),

  listProjects: () => json<Project[]>("/api/projects"),
  createProject: (input: { name: string; slug: string; description?: string }) =>
    json<Project>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  listDrive: (projectId: string, params: { parent_id?: string | null; search?: string; trash?: boolean; sort?: string; direction?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.parent_id) q.set("parent_id", params.parent_id);
    if (params.search?.trim()) q.set("search", params.search.trim());
    if (params.trash) q.set("trash", "true");
    if (params.sort) q.set("sort", params.sort);
    if (params.direction) q.set("direction", params.direction);
    return json<DriveList>(`/api/projects/${projectId}/drive?${q.toString()}`);
  },
  driveTree: (projectId: string) => json<DriveTreeNode[]>(`/api/projects/${projectId}/drive/tree`),
  driveManifest: (projectId: string) => json<DriveManifest>(`/api/projects/${projectId}/drive/manifest`),
  driveChanges: (projectId: string, since: string) => {
    const q = new URLSearchParams({ since });
    return json<DriveManifest>(`/api/projects/${projectId}/drive/changes?${q.toString()}`);
  },
  createDriveFolder: (projectId: string, input: { name: string; parent_id?: string | null }) =>
    json<DriveItem>(`/api/projects/${projectId}/drive/folders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  initDriveUpload: (projectId: string, input: {
    filename: string; total_size: number; total_chunks: number; mime?: string | null;
    parent_id?: string | null; conflict?: "cancel" | "replace" | "rename"; existing_item_id?: string | null;
  }) =>
    json<DriveUploadInit>(`/api/projects/${projectId}/drive/upload/init`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  uploadDriveChunk: async (projectId: string, uploadId: string, idx: number, chunk: Blob) => {
    const r = await fetch(`/api/projects/${projectId}/drive/upload/${uploadId}/chunk/${idx}`, withCommon({
      method: "PUT",
      headers: { "Content-Type": "application/octet-stream" },
      body: chunk,
    }));
    if (!r.ok) throw new Error(`chunk upload failed: ${r.status} ${await r.text()}`);
    return r.json();
  },
  finalizeDriveUpload: (projectId: string, uploadId: string) =>
    json<DriveItem>(`/api/projects/${projectId}/drive/upload/${uploadId}/finalize`, { method: "POST" }),
  previewDriveItem: (itemId: string) => json<DrivePreview>(`/api/drive/files/${itemId}/preview`),
  driveDownloadUrl: (itemId: string) => `/api/drive/files/${itemId}/download`,
  patchDriveItem: (itemId: string, input: { name?: string; parent_id?: string | null }) =>
    json<DriveItem>(`/api/drive/items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  pasteDriveItems: (projectId: string, input: { item_ids: string[]; target_parent_id?: string | null; mode: "copy" | "cut" }) =>
    json<{ ok: boolean; operation_id?: string | null; items: DriveItem[] }>(`/api/projects/${projectId}/drive/paste`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  deleteDriveItem: (itemId: string) => json<{ ok: boolean; operation_id?: string | null }>(`/api/drive/items/${itemId}`, { method: "DELETE" }),
  bulkDeleteDriveItems: (itemIds: string[]) =>
    json<{ ok: boolean; operation_id?: string | null }>("/api/drive/bulk-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_ids: itemIds }),
    }),
  restoreDriveItem: (itemId: string) => json<DriveItem>(`/api/drive/items/${itemId}/restore`, { method: "POST" }),
  undoDrive: (projectId: string) => json<{ ok: boolean; operation_id?: string | null }>(`/api/projects/${projectId}/drive/undo`, { method: "POST" }),
  listDriveComments: (projectId: string, folderId: string | null) =>
    json<DriveComment[]>(`/api/projects/${projectId}/drive/folders/${folderId || "root"}/comments`),
  addDriveComment: (projectId: string, folderId: string | null, body: string) =>
    json<DriveComment>(`/api/projects/${projectId}/drive/folders/${folderId || "root"}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    }),
  bulkDownloadDrive: async (itemIds: string[]) => {
    const r = await fetch("/api/drive/bulk-download", withCommon({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_ids: itemIds }),
    }));
    if (!r.ok) throw new Error(`download failed: ${r.status} ${await r.text()}`);
    return r.blob();
  },

  createRequirement: (project_id: string, input: {
    raw_description: string;
    priority?: string;
    lead_user_id?: string | null;
    collaborator_user_ids?: string[];
    start_at?: string | null;
    due_at?: string | null;
    estimate_hours?: number | null;
    estimate_confidence?: "low" | "medium" | "high" | null;
    planning_note?: string | null;
  }) =>
    json<Requirement>(`/api/projects/${project_id}/requirements`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  listRequirements: (params: { project_id?: string; mine?: boolean; assigned_to_me?: boolean; status?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.project_id) q.set("project_id", params.project_id);
    if (params.mine) q.set("mine", "true");
    if (params.assigned_to_me) q.set("assigned_to_me", "true");
    if (params.status) q.set("status", params.status);
    return json<Requirement[]>(`/api/requirements?${q.toString()}`);
  },
  getRequirement: (id: string) => json<Requirement>(`/api/requirements/${id}`),
  listAssignees: (id: string) => json<RequirementAssignee[]>(`/api/requirements/${id}/assignees`),
  updateAssignees: (id: string, input: { lead_user_id?: string | null; collaborator_user_ids?: string[] }) =>
    json<RequirementAssignee[]>(`/api/requirements/${id}/assignees`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  updateRequirementSchedule: (id: string, input: { start_at?: string | null; due_at?: string | null }) =>
    json<Requirement>(`/api/requirements/${id}/schedule`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  updateRequirementPlanning: (id: string, input: {
    estimate_hours?: number | null; estimate_confidence?: "low" | "medium" | "high" | null; planning_note?: string | null;
  }) =>
    json<Requirement>(`/api/requirements/${id}/planning`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  patchStatus: (id: string, status: string) =>
    json<Requirement>(`/api/requirements/${id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }),
  submitRequirement: (id: string) =>
    json<{ ok: boolean; status: string }>(`/api/requirements/${id}/submit`, { method: "POST" }),
  autoProcess: (id: string) =>
    json<{ ok: boolean; status: string }>(`/api/requirements/${id}/auto-process`, { method: "POST" }),

  // comments
  listComments: (req_id: string) => json<Comment[]>(`/api/requirements/${req_id}/comments`),
  addComment: (req_id: string, body: string) =>
    json<Comment>(`/api/requirements/${req_id}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    }),

  // activity
  listActivity: (req_id: string) => json<Activity[]>(`/api/requirements/${req_id}/activity`),

  // deliveries
  listDeliveries: (req_id: string) => json<Delivery[]>(`/api/requirements/${req_id}/deliveries`),
  acceptDelivery: (req_id: string) =>
    json<{ ok: boolean; status: string }>(`/api/requirements/${req_id}/accept`, { method: "POST" }),
  requestRevision: (req_id: string, reason_md: string) =>
    json<{ ok: boolean; status: string }>(`/api/requirements/${req_id}/revisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason_md }),
    }),
  claimRequirement: (req_id: string) =>
    json<{ ok: boolean; status: string }>(`/api/requirements/${req_id}/claim`, { method: "POST" }),

  listAttachments: (req_id: string) => json<Attachment[]>(`/api/requirements/${req_id}/attachments`),
  uploadSimple: async (req_id: string, file: File): Promise<Attachment> => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`/api/requirements/${req_id}/attachments`, withCommon({
      method: "POST", body: fd,
    }));
    if (!r.ok) throw new Error(`upload failed: ${r.status} ${await r.text()}`);
    return r.json();
  },

  listChatMessages: (req_id: string) =>
    json<StoredChatMessage[]>(`/api/requirements/${req_id}/chat/messages`),
  postAnswer: (req_id: string, body: {
    selected_option_key?: string; other_text?: string; text?: string;
  }) =>
    json<{ chat_message_id: string }>(`/api/requirements/${req_id}/chat/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  listCalendarEvents: (params: { start?: string; end?: string; project_id?: string; mine?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (params.start) q.set("start", params.start);
    if (params.end) q.set("end", params.end);
    if (params.project_id) q.set("project_id", params.project_id);
    if (params.mine) q.set("mine", "true");
    return json<ScheduleEvent[]>(`/api/calendar/events?${q.toString()}`);
  },
  createCalendarEvent: (input: {
    title: string; description?: string | null; project_id?: string | null; requirement_id?: string | null;
    event_type?: "custom" | "requirement_due"; start_at?: string | null; end_at: string; participant_user_ids?: string[];
  }) =>
    json<ScheduleEvent>("/api/calendar/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  patchCalendarEvent: (id: string, input: Partial<{
    title: string; description: string | null; project_id: string | null; requirement_id: string | null;
    start_at: string | null; end_at: string; participant_user_ids: string[];
  }>) =>
    json<ScheduleEvent>(`/api/calendar/events/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  deleteCalendarEvent: (id: string) => json<{ ok: boolean }>(`/api/calendar/events/${id}`, { method: "DELETE" }),
  dueReminders: () => json<Reminder[]>("/api/reminders/due"),

  getJob: (id: string) => json<BackgroundJob>(`/api/jobs/${id}`),

  listRequirementWorkspaces: (reqId: string) => json<RequirementWorkspace[]>(`/api/requirements/${reqId}/workspaces`),
  patchMyWorkspace: (reqId: string, input: {
    phase?: string; progress_percent?: number; status_note?: string | null; blocked_reason?: string | null;
  }) =>
    json<RequirementWorkspace>(`/api/requirements/${reqId}/workspaces/me`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  createWorkspaceItem: (reqId: string, input: { title: string; status?: "todo" | "doing" | "done"; sort_order?: number }) =>
    json<WorkspaceItem>(`/api/requirements/${reqId}/workspaces/me/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  patchWorkspaceItem: (itemId: string, input: Partial<{ title: string; status: "todo" | "doing" | "done"; sort_order: number }>) =>
    json<WorkspaceItem>(`/api/workspace-items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  deleteWorkspaceItem: (itemId: string) => json<{ ok: boolean }>(`/api/workspace-items/${itemId}`, { method: "DELETE" }),
  addWorkspaceUpdate: (reqId: string, body: string) =>
    json(`/api/requirements/${reqId}/workspaces/me/updates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body, kind: "manual" }),
    }),

  listMeetings: (projectId: string) => json<Meeting[]>(`/api/projects/${projectId}/meetings`),
  initMeetingUpload: (projectId: string, input: {
    filename: string; total_size: number; total_chunks: number; mime?: string | null; title?: string | null; requirement_id?: string | null;
  }) =>
    json<MeetingUploadInit>(`/api/projects/${projectId}/meetings/upload/init`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  uploadMeetingChunk: async (projectId: string, uploadId: string, idx: number, chunk: Blob) => {
    const r = await fetch(`/api/projects/${projectId}/meetings/upload/${uploadId}/chunk/${idx}`, withCommon({
      method: "PUT",
      headers: { "Content-Type": "application/octet-stream" },
      body: chunk,
    }));
    if (!r.ok) throw new Error(`meeting chunk upload failed: ${r.status} ${await r.text()}`);
    return r.json();
  },
  finalizeMeetingUpload: (projectId: string, uploadId: string) =>
    json<Meeting>(`/api/projects/${projectId}/meetings/upload/${uploadId}/finalize`, { method: "POST" }),
  getMeeting: (id: string) => json<Meeting>(`/api/meetings/${id}`),
  patchMeeting: (id: string, input: Partial<{ title: string; transcript_text: string | null; minutes_md: string | null }>) =>
    json<Meeting>(`/api/meetings/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  confirmMeetingInsight: (id: string) => json<MeetingInsight>(`/api/meeting-insights/${id}/confirm`, { method: "POST" }),
  dismissMeetingInsight: (id: string) => json<MeetingInsight>(`/api/meeting-insights/${id}/dismiss`, { method: "POST" }),

  searchKnowledge: (params: { q: string; project_id?: string | null; scope?: string | null; limit?: number }) => {
    const q = new URLSearchParams({ q: params.q });
    if (params.project_id) q.set("project_id", params.project_id);
    if (params.scope) q.set("scope", params.scope);
    if (params.limit) q.set("limit", String(params.limit));
    return json<{ query: string; hits: KnowledgeSearchHit[] }>(`/api/knowledge/search?${q.toString()}`);
  },
  askKnowledge: (input: { question: string; project_id?: string | null }) =>
    json<{ id: string; job_id: string; status: string }>("/api/knowledge/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  getKnowledgeRun: (id: string) => json<KnowledgeAskRun>(`/api/knowledge/runs/${id}`),

  workload: (params: { start?: string; end?: string; project_id?: string | null } = {}) => {
    const q = new URLSearchParams();
    if (params.start) q.set("start", params.start);
    if (params.end) q.set("end", params.end);
    if (params.project_id) q.set("project_id", params.project_id);
    return json<UserWorkload[]>(`/api/planning/workload?${q.toString()}`);
  },
  listNotifications: (status: "unread" | "all" = "unread") => json<Notification[]>(`/api/notifications?status=${status}`),
  readNotification: (id: string) => json<Notification>(`/api/notifications/${id}/read`, { method: "POST" }),
  readAllNotifications: () => json<{ ok: boolean; count: number }>("/api/notifications/read-all", { method: "POST" }),
  projectHealth: () => json<ProjectHealth[]>("/api/project-health"),
  getProjectHealth: (projectId: string) => json<ProjectHealth>(`/api/projects/${projectId}/health`),

  listTaskPlans: (reqId: string) => json<TaskPlan[]>(`/api/requirements/${reqId}/decompositions`),
  createTaskPlan: (reqId: string, stage: "dispatch" | "worker") =>
    json<TaskPlan>(`/api/requirements/${reqId}/decompositions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    }),
  confirmTaskPlan: (id: string) =>
    json<{ plan: TaskPlan; acceptance_items: RequirementAcceptanceItem[]; workspace_items: WorkspaceItem[] }>(`/api/decompositions/${id}/confirm`, { method: "POST" }),
  dismissTaskPlan: (id: string) => json<TaskPlan>(`/api/decompositions/${id}/dismiss`, { method: "POST" }),
  listAcceptanceItems: (reqId: string) => json<RequirementAcceptanceItem[]>(`/api/requirements/${reqId}/acceptance`),
};
