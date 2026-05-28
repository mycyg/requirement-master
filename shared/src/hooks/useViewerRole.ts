/**
 * Centralised role detection for a requirement view. Keeps every site
 * (TaskDetail, ActionRail, Hub cards) in agreement about what the viewer
 * can do — previously each component re-derived this and they drifted.
 *
 * A viewer can hold multiple roles on the same requirement (admin who
 * posted it; submitter who self-assigned). The single-role `viewerRole`
 * returns the highest-priority one (admin > submitter > assignee >
 * observer), but the boolean predicates let callers ask precisely:
 * "am I *also* the assignee?" without losing the admin flag.
 */
import type { Requirement } from "../api/types";

export type ViewerRole = "submitter" | "assignee" | "admin" | "observer";

export interface ViewerLike {
  id: string;
  is_admin?: boolean | null;
}

export function isSubmitter(req: Requirement, me: ViewerLike | null): boolean {
  return !!me && req.submitter_user_id === me.id;
}

export function isAssignee(req: Requirement, me: ViewerLike | null): boolean {
  if (!me) return false;
  if ((req.assignees ?? []).some((a) => a.user_id === me.id)) return true;
  if (req.claimed_by_user_id && req.claimed_by_user_id === me.id) return true;
  return false;
}

export function isAdmin(me: ViewerLike | null): boolean {
  return !!me?.is_admin;
}

/** Highest-priority single role. Useful for UI labels / debugging. */
export function viewerRole(req: Requirement, me: ViewerLike | null): ViewerRole {
  if (!me) return "observer";
  if (me.is_admin) return "admin";
  if (isSubmitter(req, me)) return "submitter";
  if (isAssignee(req, me)) return "assignee";
  return "observer";
}
