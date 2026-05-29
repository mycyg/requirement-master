# R7 Round 16 — Backend verify + adversarial re-sweep

HEAD `edfb4fd` (R7.15), branch `fix/r6-hardening`. Confirmation round 3/4.
Verified the three R7.15 backend fixes line-by-line, then attacked from fresh
angles (concurrency, partial-failure, the SQLite write-lock window across the
merge, the *other* chunked-upload finalizers R7.15 did NOT touch).

## Verdict: CLEAN

No new P1/P2 and no regression. All three R7.15 fixes are correct. The fresh
sweep surfaced one P3 disk-leak that is (a) pre-existing, not introduced by
R7.15, and (b) the *same class* the R15 report already filed as P3-2 for
meetings — R7.15 fixed the meeting instance and left the two siblings
(attachments, drive merge). It does not meet the P1/P2 bar (no integrity loss,
no security impact, no stranded DB row, file never served). Streak holds.

## R7.15 fix verification

### Fix 1 — `project_drive.py::finalize_drive_upload` version_no retry — CORRECT
- **5-try IntegrityError loop (lines 859-884):** mirrors the in-repo `next_seq`
  /`Delivery.round` pattern. On the loser of a concurrent `replace`, flush at
  873 raises on `uq_project_drive_version_no`; rollback at 877; recompute count
  at 860 (now sees the committed winner's row → N+1); retry. After 5 fails →
  clean 409, never a 500.
- **Rollback re-loads `item` by id (line 880):** safe for `replace` (the item
  is a *committed* row, still exists). For `upload_new` the IntegrityError
  branch is genuinely **unreachable**: the item is a fresh UUID, `count()` for
  that item_id is always 0 → version_no=1, and the only unique constraint on
  `ProjectDriveVersion` is `(item_id, version_no)` — a globally-unique item_id
  cannot collide. Verified `ProjectDriveVersion.__table_args__` has only
  `uq_project_drive_version_no` (models.py:194). Even if some *other* error hit
  flush on `upload_new`, the rollback discards the uncommitted item and the
  re-load returns `None` → clean 409 (line 882), never a 500/orphan. SOLID.
- **File merge AFTER the flush (lines 887-898):** confirmed the merge sits past
  the loop `break`; a retry only repeats the cheap count+insert, never writes
  the file. "Retry costs nothing on disk" — correct.
- **`version` guaranteed non-None or 409 (lines 883-884):** the `if version is
  None` guard catches the all-5-attempts-failed case. Correct.
- **No orphan version row:** the loser's candidate is discarded by rollback;
  only the winning flush survives. `previous_version_id` (captured at 834,
  before the loop, as a plain str) is unaffected by the rollback and is used
  correctly in `_record_op` at 918. SOLID.
- **Confirmed NOT a regression:** the pre-R7.15 code (`580754c`) also flushed
  the version row before the merge and held the SQLite write transaction across
  the merge. R7.15's diff touches ONLY the allocation block (lines 845-884), not
  the merge below. The write-lock-held-across-merge window (a concurrent replace
  blocks up to `busy_timeout=5000` then could OperationalError-500) is identical
  to every prior round and is implicitly accepted; R7.15 strictly *improves* the
  loser's outcome from raw-500 to retry→409.

### Fix 2 — `auto.py::_run_and_finalize` failure-branch broadcast gating — CORRECT
- **`reverted_to_ready = r.status == "ai_processing"` (line 242)** gates the
  `requirement.updated:ready` + `requirement.ready` broadcasts (lines 267-273).
  Traced every reachable status of `r` at that point: an `ai_processing`
  requirement can only transition out via user-cancel (→`cancelled`) while the
  AI runs — there is no path to `delivered`/`claimed`/etc. mid-run. So the flag
  is exactly two-valued (`ai_processing`→revert+announce; `cancelled`→silent).
  **No path where `reverted_to_ready` is wrong.**
- **`ai.failed` still unconditional (lines 259-261):** `f"req:{req_id}"`-scoped,
  only the submitter's own RequirementDetail stream sees it; harmless on a
  cancelled req (no org-wide toast). Correct.
- **Symmetric path `_mark_auto_failed` (line 356):** its `requirement.ready` is
  reached only after the `r.status != "ai_processing"` early-return guard (line
  318), so it too is gated on a genuine in-flight revert. Consistent with the
  fix. The `r` here is loaded WITHOUT a project filter (correct — must settle on
  archived/soft-deleted projects). SOLID.

### Fix 3 — `meetings.py::finalize_meeting_upload` orphan guard — CORRECT
- **Chunk sizes pre-validated before `open()` (lines 263-265):** every chunk's
  `st_size` is checked against `_expected_chunk_size` before `open(out_path)` at
  268. A bad chunk raises before any output file is created. Correct.
- **`try/except BaseException` unlinks on ANY failure (lines 279-283):** catches
  disk-full `OSError`, the size-mismatch `HTTPException`, and BaseException-only
  signals (`KeyboardInterrupt`/`SystemExit`/`CancelledError`) — on a worker kill
  mid-write the `out_path.unlink(missing_ok=True)` runs then re-raises. No
  orphan on disk-full / size-mismatch / kill. Correct.
- **Does NOT interfere with success:** the `except` only fires on a raised
  exception; on normal completion control falls through to line 284. Verified.
- **No orphan DB row either:** `create_job` (jobs.py) and the MeetingRecord both
  only `flush()`, never commit, before the merge — on a merge failure the
  request session is closed by `get_db` and the uncommitted rows roll back. So
  no orphan job/meeting row and no served-but-missing file. SOLID.

## Fresh adversarial sweep

- **Other `count()+1` allocators:** enumerated all `.count()` callers.
  - `auto.py:183` (`round_num = 1 + count(Delivery)`): NOT concurrently
    reachable — `trigger_auto` CAS-transitions to `ai_processing` (single writer
    per req); rounds are sequential (round 1 commits `delivered` before a
    re-dispatch can trigger round 2); a manual delivery (`delivery_doc_pending`
    source statuses) and an AI delivery (`ai_processing`) are mutually exclusive
    statuses. Even on the theoretical collision the insert sits inside the
    `except Exception` → `db.rollback()` → `_mark_auto_failed` recovery, which
    correctly reverts `ai_processing`→`ready`. Guarded by `uq_delivery_req_round`
    for integrity. Not a hazard.
  - `delivery_upload.py:265` (`round_num = 1 + count(Delivery)`): wrapped in
    `try/except IntegrityError → 409` (lines 317-320) with `_rollback_status`
    + `out_path.unlink`. Guarded. Not a hazard.
  - `project_drive.py:860`: now the 5-try loop (Fix 1). Guarded.
  - `users.py:120,154` + `health.py:34,48`: read-only guard checks / stats, NOT
    value allocations — never write `count()+1`. The users.py "last admin" check
    is a benign recoverable TOCTOU, not integrity-critical (accepted prior).
- **Other unconditional `requirement.ready` / org-wide broadcasts:** the only
  three emitters are auto.py:270 (Fix 2, gated), auto.py:356 (gated by the
  `ai_processing` guard), and sync.py:81 (CAS-gated dispatch, `summary_ready/
  ready→ready`, rowcount==0→409 before broadcast). All other
  `requirement.updated` publishes (requirements.py status-PATCH:360-361,
  decompositions.py:194/241, deliveries, comments.py:70 `comment.added`) are
  CAS-gated and are benign status echoes (a re-fetch), not the org-wide-toast
  `requirement.ready` class. No unconditional re-announce of a dead requirement.
- **Other chunked-upload finalizers (the seam R7.15 only partially closed):**
  See P3-1 below. `attachments.py::finalize` and `::upload_simple`, and the
  `project_drive.py` merge itself, write directly to the *final* path and only
  `os.unlink` on the explicit size-mismatch branch — a disk-full `out.write`
  orphans the file. `delivery_upload.py` is immune (writes a tmp then
  `os.replace` — the final name only appears after a complete write).
- **Concurrency re-attack (already-proven CAS not re-verified):** spot-checked
  the meeting insight confirm/dismiss CAS pair and the status-PATCH CAS — all
  `rowcount==0→rollback+409`. No new window.
- **Auth-edge:** chunk/finalize ownership (`meta.user_id == user.id`) +
  project-match checks present on drive/meeting/attachment chunk + finalize. No
  cross-project pivot. `bulk_download` re-checks each item's project. Unchanged.

## Findings

### P3-1 — orphan-file-on-disk-full in attachments + drive merge (pre-existing, same class as R15 P3-2; NOT P1/P2)
R7.15 added a `try/except BaseException: out_path.unlink()` guard to
`meetings.py::finalize_meeting_upload` (the instance R15 filed as P3-2) but left
the two structurally-identical siblings:
- `app/routers/attachments.py:206-219` (chunked finalize) and `:277-288`
  (`upload_simple`): the merge `out.write(buf)` can raise `OSError` (disk full)
  mid-write; the `os.unlink(final_path)` at 218/284 fires only on the explicit
  *size-mismatch / size-cap* branch, which is unreachable when the write itself
  raises → the partial `final_path` is orphaned.
- `app/routers/project_drive.py:889-901` (drive finalize merge): same — only the
  `total != total_size` branch (line 900) unlinks; a disk-full `out.write` at
  896 orphans `final_path`.

Why P3, not P2: identical reasoning to R15's P3-2 — in every case the
`Attachment`/`ProjectDriveVersion`+`ProjectDriveItem` rows are added/flushed but
NOT committed until *after* the merge (attachments commit at 248, drive commit
at 925), so a merge failure rolls them back on session close. No DB row ever
references the orphan → it is never served, no integrity loss, no stranded
requirement, no security impact. Pure disk leak in a dir that is not a `_partial`
sweep root (so never reclaimed). Pre-existing (drive merge is byte-identical in
`580754c`; attachments last touched `e1c008c`, untouched by R7.15) — **not a
regression**. The clean fix mirrors the meeting guard R7.15 just shipped, or the
`delivery_upload` tmp+`os.replace` pattern.

---
Effort summary: read the three target routers in full + `db.py` (WAL/
busy_timeout isolation model), `jobs.py` (commit semantics), `models.py`
constraints, and the remaining mutating routers (requirements, sync,
decompositions, comments, delivery_upload, attachments, users). Diffed
`580754c..edfb4fd` for drive + attachments to separate R7.15 changes from
pre-existing code. Confirmed absence of a global exception handler/middleware in
`main.py`. Traced the version_no rollback re-load for both `replace` and
`upload_new`, the `reverted_to_ready` reachable-status set, and the meeting
BaseException guard's success-path non-interference. All three R7.15 fixes
correct; no P1/P2; no regression. CLEAN.
