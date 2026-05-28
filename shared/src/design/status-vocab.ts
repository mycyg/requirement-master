/**
 * Centralized vocabulary for requirement status badges.
 * Single source of truth for both web and Tauri client.
 */
import type { Requirement } from "../api/types";

export type StatusTone =
  | "neutral"
  | "info"
  | "warn"
  | "accent"
  | "accent-2"
  | "success"
  | "error";

export type StatusKey = Requirement["status"];

export type StatusEntry = {
  /** Visible Chinese label */
  label: string;
  /** Semantic tone — drives the badge color */
  tone: StatusTone;
  /** Whether the badge should pulse (long-running phases) */
  pulse?: boolean;
};

export const STATUS_VOCAB: Record<StatusKey, StatusEntry> = {
  draft:                 { label: "草稿",              tone: "neutral" },
  clarifying:            { label: "沟通中",            tone: "info" },
  summary_ready:         { label: "待你投递",          tone: "warn" },
  ready:                 { label: "等接单",            tone: "warn" },
  claimed:               { label: "已接单",            tone: "info" },
  doing:                 { label: "进行中",            tone: "accent" },
  ai_processing:         { label: "AI 助理处理中",     tone: "accent-2", pulse: true },
  delivery_doc_pending:  { label: "AI 助理写交付文档中", tone: "info", pulse: true },
  delivered:             { label: "已交付",            tone: "success" },
  revision_requested:    { label: "等你重做",          tone: "error" },
  accepted:              { label: "已完成",            tone: "success" },
  cancelled:             { label: "已取消",            tone: "neutral" },
};

export function statusLabel(key: string | null | undefined): string {
  if (!key) return "";
  const entry = STATUS_VOCAB[key as StatusKey];
  return entry ? entry.label : key;
}

export function statusTone(key: string | null | undefined): StatusTone {
  if (!key) return "neutral";
  const entry = STATUS_VOCAB[key as StatusKey];
  return entry ? entry.tone : "neutral";
}

/**
 * Status progress (0-100) for showing a generic progress bar
 * even when the workspace has no explicit progress_percent yet.
 */
export const STATUS_PROGRESS: Record<StatusKey, number> = {
  draft: 0,
  clarifying: 8,
  summary_ready: 18,
  ready: 25,
  claimed: 30,
  doing: 55,
  ai_processing: 60,
  delivery_doc_pending: 80,
  delivered: 90,
  revision_requested: 70,
  accepted: 100,
  cancelled: 0,
};
