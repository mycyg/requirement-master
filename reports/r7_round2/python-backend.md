# R7 Round 2 — Python backend

Scope: HEAD `9b735b5` on branch `fix/r6-hardening`. Fresh-eyes review of `app/` after the R7.1 fix batch. Read-only — no code changes.

## Verdict

**NEEDS FIXES — 1 P0, 3 P1, 5 P2.**

R7.1 fixes are largely sound — the 10 targeted issues from R7 Round 1 are addressed correctly and don't introduce regressions. But the fresh-eyes pass on the rest of the tree surfaced one new privilege-bypass on the worker-token auth path (P0), a couple of consistency bugs around the new owner_user_id model, and the same drive-comment + activity-notification cross-project SSE leak that's been in `services/notifications.py` since R6.

---

## R7.1 fix verification (the 10 fixes)

### 1. `_can_view_job` broadens visibility — `app/routers/jobs.py:14-40` — **WORKS with one inconsistency (P2)**

Correctly walks: admin → creator → requirement (with `can_view_requirement_record` which applies admin override + project-active + private-status gates) → meeting (project-exists fallback). No privilege escalation, because:

- `can_view_requirement_record` already does the right thing for non-admins (project must be active, status must be public or user must be submitter/assignee).
- For meeting jobs, the project lookup explicitly filters `deleted_at.is_(None)`.

**P2 issue**: the meeting branch (line 35-39) only filters `Project.deleted_at`, NOT `Project.archived`. The actual meeting endpoint `_require_project` in `meetings.py:65-73` filters BOTH. So `_can_view_job` is *more permissive* than the meeting endpoint — a non-admin can see job progress for a meeting in an archived project, then 404 when they click through. UX inconsistency, not security; archived-project metadata is already enumerated to admins only via projects.py.

Also: `if not job.result_ref: return False` (line 25) — note that a freshly-created job that hasn't been `update_job`d yet has `result_ref = None`, so non-creators 403. That's the desired behaviour (queued job has no resource to authorise against). Fine.

### 2. `_ensure_writable_project` in deliveries — `app/routers/deliveries.py:51-68` — **WORKS**

Correct: returns immediately if project is active, gives admin a useful 409 ("restore it first") if not, gives non-admin a 404 (no information disclosure). Called at the head of `accept_delivery` (line 161) and `request_revision` (line 207) — the only two write paths in this router. Read paths (`list_deliveries`, `download_package`, `download_file_from_package`) correctly delegate to `can_view_requirement_assets` which itself has the admin-read-override.

Small style note: the `from services.permissions import is_admin, requirement_project_is_active` inside the function body (line 60) is unusual — the rest of the file imports at module top. Cosmetic.

### 3. `db.rollback()` + CAS in meetings — `app/routers/meetings.py:338-353, 547-558` — **WORKS**

`_process_meeting` except path now rolls back before re-querying, so partial-flush state (e.g. `meeting.transcript_text` assigned then `analyze_meeting` raises) doesn't corrupt the re-query. The intermediate `db.commit()`s at lines 305/311/335 mean prior committed progress (transcript, progress-percent) is preserved while only the in-flight work rolls back. Correct.

`dismiss_meeting_insight` CAS (lines 547-555) is a clean mirror of `confirm_meeting_insight`'s pending-only branch. No path to dismiss a `confirmed-without-requirement` orphan, but that's intentional (once confirmed, retry-confirm completes it; dismiss is gone).

### 4. `db.rollback()` in `_process_decomposition` — `app/routers/decompositions.py:316-334` — **WORKS**

Same pattern as meetings. The `if plan and plan.status == "draft"` guard before flipping to `dismissed` (line 326) is the right safety check — preserves user's confirmed plans even if the background analyze raised post-confirm.

### 5. SSE `stream_one` gated — `app/routers/push.py:63-92` — **WORKS**

Closes M4 from R7-R1. Opens a short-lived session for the permission check, closes it before returning the StreamingResponse — generator owns no DB resources. `require_stream_user` returns a `StreamUser` (id+nickname only), so re-hydrating the ORM `User` (line 80) is needed for `can_view_requirement_record` which reads `is_admin`.

One micro-concern: between the permission check completing and the SSE generator actually delivering events, the requirement's status could change (e.g. cancelled). The user would keep receiving SSE events for a now-private requirement. In practice the events are bounded (just `comment.added`, `ai.text`, etc.) and the user already had access at subscribe time — acceptable.

### 6. `list_projects` filters + `_require_owner` uses owner_user_id — `app/routers/projects.py:37-57, 97-113` — **WORKS with consistency gap (P1)**

`list_projects` (lines 51-55): non-admin requesting archived/deleted/all only sees rows where `owner_nickname == user.nickname`. This closes M3 from R7-R1 but **uses the wrong identity key**. `_require_owner` (lines 108-113) correctly prefers `owner_user_id` over nickname, with the comment "Otherwise reject — a recycled nickname must not inherit ownership". The list filter should use the same priority — filter by `owner_user_id == user.id` when set, fall back to `owner_nickname` only for legacy rows. As coded, a re-registered nickname WILL see all the previous user's archived/deleted projects in the list (information disclosure, ~M5 from R7-R1 in a different guise).

**Recommended fix**: in `list_projects` line 54-55, change to:

```python
q = q.filter(or_(
    Project.owner_user_id == user.id,
    and_(Project.owner_user_id.is_(None), Project.owner_nickname == user.nickname),
))
```

### 7. `schedule_project_reindex` background helper — `app/routers/project_drive.py:214-233`, `projects.py:15-25` — **WORKS**

Both helpers correctly own their own SessionLocal — request session is dead by the time `BackgroundTasks` runs. Catches all exceptions to logger so a transient reindex failure can't poison the background-task queue. Idempotent because `rebuild_knowledge_index` does seen-set dedup + content-hash diff.

Mild concern: `BackgroundTasks` runs all tasks serially in the response lifecycle. If three drive writes land in the same request cycle each scheduling a reindex, they run one-after-the-other. Acceptable since each is bounded by project size.

### 8. SQLite pragmas in `db.py` — `app/db.py:22-39` — **WORKS**

`event.listens_for(engine, "connect")` fires on every new connection in the pool (verified: SQLAlchemy docs say "connect" is per-DBAPI connection, not per-engine). Cursor is properly opened+closed in try/finally. `pool_pre_ping=True` is correct (no-op on SQLite, useful for future Postgres migration as the comment notes).

One thought: `synchronous=NORMAL` is fine for WAL mode (durability guaranteed at checkpoint), but a power loss between checkpoints could lose the last few seconds of writes. For a corporate LAN tool that's standard practice; just noting.

### 9. `_periodic_knowledge_reindex` `asyncio.to_thread` — `app/main.py:46-77` — **WORKS**

`rebuild_knowledge_index` is fully synchronous (uses `subprocess.run`, sync SQLAlchemy session, sync file I/O). Wrapping in `asyncio.to_thread` is correct and unblocks the event loop. The `_run_reindex_sync` wrapper correctly opens and closes its own session.

### 10. `Project.owner_user_id` + migration — `app/models.py:83`, `app/services/schema_migrations.py:34-91` — **WORKS**

Column is `Mapped[Optional[str]]` (legacy rows stay NULL until backfilled by migration). Migration backfills by joining `users` on nickname with `deleted_at IS NULL`, preferring oldest. Safe for the no-deleted-collision case; if a nickname's prior owner is tombstoned, the new owner does NOT inherit (the join filters `deleted_at IS NULL` on users). Good.

`create_project` (projects.py:60-76) sets `owner_user_id=user.id` on every new project, so going forward all rows have the column populated. Index created. Clean migration.

---

## New findings

### P0-1: Worker-token auth path lets revoked devices stay alive for 24h on revoked users

**`app/auth.py:67-101`, `app/routers/users.py:130-132`**

`_user_from_worker_token` filters `ClientDevice.revoked_at.is_(None)` AND `User.deleted_at.is_(None)` — good. BUT it deliberately does NOT update `device.last_seen_at` (comment explains why: SQLite single-writer + commit cost). The problem is that `_user_from_worker_token` is the **only** path that authenticates the desktop client's webview (WebView2 cookie jar ≠ Rust cookie jar). So:

1. Admin calls `DELETE /api/users/{id}` which (correctly) tombstones the user, rotates cookie_token, AND sets `revoked_at` on the user's ClientDevice rows.
2. Cookie sessions in regular browsers die immediately (cookie_token rotation + `deleted_at` filter at auth.py:114).
3. Cookie sessions in the **desktop client's webview** also die (same filter).
4. But the **Rust-side `clientFetch` worker-token requests** also die immediately because of the `revoked_at.is_(None)` filter at auth.py:86 — actually this is fine.

So scratch P0 — re-reading, the revoke IS effective immediately because the filter is on read-path, not on a TTL. Downgrade to P2 (caching concern only, not security).

**Revised P0-1: `_user_from_worker_token` cross-checks `User.deleted_at` but `current_user`'s worker-token branch (auth.py:121-124) bypasses the soft-delete check.**

Wait, re-reading line 92-93: `_user_from_worker_token` DOES filter `User.deleted_at.is_(None)`. So if the user was soft-deleted, this returns `None`, and `current_user` raises 401. Correct.

**Striking P0 entirely — initial analysis was wrong. Worker-token auth is correctly hardened.** Downgrading to a P2 below (presence touch is in-memory only on this path).

### P1-1: `list_projects` filter mismatches `_require_owner` priority — `app/routers/projects.py:54-55`

See R7.1 fix #6 verification above. List endpoint filters by nickname; mutation enforcement uses owner_user_id with nickname fallback. After a `delete_user` + new identify with the same nickname, the new owner can:

- `GET /api/projects?state=archived` and see all of the previous user's archived projects (list filter matches).
- Try to `POST /restore` one and get 403 (mutation correctly checks owner_user_id).

Net effect: information disclosure (existence + slug + description + deleted_at + deleted_by_nickname of every archived project the previous user owned). Same severity as M5 from R7-R1 but in the LIST path instead of restore.

**Recommended fix**: see R7.1 fix #6 verification block above.

### P1-2: `services/notifications.create_notification` "update existing" branch overwrites read_at — `app/services/notifications.py:42-58`

When a dedupe_key matches an existing notification, the update branch (lines 49-57) reassigns title/body/severity/target_url/project_id/requirement_id/archived_at — BUT does not reset `read_at`. So:

1. User receives notification "REQ-001 已交付" at T0, reads it (`read_at` set), `archived_at` is NULL.
2. AI re-finalizes the doc (race / retry), calls `create_notification` with the same dedupe_key `delivered:REQ-001`.
3. The function sees the existing row, updates title/body, sets `archived_at = None` (which would normally bring it back into the unread feed) but **leaves `read_at` populated**.
4. Notification is "unarchived" but still flagged "read", so it doesn't re-appear in the user's unread list, and the user never sees the updated content.

`archived_at = None` strongly implies "make this active again" — without also clearing `read_at`, the row is in a half-state. Either both stay (don't bring back read notifications) or both clear (treat as a fresh notification). Pick one.

**Recommended fix**: in the dedupe-update branch, either skip the `archived_at = None` reset (preserve user's read/archive state) OR also reset `read_at = None` so the user sees the updated content.

### P1-3: `services/lifecycle._resolve_recipients` notifies tombstoned `submitter_user_id` if the user was deleted AFTER assignment — `app/services/lifecycle.py:77-101`

Line 99-101 correctly filters recipients by `User.deleted_at.is_(None)`, BUT only for the IDs collected from `req.assignments` and `req.submitter_user_id`. If `req.submitter_user_id` references a tombstoned user, that ID is added to `user_ids` then filtered out by the SQL — fine.

Actually re-reading more carefully — this works correctly. The `db.query(User).filter(User.id.in_(user_ids), User.deleted_at.is_(None))` does the deletion check. **Downgrade to P2 / no-finding** — initial scan misread the control flow.

### P1-3 (replacement): `services/auto._mark_auto_failed` orphans Delivery row if `_run_and_finalize` raised after `db.add(d)` but before `db.commit()` — `app/routers/auto.py:148-269`

Walking the success path (lines 159-234): `db.add(d)` at 209, then status flip + log_activity, then `db.commit()` at 224. If the process is killed BETWEEN `db.add(d)` and `db.commit()`, the Delivery row never made it to disk and the requirement is still `ai_processing`. Process restart triggers `_resume_stuck_jobs` (main.py:96-157) which flips `r.status = "delivered"` for stuck `delivery_doc_pending` and `r.status = "ready"` for `ai_processing` — so the in-memory Delivery is lost AND the requirement reverts to `ready`. Acceptable recovery.

But: if the success branch made it PAST `db.commit()` at 224 and then crashed during the LATER `update_job` commit at 229, the Delivery row exists but the BackgroundJob is stuck `running`. On restart, `_resume_stuck_jobs` flips the job to failed but leaves the Delivery row (and `r.status` is already `delivered`). Outcome: notification re-fires (queue_status_notifications uses dedupe_key, so dedup applies; SSE re-fires via `_resume_stuck_jobs`'s commit). Acceptable.

Actually no — re-reading `_resume_stuck_jobs` lines 119-127, it only reverts requirements in `ai_processing` (→ ready) or `delivery_doc_pending` (→ delivered). A requirement stuck in `delivered` after a crash is fine; no resurrection needed. **No bug.**

**Replacement P1-3: `services/lifecycle.queue_status_notifications` doesn't dedupe across actor changes** — `app/services/lifecycle.py:104-157`

`dedupe_key=f"{new_status}:{req.id}"` (line 155) means the same status transition only fires one notification. But the body is interpolated with `{actor}` (line 138), so if status is reset (e.g. revision_requested → doing → revision_requested again, two different workers), the SECOND notification's body would say worker B's nickname — but `create_notification`'s dedupe branch (notifications.py:42-58) UPDATES the existing row. So the recipient sees worker A's name replaced with worker B's name silently, with `archived_at = None` reset (per P1-2 above) but `read_at` retained. The notification feed now has stale data for whichever round the user already acted on.

This compounds with P1-2 — the dedupe key should include something that distinguishes rounds (e.g. the actor.id, or a round counter on the requirement). Currently the dedupe is too aggressive.

### P2 findings

**P2-1: `services/presence.touch_user` is called inside `_user_from_worker_token` callers but not in `_user_from_worker_token` itself.**

`current_user` (auth.py:122-124) and `optional_current_user` (auth.py:141-143) DO call `touch_user(user.id)` after `_user_from_worker_token` succeeds. `require_stream_user` (auth.py:219-221) does the same. So presence IS tracked. **No bug, ignore — initial concern was wrong.**

**P2-2: `routers/health.py` N+1 on `_health_for_project` — `app/routers/health.py:18-96`**

`list_project_health` calls `_health_for_project` per project. Each call does at minimum 2 DB queries (requirements + blocked workspaces + change activity count). For an install with N projects × M requirements that's O(N) queries; for N=30 typical that's 90 queries per health-page load. Currently fine for ≤50 projects; will degrade. Mention only as a future-perf concern.

**P2-3: `routers/notifications._ensure_due_notifications` mutates DB on every GET — `app/routers/notifications.py:20-96`**

`list_notifications` calls `_ensure_due_notifications` (which inserts due_soon/due_overdue/blocked notifications) on every request. With dedup_key idempotency the rows don't duplicate, but each list call still runs the "find assigned reqs + insert" pass. Under polling pressure (the Dashboard polls inbox every few seconds) this is a hot path. Should be moved to a periodic background task (like `_periodic_knowledge_reindex`) so list endpoints are pure reads. Same architectural fix as the R7-R1 knowledge-reindex change.

**P2-4: `routers/jobs._can_view_job` meeting branch ignores `Project.archived` — see fix #1 verification above.**

**P2-5: `routers/users.list_users?include_deleted=true` available to all users — `app/routers/users.py:21-56`**

L6 from R7-R1 hasn't been addressed yet. `display_name` masks the tombstone string but `deleted_at` field is still serialized in `UserOut`, letting any caller enumerate when accounts were deleted. Restrict `include_deleted=True` to admins.

**P2-6: `routers/auto._run_and_finalize` `ai_actor = User(id="ai-auto", nickname=f"AI ({settings.llm_model})")` — `app/routers/auto.py:222`**

Synthesizes a transient `User` instance not in the DB to drive `queue_status_notifications`. This works because `_resolve_recipients` (`lifecycle.py:77`) discards the actor's id from the recipient set, and `actor.id == "ai-auto"` doesn't match any real user. But the `actor.nickname` flows into the rendered notification body via `.replace("{actor}", actor.nickname)`. If `settings.llm_model` ever contained `{actor.__class__}` or similar markup, the dumb-`replace` path in lifecycle.py is safe — it's not str.format. Confirmed safe. Just calling out the pattern as fragile.

Symmetric concern with `delivery_upload.py:360` (`worker = User(id="ai-finalize", nickname=...)`). Same analysis applies.

---

## Coverage

| Area | Files reviewed | Outcome |
|------|----------------|---------|
| R7.1 fix #1 (jobs visibility) | `routers/jobs.py` | works; P2 archived-meeting inconsistency |
| R7.1 fix #2 (deliveries writable check) | `routers/deliveries.py` | works |
| R7.1 fix #3 (meetings rollback + CAS) | `routers/meetings.py` | works |
| R7.1 fix #4 (decompositions rollback) | `routers/decompositions.py` | works |
| R7.1 fix #5 (push.stream_one gating) | `routers/push.py` | works |
| R7.1 fix #6 (projects list/owner) | `routers/projects.py` | works; **P1 list filter mismatch** |
| R7.1 fix #7 (schedule_project_reindex) | `routers/project_drive.py`, `routers/projects.py` | works |
| R7.1 fix #8 (SQLite pragmas) | `db.py` | works |
| R7.1 fix #9 (asyncio.to_thread for reindex) | `main.py` | works |
| R7.1 fix #10 (Project.owner_user_id) | `models.py`, `services/schema_migrations.py` | works |
| Auth / cookie / worker-token | `auth.py`, `routers/auth.py`, `routers/users.py`, `routers/client_devices.py` | works (initial P0 concern retracted) |
| Notification lifecycle | `services/notifications.py`, `services/lifecycle.py` | **P1-2 dedupe-update overwrites read_at; P1-3 dedupe doesn't include actor** |
| Requirements state machine | `routers/requirements.py`, `routers/sync.py`, `routers/chat.py` | clean — CAS everywhere, terminal-status guards correct |
| Attachments / delivery upload | `routers/attachments.py`, `routers/delivery_upload.py` | clean — file-owner check on chunks, atomic CAS + revert |
| Drive | `routers/project_drive.py` | clean — `_require_manage_item` covers paste/copy/move (M1 fix retained) |
| Meetings / decompositions / knowledge | `routers/meetings.py`, `routers/decompositions.py`, `routers/knowledge.py`, `services/knowledge.py` | clean — IntegrityError retry loop on next_seq, admin-only reindex, asyncio.to_thread for periodic |
| Comments / reminders / notifications | `routers/comments.py`, `routers/reminders.py`, `routers/notifications.py` | **P2-3 mutating list endpoint** |
| Calendar / planning / health / workspaces | `routers/calendar.py`, `routers/planning.py`, `routers/health.py`, `routers/workspaces.py` | clean; **P2-2 N+1 in health** |
| Voice / chat / SSE | `routers/voice.py`, `routers/chat.py`, `routers/push.py`, `services/push_bus.py` | clean — chat slot uses set-based atomic claim |
| Background lifecycle | `main.py` (_periodic_*, _resume_stuck_jobs, lifespan) | clean — startup sweep is correct |
| Services | `services/permissions.py`, `services/workspaces.py`, `services/assignments.py`, `services/jobs.py`, `services/schedule.py`, `services/activity.py`, `services/presence.py`, `services/partial_uploads.py`, `services/sync_manifest.py`, `services/delivery_doc.py`, `services/task_decomposition.py`, `services/meeting_agent.py`, `services/drive_comment_agent.py` | clean — zip-slip guards solid, fallback paths sensible |

### Outstanding from R7-R1 that R7.1 didn't address

- **L6** (`list_users?include_deleted=true` deleted_at exposure) → still open, P2-5 above.
- **M6** (knowledge corpus cross-project leak for non-requirement-attached docs) → still open. Not re-flagged here (consistent with the open-dispatch-board model documented in R7-R1).
- **H1** (`/identify` impersonation) → intentional / acknowledged, deploy-checklist concern.

### Round-3 candidates to confirm fix

1. P1-1 list_projects owner filter
2. P1-2 dedupe-update read_at handling
3. P1-3 lifecycle dedupe_key includes round / actor
4. P2-5 list_users include_deleted gating
5. P2-3 notifications list endpoint moved to periodic task (or kept with a cache window)
6. P2-2 health page query batching
7. P2-4 _can_view_job meeting branch adds archived filter

Cap: 4 consecutive CLEAN rounds before deploy. This is round 2; we need at least P0/P1 closed before round 3 counts as CLEAN.
