# R7 Round 11 — Backend (verify R7.10 + final sweep)

HEAD `6693426` (R7.10). Goal: prove the R7.10 finalize-zombie fix (F1) introduced
no regression in the intricate async/transaction logic, then a fresh sweep.

## Verdict: CLEAN

The R7.10 fix is correct on every path I traced. It does not just close the F1
zombie window — it also fixes a *latent* stale-broadcast bug in the old
`_mark_auto_failed` (see item 1, "behavioral improvement"). No regression found.
No new findings in the fresh sweep. **Production-ready.**

---

## R7.10 finalize-fix regression check (4 items)

### 1. `auto.py _mark_auto_failed` — status-aware, 3 branches — CORRECT

Branches (lines 298-350), every one settles the job and never leaves it running:

- **(a) requirement gone** (`not r`, 299-308): if `job_id` and job not already
  terminal → `update_job(status="failed", message="需求已不存在")` + `db.commit()`
  + `publish_job` + `return`. Job settled. No requirement write (nothing to
  write). ✔
- **(b) status ≠ ai_processing** (309-330): re-queries the job; if not terminal,
  `delivered = r.status in {"delivered","accepted"}` → settles `succeeded`
  (delivered/accepted, `error=None`) or `failed` (everything else,
  `error=reason`), commits, publishes, returns. **Does NOT touch `r.status`** —
  the committed `delivered` requirement is not clobbered. ✔ The `delivered`
  requirement → job `succeeded` is exactly right (the delivery is durable; only
  a late SSE/job-row write failed). ✔
- **(c) status == ai_processing** (331-350): `r.status = "ready"` + `ai_failed`
  activity + `update_job(failed)` + single `db.commit()` + `publish_job` (guarded
  `if job_id and job`) + the 4 `ai.failed`/`ready`/`requirement.ready` bus
  broadcasts. This is the in-flight revert. ✔

**Double-publish:** every job settle is gated on `job.status not in
{"succeeded","failed"}` (304, 318) or, in branch (c), on a fresh job lookup
(338). A job already settled by the inline path is never re-published. ✔

**Original caller (line 147, LLM-call-failure path) still correct:** at that
call site `auto_process()` raised during setup/LLM, so the DB status is still
`ai_processing` (set by the CAS in `trigger_auto`, never changed). `_mark_auto_
failed` re-queries → branch (c) → revert to `ready` + breadcrumbs + fail job +
broadcast. Identical to pre-R7.10 behavior for this case. ✔

**Behavioral improvement (not a regression):** when this path is hit for a
requirement the user *cancelled* mid-run (status `cancelled`), the OLD code
(`a6f8ada`) still ran `db.commit()` and then broadcast
`requirement.updated:{status:"ready"}` + `requirement.ready` to ALL clients —
i.e. it told every connected user a *cancelled* requirement was now "ready". The
new branch (b) settles only the job (per-job + owner channel) and emits NO
misleading global `ready` broadcast and no `ai_failed` activity row against a
deliberately-cancelled req. Strictly more correct.

### 2. `auto.py _run_and_finalize` except — CORRECT

- **Rollback before `_mark_auto_failed`:** the `except` (270-285) calls
  `db.rollback()` in its own try/except (281-284) so a poisoned session can't
  re-raise, THEN `_mark_auto_failed`, which opens a **fresh** `SessionLocal()`
  (291) — so even if the rollback silently failed, the recovery session is
  independent. ✔
- **Inline success path AND except cannot both run:** the success path's last
  statement is `shutil.rmtree` (269); the failure-branch ends with `return`
  (266). Any raise in 161-269 jumps straight to `except` and the remaining inline
  statements do not execute. There is no state where the delivered-publish AND
  the failure-recovery both fire. ✔
- **Post-commit failure window handled correctly:** if `db.commit()` at 226
  already made the requirement `delivered`, a later raise (job-update commit 231,
  or `bus.publish` 235-236) routes to `_mark_auto_failed` → branch (b) → job
  `succeeded`, requirement untouched. (`flush_status_notifications` at 234 cannot
  raise — it swallows every per-row error internally, lifecycle.py:170-173 — so
  it never triggers the except.) ✔
- **`finally: db.close()` still runs** (286-287) after inline completion OR the
  except. `_mark_auto_failed` uses its own session, so closing `db` is safe. ✔
- **`logger` defined:** auto.py:27 `logger = logging.getLogger(__name__)` (added
  R7.10); `logging` imported at line 7. `logger.exception` at 280 resolves. ✔

### 3. `delivery_upload.py _finalize_doc` + `_recover_stranded_delivery` — CORRECT

- **Fresh session:** `_recover_stranded_delivery` opens its own `SessionLocal()`
  (410), independent of the rolled-back `_finalize_doc` session. ✔
- **Idempotent:** re-queries by `delivery_id`; the status flip is guarded by
  `if r and r.status == "delivery_doc_pending"` (419). If the main path already
  committed `delivered`, this guard is false → `pending=[]`, no notification
  queued, `flush_status_notifications([])` is a no-op. ✔
- **No double-notify if main path partially succeeded:** the only realistic
  post-commit failure point is `bus.publish` at 379-385 (commit 375 and the
  error-swallowing flush 378 don't re-raise into the except). In that case the
  recover finds status `delivered`, skips the notification block, and only
  re-emits the idempotent `requirement.updated` broadcasts. Even if a `delivered`
  notification were re-queued, `create_notification` dedupes on
  `dedupe_key="delivered:{req}:ai-finalize"` (lifecycle.py:159 +
  notifications.py:42-48) with the *same* synthesized actor id, collapsing to
  one. ✔
- **Fallback doc logic:** sets `d.delivery_doc_md = fallback_doc` only
  `if not d.delivery_doc_md` (415). On a pre-commit failure the in-session doc
  assignment (361) was rolled back, so the column is empty → fallback applied; on
  a post-commit failure the doc is already persisted → fallback skipped. ✔
- **Double-failure just logs:** the inner `except` (433-436) only
  `logger.exception`s and relies on the startup `delivery_doc_pending` backstop.
  No raise escapes the detached task. ✔
- **`logger` defined:** delivery_upload.py:32. ✔

### 4. `main.py _resume_stuck_jobs` job-less backstop — CORRECT, no conflict

- **No overlap with the job-driven path in practice:** a `delivery_doc_pending`
  requirement is ONLY produced by the manual `delivery_upload` finalize endpoint,
  which carries **no BackgroundJob** (`create_job` is called only in auto.py,
  decompositions.py, knowledge.py, meetings.py — verified by grep; never in
  delivery_upload). The job-driven branch (117-129) reverts a req only via a
  stale job's `result_ref`, so it can never reach a manual-delivery
  `delivery_doc_pending`. The auto.py path writes `delivered` directly, never
  `delivery_doc_pending`. So the two paths address disjoint rows. ✔
- **Even the theoretical overlap is safe:** `SessionLocal` has
  `autoflush=False` (db.py:43), so the `stale_deliveries` SELECT does not flush
  the job-loop's pending `req.status="delivered"` and could re-match the row in
  the DB — BUT SQLAlchemy's identity map returns the SAME already-mutated
  in-session object, so the second `req.status = "delivered"` is a no-op. No
  corruption; the only effect is a slightly inflated count (the job-loop reverts
  aren't separately counted anyway). ✔
- **Commit/count logic:** `total = jobs + deliveries + meetings + asks` (167);
  single `db.commit()` only `if total` (168-169); log message updated to include
  `%d deliveries`. ✔
- **Premature-sweep guard:** filter is `status=="delivery_doc_pending" AND
  updated_at < cutoff(now-15min)`. `updated_at` has `onupdate=func.now()`
  (models.py:22-23, fires for the Core `update().values(...)` that sets
  `delivery_doc_pending` at delivery_upload.py:256). A live req <15min old is
  never swept; a >15min-old one means the previous process's `_finalize_doc`
  died (the current process spawns no live task for it). No race with a running
  task (sweep runs once at boot, before any task is created). ✔
- **Degradation note (acceptable, not a bug):** the backstop flips to
  `delivered` WITHOUT firing the "等你验收" notification (unlike
  `_recover_stranded_delivery`). This is intentional — re-notifying for
  arbitrarily-old deliveries at restart would be stale/noisy; the zip + Delivery
  row are intact and manual review works. Documented in the comment.

---

## Double-handling / double-publish check

- **auto.py:** job settle is idempotent (gated on non-terminal job status or a
  fresh re-query); inline-success vs except are mutually exclusive; post-commit
  `delivered` is never clobbered → at most one terminal job write, one set of
  requirement broadcasts. No double-publish.
- **delivery_upload.py:** `_finalize_doc` main → `_recover_stranded_delivery` →
  startup backstop form a 3-tier ladder, each guarded by
  `status == "delivery_doc_pending"` (or, for the recover, the dedupe_key). Once
  any tier flips to `delivered`, the next tier is a no-op. Notification dedupe
  (`delivered:{req}:ai-finalize`) makes re-queue across tiers collapse to one.
  No double-notify.
- **main.py backstop vs job-driven revert:** disjoint row sets in practice;
  idempotent even in the impossible overlap. No double-handle.
- **Completeness:** the only two raw `asyncio.create_task` business finalizers
  (auto:103, delivery_upload:343) are both now hardened. The other three LLM
  background runs (meetings `_process_meeting_background`, decompositions
  `_process_decomposition`, knowledge `_process_knowledge_ask`) use FastAPI
  `BackgroundTasks.add_task` and already had top-level `except Exception →
  update_job(failed) + finally` (meetings.py:338-352, decompositions.py:316-333,
  knowledge.py:145-159). F1's "no zombie on any path" requirement is now met
  codebase-wide.

## Fresh-pass findings

None. Specifically re-checked at HEAD `6693426`:

- All three touched files AST-parse clean (`ast.parse` OK).
- `_mark_auto_failed` variable scoping: module `job=None` (293) is shadowed by
  per-branch local queries in branches (a)/(b) which `return` before reaching the
  final `if job_id and job: publish_job` (342); no NameError, no stale-`job`
  publish. ✔
- `BackgroundJob`, `update_job`, `publish_job` all imported in auto.py
  (lines 20, 23). ✔
- Both `_mark_auto_failed` call sites (147, 285) pass the matching arg shape;
  `title` still consumed by the `requirement.ready` broadcast (348). ✔
- `_recover_stranded_delivery` single caller (400); `delivery_doc_ready_at` is a
  nullable column (models.py:347) so the `is None` guards are valid. ✔
- SQLite tuning unchanged (WAL + busy_timeout=5000 + FK + synchronous=NORMAL,
  db.py); `autoflush=False` accounted for in the backstop analysis above.
- No transaction is held across the `await auto_process()` / `generate_doc()`
  LLM round-trips — both read inputs in a short-lived session, close it, then run
  the model with no open txn (auto.py:121-135; delivery_upload.py:353 generates
  before opening the session at 357). Consistent with the R7.9 writer-freeing fix.

### Carryover items already resolved in R7.10 (confirmed)
- F2 (`.env.example COOKIE_SECURE`) and F3 (`create_drive_comment` None guard)
  from R10 are addressed in this commit (out of this round's backend scope, not
  re-audited in depth — both are P3/nit).

### Recommendation
Ship. The R7.10 fix is correct, idempotent on every retry tier, regression-free,
and additionally repairs a latent cancelled-requirement stale-broadcast. Declare
**PRODUCTION-READY**.
