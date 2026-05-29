# R7 Round 5 — Python backend

Scope: HEAD `8d30bc7` (R7.4 + gitignore) on branch `fix/r6-hardening`. Read-only audit. The R7.4 commit (`c9d5e89`) touched exactly 4 Python files (`app/services/notifications.py`, `app/routers/projects.py`, `app/routers/project_drive.py`, `app/routers/calendar.py`); the rest of the diff is TS/screenshots/reports. No code changed by this review.

## Verdict: CLEAN (0 P1, 0 P2 new)

All 3 R7.4 changes verified correct and complete. The fresh full-tree pass over the rest of `app/` surfaced **no new P1 and no new P2**. The 3 standing carryover P2s (`_can_view_job` archived, `list_users?include_deleted`, health N+1) are unchanged and re-confirmed — none escalate. This is Round 1 of the fresh 4-CLEAN streak and it is a genuine CLEAN.

---

## R7.4 regression check (3 items)

### 1. `notifications.create_notification` change-detection guard — **PASS (a, b, c all verified)**
`services/notifications.py:48-90`.

- **(a) genuinely-changed content still resurfaces.** `content_changed` compares `title[:256]`, `body`, `severity`, `target_url`, `project_id`, `requirement_id` against the existing row. Any real change → falls through to the resurface block (clears `read_at`/`archived_at`, bumps `updated_at`, `db.flush()`). Traced the dynamic-content callers:
  - `_ensure_due_notifications` (`routers/notifications.py:38-86`): `due_soon`/`due_overdue` bodies embed the formatted `due_at`; reschedule → body changes → resurfaces. The `due:{id}:soon:{date}` / `:overdue:{day}` keys are date-stamped, so a new day mints a new row anyway. `workspace_blocked` body is `blocked_reason[:300]`; edited reason → resurfaces.
  - `requirements.update_assignees` (`:462`, key `assigned:{id}:{uid}`) body differs from the create-time body → resurfaces on real re-assignment; identical re-fire correctly no-ops.
  - `requirements.update_requirement_schedule` (`:505`, key `due_changed:{id}:{uid}:{due_iso}`) bakes the new DDL into the key → distinct DDL = distinct row.
  - lifecycle/decompositions/knowledge keys are event-unique (`{status}:{id}:{actor}`, `decomposition:{plan}`, `knowledge:{run}`) so the dedupe path is effectively only hit by genuine retries — correct to no-op.
- **(b) early-return skips `db.flush()` — safe.** On `not content_changed` the existing row is **unmodified**, so there is nothing pending to flush. Every live caller either discards the return value and then issues its own `db.commit()` (which auto-flushes), or (decompositions/knowledge) assigns the row and later `publish_notification`s it after a `commit()`. No caller reads a freshly-assigned `.id` off the dedupe path (the row already exists with an id). No persistence is skipped.
- **(c) callers behave.** Verified all 8 live call-sites: `lifecycle.py:145` (collected, published post-commit), `decompositions.py:300`, `knowledge.py:131`, `requirements.py:157/462/505`, `notifications.py:38/51/75`. `notify_users` has **no** callers (dead helper — pre-existing, not a regression). Re-publishing an unchanged existing row over SSE is idempotent and harmless.
- Title-truncation symmetry fixed as a side benefit: insert truncates `title[:256]` and the guard now compares against `title[:256]`, so a long title no longer spuriously re-triggers each poll. (Resolves the Round-4 cosmetic sub-P2 note.)

### 2. `projects._require_owner` / `list_projects` + `project_drive._can_manage_project` — owner_user_id-only — **PASS (a, b, c all verified)**
- **(a) normal owner still manages.** `create_project` (`projects.py:64`) always sets `owner_user_id=user.id`; `_require_owner` (`:104`) returns OK when `p.owner_user_id == user.id`; `_can_manage_project` (`project_drive.py:100`) returns True on the same. Active owners unaffected.
- **(b) no legitimate active owner now 403s.** All ownership gating funnels through these two helpers — grep confirms `owner_nickname` is now **display-only** (`_to_out`, knowledge corpus text, model column). The 3 `_require_owner` call-sites (archive/restore/delete `projects.py:123/143/162`) and the drive `_require_manage_item` (`project_drive.py:103-107`) are the only consumers. `_require_manage_item` still grants the file's own `created_by_user_id`/`deleted_by_user_id`, so a contributor on a NULL-owner project keeps managing their own items.
- **(c) boot backfill guarantees it.** `schema_migrations.py:80-90` runs `UPDATE projects SET owner_user_id = (SELECT u.id FROM users u WHERE u.nickname = projects.owner_nickname AND u.deleted_at IS NULL ORDER BY u.created_at ASC LIMIT 1) WHERE owner_user_id IS NULL`. Invoked from `main.py:188` inside `lifespan` **before** `yield` — so every active-owner row is backfilled before the first request. A residual NULL means no active user holds that nickname (owner deleted → tombstoned `_deleted_…`) → correctly admin-only. The removed nickname fallback was the exact recycled-nickname inheritance hole; closing it is right.

### 3. `calendar.list_events` selectinload(created_by) — **PASS**
`routers/calendar.py:87`. `ScheduleEvent.created_by` is a real `relationship()` (`models.py:266`); `_event_out` reads `event.created_by.nickname` per row (`calendar.py:31`). `selectinload` is a relationship-loader strategy — it issues a **separate** `SELECT ... WHERE created_by_user_id IN (...)` after the primary query; it adds **no** JOIN and selects only `ScheduleEvent` in the main query, so it cannot collide with the `event_project`/`req_project` aliases or the `Requirement` outerjoin / private-status WHERE filter. The existing SQL visibility filter (`:91-105`) is byte-for-byte unchanged. Eliminates the per-row N+1 cleanly. No behavioral change to which rows are returned.

---

## New findings

**None at P1 or P2.**

---

## Carryover re-assessment

### P2-a: `_can_view_job` meeting branch missing `Project.archived` — `routers/jobs.py:35-39` — **stays P2, no escalation**
Unchanged. Meeting-job visibility filters only `Project.deleted_at`, not `archived`. Endpoint returns only `BackgroundJobOut` (status/progress/message) — no requirement/meeting content — and still requires an authed user. The meeting endpoint itself 404s archived projects, so click-through degrades gracefully. UX inconsistency only; no auth bypass / data leak / stuck state.

### P2-b: `list_users?include_deleted=true` open to all — `routers/users.py:25,30-31,53` — **stays P2, no escalation**
Unchanged. Any authed user can list soft-deleted users; `display_name` strips the `_deleted_<id8>_` prefix and appends `（已停用）`, and `deleted_at` is returned. In the LAN open-board model every live nickname/id/online/admin-flag is already enumerable and there is no password/PII; this exposes deletion metadata + a previously-public name. Should be admin-gated (hardening nicety). P2.

### P2-c: health endpoint N+1 — `routers/health.py:18-105` — **stays P2, no escalation**
Unchanged. `_health_for_project` is O(projects × reqs) with a lazy `req.assignments` load per active req. Pure read-only perf, acceptable for the ≤50-project LAN target. No correctness/security impact.

---

## Coverage

| Area | Files / sites | Outcome |
|------|---------------|---------|
| R7.4 #1 notif change-guard | `services/notifications.py`; all 8 callers (lifecycle, decompositions, knowledge, requirements×3, notifications router×3) | PASS — resurfaces on real change, no-flush safe, dead `notify_users` noted |
| R7.4 #2 owner_user_id-only | `routers/projects.py` (list+_require_owner, 3 call-sites), `routers/project_drive.py` (_can_manage_project, _require_manage_item) | PASS — active owners OK, no fallback consumers remain |
| R7.4 #2c boot backfill | `services/schema_migrations.py:76-91`, `main.py:187-191` (lifespan ordering) | PASS — backfill runs before first request, NULL ⇒ genuinely orphaned |
| R7.4 #3 calendar eager-load | `routers/calendar.py:83-123`, `models.py:266` | PASS — selectinload adds no join, filter unchanged |
| Requirements state machine + CAS | `routers/requirements.py:238-351` (allowed-map, CAS, role gates, worker-transition local-client guard) | clean — CAS `WHERE status=old` → rollback+409; `ready` reachable via sync/auto; no dead-end |
| Submit/claim/ack CAS | `routers/sync.py:40-141` | clean — `summary_ready→ready` & `ready→claimed` CAS-gated, project-active pre-check |
| AI finalize dead-ends | `routers/auto.py:150-298` | clean — no project filter, race-check-first, both paths resolve (no perpetual spinner) |
| Notifications router | `routers/notifications.py` (`_ensure_due`, list/read/read-all, project-active outerjoin) | clean — dedupe interplay correct, archived/deleted-project notifications filtered out of list |
| SSE push + bus | `routers/push.py`, `services/push_bus.py` | clean — try/finally unsubscribe, disconnect check, perm-session closed pre-stream, `stream_me` topic from auth id, no `all` fan-out for notifications |
| Swallowed exceptions | grep `except: pass/continue` (12 sites) | clean — all best-effort I/O / SSE-publish / ASR fallback; none mask a DB write |
| Carryover P2s | `routers/jobs.py`, `routers/users.py`, `routers/health.py` | re-confirmed P2, no escalation |
| Syntax sanity | `ast.parse` over all of `app/**/*.py` | ALL PARSE OK |

### Gate note
Round 4 was CLEAN. R7.4 fixed Round-4's findings without introducing regressions (all 3 changes verified PASS) and even closed the Round-4 title-truncation cosmetic note. Round 5 is **CLEAN with zero new P1/P2**. Counts as Round 1 of the fresh 4-CLEAN streak.
