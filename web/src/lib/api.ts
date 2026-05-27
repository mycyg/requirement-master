import type {
  Activity, Attachment, Comment, Delivery, DriveItem, DriveList, DrivePreview, DriveTreeNode, DriveUploadInit,
  Identity, Project, Requirement, RequirementAssignee, StoredChatMessage, UserOption,
} from "./types";

const COMMON: RequestInit = { credentials: "include" };

async function json<T>(input: string, init?: RequestInit): Promise<T> {
  const r = await fetch(input, { ...COMMON, ...init });
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
    const r = await fetch(`/api/projects/${projectId}/drive/upload/${uploadId}/chunk/${idx}`, {
      ...COMMON,
      method: "PUT",
      headers: { "Content-Type": "application/octet-stream" },
      body: chunk,
    });
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
  bulkDownloadDrive: async (itemIds: string[]) => {
    const r = await fetch("/api/drive/bulk-download", {
      ...COMMON,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_ids: itemIds }),
    });
    if (!r.ok) throw new Error(`download failed: ${r.status} ${await r.text()}`);
    return r.blob();
  },

  createRequirement: (project_id: string, input: {
    raw_description: string;
    priority?: string;
    lead_user_id?: string | null;
    collaborator_user_ids?: string[];
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
    const r = await fetch(`/api/requirements/${req_id}/attachments`, {
      ...COMMON, method: "POST", body: fd,
    });
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
};
