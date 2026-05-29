# R7 Round 18 — Data-integrity frozen confirmation

HEAD `3dcf440` (R7.17), branch `fix/r6-hardening`. Frozen-tree backend +
data-integrity confirmation. R7.17 was frontend-only; no backend file changed
since R7.16 (verified `git log` of touched files). Re-swept the full data layer
from source, not from prior reports, across all seven requested invariants.

## Verdict: CLEAN (no P1/P2)

No P1 or P2 finding. The tree does not change. The data layer is consistent
with the 15 prior confirmations. One pre-existing P3 (non-blocking, unchanged
risk class) is noted below; it has been implicitly accepted in earlier rounds.

## CAS / terminal-state / FK / migration / dedupe / N+1 status

### CAS race-safety — CLEAN
Every status/state mutation uses the same `UPDATE … WHERE id=? AND status=old`
+ `rowcount==0 → rollback → re-read → 409` pattern. No lost update, no double-act:
- `requirements.py:310` PATCH /status (allowed-transition table + worker-role gate, then CAS).
- `sync.py:59` submit (ready/summary_ready → ready); `sync.py:138` claim (ready → claimed).
- `auto.py:84` auto-process (summary_ready/ready → ai_processing).
- `deliveries.py:172` accept (delivered → accepted); `deliveries.py:226` revision (delivered → revision_requested) — mutually exclusive winners.
- `delivery_upload.py:250` finalize (claimed/doing/revision_requested → delivery_doc_pending).
- `decompositions.py:176` confirm / `:224` dismiss (both draft-only CAS).
- `meetings.py:461` confirm-insight (pending OR confirmed-without-requirement) / `:555` dismiss (pending-only).
All five monotonic allocators are IntegrityError/CAS-guarded with per-attempt
`db.rollback()` + ORM re-load: `create_requirement` next_seq (requirements.py:118,
5-try), `confirm_meeting_insight` next_seq (meetings.py:486, 5-try), drive
comment-agent draft next_seq (project_drive.py:1400, 5-try), `finalize_drive_upload`
version_no (project_drive.py:856, 5-try on `uq_project_drive_version_no`),
`Delivery.round` (count+1 guarded by `uq_delivery_req_round` → IntegrityError→409
in delivery_upload.py:317, and CAS-gated single-writer in auto.py:183).

### Terminal-state reachability — CLEAN
No requirement/job/meeting/ask can be permanently stranded:
- `_resume_stuck_jobs` (main.py:99) boot sweep: stale `running` jobs → failed +
  revert ai_processing→ready / delivery_doc_pending→delivered; jobless
  delivery_doc_pending → delivered (+delivery_doc_ready_at backfill); processing
  meetings → failed; running asks → failed. Committed once, logged.
- `_run_and_finalize` (auto.py:107) wraps the post-LLM finalize in try/except →
  `_mark_auto_failed`, which is status-aware (won't clobber a committed
  `delivered`, only settles the job). Cancel-mid-AI guarded at :166 and :242.
- delivery_upload finalize: `_rollback_status` (delivery_upload.py:272) reverts
  the CAS + unlinks the file on os.replace / Delivery-insert / commit failure.

### FK integrity — CLEAN
- `delete_requirement` (requirements.py:644-657) explicitly NULLs the SET-NULL
  cross-refs that legacy SQLite tables may still hold under NO ACTION
  (ProjectDriveComment.draft_requirement_id, MeetingInsight.target/created,
  Requirement.source_requirement_id) before `db.delete(r)`. Notifications
  archived first to kill dead deep-links.
- `meeting_records.requirement_id` is NOT null'd in app code — verified safe:
  the table's CREATE TABLE has carried `ON DELETE SET NULL` since its first
  commit (`30812c2`), so no install ever has NO ACTION there; the DB handles it.
  Same for `Notification.requirement_id` (DB-level SET NULL; the archive is UX).
- User delete is soft-delete only (users.py:85) — tombstone nickname + rotate
  cookie + revoke devices; no hard delete → no orphaned FK to users.id.
- Boot orphan null-out (schema_migrations.py:643-667) covers the 5 cross-ref
  columns so a pre-`foreign_keys=ON` orphan can't block a future UPDATE.

### Transaction-across-await — CLEAN
Every `await` (publish_job / bus.publish / flush_status_notifications /
publish_notification / auto_process / to_thread) fires AFTER `db.commit()`.
The lifecycle contract is enforced: `queue_status_notifications` (sync, no
commit/publish) → `db.commit()` → `flush_status_notifications` (await). Spot-
checked requirements/sync/deliveries/auto/meetings/delivery_upload — no write
held open across a suspension point. Sync-context publishes use the anyio
`from_thread` bridge with poll-delivery fallback (notifications.py:108).

### Migration idempotency — CLEAN
`ensure_runtime_schema` (schema_migrations.py) is all `ADD COLUMN`-if-absent,
`CREATE TABLE/INDEX IF NOT EXISTS`, `INSERT OR IGNORE`, and idempotent UPDATEs.
Re-run-safe with no data loss. The owner_user_id backfill keeps the
`u.created_at <= projects.created_at` guard, so a recycled nickname cannot
inherit a legacy NULL-owner project. Assignment backfill uses INSERT OR IGNORE
against `uq_requirement_assignment_user`.

### Notification dedupe — CLEAN
`create_notification` (notifications.py:43) keeps the read-stickiness fix:
on a dedupe_key hit it only resurfaces (clear read/archived + bump updated_at +
re-push) when content actually changed; identical re-fires return the existing
row untouched, so `_ensure_due_notifications` polling can't make a read item
stick unread. dedupe_key includes actor id so a revision→doing→revision cycle
by two workers is two genuine events, not a silent overwrite.

### N+1 / unbounded hot-path — CLEAN
- `drive_manifest` / `drive_changes` (project_drive.py:631/657): exactly 2
  queries via `_build_manifest_maps` (item_map + version_map IN-clause), then
  in-memory render through `_item_path_from_map` / `version_map.get`. No per-
  item or per-ancestor query. 50000-item cap warns (not silently truncates).
- `calendar.list_events` (calendar.py:69): SQL-only visibility filtering
  (aliased project joins + EXISTS for assignment), `selectinload(created_by)`,
  hard `.limit(500)`. No N+1 post-filter loop.
- `sync_manifest.build` is single-requirement scoped (on-demand tray fetch, not
  a fan-out poll); bounded per call.

## P3 notes (non-blocking)
- P3-1 (pre-existing, unchanged): the success-path delivery merge in
  `finalize_drive_upload` / attachment + delivery finalizers hold the SQLite
  write transaction across the file merge window; a concurrent writer can wait
  up to `busy_timeout=5000ms` then OperationalError-500. Same class accepted in
  every prior round (R7.16 backend-adversarial filed the disk-leak sibling as
  P3). No integrity loss, no stranded row, file never served on the loser path.
  Not introduced or worsened by R7.16/R7.17. Tree-freeze threshold not met.
