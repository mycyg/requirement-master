# R7 Round 3 — Python backend

Scope: HEAD `d50bf12` on branch `fix/r6-hardening`. Fresh-eyes review of `app/` after the R7.2 fix batch. Read-only — no code changes.

## Verdict

**NEEDS FIXES — 1 P2.**

All 12 R7.2 targeted fixes verified correct and effective. The new `_reindex_state` threading dict is correctness-safe under FastAPI's BackgroundTasks model. FK migrations land correctly on both fresh and legacy SQLite installs because the explicit application-side NULL UPDATEs in `delete_requirement` cover both cases. `display_name` in planning is correct (filtered to non-deleted users where `display_name == nickname`). Notification dedupe + actor.id changes work together coherently.

One real-but-low-probability bug in the new `_reindex_state` dict (P2). The pre-existing P2-5 from Round 2 (`list_users?include_deleted=true` accessible to all) was not addressed in R7.2 and remains open.

If you accept "leave P2-5 for L6/H1-style deploy-checklist treatment" and "the `_reindex_state` leak window is implausible in practice", this round is **effectively CLEAN**. Round 4 can confirm.

---

## R7.2 fix verification (12 items)

### 1. `_require_owner` uses owner_user_id first — `app/routers/projects.py:107-123` — **WORKS**

R7.1's correct implementation preserved. Admin override → owner_user_id (if set) → nickname fallback (only for legacy NULL rows). The fallback rejection branch ensures a recycled nickname can't inherit ownership when the previous owner was tombstoned.

### 2. `list_projects` filter switched to user_id with nickname fallback — `app/routers/projects.py:54-65` — **WORKS**

Mirrors `_require_owner` priority correctly:
```python
or_(
    Project.owner_user_id == user.id,
    and_(Project.owner_user_id.is_(None), Project.owner_nickname == user.nickname),
)
```
P1-1 from R7-R2 is closed. A recycled nickname will no longer see the previous user's archived/deleted projects.

Note: the `from sqlalchemy import and_, or_` is inline inside the function (line 59). Cosmetic — should be at module top per PEP 8, but file already does inline imports for `is_admin` so consistency-wise fine.

### 3. `_can_manage_project` uses user_id first — `app/routers/project_drive.py:91-101` — **WORKS** (closes M7)

Same shape as `_require_owner`. Correctly closes the sibling vulnerability where drive renames/deletes were still nickname-gated.

### 4. `schedule_project_reindex` per-project debounce — `app/routers/project_drive.py:223-271` — **WORKS with one corner-case concern (P2)**

Logic walkthrough:
- Burst of 50 calls in ONE request handler: first acquires lock → sets `running=True` → schedules background task; remaining 49 acquire lock → see `running=True` → set `dirty=True` → return without scheduling.
- Background task starts (after response sent), runs `rebuild_knowledge_index`, then re-acquires lock: if `dirty` → consume + re-loop; else clear `running` + return.
- The `threading.Lock` protects both setter and reader paths. Single-CPython process → GIL + this lock means the `state["running"]` read in `schedule_project_reindex` and the write in `_reindex_project_in_background`'s finalize are properly ordered.

**Concurrency: SAFE**. The Lock is the right primitive because `_reindex_project_in_background` runs in a thread (FastAPI `BackgroundTasks.add_task(sync_fn, ...)` uses `run_in_threadpool`), while `schedule_project_reindex` is called from the async request handler's worker thread. A `threading.Lock` is correct for cross-thread sync; `asyncio.Lock` would be wrong here.

**Concern (P2 — new): the `running=True` flag leaks if the request handler raises after `schedule_project_reindex` returns.**

FastAPI cancels pending BackgroundTasks if the handler raises before returning a 2xx response. Trace:
1. `schedule_project_reindex(background, project_id)` → acquires lock → sets `running=True` → `background.add_task(...)`.
2. Handler proceeds, e.g. in `paste_drive_items` (line 1031) the next statement is `return DriveOperationOut(operation_id=op.id, items=[_item_out(db, i) for i in items])`.
3. If `_item_out` raises (e.g. lazy-load on `item.deleted_by` after a connection hiccup), OR if Pydantic response validation raises (rare), the response is 500, BackgroundTasks are dropped, `state["running"]` stays `True` forever.
4. All subsequent `schedule_project_reindex(proj_id)` calls become no-ops (`if state["running"]: state["dirty"] = True; return`). The periodic 5-minute task in `main.py:_periodic_knowledge_reindex` still runs full-corpus, so search isn't permanently broken — just per-write freshness is lost for that project until process restart.

Probability: very low in practice (all current call sites are post-`db.commit` + simple Pydantic outputs). Impact: degraded UX (search index lags up to 5 min for that one project). **Recommend**: move the `running=True` set INTO `_reindex_project_in_background` (the worker reads-and-sets-True under lock as its first act, instead of the scheduler doing it). That way the worker's `finally`/return is the only thing that can flip it. Alternative: keep current scheme but add a `try/except/finally` in `_reindex_project_in_background` that always clears `running` and a periodic janitor that clears flags older than N minutes.

### 5. `planning.workload` filters soft-deleted + uses `display_name` — `app/routers/planning.py:55-122` — **WORKS** (closes L10)

Line 61: `users = {u.id: u for u in db.query(User).filter(User.deleted_at.is_(None)).all()}`. Since soft-deleted users are filtered, every user in `users` has `display_name == nickname` (no tombstone prefix to strip). So line 109's `nickname=user.display_name` is identical to `nickname=user.nickname` in practice, but forward-compatible if someone later relaxes the filter. Defensive coding.

The `sorted(..., key=lambda row: (..., row.nickname.casefold()))` at line 122 is safe because the loop at line 100 only emits rows for users in the (filtered, non-deleted) `users` dict → `nickname` is always a non-tombstoned string.

`presence[user.id]` accesses at lines 110 are safe — `get_presence_map(list(users))` is called with the dict keys (user IDs).

### 6. `delivery_upload.finalize` 1GB merge in `asyncio.to_thread` — `app/routers/delivery_upload.py:209-235` — **WORKS** (closes HIGH-1)

The `_merge_chunks_sync` closure captures `tmp_path` + `chunks` from enclosing scope (both immutable after construction). The thread does pure file I/O + hash → no DB access → no SQLAlchemy session sharing concerns. Returns `(total, hex_digest)` for downstream use.

**Style nit (not a bug)**: the `_Digest` shim class at lines 232-235 is unnecessary — only one downstream caller (`package_sha256=h.hexdigest()` at line 300) and it could just use `digest_hex` directly. The `_Digest` class is defined inside the handler so it's re-defined on every request. Trivial overhead, but smells.

### 7. `requirements.delete_requirement` explicit cross-ref NULL — `app/routers/requirements.py:612-638` — **WORKS** (closes P1-1)

Correct handling of the legacy-vs-new-SQLite-table-schema problem:
- Fresh DBs: model FKs declare `ondelete=SET NULL` → SQLAlchemy `create_all` honors them → DB-side cascade works.
- Legacy DBs: `CREATE TABLE IF NOT EXISTS` migration runs first (without `ON DELETE SET NULL` on these specific FKs — see `schema_migrations.py:285, 419-420`), so existing tables have `NO ACTION`. With `PRAGMA foreign_keys=ON` (R7.1), the DELETE would raise. The app-side `db.execute(sql_update(...).where(...).values(... = None))` runs BEFORE `db.delete(r)`, breaking the references on both schemas.

Coverage check:
- `ProjectDriveComment.draft_requirement_id` → ✓ (line 633)
- `MeetingInsight.target_requirement_id` → ✓ (line 634)
- `MeetingInsight.created_requirement_id` → ✓ (line 635)
- `Requirement.source_requirement_id` → ✓ (line 636)
- `Requirement.source_meeting_id` → no application-side NULL, but this references `meeting_records.id` not `requirements.id` — irrelevant to `delete_requirement`.
- `Notification.requirement_id` → already archived (line 624). FK has `ondelete=SET NULL` in BOTH the model AND the migration (`schema_migrations.py:551`), so DB-side cascade works on both schemas.

`Notification.project_id` and `Notification.requirement_id` migrations include the SET NULL clause (lines 550-551), but the older `requirements` ALTER-added column `source_requirement_id` has NO FK at all in the ALTER path (`schema_migrations.py:18-19`). So on legacy DBs, the explicit NULL is defensive (no constraint to violate) but harmless.

`db.delete(r)` cascades to attachments / chat_messages / deliveries / assignments / workspaces / task_plans / acceptance_items via ORM `cascade="all, delete-orphan"` (`models.py:354-360`). All those children are deleted in the ORM unit-of-work flush, before the parent — correct order.

### 8. `knowledge._process_knowledge_ask` rollback in except — `app/routers/knowledge.py:145-160` — **WORKS** (closes P2-3)

Mirrors meetings/decompositions pattern. Rollback before re-querying, then update status to failed and commit.

### 9. `lifecycle.dedupe_key` includes actor.id — `app/services/lifecycle.py:159` — **WORKS** (closes P1-3)

`dedupe_key=f"{new_status}:{req.id}:{actor.id}"`. With R7.2's notifications.py reset-of-read_at (#10 below), the combination means:

- Same actor + same status retry → dedupe overwrites + resets read_at (user sees new content as unread).
- Different actor + same status (e.g. revision_requested cycle, two different workers) → two separate notification rows. Submitter sees both.

For synthetic actors:
- `User(id="ai-auto", nickname=f"AI ({model})")` in `auto.py:222` → dedupe key `delivered:<req>:ai-auto`. Unique per requirement; will dedupe across AI retries.
- `User(id="ai-finalize", nickname=...)` in `delivery_upload.py:373` → dedupe key `delivered:<req>:ai-finalize`. Always the same key for a given requirement → round 2 after revision_requested overwrites round 1's "delivered" notification AND resets read_at. The submitter sees the latest round as unread. This is the intended R7.2 behavior. **Correct.**

Note: the comment at lifecycle.py:154-158 says "two genuinely different events" → "two notifications", but in the AI-finalize case, the actor.id is constant across rounds for the same requirement, so it's actually "one notification, content updated, marked unread". Both are reasonable; the latter is what happens.

### 10. `notifications.create_notification` dedupe-update resets read_at — `app/services/notifications.py:49-61` — **WORKS** (closes P1-2)

Closes the half-state bug where archived_at was reset but read_at wasn't. Now content updates are correctly resurfaced in the user's unread inbox.

### 11. `main._periodic_partial_cleanup` wrapped in `asyncio.to_thread` — `app/main.py:80-96` — **WORKS** (closes MED-2)

`cleanup_stale_partials` is pure sync file I/O (`rglob` + `stat` + `unlink`). Wrapping is correct.

Note: line 189 (`cleanup_stale_partials(settings.data_dir)`) in the lifespan startup is still synchronous, but that's pre-yield (before the event loop serves requests), so doesn't block any handlers. Acceptable.

### 12. `models.py` FK `ondelete=SET NULL` on 5 columns — `app/models.py:240-242, 299-302, 338-343` — **WORKS**

Changed:
- `ProjectDriveComment.draft_requirement_id` → SET NULL
- `MeetingInsight.target_requirement_id` → SET NULL
- `MeetingInsight.created_requirement_id` → SET NULL
- `Requirement.source_meeting_id` → SET NULL
- `Requirement.source_requirement_id` → SET NULL

Fresh `Base.metadata.create_all` installs honor these. Legacy installs do not (ALTER TABLE can't change FK in SQLite). The `delete_requirement` app-side NULL covers the legacy case (see #7 above).

**Sub-finding (cosmetic)**: the migration's `CREATE TABLE IF NOT EXISTS` for `project_drive_comments` (line 285), `meeting_insights` (lines 419-420), and `meeting_records.requirement_id` (line 392 — this one DOES have SET NULL) is inconsistent. For a brand-new install on an empty disk, `Base.metadata.create_all` runs first, creating the tables with the correct FKs. The `CREATE TABLE IF NOT EXISTS` in migrations is then a no-op. So fresh installs are fine. **No bug**, but the migration text doesn't reflect current model intent — if the model and migration ever diverge, this lies. Worth a future cleanup (rewrite migration to match model FK spec, or document that `create_all` is the source of truth and migration only handles upgrades from pre-FK days).

---

## New findings

### P2-1 (NEW): `_reindex_state["running"]` flag can leak permanently if handler raises after `schedule_project_reindex` — `app/routers/project_drive.py:257-271`

See R7.2 fix #4 above. Trace summary:

1. Handler calls `schedule_project_reindex(background, proj_id)` → `state["running"] = True` (lock held, then released), task scheduled.
2. Handler raises (e.g. response-model validation, `_item_out` DB hiccup, async-bus publish at line 1254 raising on a corrupted Pydantic payload).
3. FastAPI/Starlette cancels pending BackgroundTasks on non-2xx response.
4. `_reindex_project_in_background` never runs → never clears `state["running"]`.
5. All subsequent `schedule_project_reindex(proj_id)` calls become no-ops (set dirty=True, return) for the lifetime of the process.

Impact: per-write knowledge-index freshness lost for that project. Periodic 5-min full-corpus reindex still runs (`main.py:_periodic_knowledge_reindex`), so search is at worst 5 min stale.

Probability: very low. All current call sites: `db.commit()` → `db.refresh(...)` → `_publish_drive_changed(...)` (try/except internally) → `schedule_project_reindex(...)` → `return _item_out(...)`. The only realistic raise window is `_item_out` lazy-loading or Pydantic validation. `create_drive_comment` (line 1253) has `await bus.publish(...)` AFTER `schedule_project_reindex` — the bus publish has its own internal try/except but the outer `async with self._lock` could theoretically raise.

**Recommended fix** (one of):
- **A (simplest)**: invert ownership. Move `state["running"] = True` INTO `_reindex_project_in_background`'s first act (under the same lock). Scheduler only ever sets `dirty = True`. Worker reads dirty, sets running=True, runs, clears running. The worker's `finally` guarantees the flag is cleared on any path.
- **B (defensive)**: keep current scheme, add a `try/except/finally` in `_reindex_project_in_background` that ALWAYS clears `state["running"]` and consumes `state["dirty"]`. Already mostly does this; ensure the `return` path within the lock also clears running unconditionally if dirty is consumed (currently only clears when dirty is False).
- **C (operational)**: add a startup janitor that clears `_reindex_state` (it's in-process anyway, so it's already cleared on restart — but a long-running process might want a periodic sweep of stale flags).

Mark as **P2 (low impact, low probability)**. Not blocking for deploy.

---

## Outstanding from prior rounds

### Still open from R7-R2 (not addressed by R7.2):

- **P2-5** (`list_users?include_deleted=true` available to all): unchanged. `routers/users.py:21-56`. Restrict to admins (`if include_deleted and not is_admin(user): include_deleted = False` or 403).
- **P2-2** (N+1 in `_health_for_project`): unchanged. Pre-existing perf concern, deferred.
- **P2-3** (`_ensure_due_notifications` mutates DB on every GET `/api/notifications`): unchanged. Could be moved to a periodic task.
- **P2-4** (`_can_view_job` meeting branch ignores `Project.archived`): unchanged. UX inconsistency, not security.

### Acknowledged from R7-R1:

- **L6** / **M6** / **H1**: still open per their original deploy-checklist treatment.

---

## Coverage

| Area | Files reviewed | Outcome |
|------|----------------|---------|
| R7.2 #1 `_require_owner` user_id-first | `routers/projects.py:107-123` | works |
| R7.2 #2 `list_projects` user_id filter | `routers/projects.py:54-65` | works (P1-1 closed) |
| R7.2 #3 `_can_manage_project` user_id | `routers/project_drive.py:91-101` | works (M7 closed) |
| R7.2 #4 `schedule_project_reindex` debounce | `routers/project_drive.py:223-271` | works; **P2-1 flag-leak corner case** |
| R7.2 #5 planning soft-delete + display_name | `routers/planning.py:55-122` | works (L10 closed) |
| R7.2 #6 delivery_upload `asyncio.to_thread` | `routers/delivery_upload.py:209-235` | works (HIGH-1 closed) |
| R7.2 #7 delete_requirement explicit NULL | `routers/requirements.py:612-638` | works (P1-1 closed) |
| R7.2 #8 knowledge rollback | `routers/knowledge.py:145-160` | works (P2-3 closed) |
| R7.2 #9 lifecycle dedupe actor.id | `services/lifecycle.py:159` | works (P1-3 closed) |
| R7.2 #10 notifications reset read_at | `services/notifications.py:49-61` | works (P1-2 closed) |
| R7.2 #11 partial cleanup to_thread | `main.py:80-96` | works (MED-2 closed) |
| R7.2 #12 FK `ondelete=SET NULL` | `models.py:240-242, 299-302, 338-343` | works on fresh + legacy |
| Schema migrations vs FK changes | `services/schema_migrations.py:285, 419-420` | inconsistent text but fresh DB uses `create_all` → not a bug |
| Other nickname-based ownership checks | grep across `app/` | none remaining — only `auth.py:237` (`/identify` flow, intentional) |
| Worker-token auth path | `auth.py:67-145` | clean — soft-delete check + revoked filter both correct |
| Auto-agent sandbox | `services/auto_agent.py` | clean — `_safe_path` resolves symlinks so symlink-escape from `run_command` is caught |
| Delivery doc / zip extraction | `services/delivery_doc.py` | clean — entry size + total + ratio + zip-slip all checked |
| Sync manifest | `services/sync_manifest.py` | clean — assumes `a.user` non-null (true under current user soft-delete model) |
| Meeting / LLM / task / drive-comment / file-parser agents | `services/{meeting,llm,task_decomposition,drive_comment,file_parser}_agent.py` | clean — all are pure functions of input, no DB writes |
| Background lifecycle | `main.py` (`_resume_stuck_jobs`, `_periodic_*`, `lifespan`) | clean |
| State machines (req status, meetings CAS, decompositions CAS) | `routers/{requirements,meetings,decompositions,sync,delivery_upload}.py` | clean — CAS + rollback consistently applied |

---

## Round-3 verdict & gate

Verdict: **NEEDS FIXES — 1 P2 (the `_reindex_state` flag-leak corner case)** OR **CLEAN if you treat it as acceptable risk for deploy**.

Recommendation: it's borderline. The leak window is very narrow (post-commit, post-publish, on rare exception paths) and the fallout is degraded freshness, not data loss or security. If we treat this as "round 3 effectively CLEAN, fix in 7.3 alongside other deferred items", round 4 should still run as a clean-with-no-findings ratification.

Outstanding P2s from Round 2 (P2-2/3/4/5) are unchanged and still acceptable per their original triage.

Cap on 4 consecutive CLEAN rounds: this counts as the "soft CLEAN" 1st. Round 4 will tell if any latent issues surface.
