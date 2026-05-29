# R7 Round 4 — Python backend

Scope: HEAD `a5c700e` (R7.3) on branch `fix/r6-hardening`. Fresh-eyes, read-only audit of all of `app/` (routers, services, models, auth, config, db, main). No code changed.

## Verdict: CLEAN (0 P1, 0 P2 new) — 3 carryover P2s re-confirmed, all correctly triaged as non-blocking

All 10 R7.3 fixes verified correct and complete. The fresh-eyes pass over the rest of the tree surfaced **no new P1 and no new P2**. The 3 carryover P2s from Round 3 (`_can_view_job` archived, `list_users?include_deleted`, health N+1) are still present and were re-assessed — **none escalate to P1**; all are UX/perf/marginal-disclosure within the explicitly-accepted LAN open-board trust model. The prior Round-3 P2-1 (`_reindex_state` running-flag leak) is **closed** by fix #9.

This is a genuinely clean round. Recommend it counts as a CLEAN ratification.

---

## R7.3 fix verification (10 items)

### 1. `auth.py` /identify — reverted 409, reuses existing account — **PASS**
`routers/auth.py:41-60` calls `get_or_create_user` then `issue_cookie`; no conflict/409/lockout path remains. `auth.py:227-244` `get_or_create_user` filters `nickname == n AND deleted_at IS NULL`: a tombstoned account cannot self-resurrect (returns a fresh row), and a recycled nickname onboards cleanly. `_validate_nickname` still reserves the `_deleted_` prefix and rejects control chars. No lockout path. Correct LAN-trust behavior.

### 2. `auto.py` `_run_and_finalize` + `_mark_auto_failed` no project filter — **PASS**
`routers/auto.py:155` and `:280` both `db.query(Requirement).filter(Requirement.id == req_id)` with **no** project-active join. AI jobs on a project archived mid-run now resolve (write delivery or mark failed) instead of stranding `ai_processing` + `running` forever. Cancel-aware guard (`if r.status == "ai_processing"`) preserved on both failure paths (`:240`, `:284`). Success path race-checks `r.status != "ai_processing"` → short-circuits the job to `succeeded`+skip (`:164-178`), so no perpetual spinner.

### 3. project_drive.py + projects.py — removed sync `rebuild_knowledge_index` — **PASS**
Grep over `app/` confirms the only direct `rebuild_knowledge_index` callers are: `main.py:62` (periodic, in `asyncio.to_thread`), `routers/knowledge.py:70` (admin-only on-demand endpoint), and the background worker `_reindex_project_in_background`. **Every** write path in `project_drive.py` (11 sites: create/patch/paste/copy/cut/delete/bulk-delete/restore/undo/comment) and `projects.py` (archive/restore/delete) uses `schedule_project_reindex(background, …)` as the last statement — no synchronous reindex on any write path. Self-DoS closed.

### 4. `meetings.confirm_meeting_insight` two-phase + idempotent fast-path — **PASS**
`routers/meetings.py:431-462`. `creates_requirement = kind in {new_requirement, requirement_change}`. `already_done = status != "pending" AND (not creates_requirement OR created_requirement_id is not None)`. Verified all cases:
- non-creating, confirmed/dismissed → fast-path 200 (correct).
- creating, confirmed + req-id set → fast-path 200 (work done).
- creating, confirmed + req-id NULL → falls through → CAS accepts the stranded retry (`status==pending OR (status==confirmed AND created_requirement_id IS NULL)`) → completes.
- creating, **dismissed** + NULL → `already_done` False BUT CAS matches neither branch → rollback → returns dismissed state. A dismissed insight cannot be resurrected by confirm (defensive layering between `already_done` and the CAS is correct).
The CAS-confirm is committed (`:466`) **before** requirement creation, so a non-IntegrityError mid-create rolls back + 500 (`:510-517`) leaving the insight durably `confirmed`+NULL — retryable. `dismiss` CAS only accepts `pending`, so the sole recovery path for a stranded confirm is retry-confirm (intended). Idempotent fast-path logic is correct.

### 5. `calendar.py` — removed `_visible_event` N+1, SQL filter complete — **PASS (for non-admins)**
`routers/calendar.py:88-102`. SQL filter enforces, per event: event-project active (or no project), AND requirement branch (`Requirement.id.isnot(None) AND req_project active AND (status NOT IN PRIVATE OR submitter==user OR claimed_by==user OR assigned_exists)`). Matches `can_view_requirement_record` for non-admins exactly; `assigned_exists` + `claimed_by` together cover `is_assigned_user`. Orphan-requirement events (req row deleted) are correctly hidden (`Requirement.id.isnot(None)` fails on the LEFT-JOIN NULL). **Private-status + project-active are both present** — filter complete. See "New findings → none / note" below for the only behavioral delta (admin no longer sees archived/private-req events in the calendar aggregate — a read-side *reduction*, not a leak; P2-grade UX at most, not flagged as a finding).

### 6. `decompositions.py` — `db.refresh(plan.requirement.project)` — **PASS**
`routers/decompositions.py:268-276`. After `analyze_requirement` (LLM, ~30s), it refreshes the requirement, then explicitly `db.refresh(plan.requirement.project)` guarded by `if plan.requirement.project is not None`, then re-runs `requirement_project_is_active`. SQLAlchemy `db.refresh()` does not cascade to relationships, so the explicit project refresh is exactly what's needed to detect an archive-during-LLM. Confirms to `dismissed` + fails the job on detection. Correct.

### 7. `delivery_upload.py` — per-chunk stat + inspect_zip + rmtree to_thread; `_Digest` removed — **PASS**
`routers/delivery_upload.py`. `_validate_and_merge_sync` (`:207-224`) now folds the per-chunk `.stat().st_size` validation into the threaded merge; called via `asyncio.to_thread` (`:226`). `inspect_zip_entries` in `to_thread` (`:236`). `shutil.rmtree(pdir, True)` in `to_thread` (`:328`). `_Digest` shim gone — `digest_hex` used directly (`:298`). The post-CAS work is fully exception-protected with `_rollback_status` (rollback-then-revert-UPDATE-then-commit) on `os.replace` failure, `IntegrityError`, and any other exception (`:287-324`) — no permanent `delivery_doc_pending` strand.

### 8. `schema_migrations.py` — 5 idempotent orphan-FK SET NULL UPDATEs — **PASS**
`services/schema_migrations.py:637-661`. Exactly 5: `project_drive_comments.draft_requirement_id`, `meeting_insights.target_requirement_id`, `meeting_insights.created_requirement_id`, `requirements.source_requirement_id`, `requirements.source_meeting_id`. Each `WHERE col IS NOT NULL AND col NOT IN (SELECT id FROM <parent>)`. Idempotent (re-run matches 0 rows). `NOT IN` is NULL-safe here because the subquery selects PKs (never NULL). SET-NULL only *removes* references → can never violate FK even with `PRAGMA foreign_keys=ON` (which the migration engine has, via the shared `db.py` connect listener). The ALTER-added columns carry no inline FK clause, so the migration itself introduces no enforceable constraint. Correct on fresh + legacy.

### 9. `schedule_project_reindex` — worker owns the `running` flag — **PASS (closes Round-3 P2-1)**
`routers/project_drive.py:235-283`. `schedule_project_reindex` now **only** calls `background.add_task(_reindex_project_in_background, project_id)` — it no longer touches `_reindex_state`. The worker acquires `running=True` under the lock as its first act (`:248-253`) and a `finally` (`:268-272`) unconditionally clears it. A request that raises after scheduling (BackgroundTask cancelled) can no longer leak a sticky `running=True`. Coalescing loop (consume `dirty`, re-run) is correct; `threading.Lock` is the right primitive (worker runs in the threadpool, scheduler on the request worker thread). The Round-3 leak window is **gone**.

### 10. `meetings.init_meeting_upload` — split 404 vs 403 — **PASS**
`routers/meetings.py:157-162`: `requirement_id` not in project → 404; found but `not can_view_requirement_record` → 403. No longer merged into a 400.

---

## Carryover P2 re-assessment

### P2-a: `_can_view_job` meeting branch missing `Project.archived` — `routers/jobs.py:35-39` — **stays P2, does NOT escalate**
Still filters only `Project.deleted_at`, not `archived`. Endpoint returns only `BackgroundJobOut` (status/progress/message) — no requirement/meeting content. Still requires an authenticated user who can see the (live) project. The meeting endpoint itself 404s on archived projects, so click-through fails gracefully. No auth bypass, no data exposure, no stuck state. UX inconsistency only.

### P2-b: `list_users?include_deleted=true` open to all — `routers/users.py:25,30-31` — **stays P2, does NOT escalate**
Any authenticated user can list soft-deleted users; the response carries `deleted_at` (`:53`). **Correction to a prior-round note**: `display_name` does NOT mask — it strips the `_deleted_<id8>_` prefix and appends `（已停用）` (`models.py:45-54`), so the *original nickname* IS revealed (e.g. `Alice（已停用）`) along with the deletion timestamp. Even so: in the LAN open-board model every live nickname/id/online-status/admin-flag is already enumerable to all users; there is no password/PII. This exposes deletion metadata + a name that was public anyway. No auth bypass, no escalation, no corruption. Hardening nicety (should be admin-gated). P2.

### P2-c: health endpoint N+1 — `routers/health.py:18-105` — **stays P2, does NOT escalate**
`_health_for_project` runs ~3 queries/project + a lazy `req.assignments` load per active requirement (`:62`), so `list_project_health` is O(N projects × M reqs). Pure read-only perf; acceptable for the ≤50-project LAN target. No correctness/security impact.

---

## New findings

**None at P1 or P2.**

Two sub-P2 observations recorded for completeness (NOT findings, no action required for the gate):
- **calendar admin read-reduction** (`routers/calendar.py:88-102`): the new pure-SQL filter has no admin override, so an admin no longer sees calendar events linked to archived-project / private-status requirements that the old `_visible_event`→`can_view_requirement_record` admin bypass surfaced. This is a *reduction* in admin visibility (safe direction), consistent with the event-project branch which never had an admin override. Sub-P2 UX, not a leak.
- **notifications dedupe-update skips `title[:256]` truncation** (`services/notifications.py:53` vs insert `:68`): harmless on SQLite (VARCHAR length unenforced) and all notification titles are short fixed strings. Would matter only on a future Postgres migration. Cosmetic.

---

## Coverage (what I read)

| Area | Files | Outcome |
|------|-------|---------|
| R7.3 #1 identify revert | `routers/auth.py`, `auth.py` (`get_or_create_user`, `_validate_nickname`) | PASS — no lockout, no self-resurrect |
| R7.3 #2 auto no-project-filter | `routers/auto.py` (full) | PASS — both paths resolve archived-mid-run, cancel-aware |
| R7.3 #3 no sync reindex | grep `app/`; `routers/project_drive.py`, `projects.py` (all write sites) | PASS — only periodic/admin/worker call rebuild |
| R7.3 #4 confirm two-phase | `routers/meetings.py:413-558` | PASS — all `already_done`/CAS/dismiss cases traced |
| R7.3 #5 calendar SQL filter | `routers/calendar.py`; `services/permissions.py`, `assignments.py` | PASS for non-admins; admin read-reduction noted |
| R7.3 #6 decomp project refresh | `routers/decompositions.py` (full) | PASS — relationship refresh correct |
| R7.3 #7 delivery to_thread | `routers/delivery_upload.py` (full) | PASS — stat+inspect+rmtree threaded; `_Digest` gone; rollback solid |
| R7.3 #8 orphan FK cleanup | `services/schema_migrations.py:1-75, 628-661`; `db.py` | PASS — idempotent, NULL-safe, FK-safe |
| R7.3 #9 reindex flag ownership | `routers/project_drive.py:223-283` | PASS — Round-3 P2-1 closed |
| R7.3 #10 init 404/403 split | `routers/meetings.py:144-179` | PASS |
| Requirements state machine | `routers/requirements.py` (transition map, CAS, delete_requirement) | clean — explicit allowed-map + CAS + cross-ref NULL on delete |
| Accept/revision CAS | `routers/deliveries.py` | clean — `delivered→accepted/revision` CAS + submitter check + writable-project |
| Claim/submit/sync CAS | `routers/sync.py` | clean — all CAS-gated + project-active |
| Chat slot claim | `routers/chat.py` | clean — atomic set claim, status re-check under fresh session |
| Notification lifecycle | `services/notifications.py`, `services/lifecycle.py` | clean — dedupe resets read_at+archived_at; actor.id in key; str.replace; soft-del filter; user-scoped publish |
| Drive write/manage gating | `routers/project_drive.py` (manage_item, paste/copy/cut/delete/restore/undo) | clean — owner_user_id-first, M1 copy check retained, cycle guards |
| Project lifecycle | `routers/projects.py` | clean — list filter mirrors `_require_owner` (owner_user_id-first) |
| Attachments + download | `routers/attachments.py` | clean — `Path(...).name` sanitize, user_id chunk owner, asset-view gate |
| Delivery zip / download | `routers/deliveries.py`, `services/delivery_doc.py` | clean — zip-slip + zip-bomb + ratio guards; download matches safe_name |
| AI sandbox | `services/auto_agent.py` (`_safe_path`, `_tool_run_command`) | clean — resolve()-containment (symlink-safe), shell=False, allowlist, no-dep-install |
| Knowledge search/index | `routers/knowledge.py`, `services/knowledge.py` | clean — admin-only reindex, per-user visibility intersect, two-pass cleanup |
| SSE push | `routers/push.py` | clean — stream_one gated, stream_me topic from auth id |
| Workspaces / planning / reminders / calendar mut | `routers/workspaces.py`, `planning.py`, `reminders.py`, `calendar.py` | clean — owner/assignee gating, soft-del user filter, project-active |
| Meetings background | `routers/meetings.py` (`_process_meeting`, finalize, list/get/patch) | clean — async loop, rollback-on-exc, `_require_project` archived filter |
| Voice / client-devices / users / comments / notifications router | respective files | clean — proxy auth, device user-scoping, admin-gated delete/admin, ownership checks |
| Background lifecycle | `main.py` (`_resume_stuck_jobs`, `_periodic_*`, `lifespan`, `_validate_runtime_config`) | clean — 15-min sweep cancel-safe, prod config validation |
| Auth paths | `auth.py` (cookie, worker-token, stream, client-device) | clean — soft-del + revoked filters on all read paths |
| Swallowed exceptions | grep `except: pass` across `app/` (8 sites) | clean — all best-effort (file stat/unlink, SSE publish fallback, ASR fallback); none mask a DB write |
| Residual nickname-auth | grep `owner_nickname ==` / `nickname == user` | clean — only the 2 documented legacy `owner_user_id IS NULL` fallbacks remain |
| Syntax sanity | `ast.parse` on all 11 R7.3-touched files | all parse OK |

### Gate note
Round 3 was "soft CLEAN" (1 P2, now closed). Round 4 is **CLEAN with zero new P1/P2**. The 3 standing P2s are stable, correctly triaged, and within the documented LAN open-board trust model. This is a clean ratification round.
