export type Identity = { id: string; nickname: string; created: boolean };

export type Project = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  owner_nickname: string;
  archived: boolean;
  created_at: string;
};

export type Requirement = {
  id: string;
  code: string;
  project_id: string;
  project_slug: string;
  submitter_nickname: string;
  title: string | null;
  raw_description: string | null;
  summary_md: string | null;
  status:
    | "draft" | "clarifying" | "ready" | "claimed" | "doing" | "ai_processing"
    | "delivered" | "revision_requested" | "accepted" | "cancelled";
  priority: string;
  start_at: string | null;
  due_at: string | null;
  claimed_at: string | null;
  done_at: string | null;
  delivered_at: string | null;
  accepted_at: string | null;
  sync_state: string;
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
