# R7 Round 21 — Final adversarial backend

HEAD `3dcf440` (R7.17). Frozen tree. 4th of 4 consecutive-clean ship gate. R18/R19/R20 clean.
Mandate: one last ruthless hunt for any P1/P2 across genuinely-new combinations.

## Verdict: CLEAN

No P1/P2 found after exercising every mandated vector with real tracing. Two pre-existing,
correctly-mitigated behaviors are noted below as forward-looking P3s (non-blocking) for the
documented-future Postgres migration only; they are safe on the shipping SQLite-on-Ubuntu config.

---

## 3-way concurrency composition
Vector: submitter cancels WHILE worker finalizes delivery WHILE admin archives the project,
all on one requirement.

- **Cancel vs finalize**: `PATCH /status` cancel and `delivery_upload.finalize` both use atomic
  CAS on `Requirement.status` (`requirements.py:310-314`, `delivery_upload.py:250-257`). Only one
  transition wins; the loser gets `rowcount==0` → 409 with the live status. Allowed map permits
  `delivery_doc_pending → cancelled`, and the finalize CAS scopes to
  `{claimed,doing,revision_requested}`, so the two never silently co-write.
- **Two concurrent finalizes**: first CAS moves status out of the deliverable set; second gets
  `rowcount==0` → 409. Belt-and-suspenders `UNIQUE(requirement_id, round)` on `deliveries`
  (`models.py:517`) + the `IntegrityError`→409 handler (`delivery_upload.py:317`) make a
  double-insert race impossible to corrupt.
- **Archive composing in**: `_require_req` filters archived/deleted projects (`delivery_upload.py:62`),
  but admin can archive in the gap between that check and the CAS. Result is a delivery completing
  into a just-archived project — cosmetic only (submitter gets a "等你验收" toast for an archived
  project); no state corruption, no crash, accept still gated by project-active checks elsewhere.
- **`os.replace` failure during cancel**: finalize's `_rollback_status` revert is itself a CAS
  (`WHERE status='delivery_doc_pending'`). If cancel won in the window, the revert matches 0 rows →
  no-op → cancel correctly stands. (One cosmetic artifact noted in P3 #2.)

The CAS guards **compose**: every status mutator is either an atomic CAS or a fresh-session
read-recheck-write, so three-way interleaving converges to a single consistent terminal state.

## Code-allocation contention / retry exhaustion
Vector: background AI task + meeting-insight-confirm + drive-comment-classify all allocating
`SLUG-NNN` on the same project simultaneously.

- All three writers share the identical pattern: read project → `next_seq += 1` →
  `code = f"{slug.upper()}-{next_seq:03d}"` → flush → on `IntegrityError` rollback + retry ≤5
  (`requirements.py:118-189`, `meetings.py:486-527`, `project_drive.py:1400-1434`). After rollback
  each re-reads the project fresh (`_require_project`), so no stale `next_seq` is carried forward.
- **Realistic contention model**: `confirm_meeting_insight` and `create_drive_comment` are
  `async def` (event-loop-serialized; the read→increment→flush has no `await` between, so they
  cannot interleave at statement level against each other). `create_requirement` is `def`
  (threadpool) and is the only one that can truly race at the OS-thread level. The 5-try budget is
  ample: SQLite serializes writers, so collisions are rare and each retry re-reads a now-advanced
  `next_seq`. Budget exhaustion is not reachable under realistic 3-way load.
- **Failure is graceful in all three**: `create_requirement` → 409 "please retry"; meeting-confirm
  leaves the insight `confirmed-without-requirement` (CAS re-accepts a manual retry); drive-comment
  leaves the comment safely `posted` (user text never lost) and logs. No corruption, no partial
  requirement, no double-allocated code (UNIQUE on `code` enforces it).

## Notification / reindex / soft-delete / integer / encoding edges

- **Notification threadsafe-publish vs rapid /stream/me connect/disconnect** — CLEAN.
  `PushBus` serializes subscribe/unsubscribe/publish under one `asyncio.Lock` (`push_bus.py:24-44`).
  `publish_notification_threadsafe` bridges from the threadpool via `anyio.from_thread.run`, so the
  actual `bus.publish` executes on the loop under the lock — no race on `_subs`. A publish to a
  just-disconnected subscriber lands in a GC'd local queue (no leak); `QueueFull` is dropped. The
  no-loop fallback logs and degrades to poll-delivery (row already persisted).
- **Reindex debounce (running/dirty) under 50 writes + admin /reindex + periodic tick** — CLEAN
  (self-healing). There is a narrow window where a `dirty=True` set between a worker's
  `return` and its `finally: running=False` can leave `dirty=True` with no worker running
  (`project_drive.py:314-331`), i.e. the "at most 2 reindexes" promise can drop a trailing rebuild.
  Impact is bounded: the 5-minute periodic **full** rebuild (`main.py:62`, no project filter)
  re-covers every project, so worst case is ≤5-min search-freshness lag — not data loss. Flags never
  leak permanently because the worker owns `running` and clears it in `finally`; a crashed scheduler
  only set `dirty`. Admin `/reindex` is a synchronous full rebuild, independent of the flags.
- **Soft-delete sole lead mid-delivery** — CLEAN. User soft-delete revokes `ClientDevice` rows +
  rotates `cookie_token` (`users.py:129-132`), so an in-flight chunked upload's next `chunk`/
  `finalize` (worker-token auth) gets 401/403 and stalls; the partial dir is GC'd by the 24h sweep
  (`partial_uploads.py`). If finalize already committed and `_finalize_doc` is mid-run, it notifies
  the **submitter** (not the deleted lead) and never dereferences a missing user — users are only
  ever soft-deleted (never hard-deleted; ~15 FK tables), so `a.user.nickname` in
  `sorted_assignments`/`sync_legacy_lead` is always present (tombstoned → masked to "已删除用户").
  No NPE, no orphaned Delivery.
- **`next_seq` 999→1000 width** — CLEAN. `:03d` is a *minimum* width and widens gracefully
  (`SLUG-1000`). `code` is `String(64) UNIQUE` matched as an exact string, so `SLUG-999`/`SLUG-1000`
  never collide. No code path slices/parses the code by digit width, and no listing orders by `code`
  (all `order_by(created_at)`); lexical mis-sort of widened codes is moot.
- **RTL / zero-width / combining unicode in nickname or code → path/filename/dedupe_key** — CLEAN.
  Drive files land at `{data_dir}/project_drive/{project_id}/{item_id}/{version_id}-{name}` with all
  path segments being internal UUIDs; `_safe_filename` = `Path(name).name` strips any
  separator/traversal for the running OS (`project_drive.py:375`). Delivery dirs key on `req_id`
  (UUID), not code/nickname. Knowledge corpus `_safe_name` whitelists `[a-zA-Z0-9_.-]` and applies
  only to `source_type`/`source_id` (UUIDs/enums), never user text. Notification `dedupe_key`s are
  built from `req.id`/`actor.id`/`status` only — no nickname/code, so unicode can't corrupt them.
  Notification template substitution uses `str.replace`, not `str.format` (`lifecycle.py:124-139`),
  so a `{...}` nickname can't trigger KeyError or attribute access.

## Findings (if any)
No P1/P2.

P3 (non-blocking, forward-looking — safe on the shipping SQLite config):
1. The three background finalizers — `auto._run_and_finalize` success path (`auto.py:212`),
   `delivery_upload._finalize_doc` (`delivery_upload.py:365`), and `_recover_stranded_delivery` —
   flip status with a read-then-write rather than a CAS. Today this is correct because SQLite's
   snapshot isolation refuses the stale write (a concurrent cancel committing after the finalizer's
   read → SQLITE_BUSY_SNAPSHOT), and the `except Exception` recovery re-checks status in a **fresh**
   session and no-ops when the cancel won. Under PostgreSQL READ COMMITTED (the documented future
   target in `db.py`) the stale write would silently commit and resurrect a cancelled requirement as
   `delivered`. Convert these three to CAS (`WHERE status='delivery_doc_pending'/'ai_processing'`)
   before any non-SQLite migration. Not reachable on the ship config.
2. Cosmetic: the cancel CAS does not clear `delivered_at`. In the extremely narrow window where
   finalize's CAS set `delivered_at`, then `os.replace` failed, then cancel won the revert race, a
   cancelled requirement can carry a stale `delivered_at` with no Delivery row. `delivered_at` is
   display-only (never gates logic/filters), so this is purely cosmetic.

Gate result for Round 21: **CLEAN** — the 4th consecutive clean round. The system holds under the
hardest new 3-way and contention combinations. Ship gate passes.
