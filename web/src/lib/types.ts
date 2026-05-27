export type Identity = { id: string; nickname: string; created: boolean };

export type UserOption = { id: string; nickname: string; is_online?: boolean; last_seen_at?: string | null };

export type RequirementAssignee = {
  user_id: string;
  nickname: string;
  role: "lead" | "collaborator";
  assigned_at: string;
};

export type Project = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  owner_nickname: string;
  archived: boolean;
  created_at: string;
};

export type DriveItem = {
  id: string;
  project_id: string;
  parent_id: string | null;
  name: string;
  kind: "file" | "folder";
  size_bytes: number | null;
  mime: string | null;
  sha256: string | null;
  version_no: number | null;
  has_preview: boolean;
  created_by_nickname: string | null;
  updated_by_nickname: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};

export type DriveBreadcrumb = { id: string | null; name: string };
export type DriveTreeNode = { id: string; name: string; parent_id: string | null; children: DriveTreeNode[] };
export type DriveList = {
  project_id: string;
  parent_id: string | null;
  breadcrumbs: DriveBreadcrumb[];
  items: DriveItem[];
};
export type DrivePreview = {
  item_id: string;
  name: string;
  preview_type: "pdf" | "html" | "markdown" | "code" | "unsupported";
  mime: string | null;
  content: string | null;
  download_url: string;
  render_url: string | null;
  version_no: number | null;
};
export type DriveUploadInit = {
  upload_id: string | null;
  chunk_size: number;
  conflict?: string | null;
  existing_item?: DriveItem | null;
};

export type Requirement = {
  id: string;
  code: string;
  project_id: string;
  project_slug: string;
  submitter_nickname: string;
  claimed_by_user_id: string | null;
  claimed_by_nickname: string | null;
  title: string | null;
  raw_description: string | null;
  summary_md: string | null;
  status:
    | "draft" | "clarifying" | "summary_ready" | "ready" | "claimed" | "doing" | "ai_processing"
    | "delivery_doc_pending" | "delivered" | "revision_requested" | "accepted" | "cancelled";
  priority: string;
  start_at: string | null;
  due_at: string | null;
  claimed_at: string | null;
  done_at: string | null;
  delivered_at: string | null;
  delivery_doc_ready_at: string | null;
  accepted_at: string | null;
  sync_state: string;
  assignees: RequirementAssignee[];
  created_at: string;
  updated_at: string;
};

export type Attachment = {
  id: string;
  filename: string;
  mime: string | null;
  size_bytes: number;
  sha256: string | null;
  role_in_req: string | null;
  has_parsed_text: boolean;
  created_at: string;
};

export type ChoiceOption = { key: string; label: string };

export type AskChoicePayload = {
  question: string;
  options: ChoiceOption[];
  allow_other?: boolean;
  target_file_id?: string;
};

export type AskOpenPayload = {
  question: string;
  placeholder?: string;
};

export type SummarizePayload = {
  title: string;
  summary_md: string;
  complexity?: "low" | "medium" | "high";
  ai_doable?: boolean;
  ai_reason?: string;
};

export type AgentParsed =
  | { action: "ask_choice"; payload: AskChoicePayload }
  | { action: "ask_open"; payload: AskOpenPayload }
  | { action: "summarize"; payload: SummarizePayload };

export type StoredChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  kind: string;
  content: any;
  selected_option_key: string | null;
  user_other_text: string | null;
  created_at: string;
};

export type Comment = {
  id: string;
  author_nickname: string;
  body: string;
  created_at: string;
};

export type Activity = {
  id: string;
  actor_nickname: string;
  action: string;
  detail_json: string | null;
  created_at: string;
};

export type Delivery = {
  id: string;
  round: number;
  package_size: number;
  package_sha256: string;
  file_count: number;
  delivery_doc_md: string | null;
  notes: string | null;
  submitted_by_nickname: string;
  created_at: string;
  files: { name: string; size: number }[];
};
