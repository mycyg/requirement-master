# R7 Round 3 — Data integrity + Performance

## Verdict
**3 findings (0 P0, 1 P1, 2 P2).** All eight R7.2 fixes are correctly implemented and address the Round 2 findings they target. The new findings are: (1) the explicit cross-ref NULL-out in `delete_requirement` covers 4 of 5 R7.2 SET-NULL FKs but the orphan-cleanup hole called out in R7 Round 2 P1-1 (existing data with dangling refs created BEFORE FKs flipped ON) was NOT addressed in `schema_migrations.py`; (2) Round 2 P2-1 (tombstoned-owner backfill leaves NULL → recycled-nickname inherits ownership) remains unfixed; (3) `inspect_zip_entries` + `os.replace` on a 1GB file still run on the event loop after the merge moved off it.

Not ship-blocking. The R7.2 mainline regressions from R7.1's WAL+FK flip are closed; the residuals are corner cases on pre-existing data and a smaller event-loop window in the same handler that was already partially fixed.

---

## R7.2 fix verification

### F1 — `Project.owner_user_id` column + backfill — VERIFIED with caveat
- `app/models.py:83` adds `owner_user_id: Optional[str]` with `index=True`. Correct nullable to allow legacy rows.
- `app/services/schema_migrations.py:34-91` migration is idempotent: PRAGMA-checked column add, `CREATE INDEX IF NOT EXISTS`, backfill uses `WHERE owner_user_id IS NULL` so re-runs are no-ops.
- `app/routers/projects.py:81` `create_project` now sets `owner_user_id=user.id` on new rows.
- `app/routers/projects.py:107-123` `_require_owner` uses identity-first.
- `app/routers/projects.py:58-65` `list_projects` mirrors `_require_owner` for archived/deleted enumeration — closes R7 Round 2 P2-2.
- `app/routers/project_drive.py:91-101` `_can_manage_project` uses identity-first — addresses M7 from Round 2 security review.

**Caveat (P2-A below):** R7 Round 2 P2-1 (tombstoned-owner projects get `owner_user_id = NULL`) was NOT addressed. The backfill SQL still filters `WHERE u.deleted_at IS NULL`, so projects whose owner was tombstoned before R7.1 deploy keep `owner_user_id = NULL` and fall through to the nickname-equality branch in `_require_owner` / `list_projects` — exactly the recycled-nickname bug the migration was meant to close.

### F2 — FK `ondelete=SET NULL` on 5 cross-reference columns — VERIFIED
`app/models.py`:
- `ProjectDriveComment.draft_requirement_id` (line 240) — SET NULL
- `MeetingInsight.target_requirement_id` (line 299) — SET NULL
- `MeetingInsight.created_requirement_id` (line 304) — SET NULL
- `Requirement.source_requirement_id` (line 341) — SET NULL
- `Requirement.source_meeting_id` (line 338) — SET NULL

All 5 FK declarations now carry `ondelete="SET NULL"`. New installs (via `Base.metadata.create_all`) will get the correct cascade.

**Caveat (P1-A below):** Legacy installs that ran `CREATE TABLE` from `schema_migrations.py` BEFORE this commit have the no-action FK constraint baked into the table schema (`project_drive_comments` line 285, `meeting_insights` lines 419-420). ALTER TABLE in SQLite cannot change an FK's ON DELETE clause; the only ways to migrate are (a) a full table rebuild via `CREATE TABLE _new` + `INSERT ... SELECT` + `DROP` + `RENAME`, or (b) the application-level workaround in F3 (which works for delete_requirement but NOT for any future cascade-from-meeting hard delete).

### F3 — `delete_requirement` explicit cross-ref NULL-out — VERIFIED, covers 4 of 5
`app/routers/requirements.py:627-636` correctly NULLs out:
- `ProjectDriveComment.draft_requirement_id` (line 633)
- `MeetingInsight.target_requirement_id` (line 634)
- `MeetingInsight.created_requirement_id` (line 635)
- `Requirement.source_requirement_id` (line 636)

The 5th FK in F2 (`Requirement.source_meeting_id`) is intentionally NOT in this list because it points FROM the requirement-being-deleted TO a MeetingRecord — when the requirement is deleted, this row goes away with it, so no inbound reference to clean. Correct asymmetry.

Verified: no `DELETE /meetings/{id}` endpoint exists (`grep -r 'delete.*meeting'` returns no router hits), so the reverse direction (delete a MeetingRecord with surviving Requirements pointing at it) cannot fire in user-driven flows. MeetingRecord rows are only removed via CASCADE from `projects.id` — and projects are only soft-deleted, so this cascade never fires today. Acceptable.

### F4 — `knowledge._process_knowledge_ask` rollback in except — VERIFIED
`app/routers/knowledge.py:145-156`. `db.rollback()` is the first statement inside the `except` (line 149), before either of the two re-queries on lines 150-151 can autoflush dirty state. Matches the R7.1 pattern for meetings + decompositions.

### F5 — `lifecycle.queue_status_notifications` dedupe_key includes actor.id — VERIFIED
`app/services/lifecycle.py:159` — `dedupe_key=f"{new_status}:{req.id}:{actor.id}"`. A revision_requested → doing → revision_requested cycle from two different workers now creates two distinct notifications (different actor.id segments), so neither silently overwrites the other.

Verified no collision with the synthetic `User(id="ai-finalize", …)` from `delivery_upload._finalize_doc:373` — that path emits the "delivered" notification with `actor.id == "ai-finalize"`, which can never collide with a real user's revision_requested.

### F6 — `notifications.create_notification` dedupe-update resets `read_at` — VERIFIED
`app/services/notifications.py:48-61`. Lines 59-60 reset both `read_at = None` and `archived_at = None` along with content. A previously-read notification whose content mutates surfaces back in the inbox as unread — correct.

### F7 — `project_drive.schedule_project_reindex` per-project in-flight debounce — VERIFIED
`app/routers/project_drive.py:231-271`. `_reindex_lock` (threading.Lock) wraps all `_reindex_state` reads/writes:
- `schedule_project_reindex` (line 265-271): under lock, sets `running=True` and only `add_task`s if not already running; otherwise sets `dirty=True` and returns.
- `_reindex_project_in_background` (line 235-253): runs reindex; then under lock, if `dirty=False` clears `running=False` and returns; if `dirty=True` clears it and re-loops once more.

Bulk 50-paste correctly coalesces to ≤2 reindex runs (one immediate, one trailing). Thread-safety is correct — `threading.Lock` is the right primitive because BackgroundTasks run on Starlette's threadpool (per Round 2 verification), not on the event loop.

Two minor observations (not findings):
- `_reindex_state` grows unbounded as projects are touched; entries are never removed. At 30 LAN users × N projects this is harmless (each entry is ~100 bytes).
- `app/routers/projects.py:149, 168, 186` (archive/restore/soft_delete_project) use `background.add_task(_reindex_project_in_background, ...)` directly, bypassing the debounce. Infrequent operations so no real cost, but inconsistent — debouncer is bypassed for project-level lifecycle events.

### F8 — `delivery_upload.finalize` 1GB merge in `asyncio.to_thread` — VERIFIED partially
`app/routers/delivery_upload.py:213-226`. The chunk merge loop is correctly wrapped in `asyncio.to_thread(_merge_chunks_sync)`. Event-loop block during the multi-second hashing pass is eliminated.

**Caveat (P2-B below):** the SAME handler still does sync `inspect_zip_entries(tmp_path)` at line 238 (central-dir read of a 1GB zip) and `os.replace(tmp_path, out_path)` at line 290 on the event loop. Plus 1000× `c.stat().st_size` calls in the chunk validation loop at lines 197-203. Together a few hundred ms of residual event-loop work; much smaller than the multi-second merge but the original critique applies in miniature.

### F9 — `_periodic_partial_cleanup` wrapped in `asyncio.to_thread` — VERIFIED
`app/main.py:88-96`. `await asyncio.to_thread(cleanup_stale_partials, settings.data_dir)` is correct. Line 189 in `lifespan` still calls it sync, but that's BEFORE the app starts serving — acceptable as documented.

---

## Prior unfixed status

### R7 Round 2 — P1-1 (FK orphan cleanup) — PARTIALLY ADDRESSED → see P1-A
The model-side fix landed (F2). The application-side workaround landed (F3). But the suggested orphan-cleanup `UPDATE … WHERE draft_requirement_id NOT IN (SELECT id FROM requirements)` was NOT added to `schema_migrations.py`. Production installs with pre-R7.1 dangling FK rows will still fail when those rows are next updated under `foreign_keys=ON`.

### R7 Round 2 — P2-1 (tombstoned-owner backfill) — NOT ADDRESSED → see P2-A
Same gap as Round 2. The backfill at `schema_migrations.py:80-90` still uses `WHERE u.deleted_at IS NULL` and there's no second-pass match against tombstoned nicknames.

### R7 Round 2 — P2-2 (list_projects nickname filter) — FIXED
`app/routers/projects.py:58-65` now uses the identity-first pattern. Closed.

### R7 Round 2 — P2-3 (knowledge missing rollback) — FIXED (F4)

### R7 Round 2 — HIGH-1 (delivery_upload event-loop merge) — FIXED for merge (F8); see P2-B for residual

### R7 Round 2 — MED-1 (reindex burst amplification) — FIXED (F7)

### R7 Round 2 — MED-2 (`_periodic_partial_cleanup` event-loop block) — FIXED (F9)

### R7 Round 1 perf items remaining unchanged
Still unfixed (all already documented, not re-listed as new findings here):
- R1 HIGH-4: `notifications` "ensure due" on every poll — ~9k writes/min sustained at full load; WAL has demoted severity but still wasteful.
- R1 HIGH-6: `calendar._event_out` N+1 on `created_by.nickname` — needs `selectinload(ScheduleEvent.created_by)` on the query at `app/routers/calendar.py:83`.
- R1 HIGH-7: `meetings._meeting_out` N+1 on insights — needs `selectinload` or batched fetch at `app/routers/meetings.py:105-142`.
- R1 HIGH-8: `drive_manifest` O(N × depth) on `_item_path` walk — needs a single-query path computation at `app/routers/project_drive.py:174-198`.
- R1 HIGH-9: `reminders` N+1 workspace lookup per requirement at `app/routers/reminders.py:62-84`.
- R1 MED-10/11/12/13: composite indexes, deliveries zip-per-row, sync_manifest lazy loads, Vite chunking — all unchanged.

---

## New findings

### P1-A — Pre-R7.1 dangling FK orphans still bite on any UPDATE under `foreign_keys=ON`
**Files:** `app/services/schema_migrations.py:34-91`, `app/models.py:240, 299, 304, 341` (the SET-NULL columns)

The R7 Round 2 P1-1 fix sketch had two parts: (a) add `ondelete=SET NULL` to the model + null-out at delete time, and (b) one-shot orphan cleanup at boot. Part (a) landed in R7.2 (F2 + F3). Part (b) is still missing.

**Concrete scenario:**
1. Production install on R7.0 (no `foreign_keys=ON`). Admin hard-deletes requirement REQ-123. A `ProjectDriveComment` row still has `draft_requirement_id = 'REQ-123'` (dangling).
2. R7.2 deploys. PRAGMA `foreign_keys=ON` is in effect. The legacy CREATE TABLE constraint on `project_drive_comments.draft_requirement_id` is still NO ACTION (ALTER TABLE can't change it).
3. A user edits that drive comment's body via `PATCH /api/drive/comments/{id}` — any UPDATE on the row that doesn't first NULL the FK column will raise `IntegrityError: FOREIGN KEY constraint failed`.

SQLite's `foreign_keys=ON` check fires on row-modify, not just on row-insert. Even a NOTOUCH-style UPDATE (where the FK column is unchanged) is checked, because SQLite re-verifies all FK constraints on the row when ANY column is written under `PRAGMA foreign_keys=ON`.

**Risk:** any pre-R7.1 install with dangling cross-refs gets sporadic 500s on subsequent edits of those rows. Bounded — only affects rows with broken FKs from before — but invisible until users hit them.

**Fix sketch:** in `ensure_runtime_schema`, before the index-creation block runs, add:
```sql
UPDATE project_drive_comments SET draft_requirement_id = NULL
 WHERE draft_requirement_id IS NOT NULL
   AND draft_requirement_id NOT IN (SELECT id FROM requirements);

UPDATE meeting_insights SET target_requirement_id = NULL
 WHERE target_requirement_id IS NOT NULL
   AND target_requirement_id NOT IN (SELECT id FROM requirements);

UPDATE meeting_insights SET created_requirement_id = NULL
 WHERE created_requirement_id IS NOT NULL
   AND created_requirement_id NOT IN (SELECT id FROM requirements);

UPDATE requirements SET source_requirement_id = NULL
 WHERE source_requirement_id IS NOT NULL
   AND source_requirement_id NOT IN (SELECT id FROM requirements);

UPDATE requirements SET source_meeting_id = NULL
 WHERE source_meeting_id IS NOT NULL
   AND source_meeting_id NOT IN (SELECT id FROM meeting_records);
```
Idempotent (post-run, all 5 queries match zero rows). Cost: 5× full-table scan at boot — ~100ms per query on the target scale.

Severity: P1 because this is the same FK regression class as Round 2 P1-1 — production installs predating R7.1 have the dangling rows and will hit 500s on next edit. Round 2 explicitly called out part (b) and it wasn't picked up.

### P2-A — Project ownership backfill still leaves NULL for tombstoned-owner rows
**File:** `app/services/schema_migrations.py:80-90` (unchanged from Round 2)

The R7 Round 2 P2-1 finding is verbatim still alive. The backfill only matches owners with `u.deleted_at IS NULL`. If admin tombstoned alice before R7.1 deploy, alice's projects have `owner_user_id = NULL` post-migration. `_require_owner` and `list_projects` both fall through to the nickname-equality branch — and a new user registering nickname "alice" inherits archive/restore/delete rights on alice's projects.

The fact that R7.2 fixed the `list_projects` filter (R2 P2-2) makes the residual exposure smaller — a new "alice" can't enumerate the old alice's archived projects via state=deleted anymore. But the `_require_owner` fallback still grants WRITE access if the new "alice" happens to know the project_id.

**Fix sketch:** in `ensure_runtime_schema`, add a second backfill pass that recovers the tombstoned owner via the `_deleted_<id8>_<original>` pattern, OR change `_require_owner` to deny ownership entirely when `owner_user_id IS NULL`:
```python
def _require_owner(p, user):
    if is_admin(user):
        return
    if p.owner_user_id is not None:
        if p.owner_user_id != user.id:
            raise HTTPException(403, ...)
        return
    # Legacy row with no owner_user_id — require admin remediation
    # rather than accept the nickname-equality fallback. Logs a warning
    # so ops can run `UPDATE projects SET owner_user_id = '<id>' WHERE id = '<pid>'`.
    raise HTTPException(403, "project ownership has not been migrated; ask an admin")
```
Stricter — locks out genuine pre-migration owners who weren't tombstoned. The two-pass backfill approach is safer.

Severity: P2 unchanged — only triggers under (tombstoned owner) ∧ (nickname re-registered) ∧ (new owner knows the project_id).

### P2-B — `delivery_upload.finalize` residual sync I/O on event loop
**File:** `app/routers/delivery_upload.py:172, 197-203, 238, 290, 328`

F8 fixed the 7-second merge block. Three smaller sync ops remain on the event loop in the same `async def`:
1. **Per-chunk stat loop** (lines 197-203): for a 1000-chunk upload, 1000 `c.stat().st_size` syscalls. ~50ms on Linux, ~200ms on Windows with AV.
2. **`inspect_zip_entries(tmp_path)`** (line 238): `zipfile.ZipFile(zip_path)` seeks to end of file, reads central directory, iterates infolist. On a 1GB zip with 10000 entries: ~200-500ms (mostly the central-dir scan + per-entry path validation).
3. **`os.replace(tmp_path, out_path)`** (line 290): metadata-only on same mount → <1ms. Cross-mount → multi-second fallback to copy+unlink. Same `data_dir/deliveries/` tree so same mount today, but `settings.data_dir` is configurable and a misconfig where partial + deliveries land on different mounts silently degrades into a sync copy.
4. **`shutil.rmtree(pdir, ignore_errors=True)`** (line 328): walks partial dir to delete remaining files — should be near-empty after merge, but sync walk on event loop.

Cumulative ≈ 0.3-1s of event-loop work per finalize on a 1GB upload. Not in the same class as the 7-second merge but worth noting since the same async def handler was already partially fixed.

**Fix sketch:** wrap the chunk validation + zip inspection + replace + rmtree into a single `_finalize_io_sync()` helper and `await asyncio.to_thread(_finalize_io_sync)`. Two extra lines.

Severity: P2 — much smaller blast radius than the 7-second merge (now-fixed). Promote to P1 if/when delivery sizes scale to 10GB+.

---

## Coverage

### R7.2 fix sites reviewed (all 9 verified)
- `app/models.py:71-91, 240, 299-306, 338-343` — owner_user_id + 5 SET NULL FKs.
- `app/services/schema_migrations.py:34-91` — backfill + index.
- `app/routers/requirements.py:596-638` — explicit cross-ref NULL-out + delete.
- `app/routers/projects.py:38-65, 81, 107-123` — identity-first ownership + list filter.
- `app/routers/project_drive.py:91-101, 223-271` — `_can_manage_project` + reindex debounce.
- `app/routers/knowledge.py:110-160` — rollback before re-query.
- `app/services/notifications.py:42-77` — dedupe-update resets read_at.
- `app/services/lifecycle.py:104-161` — dedupe_key includes actor.id.
- `app/routers/delivery_upload.py:171-226` — merge in to_thread.
- `app/main.py:80-96, 193-194` — periodic cleanup in to_thread + task wiring.

### `_reindex_state` thread-safety — clean
`_reindex_lock` (threading.Lock) wraps every read/write of `_reindex_state`. BackgroundTasks dispatch on Starlette's threadpool (verified Round 2), so threading.Lock is correct primitive. No race window between `schedule_project_reindex` and the worker's loop-end check (both happen under the lock).

### Backfill idempotency — clean
- Column-add gated by `PRAGMA table_info(projects)` membership check.
- `UPDATE … WHERE owner_user_id IS NULL` matches zero rows on second run.
- `CREATE INDEX IF NOT EXISTS` is idempotent.
- BUT: orphan case (`owner_user_id` stays NULL for tombstoned-owner rows) is silently re-attempted on every boot with no resolution — see P2-A.

### Cross-ref NULL-out coverage — complete for delete_requirement
4 of 5 R7.2 SET NULL FKs are explicitly nulled in `delete_requirement`. The 5th (`Requirement.source_meeting_id`) doesn't need it because it points FROM the deleted row TO a MeetingRecord — deleting the requirement removes the row entirely. Inbound direction (delete MeetingRecord with surviving Requirements) is not exposed via any user-facing endpoint today.

### Other `db.delete(...)` callsites scanned — no new FK regressions
Reviewed 7 sites (`grep db.delete\(`): `calendar.py:191` (ScheduleEvent, no inbound FKs), `assignments.py:106` (RequirementAssignment, no inbound FKs), `decompositions.py:285` (RequirementTaskItem, cascade-clean), `knowledge.py:342` (KnowledgeDocument, no inbound FKs), `schedule.py:53` (ScheduleEvent), `workspaces.py:165` (RequirementWorkspaceItem), `requirements.py:637` (the audited path). None touch the 5 new SET-NULL relationships.

### Periodic task event-loop hygiene — clean
- `_periodic_knowledge_reindex` (CRIT-1 from R1) — runs in `asyncio.to_thread`.
- `_periodic_partial_cleanup` (MED-2 from Round 2) — runs in `asyncio.to_thread`.
- `_resume_stuck_jobs` — one-shot at startup, runs before serving begins. OK.
- Shutdown cancellation at lines 198-203 cancels both periodic tasks cleanly.

### Unbounded `.all()` audit — unchanged from R1
31 `.all()` calls across 17 routers, 10 of which have `.limit()`. The remaining ~20 unbounded `.all()` calls are mostly bounded by their natural data shape (project list, user list, assignment list per requirement). R1 already flagged the few that aren't (notifications list, reminders list).

### N+1 audit — unchanged from R1
The 4 known N+1 hot paths (calendar `created_by`, meetings `insights`, drive `_item_path`, reminders `workspace`) all unchanged. No new N+1 introduced by R7.2.

### Sync work on event loop — clean except P2-B
Audited all `async def` handlers in routers for sync I/O. Only the residual in `delivery_upload.finalize` (P2-B) remains. Other handlers either offload via `asyncio.to_thread` or have pure DB work (which SQLAlchemy executes via the sync engine — but that's a separate architectural concern out of scope here).

---

## Summary

R7.2 cleanly closes 6 of the 7 R7 Round 2 findings (P1-1 partial, P2-1 unfixed, P2-2 fixed, P2-3 fixed, HIGH-1 fixed, MED-1 fixed, MED-2 fixed). The two residuals (P1-A orphan cleanup, P2-A tombstoned-owner backfill) and the new P2-B (residual delivery-finalize event-loop work) are bounded corner cases. P1-A is the most operationally important — production installs upgrading from pre-R7.1 should run a one-shot orphan cleanup before enabling `foreign_keys=ON` in earnest, or accept sporadic 500s on edits of legacy dangling-FK rows until ops manually clean them.

Recommend an R7.3 with: P1-A orphan cleanup in `schema_migrations.py` (~10 lines, idempotent), P2-A two-pass backfill OR strict NULL-owner deny (~5 lines), P2-B wrap residual sync I/O in `asyncio.to_thread` (~2 lines).
