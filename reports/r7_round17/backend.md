# R7 Round 17 — Backend freeze confirmation

HEAD `f360bef` (R7.16). Read-only review. No code written/edited.

## Verdict: CLEAN (no P1/P2)

R7.16's three merge guards are correct and the full sweep surfaces no P1/P2.
The tree is ship-ready at this freeze point. P3 notes (non-blocking) below.

## R7.16 merge-guard verification

The three new guards verbatim-match the R7.15 meetings pattern
(`meetings.py:267-283`: pre-validate → write-inside-try → validate-inside-try →
`except BaseException: <path>.unlink(missing_ok=True); raise`). delivery_upload
is independently immune via `tmp_path` + `os.replace` (`delivery_upload.py:199,
288`). All four upload merges are now consistent.

1. attachments.finalize_upload — `attachments.py:206-223`
   - Chunk set + per-chunk sizes pre-validated BEFORE the `try`/`open`
     (`:183-196`), so a bad-chunk raise can't strand a half-merged blob.
   - Success path: writes, then size-check INSIDE try; on match, falls through
     to `sha = h.hexdigest()` (`:225`) with no unlink. Correct — no swallowed
     success.
   - Failure path: disk-full mid-write OR the size-mismatch HTTPException
     (now raised at `:218`, inside try) → single `final_path.unlink(missing_ok
     =True)` (`:222`) → `raise` re-raises the ORIGINAL exception (including the
     400 size-mismatch). Status code preserved.
   - No double-unlink: the old `os.unlink(final_path)` before the raise is gone;
     exactly one unlink in the `except`. Verified only-unlink in file at
     `:156,161,222,295` — none on the success path of this fn.

2. attachments.upload_simple — `attachments.py:281-296` (async)
   - Over-size branch (`:287-288`) now raises the 413 HTTPException INSIDE the
     try; the old `out.close(); os.unlink(...)` is removed. The `with open(...)`
     context closes the handle on the way out of the block (exception unwinds
     it), then the `except` unlinks once and re-raises the 413. Correct — no
     double-unlink, status 413 preserved.
   - Covers disk-full + client-disconnect mid-stream too (both land in the
     `except`). Success path falls through to `Attachment(...)` (`:298`) with no
     unlink.

3. project_drive.finalize_drive_upload — `project_drive.py:889-908`
   - Same shape; version_no allocation + flush (`:859-884`) happen BEFORE the
     merge, rows uncommitted at merge time → roll back on any later failure, so
     only the on-disk blob needs the unlink. Comment is accurate.
   - Success path → `version.storage_path = str(final_path)` (`:910`), no unlink.

`except BaseException` vs `except Exception`: CORRECT here. For the async
upload_simple, a client disconnect surfaces as `asyncio.CancelledError`
(a BaseException, not Exception); catching it is exactly what cleans up the
orphan, and the immediate `raise` re-propagates cancellation untouched — nothing
is swallowed. KeyboardInterrupt/SystemExit likewise pass through after cleanup.
The two sync fns (`def`) won't see CancelledError but BaseException is harmless
and keeps the family uniform. No behavioral risk.

No double-unlink, no swallowed success, no interference with the success path in
any of the three. delivery_upload untouched and already immune.

## Full sweep status

- CAS / concurrency: status transitions use CAS (`delivery_upload.py:253-263`
  reverts on `rowcount==0`; chat terminal-status guard `chat.py:187,229`). No
  new gaps.
- Background-task terminal states: every bg path reaches succeeded/failed via
  try/except — `_process_meeting` (meetings.py:346-359), `_finalize_doc`
  (delivery_upload.py:393-407 → `_recover_stranded_delivery`), `_run_and_finalize`
  (auto.py:279-294 → `_mark_auto_failed`, status-aware), decompositions/knowledge
  (`status="failed"` on except). `update_job` stamps `finished_at` on terminal
  (jobs.py:56-57).
- Zombie jobs: two detached `asyncio.create_task` finalizers (auto.py:103,
  delivery_upload.py:343) both have top-level except → terminal recovery. Boot
  sweep `_resume_stuck_jobs` (main.py:99-129) reverts running>cutoff jobs +
  ai_processing/delivery_doc_pending requirements. Periodic loops cancelled +
  awaited on shutdown (main.py:212-220). No zombie path found.
- The 4 monotonic allocators — all retry-guarded with the IntegrityError loop:
  requirements.create next_seq (requirements.py:118-189), meetings confirm
  next_seq (meetings.py:486-527), drive-comment next_seq (project_drive.py:1400-
  1434, comment committed first → never lost), drive version_no
  (project_drive.py:859-884, `uq_project_drive_version_no`). The 5th, auto.py
  Delivery round (auto.py:183 count+1), is structurally single-flight (gated by
  `r.status=="ai_processing"`, race-checked at :166) AND DB-protected by
  `uq_delivery_req_round` (models.py:517) with the collision caught via auto.py's
  generic except → `_mark_auto_failed`. Safe.
- Permissions matrix (permissions.py): READ paths give admin a pre-filter bypass
  (including project-active); WRITE paths keep the project-active filter before
  the admin check. Consistent with the documented contract. No privilege gap.
- LLM parse fail-closed: meeting_agent (:101,131,137-139 → `_fallback`, flagged
  "建议人工确认", never auto-confirms), task_decomposition (:105,131,133-135 →
  `_fallback`), drive_comment_agent (:98-100 raises RuntimeError → caller
  project_drive.py:1367-1380 commits comment as "review_failed", NO auto draft).
  All fail-closed; no path silently materializes a requirement on parse failure.
- No txn-across-await: SQLite single-writer discipline holds. `_process_meeting`
  commits before each `await` (meetings.py:313,319,343). create_drive_comment
  commits the pending row before `await classify_drive_comment` (project_drive.py
  :1366-1368). No open transaction spans an LLM/network await.
- Migration safety: schema_migrations.ensure_runtime_schema is idempotent —
  PRAGMA-guarded ALTERs, `CREATE TABLE/INDEX IF NOT EXISTS`, `INSERT OR IGNORE`,
  all in one `engine.begin()`; owner backfill has the `created_at <=` guard
  against recycled-nickname re-inheritance (sqlite-only, no-op elsewhere).

## P3 notes (non-blocking — will NOT change the tree)

- P3 (disk-leak edge, pre-existing, out of R7.16 scope): the chunk-RECEIVE
  handlers `upload_chunk` (attachments.py:146-159) and the drive equivalent
  (project_drive.py ~:792) use `except HTTPException` (not BaseException), so a
  client disconnect mid-chunk-stream (CancelledError) leaves that one `*.bin`
  temp chunk in `pdir`. It is NOT a merge orphan — it's swept by
  `cleanup_stale_partials` on boot, the periodic partial cleanup, and
  `shutil.rmtree(pdir)` on finalize. Same disk-leak class R7.16 closed for the
  merge family; harmless, eventually reclaimed. Mentioned only for completeness.
- P3 (observability): the disk-full unlink in the four merge guards is silent
  (no log line on cleanup). A `logger.warning("cleaned orphan after merge fail
  …")` would aid post-incident triage. Cosmetic.
- P3 (consistency nit): meetings/attachments/drive guards comment "(disk full,
  size-mismatch, a kill)"; "a kill" reads slightly informally but is accurate
  (KeyboardInterrupt/SystemExit are BaseExceptions and ARE cleaned up). No action
  needed.

Nothing in P3 blocks ship or alters behavior. Freeze confirmed: CLEAN (no P1/P2).
