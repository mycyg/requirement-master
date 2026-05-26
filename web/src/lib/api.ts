import type {
  Activity, Attachment, Comment, Delivery,
  Identity, Project, Requirement, StoredChatMessage,
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

  listProjects: () => json<Project[]>("/api/projects"),
  createProject: (input: { name: string; slug: string; description?: string }) =>
    json<Project>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),

  createRequirement: (project_id: string, input: { raw_description: string; priority?: string }) =>
    json<Requirement>(`/api/projects/${project_id}/requirements`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  listRequirements: (params: { project_id?: string; mine?: boolean; status?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.project_id) q.set("project_id", params.project_id);
    if (params.mine) q.set("mine", "true");
    if (params.status) q.set("status", params.status);
    return json<Requirement[]>(`/api/requirements?${q.toString()}`);
  },
  getRequirement: (id: string) => json<Requirement>(`/api/requirements/${id}`),
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
