# R7 Round 15 — Backend adversarial

HEAD `580754c`. Confirmation round 2/4. Genuine adversarial effort: I did NOT
re-verify the already-proven CAS/status-guard patterns — I attacked the seams
those proofs don't cover (unhandled IntegrityError on the *other* monotonic
counter, tz-aware datetime round-trip, post-CAS SSE on terminal status,
partial-file orphans on the merge path).

## Verdict: CLEAN (no P1/P2). One P3 + two P3/observational notes below.

No bug found that corrupts state, crashes a hot endpoint, injects, leaks across
the trust boundary, or strands a requirement/job. The streak holds. The single
concrete P3 is reported precisely so it can be triaged, but it does not meet the
P1/P2 bar (no integrity loss, no security impact, narrow same-user trigger).

## Attack: malformed input

- **Nickname** (`auth.py::_validate_nickname`): rejects empty, `_deleted_`
  prefix, and control chars `\r\n\t\x00`; Pydantic bounds `1..64`. UTF-8 CJK /
  emoji allowed by design. Tombstone-prefix squat blocked. SOLID.
- **Project slug**: `pattern=r"^[a-z0-9][a-z0-9\-_]*$"`, `1..64`. No traversal,
  no upper/space. `code = f"{slug.upper()}-{seq:03d}"` — at seq 1000 formats
  `SLUG-1000` (4 digits; `:03d` is a min-width, not a truncation). No overflow,
  `code` stays unique. SOLID.
- **Filenames** (drive/delivery/meeting): every write path funnels through
  `Path(name).name` (`_safe_filename` / `Path(...).name` in meeting init), so
  `../`, absolute paths, and embedded separators collapse to the basename. The
  on-disk name is further namespaced `{version_id}-{name}` / `{idx:06d}.bin`.
  No traversal reachable. SOLID.
- **Inline download MIME** (`download_drive_file`): `_INLINE_SAFE_MIME_PREFIXES`
  excludes svg/html/xml; everything non-safe forced to `attachment` +
  `application/octet-stream` + `X-Content-Type-Options: nosniff`. Stored-XSS
  pivot closed. SOLID.
- **Unbounded text fields (NOTE, not a new finding):** `CommentCreateIn.body`,
  `RequirementCreateIn.raw_description`, `MeetingPatchIn.transcript_text/
  minutes_md`, `ScheduleEvent(Create|Patch)In.description`,
  `ProjectCreateIn.description`, `AnswerIn.text/other_text`,
  `KnowledgeAskIn` is bounded but the chat answers are not. These have
  `min_length=1` (or none) but NO `max_length`, and several fan out over SSE
  (`comment.added` echoes the full body to every `req:{id}` subscriber). There
  is NO global request-body-size middleware (`grep` confirms none). A 500 MB
  comment body would be accepted, persisted, and broadcast — a memory-
  amplification vector. This is consistent with the documented LAN-only "open
  dispatch board" trust model (see `reports/codex_review/security.md`), was not
  newly introduced this round, and is an accepted risk in that threat model —
  flagging only for completeness, not as a regression.

## Attack: concurrency windows

- **Double-submit / double-claim / double-auto-process / double-finalize / two
  meeting-insight-confirms / double-dismiss / status double-PATCH:** every one
  is guarded by an atomic `UPDATE ... WHERE status IN {...}` CAS with
  `rowcount==0 → rollback + 409`. Re-attacked the *insight confirm* path
  specifically: the CAS deliberately also matches `confirmed && created_req IS
  NULL` to let a stranded retry complete, and the requirement-create uses a
  5-try `next_seq` IntegrityError loop. Verified the dismiss CAS mirrors it so a
  confirm can't sneak past a dismiss. SOLID.
- **next_seq collision across the THREE writers** (`create_requirement`,
  `confirm_meeting_insight`, `create_drive_comment`): all three use the same
  5-try `IntegrityError`-on-`code`-UNIQUE retry loop. Verified all three.
- **`ProjectDriveVersion.version_no` allocation — the seam the next_seq proof
  does NOT cover.** See Findings P3-1. This is the one place a monotonic
  counter is `count()+1` with NO IntegrityError catch and NO retry, unlike
  every sibling counter the codebase hardened.
- **Submitter cancels while AI/worker delivers:** `auto.py` re-reads status
  after the LLM and only writes the delivery if still `ai_processing` (else
  short-circuits the job to "succeeded-skipped" + rmtree). `delivery_upload`
  finalize CAS refuses to overwrite a `cancelled` row and reverts on any
  post-CAS failure. SOLID.
- **Admin archives/soft-deletes project mid-AI:** `_run_and_finalize` /
  `_mark_auto_failed` deliberately query WITHOUT the project-active filter so
  the job always settles and the requirement never stays `ai_processing`
  forever. SOLID.

## Attack: partial failure

- **Chunk abandoned midway:** `partial_uploads.cleanup_stale_partials` sweeps
  all four `_partial` staging roots (drive/delivery/meeting/uploads) older than
  24h. SOLID.
- **`os.replace` / Delivery insert fails after CAS** (delivery finalize):
  `_rollback_status` reverts `delivery_doc_pending → prior_status`,
  IntegrityError on `uq_delivery_req_round → 409`, file unlinked on every
  branch. `_finalize_doc` + `_recover_stranded_delivery` give a fresh-session
  second attempt so a `delivery_doc_pending` row can't strand (no job_id to
  drive the restart sweep). SOLID.
- **LLM/ASR mid-stream then disconnect:** `chat_step` wraps `step()` in
  try/except → emits `error` SSE, still re-checks status before writing
  `summary_ready`. `_transcribe_or_decode` swallows the httpx error → plain-text
  decode → default message. Meeting `_process_meeting` rolls back a partially-
  flushed txn before re-querying. SOLID.
- **Disk-full during zip / merge:** auto-agent finalize and delivery finalize
  both route a late-stage exception to a terminal job state. NOTE P3-2:
  `finalize_meeting_upload` writes `out_path` then can raise on a chunk
  size-mismatch / `out.write` IOError before commit; only the explicit
  size-mismatch branch unlinks. A disk-full `out.write` leaves a partial audio
  file orphaned (the MeetingRecord row is rolled back by session close, so it's
  never served). Minor disk leak, swept on no schedule (meeting dir isn't a
  `_partial` root). Low impact.

## Attack: boundary / auth-edge / time-encoding

- **due_at past/future/null:** reminders filter `due_at IS NOT NULL` + `<=
  horizon`; `_kind(minutes)` handles negative (overdue). null due_at blocks
  submit (`DDL is required before dispatch`). SOLID.
- **TIME/ENCODING — tz-aware datetime (the headline attack):** all datetime
  columns are plain `DateTime` (NOT `DateTime(timezone=True)`). I empirically
  tested SQLAlchemy 2.0.48 + SQLite: an aware `+08:00` datetime is stored as the
  naive components (offset dropped) and reads back **naive**, so
  `reminders.py:64` `req.due_at - datetime.utcnow()` (naive − naive) does NOT
  raise `TypeError`. The offset-drop is a correctness quirk (DDL stored at wall-
  clock, not converted to UTC) but benign in a single-timezone LAN office, and
  crucially is NOT a crash. `drive_changes` even normalizes `since` to naive
  before comparing. No aware/naive crash path exists. SOLID.
- **User deleted mid-session:** `current_user` / `require_stream_user` filter
  `deleted_at IS NULL`; `delete_user` rotates `cookie_token` (kills cookies),
  revokes all ClientDevice rows (kills worker token), drops admin, tombstones
  nickname, refuses self-delete + last-admin. Worker token after revoke →
  `_user_from_worker_token` filters `revoked_at IS NULL`. SOLID.
- **Soft-deleted project's requirement via old assignee:** every requirement
  router goes through `_ensure_requirement_project_active` /
  `_require_project` (archived==False, deleted_at IS NULL) → 404. SOLID.
- **Admin flag toggled mid-request:** `set_user_admin` refuses last-admin
  revoke and refuses soft-deleted targets. Per-request `is_admin` read is
  point-in-time — acceptable. SOLID.

## Findings

### P3-1 — `ProjectDriveVersion.version_no` race: unhandled IntegrityError → 500 + orphan file (NOT P1/P2)
`app/routers/project_drive.py:848` in `finalize_drive_upload`:
```python
version_no = (db.query(ProjectDriveVersion).filter(ProjectDriveVersion.item_id == item.id).count() or 0) + 1
```
`ProjectDriveVersion` has `UniqueConstraint("item_id","version_no")`
(`models.py:194`). Two concurrent `conflict="replace"` finalizes on the SAME
existing file (same user, two upload sessions — e.g. a double-click on the
"replace" confirm that fires two completed uploads) both `count()` before either
commits, both compute `N+1`. The merge loop (line 865) writes the full file to
`final_path` BEFORE the `commit()` at line 901. The second `commit()` raises
`IntegrityError` on `uq_project_drive_version_no`, which is **uncaught** (no
global exception handler in `main.py`; `get_db` only `close()`s) → the client
sees a raw **500**, and the merged file (`{version_id}-{filename}`, a unique
path so the two don't collide) is **orphaned on disk** (the drive file dir is
not a `_partial` sweep root).

Why P3, not P2: the unique constraint *preserves* integrity (no duplicate
version_no, no data corruption); no security impact; same-user-only trigger.
The defect is (a) a 500 where a clean 409 "refresh and retry" is expected, and
(b) a small disk leak. Notably this is the SAME class the codebase already
hardened for the analogous `Delivery.round` (IntegrityError → 409,
`delivery_upload.py:317-320`) and the three `next_seq` writers (5-try loops),
so the fix would mirror an existing in-repo pattern — wrap the version insert in
an IntegrityError handler that unlinks `final_path` and returns 409 (or re-reads
the count and retries).

### P3-2 — meeting finalize partial-file orphan on disk-full (low, observational)
`app/routers/project_drive.py` n/a — `app/routers/meetings.py:261-272`: a disk-
full `out.write` during the chunk merge raises before `commit()`; only the
explicit `total != total_size` branch (line 273-274) unlinks `out_path`. The
MeetingRecord/job rows are rolled back by session close (no orphan row, nothing
served), but the partial audio file is left in the (non-swept) meeting dir.
Low impact; symmetry with the delivery-merge cleanup would close it.

### P3-3 — auto-fail SSE re-broadcasts `requirement.ready` even when user cancelled (observational)
`app/routers/auto.py:259-264`: in the AI-failure branch, `r.status = "ready"` is
gated on `r.status == "ai_processing"`, but the `requirement.ready` /
`requirement.updated status=ready` SSE publishes at lines 259-264 fire
unconditionally. If the submitter cancelled mid-AI, the DB row stays `cancelled`
(correct) but clients receive a spurious "available again" broadcast. Self-
heals on next fetch (clients re-read the cancelled row); pure UI flicker, no DB
inconsistency. Mentioned for completeness.

---
Effort summary: read schemas/models/auth/db + lifecycle/assignments and the 8
mutating routers (requirements, sync, auto, delivery_upload, meetings, comments,
users, project_drive, chat) in full; empirically tested the aware-datetime
round-trip against the repo's actual SQLAlchemy 2.0.48; traced the version_no /
next_seq / Delivery.round counter trio for handler symmetry; confirmed absence
of a global body-size middleware and exception handler. No P1/P2. CLEAN.
