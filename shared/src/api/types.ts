export type Identity = { id: string; nickname: string; created: boolean };

export type UserOption = {
  id: string;
  nickname: string;
  is_online?: boolean;
  last_seen_at?: string | null;
  availability_status?: "free" | "busy" | "custom";
  availability_text?: string | null;
  availability_updated_at?: string | null;
};

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
  deleted_at: string | null;
  deleted_by_nickname: string | null;
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

export type DriveManifestItem = {
  id: string;
  parent_id: string | null;
  path: string;
  name: string;
  kind: "file" | "folder";
  size_bytes: number | null;
  mime: string | null;
  sha256: string | null;
  version_no: number | null;
  updated_at: string;
  deleted_at: string | null;
  download_url: string | null;
};

export type DriveManifest = {
  project_id: string;
  project_slug: string;
  cursor: string;
  items: DriveManifestItem[];
};

export type DriveComment = {
  id: string;
  project_id: string;
  folder_id: string | null;
  author_nickname: string;
  body: string;
  status: "pending_llm" | "posted" | "draft_created" | "review_failed";
  llm_kind: string | null;
  llm_reason: string | null;
  draft_requirement_id: string | null;
  created_at: string;
  updated_at: string;
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
  estimate_hours: number | null;
  estimate_confidence: "low" | "medium" | "high" | null;
  planning_note: string | null;
  start_at: string | null;
  due_at: string | null;
  source_meeting_id: string | null;
  source_requirement_id: string | null;
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

export type BackgroundJob = {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress_percent: number;
  message: string | null;
  result_ref: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type WorkspaceItem = {
  id: string;
  workspace_id: string;
  title: string;
  status: "todo" | "doing" | "done";
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type ProgressUpdate = {
  id: string;
  requirement_id: string;
  workspace_id: string | null;
  actor_nickname: string;
  kind: string;
  body: string;
  phase: string | null;
  progress_percent: number | null;
  created_at: string;
};

export type RequirementWorkspace = {
  id: string;
  requirement_id: string;
  user_id: string;
  nickname: string;
  phase: string;
  progress_percent: number;
  status_note: string | null;
  blocked_reason: string | null;
  items: WorkspaceItem[];
  updates: ProgressUpdate[];
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

export type ScheduleEvent = {
  id: string;
  project_id: string | null;
  requirement_id: string | null;
  title: string;
  description: string | null;
  event_type: "custom" | "requirement_due";
  start_at: string | null;
  end_at: string;
  participant_user_ids: string[];
  created_by_nickname: string;
  created_at: string;
  updated_at: string;
};

export type Reminder = {
  id: string;
  kind: string;
  title: string;
  project_slug: string | null;
  requirement_id: string | null;
  requirement_code: string | null;
  due_at: string;
  status: string;
  minutes_until_due: number;
  phase: string | null;
  progress_percent: number | null;
  blocked_reason: string | null;
};

export type MeetingInsight = {
  id: string;
  meeting_id: string;
  kind: "new_requirement" | "requirement_change" | "normal_note";
  title: string;
  description: string;
  target_requirement_id: string | null;
  confidence_reason: string | null;
  status: "pending" | "confirmed" | "dismissed";
  created_requirement_id: string | null;
  created_at: string;
  updated_at: string;
};

export type Meeting = {
  id: string;
  project_id: string;
  requirement_id: string | null;
  title: string;
  audio_filename: string;
  audio_mime: string | null;
  audio_size_bytes: number;
  transcript_text: string | null;
  minutes_md: string | null;
  status: "processing" | "ready" | "failed";
  job_id: string | null;
  uploaded_by_nickname: string;
  insights: MeetingInsight[];
  created_at: string;
  updated_at: string;
};

export type MeetingUploadInit = {
  upload_id: string;
  chunk_size: number;
};

export type RequirementAcceptanceItem = {
  id: string;
  requirement_id: string;
  title: string;
  description: string | null;
  status: string;
  sort_order: number;
  source_plan_id: string | null;
  created_at: string;
  updated_at: string;
};

export type TaskPlanItem = {
  id: string;
  plan_id: string;
  title: string;
  description: string | null;
  item_type: "task" | "risk" | "acceptance";
  suggested_user_id: string | null;
  suggested_nickname: string | null;
  estimate_hours: number | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type TaskPlan = {
  id: string;
  requirement_id: string;
  stage: "dispatch" | "worker";
  status: "draft" | "confirmed" | "dismissed";
  summary: string | null;
  risks: string | null;
  job_id: string | null;
  created_by_nickname: string;
  target_user_id: string | null;
  target_nickname: string | null;
  confirmed_at: string | null;
  items: TaskPlanItem[];
  created_at: string;
  updated_at: string;
};

export type KnowledgeSearchHit = {
  document_id: string;
  project_id: string | null;
  requirement_id: string | null;
  source_type: string;
  source_id: string;
  title: string;
  source_url: string;
  line_no: number;
  snippet: string;
};

export type KnowledgeAskRun = {
  id: string;
  question: string;
  project_id: string | null;
  status: "running" | "succeeded" | "failed";
  job_id: string | null;
  answer_md: string | null;
  citations: KnowledgeSearchHit[];
  trace: Record<string, any>[];
  created_at: string;
  updated_at: string;
};

export type WorkloadRequirement = {
  id: string;
  code: string;
  title: string | null;
  project_id: string;
  project_slug: string;
  status: string;
  due_at: string | null;
  estimate_hours: number | null;
  progress_percent: number | null;
  blocked_reason: string | null;
};

export type UserWorkload = {
  user_id: string;
  nickname: string;
  is_online: boolean;
  availability_status: "free" | "busy" | "custom";
  availability_text: string | null;
  task_count: number;
  estimate_hours: number;
  capacity_hours: number;
  load_percent: number;
  overdue_count: number;
  blocked_count: number;
  due_this_week_count: number;
  requirements: WorkloadRequirement[];
};

export type Notification = {
  id: string;
  type: string;
  severity: "normal" | "high" | "urgent" | string;
  title: string;
  body: string | null;
  target_url: string | null;
  project_id: string | null;
  requirement_id: string | null;
  read_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectHealth = {
  project_id: string;
  project_name: string;
  project_slug: string;
  score: number;
  risk_level: "healthy" | "watch" | "risk" | string;
  risks: string[];
  overdue_count: number;
  blocked_count: number;
  unclaimed_count: number;
  due_soon_count: number;
  revision_count: number;
  change_count: number;
  active_count: number;
  accepted_count: number;
  throughput_30d: number;
  avg_cycle_hours: number | null;
  load_hours: number;
};
