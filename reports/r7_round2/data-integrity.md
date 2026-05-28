# R7 Round 2 — Data integrity

## Verdict
**3 findings (0 P0, 1 P1, 2 P2).** The four R7.1 fixes from Round 1 all land correctly. New findings are knock-on effects of the WAL + `foreign_keys=ON` switchover (one P1) and one residual gap in the recycled-nickname defense (P2). The third P2 is a missing-rollback symmetry break in `knowledge._process_knowledge_ask` that the same Round 1 review template caught for `meetings` and `decompositions` but missed for `knowledge`.

Not ship-blocking. Recommend an R7.2 to close the FK-introduced hard-delete regression and the nickname-recycle leak in `list_projects` filter.

---

## R7.1 fix verification

### Fix 1 — `deliveries.accept_delivery` / `request_revision` archive guard — VERIFIED
`app/routers/deliveries.py:51-68` defines `_ensure_writable_project` correctly:
- Calls `requirement_project_is_active(req)` — same predicate used by sync/auto/requirements.
- Admin gets 409 with restore hint (NOT 200) — preserves admin-write-respects-archive invariant from `permissions.py`.
- Non-admin gets 404 (matches the read-side masking).

Both endpoints invoke it BEFORE the `r.status != "delivered"` check (lines 161, 207), so an archived-project requirement now returns 404/409 before the CAS even runs. Correct ordering.

### Fix 2 — `meetings._process_meeting` rollback before re-query — VERIFIED
`app/routers/meetings.py:338-353`. `db.rollback()` is the first statement inside the `except`, before either `db.query(MeetingRecord)` or `db.query(BackgroundJob)` reloads can autoflush dirty state from the failed try-block. Clean.

### Fix 3 — `decompositions._process_decomposition` rollback before re-query — VERIFIED
`app/routers/decompositions.py:316-333`. Same shape as the meetings fix; rollback first, then re-query plan + job, only flips status if `status == "draft"` (preserves already-confirmed plans). Correct.

### Fix 4 — `meetings.dismiss_meeting_insight` CAS — VERIFIED
`app/routers/meetings.py:532-558`. Mirrors `confirm_meeting_insight` correctly:
- CAS predicate `MeetingInsight.status == "pending"` (no extra `or_` arm — dismiss has no equivalent of confirm's "confirmed-but-stranded" retry semantics).
- On rowcount==0: `db.rollback()` + `db.refresh(insight)` + return latest state (no 409, treated as idempotent — sensible UX for a dismiss button).
- On rowcount==1: `db.commit()` + return.

A concurrent confirm + dismiss now resolves with the first-writer-wins semantics. The other gets a no-op return.

### Fix 5 — Identity-based project ownership — PARTIALLY VERIFIED
`app/models.py:71-90` adds `owner_user_id: Optional[str]`.
`app/services/schema_migrations.py:34-91` migration is idempotent (PRAGMA table_info check; `CREATE INDEX IF NOT EXISTS`).
`app/routers/projects.py:97-113` `_require_owner` checks `owner_user_id` first, falls back to nickname.

Caveats (see P2-1 below): the **backfill** at `schema_migrations.py:80-90` has a hole — projects whose original owners were tombstoned BEFORE the migration ran get `owner_user_id = NULL` (the subquery filters `u.deleted_at IS NULL`). For those rows `_require_owner` falls through to the nickname-equality branch and the recycled-nickname bug persists. Also, `list_projects` line 55 still filters by `owner_nickname == user.nickname`, leaking tombstoned-owner project metadata to a re-registered nickname (see P2-2).

### Fix 6 — SQLite WAL + busy_timeout + foreign_keys ON — VERIFIED for runtime; carries one P1 side-effect
`app/db.py:22-39`. PRAGMA set in a `connect` event listener (per-connection — correct because `synchronous`, `busy_timeout`, and `foreign_keys` are per-connection settings; `journal_mode=WAL` is persisted in the DB header but re-asserting it is a no-op).

WAL switchover hazards reviewed:
- **No data-loss risk** on the journal-mode change itself: SQLite atomically migrates the rollback journal at the first connect-event after the upgrade.
- **synchronous=NORMAL trade-off**: a power loss can lose the most recently committed transactions inside the WAL. Acceptable for this workload but should be documented.
- **Backup hazard**: tools that copy only `*.db` and skip `*-wal` / `*-shm` now get stale snapshots. Worth a one-liner in deployment docs.
- **Windows / network-share gotcha**: WAL needs shared-memory mapping that doesn't work on SMB/NFS. Production runs Ubuntu 26.04 (per project memory), so non-issue.
- **foreign_keys=ON behavior change** → see new P1-1 below: previously-tolerated near-orphan FKs now fail with IntegrityError.

---

## New findings

### P1-1 — `foreign_keys=ON` breaks `DELETE /requirements/{req_id}` for cross-referenced requirements
**Files:** `app/db.py:37`, `app/models.py:240, 297, 300, 333`, `app/routers/requirements.py:626`

Now that `PRAGMA foreign_keys=ON` is in effect, the previously-ignored FKs on:
- `ProjectDriveComment.draft_requirement_id` → `requirements.id` (no `ondelete`, default RESTRICT)
- `MeetingInsight.target_requirement_id` → `requirements.id` (no `ondelete`)
- `MeetingInsight.created_requirement_id` → `requirements.id` (no `ondelete`)
- `Requirement.source_requirement_id` → `requirements.id` (no `ondelete`)
- `Requirement.source_meeting_id` → `meeting_records.id` (no `ondelete`)

…will refuse `db.delete(r)` in `delete_requirement` (line 626) for any requirement that:
1. Was spawned by a drive comment (`ProjectDriveComment.draft_requirement_id` references it), OR
2. Was confirmed from a meeting insight (`MeetingInsight.created_requirement_id` references it), OR
3. Targets an in-flight meeting insight (`MeetingInsight.target_requirement_id` references it), OR
4. Has been forked into a child requirement (`Requirement.source_requirement_id` references it).

Before the FK enforcement flip, `db.delete(r)` would succeed and silently leave dangling references. After R7.1, the same call raises `sqlalchemy.exc.IntegrityError` and returns a 500 to the user / admin.

**Risk:** admin deletes a requirement that has any of the above back-refs → 500. The user-facing endpoint doesn't catch IntegrityError; the transaction rolls back and the DELETE returns "Internal Server Error".

**Existing-data hazard on switchover**: production databases that ran before this fix may already contain rows that violate these FKs (e.g., a Requirement was deleted but a ProjectDriveComment.draft_requirement_id still points at the gone id). With `foreign_keys=ON`, *any* operation that touches those rows for write may surface the orphan — though SQLite only enforces FK at modify time, so existing orphans are tolerated until something touches them.

**Fix sketch:**
- Add `ondelete="SET NULL"` to all four columns above (consistent with `Notification.{project_id, requirement_id}` precedent at models.py:156-157), OR
- In `delete_requirement` before `db.delete(r)`, explicitly null out the back-refs:
  ```python
  db.query(ProjectDriveComment).filter(ProjectDriveComment.draft_requirement_id == req_id)\
    .update({"draft_requirement_id": None})
  db.query(MeetingInsight).filter(MeetingInsight.target_requirement_id == req_id)\
    .update({"target_requirement_id": None})
  db.query(MeetingInsight).filter(MeetingInsight.created_requirement_id == req_id)\
    .update({"created_requirement_id": None})
  db.query(Requirement).filter(Requirement.source_requirement_id == req_id)\
    .update({"source_requirement_id": None})
  ```
- Also: run a one-shot orphan-cleanup query in `schema_migrations.py` before flipping foreign_keys ON, e.g. `UPDATE project_drive_comments SET draft_requirement_id = NULL WHERE draft_requirement_id NOT IN (SELECT id FROM requirements)`. Idempotent.

Severity: P1 because R7.1 effectively introduced a regression in a previously-working DELETE path. A submitter trying to clean up an old draft that was spawned from a drive comment now sees 500. Admin same.

### P2-1 — Project ownership backfill leaves NULL for projects whose original owner was tombstoned pre-migration
**Files:** `app/services/schema_migrations.py:80-90`, `app/routers/projects.py:108-113`

The backfill SQL filters `WHERE u.deleted_at IS NULL`. If an admin tombstoned alice (`_deleted_<id8>_alice`) before the migration was applied (e.g., R7.1 deployment lands on a long-running install), every project that alice owned gets `owner_user_id = NULL`. The fallback branch in `_require_owner` (line 112) then matches by `p.owner_nickname == user.nickname` — exactly the recycled-nickname bug the migration was meant to close.

**Concrete scenario:**
1. Admin deletes alice on day N → `alice` user row has `deleted_at` set, nickname tombstoned, `projects.owner_user_id` doesn't exist yet.
2. R7.1 deploys on day N+1 → migration runs `UPDATE projects SET owner_user_id = (SELECT u.id … WHERE u.nickname = projects.owner_nickname AND u.deleted_at IS NULL)`. Subquery returns 0 rows for alice's projects. `owner_user_id` stays NULL.
3. Bob registers nickname "alice" on day N+2 → `get_or_create_user` creates new user with id `bobid`, nickname `alice`.
4. Bob calls archive_project on alice's project → `_require_owner` sees `p.owner_user_id is None`, falls through to `p.owner_nickname == user.nickname` ("alice" == "alice") → **success, Bob now owns alice's project**.

**Fix sketch:** in the backfill, ALSO try to recover the original owner from the tombstoned nickname:
```sql
-- Second pass: match the deleted owner by tombstoned nickname
UPDATE projects
SET owner_user_id = (
    SELECT u.id FROM users u
    WHERE u.nickname LIKE '_deleted_' || substr(u.id, 1, 8) || '_' || projects.owner_nickname
    LIMIT 1
)
WHERE owner_user_id IS NULL
```
…or, simpler and stricter: change the nickname-fallback in `_require_owner` to ONLY accept when no user has been soft-deleted with that nickname tombstone. The cleanest design is to require admin remediation for any NULL owner_user_id row (deny ownership, log a warning).

Severity: P2 — only triggers when (a) original owner was tombstoned, (b) project's `owner_user_id` is NULL post-migration, (c) a new user with the original nickname registers. Bounded; recovery is `UPDATE projects SET owner_user_id = '<admin-id>' WHERE id = '<proj-id>'` as a one-shot manual fix.

### P2-2 — `list_projects` non-admin filter still uses nickname, leaking tombstoned owner's archived/deleted projects
**File:** `app/routers/projects.py:51-55`

```python
if state in ("archived", "deleted", "all") and not is_admin(user):
    q = q.filter(Project.owner_nickname == user.nickname)
```

Same recycled-nickname bug as P2-1, applied to project-list visibility. A new user named "alice" can enumerate the previous alice's archived/deleted projects via `GET /api/projects?state=deleted`.

**Fix sketch:** mirror the `_require_owner` pattern:
```python
if state in ("archived", "deleted", "all") and not is_admin(user):
    q = q.filter(
        or_(
            Project.owner_user_id == user.id,
            and_(Project.owner_user_id.is_(None), Project.owner_nickname == user.nickname),
        )
    )
```

Severity: P2 — disclosure of project-name + slug + description of someone else's archived/deleted work, not write access. The restore button on those rows then 403s via `_require_owner` (once P2-1 is fixed), but the leak itself is wrong.

### P2-3 — `knowledge._process_knowledge_ask` except block missing `db.rollback()` (symmetric R7.1 gap)
**File:** `app/routers/knowledge.py:145-152`

```python
except Exception as exc:
    row = db.query(KnowledgeAskRun).filter(KnowledgeAskRun.id == run_id).first()
    job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
    ...
    db.commit()
```

R7.1 patched the equivalent in `meetings._process_meeting` and `decompositions._process_decomposition` (added `db.rollback()` first), but this same pattern in `knowledge._process_knowledge_ask` was not touched. If the LLM-answer step at line 125 raises after a partial autoflush (it shouldn't currently — `search_knowledge` is read-only, `answer_from_hits` is pure — but the failure mode is identical), the re-queries at lines 146-147 would autoflush dirty state.

Currently the body of the try only writes via `update_job` (which uses ORM mutation) and `row.answer_md = ...` / `row.status = "succeeded"` — none flush mid-call, so the autoflush hazard is theoretical. But the symmetry break is worth closing for the same one-line cost as the other two.

Severity: P2 — same shape as the original P1 caught for meetings/decompositions in Round 1, but lower blast radius (KnowledgeAskRun has no notifications fan-out and no cross-referenced rows).

---

## Coverage

### R7.1 fix verification — clean (5 of 6 fully passing; ownership backfill has the P2-1 gap)

### Background-task DB sessions — clean
Re-audited all 18 `SessionLocal()` call-sites:
- `auth.py:208` — `try/finally: db.close()`. Read-only.
- `main.py:60, 106` — periodic reindex + startup stuck-job sweep. Own session, `finally: db.close()`.
- `routers/auto.py:110, 119, 135, 148, 273` — five separate sessions across the lifecycle, each scoped with `try/finally: db.close()`. Outer `except` in `_run_and_finalize` opens a fresh session via `_mark_auto_failed`.
- `routers/chat.py:110, 162` — both `try/finally: db.close()`. The 162 one isn't inside an `except` so an exception during `db2.commit()` would skip rollback — but `finally: close()` discards pending state anyway.
- `routers/decompositions.py:246` — `try/except/finally: db.close()` with R7.1 rollback fix. Correct.
- `routers/delivery_upload.py:344` — `try/finally: db.close()`. No `except` — see note below.
- `routers/knowledge.py:111` — `try/except/finally: db.close()`. **Missing rollback in except — see P2-3**.
- `routers/meetings.py:298` — `try/except/finally: db.close()` with R7.1 rollback fix. Correct.
- `routers/projects.py:19` — background reindex helper. `try/except/finally: db.close()`. Correct.
- `routers/project_drive.py:217` — same as projects.py:19. Correct.
- `routers/push.py:77` — SSE-init permission check; closed before generator starts. Correct (deliberate — long-lived stream must not hold a session).

Note: `delivery_upload._finalize_doc` (line 344) has no `except` — relies on `finally: db.close()` to discard pending state. SQLAlchemy's session close DOES roll back any pending transaction, so this is safe. Asymmetric with the other background tasks but not a bug.

### Non-CAS status mutations — minor remaining gaps
Audited all 13 `.status = "..."` writes outside CAS:
- `chat.py:124` (`draft → clarifying`) and `chat.py:191` (→ `summary_ready`) — guarded by `_claim_chat_slot` mutex per requirement. Single-writer-per-req invariant holds. No CAS needed under current arch but TOCTOU exists against admin cancellation; minor.
- `auto.py:210` (→ `delivered`), `auto.py:241/285` (→ `ready`), `meetings.py:322` (→ `ready`), `meetings.py:346` (→ `failed`), `decompositions.py:260/278/327` (→ `dismissed`), `delivery_upload.py:352` (→ `delivered`), `knowledge.py:129/149` — all in background tasks where only one in-process worker owns each row (created_at-keyed). No concurrent writer; CAS would be belt-and-suspenders.
- `project_drive.py:1186/1209/1212` — write on a row just inserted in the same request. No race possible.
- `requirements.py:584` (`finalize_summary` → `summary_ready`) — synchronous endpoint, two-tab race produces idempotent double-write (same final state) but double-fires the activity log and SSE event. Minor cosmetic.

No P1 found in this audit pass. The P1 from Round 1 (`dismiss_meeting_insight` missing CAS) is the only true race that needed CAS; R7.1 closed it.

### CAS rowcount==0 paths — clean
All 12 CAS sites verified to `db.rollback()` + re-query + return current state. New sites added by R7.1 (`deliveries.py:177, 231`, `meetings.py:458, 552`) follow the same template.

### WAL switchover — clean except for FK-enforcement side effect (P1-1)
- Journal-mode flip is persistent and safe.
- `synchronous=NORMAL` durability trade documented in the code comment.
- `busy_timeout=5000` is reset per-connection by the listener.
- `foreign_keys=ON` is the only one that changes existing-data semantics — see P1-1 for the hard-delete regression.

### Schema invariants & cascades — unchanged from Round 1 except for the new index
- `ix_projects_owner_user_id` added (line 91) — supports the `owner_user_id` lookup. Good.
- All cascade-deletes still correct.
- Soft-delete invariants on Project and User unchanged.

### Race conditions across boundaries — unchanged from Round 1
No new races introduced by R7.1.

---

## Conclusion

R7.1 is **substantively clean**: 4 of the 4 explicit Round 1 P1s (deliveries archive guard, meetings rollback, decompositions rollback, dismiss-insight CAS) are correctly addressed. The R7.1 ownership fix is correct on the live-data path but has a backfill blind spot (P2-1) and a missed peer-filter in `list_projects` (P2-2).

The one new P1 (`foreign_keys=ON` breaks the requirement-hard-delete path for cross-referenced requirements) is a regression introduced by R7.1's WAL fix. It needs to be addressed in R7.2 before this lands in production with realistic data — any existing install with drive-comment-spawned or meeting-confirmed requirements will get 500s on `DELETE /api/requirements/{req_id}`.

Recommend an R7.2 with:
1. P1-1 fix: add `ondelete="SET NULL"` to the four FK columns + a one-shot orphan cleanup in `schema_migrations.py`.
2. P2-1 fix: extend the backfill to cover tombstoned-owner projects, OR make `_require_owner` deny when `owner_user_id is None`.
3. P2-2 fix: mirror `_require_owner`'s identity-first pattern in the `list_projects` filter.
4. P2-3 fix: add `db.rollback()` to `knowledge._process_knowledge_ask` except block.

Total: ~30 lines of code, all in 4 files, no schema migration risk beyond a single nullable-column-already-exists check.
