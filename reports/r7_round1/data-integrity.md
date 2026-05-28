# R7 Round 1 — Data integrity review

## Verdict
**6 findings (0 P0, 4 P1, 2 P2).** R7's revert + admin-read restore is sound and resolves the four codex-introduced regressions the R6 audit flagged. CAS patterns are correct everywhere they appear (12 sites verified), background-task session lifecycles are clean (own SessionLocal, finally close, rollback-equivalent via the outer except), tombstone filtering for projects/users is consistent in user-facing reads. The remaining issues are: (1) a small set of write paths inside `deliveries.py` and a few mutate-after-read paths skip `requirement_project_is_active`, (2) `confirm_meeting_insight` still has a tiny pre-commit transaction state issue if the early-return idempotent fast path observes an uncommitted insight from another in-flight request (only theoretical under single-writer SQLite — flagged P2), (3) `_process_meeting` failure rollback path doesn't `db.rollback()` before re-loading rows, (4) `meeting_insight.dismiss` doesn't CAS, (5) a couple of cancel-aware gaps in lifecycle.

Nothing in this list is ship-blocking. The CAS + `_active_requirement_query` + `_ensure_requirement_project_active` foundation laid in R1-R7 is intact.

---

## P0 / P1 / P2 buckets

### P0 — none

No ship-blockers identified this round. The five Codex P0s flagged in `reports/codex_review/SUMMARY.md` are all confirmed fixed in `306edbd`:

| Codex P0 | Verified fix | Where |
|---|---|---|
| `auth.identify` 409 lockout | Reverted; comment + intent doc-string added | `app/routers/auth.py:46-60` |
| `auto._mark_auto_failed` archived-project drop | Project filter removed; comment cites symmetric rationale | `app/routers/auto.py:272-305` |
| `auto._run_and_finalize` archived-project drop | Project filter removed on `r = db.query(Requirement)…` | `app/routers/auto.py:155-158` |
| Synchronous `_refresh_project_knowledge` in 13 hot paths | All call-sites deleted; `_periodic_knowledge_reindex` retained | `app/main.py:46-67` (periodic), `app/routers/project_drive.py` + `projects.py` (clean) |
| `confirm_meeting_insight` strands non-IntegrityError | New `confirmed-but-stranded` CAS arm + `except Exception` revert | `app/routers/meetings.py:438-515` |

The R7 fix for the meeting-insight strand is **subtle and correct**: instead of attempting to roll the insight back to `pending` (which would race with retries that already passed the early-return gate), R7 expanded the CAS predicate so any retry can re-apply the confirm if `created_requirement_id IS NULL`. This is the cleaner design.

Admin-read override restored in `app/services/permissions.py:50-80` — docstring at top of file (lines 1-22) explicitly documents the read/write split.

### P1 — important

#### P1-1 — `deliveries.accept_delivery` / `request_revision` skip `requirement_project_is_active`
**File:** `app/routers/deliveries.py:44-48, 138-176, 178-238`

`_require_req` here is the bare two-liner that does NOT join `Project` or filter `Project.archived == False, Project.deleted_at.is_(None)`. So a submitter can still:
- POST `/api/requirements/{req_id}/accept` after admin archived the project → flips `status=delivered → accepted` even though every other read path is now 404ing for that project.
- POST `/api/requirements/{req_id}/revisions` after archive → opens a new `RevisionRequest` row and flips back to `revision_requested`.

The CAS guard on `status == "delivered"` prevents *concurrency* races but does NOT prevent the *cross-state* race where admin's archive lands between the submitter's UI load and click. Every other status-changing endpoint (`requirements.update_status`, `sync.submit`, `auto.trigger_auto`, `delivery_upload.finalize`) goes through `_active_requirement_query` or `_ensure_requirement_project_active` first.

**Risk:** an "archived" project's requirements continue to silently advance through `delivered → accepted` after archive. Notifications fire and SSE publishes — surprising users who were told the project was sealed.

**Fix sketch:** swap `_require_req` for the join+filter pattern used in `sync.py:_active_requirement_query` (or just add `_ensure_requirement_project_active(r)` after fetch). Decision is whether admin should be allowed to override (per the new read/write split in `permissions.py`: write paths still respect project-active, so the answer is "no for normal submitter, yes only for admin via restore-first").

#### P1-2 — `_process_meeting` failure path mutates without rollback
**File:** `app/routers/meetings.py:338-349`

```python
except Exception as exc:
    meeting = db.query(MeetingRecord).filter(MeetingRecord.id == meeting_id).first()
    job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
    ...
    db.commit()
```

If the exception was raised mid-flush (e.g. inside `db.add(MeetingInsight(...))` on lines 324-333), the session is in a "dirty" state. `db.query(...)` on a dirty-rollback-pending session will autoflush whatever pending state remains, potentially re-raising the original error (or partially flushing the bad insight). The successful pattern elsewhere is `db.rollback()` FIRST, then re-query.

`_run_and_finalize` in `auto.py:144-146` handles this correctly — it catches and immediately calls `_mark_auto_failed` which opens a NEW session.

**Fix sketch:** add `db.rollback()` as the very first line of the `except`, before any new query. Cost: zero. Benefit: prevents the rare case where ASR succeeded + LLM analysis returned malformed JSON + insight insert raised partway through.

`_process_decomposition` (`decompositions.py:316-330`) has the same shape. Same fix.

#### P1-3 — `meetings.dismiss_meeting_insight` not CAS-guarded
**File:** `app/routers/meetings.py:528-545`

```python
if insight.status == "pending":
    insight.status = "dismissed"
    ...
    db.commit()
```

Two concurrent "dismiss" + "confirm" tabs both pass the `== "pending"` check, both write. `confirm_meeting_insight` later changed status to `confirmed`, but `dismiss` blind-overwrites to `dismissed`. Result: insight ends up `dismissed` AND `created_requirement_id IS NOT NULL` (orphan draft requirement in `draft` state with no owning insight to confirm/dismiss).

`confirm_meeting_insight` uses CAS correctly (line 449-453); `dismiss_meeting_insight` should mirror it:
```python
cas = db.execute(
    sql_update(MeetingInsight)
    .where(MeetingInsight.id == insight_id, MeetingInsight.status == "pending")
    .values(status="dismissed", confirmed_by_user_id=user.id, confirmed_at=datetime.utcnow())
)
if cas.rowcount == 0:
    db.refresh(insight)
    return _insight_out(insight)
```

Severity: P1 (not P0) because under single-writer SQLite + single worker the actual race window is microseconds. But the pattern is wrong and a 2nd worker would expose it immediately.

#### P1-4 — `_run_and_finalize` success-but-stale-status branch leaks Delivery zip file
**File:** `app/routers/auto.py:159-178`

```python
if outcome.success:
    if r.status != "ai_processing":
        # mark job succeeded, shutil.rmtree(workdir)
        return
```

Code correctly skips the Delivery row insert if the requirement was cancelled mid-AI. But the actual zip artifact at `pkg_path` (= `data/deliveries/<req_id>/round-N-ai.zip`) is created LATER in the success branch (lines 184-198). So in this branch we only need to clean `workdir`, which is correct.

**Different leak**: lines 159-178 wipe `workdir` but the AI may have created scratch artifacts under `data/auto/<req_id>/inputs/` that the inputs collection step (lines 119-129) hard-linked to. If `workdir == data/auto/<req_id>` and `shutil.rmtree(workdir)` succeeds, fine. But there's no cleanup of `outputs_root = workdir / "outputs"` if the workdir mid-tree was on a separate volume and rmtree partially failed. Not a real bug but worth a `shutil.rmtree(workdir, ignore_errors=True)` in a `finally` block at the top of `_run_and_finalize` for the cancelled / failed paths too — currently only success cleanups happen.

Severity: P1 disk-leak under specific cancel-during-AI flows. Not a correctness bug.

### P2 — minor

#### P2-1 — `confirm_meeting_insight` early-return reads stale insight state
**File:** `app/routers/meetings.py:415-432`

The idempotent fast-path reads `insight.status != "pending"` from the ORM-cached object — this object was loaded at line 415 BEFORE the CAS. Under single-worker SQLite + same-process autoflush rules this is fine (the calling request's read happens-before any other request's write). But the comment on line 421 ("a previous attempt that crashed mid-create") suggests retries from the SAME user — those previous attempts ran in a different request, so the insight row IS already committed and the new request's query at line 415 sees the latest state. Correct.

The only theoretical bug: `db.query(...).first()` at line 415 with stale autoflush. Modern SQLAlchemy with `expire_on_commit=True` would refresh next access, but the early-return doesn't trigger any access. **Hardening**: explicitly call `db.refresh(insight)` before the `creates_requirement` check, or add `with_for_update()` (won't help on SQLite without true row locks).

Cost ≈ 1 line. Risk = essentially zero on current single-writer config.

#### P2-2 — `lifecycle.queue_status_notifications` skips notifications when actor IS soft-deleted but the actor User row is in-flight
**File:** `app/services/lifecycle.py:77-101`

`_resolve_recipients` filters `User.deleted_at.is_(None)` for RECIPIENTS but the ACTOR (passed in by caller) is not checked. If the actor is in the process of being soft-deleted by an admin in another tab while their own action is mid-flush:
1. Tab A: actor submits → row appended, commit pending
2. Tab B: admin deletes actor → status set to deleted_at, commit
3. Tab A: notification fires with actor.nickname = `_deleted_<id8>_<orig>`

The notification body becomes `"_deleted_abc12345_alice 接走了「FOO-001」"`. Cosmetic.

**Fix**: use `actor.display_name` (already defined in `models.py:46-54`) instead of `actor.nickname` in the substitution map. Pre-existing minor.

---

## Coverage

### Transaction boundaries — clean
Verified every `db.commit()` site in the modified routers:
- `auth.py`, `auto.py`, `chat.py`, `comments.py`, `decompositions.py`, `delivery_upload.py`, `deliveries.py`, `meetings.py`, `notifications.py`, `projects.py`, `requirements.py`, `sync.py`, `users.py`, `workspaces.py`.
- Every CAS-then-commit pattern correctly does `db.rollback()` before re-reading current state (chat.py:188, requirements.py:304-308, sync.py:64-68, sync.py:143-149, auto.py:87-91, delivery_upload.py:247-252, deliveries.py:156-160, deliveries.py:209-213, decompositions.py:181-183, decompositions.py:229-231, meetings.py:454-458).
- Mixed `sql_update` + ORM in same transaction: requirements.py:299-309 correctly uses `db.refresh(r)` after CAS to align ORM state. delivery_upload.py:239-253 same. auto.py:82-92 same. meetings.py:449-463 same.

### Background tasks — clean
- `_run_and_finalize` (`auto.py:105-269`): opens dedicated `SessionLocal()`, has top-level `try/except/return` that calls `_mark_auto_failed`. The `finally: db.close()` at line 268-269 covers the body session. Cancel-aware on the success/failure branches.
- `_mark_auto_failed`: own `SessionLocal()`, `try/finally: db.close()`. Project-filter correctly DROPPED in R7.
- `_process_meeting`: own `SessionLocal()`, `try/except/finally: db.close()`. R7 didn't change. (See P1-2 for the missing rollback.)
- `_process_decomposition`: own `SessionLocal()`, `try/except/finally: db.close()`. R7 added `db.refresh(plan.requirement)` + `db.refresh(plan.requirement.project)` (lines 273-275) — this DOES trigger the stale-archive check correctly.
- `_finalize_doc`: own `SessionLocal()`, `try/finally: db.close()`. Best-effort recovery.
- `_periodic_knowledge_reindex` / `_periodic_partial_cleanup`: opens own session in loop, catches/logs Exception, sleeps. Idempotent — `rebuild_knowledge_index` upserts by `(source_type, source_id)`.
- `_resume_stuck_jobs`: one-shot startup, `try/except/finally: db.close()`. Idempotent (only flips `running → failed`).

### CAS rowcount==0 path — clean
All 12 CAS sites return 409 with `current_status` instead of 500 or silent success. Verified: requirements.py:304, sync.py:64, sync.py:143, auto.py:87, delivery_upload.py:247, deliveries.py:156, deliveries.py:209, decompositions.py:181, decompositions.py:229, meetings.py:454.

Special note on meetings.py:454-458 — R7's CAS with `or_(status=='pending', and_(status=='confirmed', created_requirement_id.is_(None)))` is correctly written. CAS rowcount==0 means the insight is in a terminal state we don't accept retry for; refresh+return is the right thing.

### Schema invariants — clean
- `models.py:339-345`: `Requirement.{attachments, chat_messages, deliveries, assignments, workspaces, task_plans, acceptance_items}` all use `cascade="all, delete-orphan"`. Hard delete of requirement (admin path in `requirements.py:596-628`) correctly cleans associated child rows.
- `Project.requirements` + `Project.drive_items` cascade-delete. But Project soft-delete via `deleted_at` is the standard path — cascade only applies on hard-delete.
- Foreign-key `ondelete`: most user-id FKs DO NOT have `ondelete` set (default RESTRICT). This is intentional per the `User.deleted_at` docstring (lines 39-43) — soft-delete is mandatory. Hard-deleting a user would raise IntegrityError, which is the correct guard.
- `Notification.user_id` is `ondelete="CASCADE"` (line 145) — but `users.delete_user` soft-deletes, so cascade never fires in practice. If a future migration ever hard-deletes a user, all their notifications vanish silently. Document or downgrade.
- `Notification.{project_id,requirement_id}` is `ondelete="SET NULL"`. Combined with `delete_requirement` archiving notifications first (`requirements.py:623-625`), this prevents orphan notifications with dangling links.
- Unique constraints: `Requirement.code` UNIQUE; `requirements.create_requirement` has 5-iteration retry on IntegrityError. `Delivery (requirement_id, round)` UNIQUE; `delivery_upload.finalize` catches IntegrityError → rolls back status. `RequirementAssignment (req_id, user_id)` UNIQUE; `replace_assignments` deletes-then-inserts so dedup is by construction. `KnowledgeDocument (source_type, source_id)` UNIQUE; `rebuild_knowledge_index` upserts.

### Tombstone filtering — clean for user-facing reads
- Projects: every list/get endpoint in routers I reviewed (projects.py, requirements.py, sync.py, attachments.py, comments.py, chat.py, meetings.py, decompositions.py, reminders.py, notifications.py, planning.py, calendar.py, workspaces.py, knowledge.py, project_drive.py) correctly applies `Project.archived == False, Project.deleted_at.is_(None)` either directly or via `requirement_project_is_active`. The admin-read override correctly short-circuits.
- Users: `display_name` masks the `_deleted_<id8>_` prefix everywhere the model is read. `requirements._display_nickname` + `_assignee_out` apply masking. `lifecycle._resolve_recipients` filters out deleted users from notification recipients. `services/knowledge.py:139-145` filters chat messages of deleted submitters.

### Soft-delete invariants
- Project archived → no new requirements (`requirements.create_requirement:122-125` rejects), no new comments (`comments._require_req` filters), no new chats (`chat._require_req` filters), no new attachments (`attachments._require_req` filters). **Partial gap**: `deliveries.accept_delivery` and `request_revision` (P1-1) skip this filter for already-delivered work.
- User soft-deleted: `forget_user_cookie` rotates `cookie_token` → all browser sessions invalidated. `ClientDevice.revoked_at` set for all devices → worker-token auth fails. Tombstoned `nickname` frees the original. The user retains historical requirements (no FK cascade) — correct.
- Project restore: `projects.restore_project:109-122` clears both `archived` and `deleted_at`. No orphaned associations because nothing was hard-deleted.
- User: NO restore endpoint exists. Soft-deleted users cannot be brought back without manual DB intervention (per `get_or_create_user:227-244` docstring). Acceptable per design.

### Race conditions across boundaries
- Client upload chunk while admin archives: chunk PUT (`attachments.upload_chunk`) does not re-validate project state per chunk (only at `init` and `finalize`). Acceptable — finalize will 404 and cleanup happens via `cleanup_stale_partials`.
- Two users claim same `ready` requirement at exact moment: CAS in `sync.claim:138-149` correctly serializes. Loser gets 409 with current status.
- SSE notification while user being soft-deleted: SSE channel is per-user (`bus.publish(f"user:{user_id}", ...)`). After soft-delete the cookie is rotated → next SSE reconnect fails 401. In-flight already-emitted events are delivered. Notification rows for deleted users remain (cascade on user-delete would clean them but we don't hard-delete). Acceptable.

---

## Conclusion

R7 is a clean revert + read-override restore. The four Codex P0 regressions are confirmed fixed. Foundation (CAS + project-active + tombstone) is sound. The 4 P1 findings are all in surface area Codex didn't actually touch in R6 (deliveries.py accept/revision, dismiss_meeting_insight, _process_meeting rollback ordering, auto.py workdir leak) — i.e. pre-existing weaknesses that are now more visible because the rest of the system tightened around them.

Recommend addressing P1-1 (deliveries archive gate) and P1-3 (dismiss CAS) in R7.1 to close the symmetry. P1-2 and P1-4 are safe to defer.

If 4 consecutive clean rounds is the target, this round is **not clean** in the strict sense, but the gap is narrow and well-scoped. None of the findings are codex-introduced — they predate the R6 review entirely.
