# R7 Round 2 — Performance

## Verdict
NOT CLEAN — **3 findings** (0 critical, 1 high, 2 medium). The two R7.1
CRIT fixes (event-loop offload + SQLite WAL) are correct and effective.
However, the new `schedule_project_reindex` helper amplifies write
pressure on busy drives, the R1 HIGH-3 sync-merge on `delivery_upload.finalize`
is still alive in an `async def`, and `_periodic_partial_cleanup`
inherited the same event-loop-blocking pattern that CRIT-1 fixed for
reindex.

---

## R7.1 fix verification

### CRIT-1 (`_periodic_knowledge_reindex` → `asyncio.to_thread`) — CORRECT
File: `app/main.py:46-77`.

- Closure `_run_reindex_sync` (line 59-64) creates its **own**
  `SessionLocal()` inside the worker thread, then closes it in `finally`.
  This is the canonical SQLAlchemy pattern — sessions/connections live
  entirely inside the thread, so the `check_same_thread=False` on the
  SQLite connection is defensive but not strictly required for this
  call.
- `pool_pre_ping=True` (no-op for SQLite, useful if/when Postgres) means
  the pooled connection is sanity-checked before reuse — won't surprise
  a freshly-spawned thread with a stale handle.
- Exception logging via `_logger.exception` keeps the loop alive after a
  reindex failure. Sleep is OUTSIDE the try, so a thrown-then-sleep
  pattern still throttles to 5min between attempts. ✓
- The two `await asyncio.sleep(...)` calls run on the main event loop —
  the only event-loop work this task does — which is what we want.
- No risk of "next iteration starts before previous finishes" because
  awaits are sequential within the same coroutine. ✓

Minor nit (not a finding): `from services.knowledge import rebuild_knowledge_index`
is at line 57 inside the coroutine, so the import happens at first tick
(after the 60s sleep). On a cold start the import faults a bunch of
SQLAlchemy/Pydantic machinery one extra time but it's negligible.

### CRIT-2 (SQLite WAL + busy_timeout + foreign_keys + pool_pre_ping) — CORRECT
File: `app/db.py:22-39`.

- `journal_mode=WAL` is persistent (once set, the DB file's header records
  it; the `-wal` and `-shm` sidecar files appear next to the DB). Future
  process restarts see WAL automatically; even external `sqlite3` CLI
  callers will see WAL once it's been switched.
- `synchronous=NORMAL` matches WAL's safety profile (fsync at checkpoint,
  not every commit). Correct.
- `busy_timeout=5000` (5s) means concurrent writers block up to 5s
  instead of failing instantly with `SQLITE_BUSY`. Combined with WAL's
  reader-doesn't-block-writer semantics this eliminates almost all the
  R1 contention scenarios under realistic ~30-user load.
- `foreign_keys=ON` is per-connection in SQLite, so the listener has to
  run on EVERY connect — which it does (via `event.listens_for(engine,
  "connect")`). ✓
- The `dbapi_conn.cursor()` / `try` / `cur.close()` block is correctly
  cleaning up the cursor. Pragmas don't return rows so no `fetchall`
  needed.
- Only registered when `database_url.startswith("sqlite")` — guards
  against accidental Postgres misconfig.

### NEW BackgroundTasks reindex helper — CORRECT WIRING, see HIGH-2 below
File: `app/routers/project_drive.py:214-233`, `app/routers/projects.py:15-25`.

- Wired into 11 drive mutation endpoints + 3 project endpoints. Sync
  `def` background functions are dispatched by Starlette via
  `run_in_threadpool` (verified at `starlette.background.BackgroundTask.__call__`),
  so they don't block the event loop.
- Owns its own DB session — correct, request session is already closed.
- BackgroundTasks run AFTER the response is sent, so user latency is
  unchanged.

The wiring is mechanically correct, but the workload pattern it creates
under burst writes is a new MED finding (see MED-1).

---

## R7 R1 unfixed status

### HIGH-3 (sync 1 GB merge in `async def` finalize) — STILL ALIVE
File: `app/routers/delivery_upload.py:171-219`.

`async def finalize` (line 172) still runs the sync `open()` → `read(1MB)`
→ `write(buf)` chunk merge loop directly on the event loop (lines
211-219). For a 1 GB upload at ~150 MB/s local disk that's ~7s of
event-loop block — every SSE consumer stalls, every other handler queues
behind it. This is the single most user-visible perf issue still
outstanding.

Note: `meetings.finalize_meeting_upload` (line 224, also referenced in
R1) is `def` not `async def`, so it runs in the threadpool — not as
severe but still blocks the worker thread for the merge duration.
`project_drive.finalize_drive_upload` (line 679) is also `def` — same.
Only the delivery path is event-loop-blocking.

**Promote to HIGH-1 of this round.** Fix sketch unchanged from R1:
wrap merge in `asyncio.to_thread`, or move to a `BackgroundTask` and
return 202.

### HIGH-4 (notifications "ensure due" on every poll) — STILL ALIVE
File: `app/routers/notifications.py:20-86`.

Unchanged from R1. Every `GET /api/notifications` (called by every web
tab + every Tauri client every 60s) still triggers up to 300 dedupe
SELECT + INSERT/UPDATE round-trips inside the request handler. With
CRIT-2's WAL fix this no longer locks readers out, but it's still a
significant write-amplification source.

**Holding as MED-2 of this round** — WAL has demoted the severity since
write contention no longer cascades into reader failures, but the
sustained 9k writes/min under full load is still wasteful and stresses
WAL checkpoint frequency.

### HIGH-5 (Dashboard 7-fan-out every 6s) — ACCEPTABLE
File: `web/src/pages/Dashboard.tsx:38-58`.

R1 already noted visibility-pause is working. Re-confirmed at line 74-77.
Pause-on-blur (vs only document.hidden) still missing but at ~10-15
simultaneously-open tabs × WAL-enabled SQLite, this is no longer a
perf concern. **Closed — accepted as-is.**

### HIGH-6 (calendar `_event_out` N+1 on `created_by.nickname`) — STILL ALIVE
File: `app/routers/calendar.py:20-34, 68-114`.

Unchanged. The query at line 83 does NOT `selectinload(ScheduleEvent.created_by)`,
yet `_event_out` reads `event.created_by.nickname` at line 31. Up to 500
extra `SELECT users WHERE id=?` queries per `GET /api/calendar/events`
call. Not on a hot polling path, but the calendar page does refresh on
navigation.

**Holding for the unfixed-list — single fix, low risk.** Not a Round 2
finding (already documented in R1).

### HIGH-7 (meetings `_meeting_out` N+1 on insights) — STILL ALIVE
File: `app/routers/meetings.py:105-142`.

Unchanged. `_meeting_out(db, row)` at line 105 still issues a fresh
`SELECT MeetingInsight WHERE meeting_id=?` per meeting (line 107-111),
called in a loop at line 142 with `.limit(100)`.

**Holding for the unfixed-list — already documented in R1.**

### HIGH-8 (drive_manifest O(N × depth) queries) — STILL ALIVE
File: `app/routers/project_drive.py:174-198, 521-535`.

Unchanged. `_item_path` (line 174) walks the parent chain calling
`_require_item` per ancestor → one query per parent. `_drive_manifest_item`
calls `_item_path` per item AND `_current_version` (one extra query per
file row). For a project with 200 files nested 5 deep that's ~1000
queries per `GET /drive/manifest`.

**Holding for the unfixed-list — already documented in R1.**

### HIGH-9 (reminders N+1 workspace per requirement) — STILL ALIVE
File: `app/routers/reminders.py:62-84`.

Unchanged. Per-row workspace SELECT inside the result-building loop.
Called every 60s by every Tauri client.

**Holding for the unfixed-list — already documented in R1.**

### MED-10/11/12/13 — STILL ALL UNFIXED
- MED-10 composite indexes (notifications, drive_items, requirements):
  no schema changes in R7.1 except the new `owner_user_id` column +
  index. The R1 list still applies.
- MED-11 deliveries zip-per-row: untouched.
- MED-12 sync_manifest lazy loads: untouched.
- MED-13 Vite chunking: untouched.

---

## New findings

### HIGH-1. `delivery_upload.finalize` sync merge on event loop (promoted from R1 HIGH-3)
File: `app/routers/delivery_upload.py:172, 211-219`.

Re-stated here because R7.1 did not touch it AND R7.1 added new
event-loop hygiene work (CRIT-1), making it the worst remaining
event-loop blocker. Same details as R1 HIGH-3: `async def` + sync
open/read/write loop = up to ~7s of event-loop block per 1 GB delivery
upload finalize.

**Fix sketch**: `await asyncio.to_thread(_merge_chunks, chunks, tmp_path)`
where `_merge_chunks` is the existing 211-219 loop extracted. Two-line
change.

### MED-1. `schedule_project_reindex` triggers full project reindex on every drive write
File: `app/routers/project_drive.py:226-233`, called at 11 sites
(grep `schedule_project_reindex` shows 11 hits in project_drive +
3 in projects). Also `app/routers/projects.py:138, 158, 176`.

Each call enqueues `_reindex_project_in_background(project_id)` which
runs `rebuild_knowledge_index(db, project_id=project_id)`. That walks
the entire project's requirements + chats + comments + activity logs +
workspace updates + meetings + meeting insights + drive files +
deliveries — i.e. for a 1000-requirement / 200-file project, ~1000-2000
DB queries + ~1000-2000 corpus-file writes + one SQLite commit covering
all KnowledgeDocument upserts.

The R7.1 commit comment claims "duplicates coalesce naturally via
SQLite's serialize-writes guarantee" but that's incorrect — SQLite
serializes EXECUTION of writes, not WORK. If a user uploads 5 files in
10 seconds, 5 BackgroundTasks fire, all 5 do the full project scan,
all 5 write the same corpus markdown files, all 5 acquire the writer
lock in sequence. Total wasted work: 5× a single reindex.

Worst-case scenario: a paste-copy of 50 items + a bulk-delete + a
patch_drive_item in rapid succession = ~52 reindexes queued; if the
project is large, the threadpool backlog grows and starves other sync
endpoints (Starlette's default threadpool is 40; reindex tasks can
hold those threads for tens of seconds each).

**Fix sketch**:
- Debounce: keep a `{project_id: asyncio.TimerHandle}` dict and reset
  the timer on each call — actual reindex fires 5-10s after the LAST
  write, coalescing bursts. Requires the helper to live in an async
  context not BackgroundTasks.
- OR: add an `in-flight` set + "pending-reindex" flag per project — if
  reindex is already running for project X and another schedule arrives,
  just set the flag; when the running one finishes, it checks the flag
  and re-runs once.
- OR: make `rebuild_knowledge_index` content-hash-aware (it computes
  `content_hash` per doc but doesn't compare to existing row's hash
  before re-writing the markdown file + UPDATE statement). Adding `if
  row.content_hash == content_hash: continue` skips most no-op work
  during redundant reindexes.

Severity: MED because at ~30 LAN users with typical drive activity
this is wasteful but not user-blocking. Would promote to HIGH if drive
activity scales (CI sync, batch imports, large project migrations).

### MED-2. `_periodic_partial_cleanup` blocks event loop with `rglob("*")` scan
File: `app/main.py:80-93`, `app/services/partial_uploads.py:24-50`.

`cleanup_stale_partials(settings.data_dir)` is awaited directly on the
event loop without `asyncio.to_thread`. The function walks 4 partial
directories with `child.rglob("*")` per child — on a system with hundreds
of stale GB-sized uploads (R7.1 commit notes "multi-week uptime
accumulated stale uploads"), this becomes seconds of `os.stat` calls
blocking every SSE stream.

Same class of bug as CRIT-1 — sync I/O on the event loop in a periodic
task — but lower frequency (6h vs 5min) and smaller blast radius. The
fix is identical: `await asyncio.to_thread(cleanup_stale_partials,
settings.data_dir)`.

Also note: the SAME function is called at startup (line 186) inside
`lifespan()` BEFORE the app starts serving — there it's fine because
nothing's listening yet.

---

## Coverage

Reviewed (read-only):
- `app/db.py` — full SQLite pragma config (CRIT-2 verification)
- `app/main.py` — lifespan tasks (CRIT-1 verification + MED-2 discovery)
- `app/services/knowledge.py` — `rebuild_knowledge_index` + `_source_docs`
  (workload of background reindex)
- `app/routers/project_drive.py` — every `schedule_project_reindex`
  call site + `_item_path`/`_item_out`/`_drive_manifest_item`
- `app/routers/projects.py` — archive/restore/delete reindex hooks
- `app/routers/notifications.py` — HIGH-4 re-check
- `app/routers/calendar.py` — HIGH-6 re-check
- `app/routers/reminders.py` — HIGH-9 re-check
- `app/routers/meetings.py` — HIGH-7 + HIGH-3 (meetings finalize) re-check
- `app/routers/delivery_upload.py` — HIGH-3 (delivery finalize) re-check
- `app/services/partial_uploads.py` — MED-2 discovery
- `web/src/pages/Dashboard.tsx` — HIGH-5 re-check
- `app/services/schema_migrations.py` — R7.1 schema delta
- Starlette source `starlette.background.BackgroundTask.__call__`
  (confirmed sync BG tasks run via `run_in_threadpool`)
- Starlette source `starlette.routing.request_response`
  (confirmed sync endpoints dispatch via `run_in_threadpool`)

Verified working correctly (no longer concerns):
- WAL persistence — set-once via PRAGMA, persists across restarts.
- `asyncio.to_thread` + per-thread `SessionLocal()` — canonical pattern,
  no thread-safety violation. SQLAlchemy sessions are NOT shared across
  threads, each thread gets its own.
- `pool_pre_ping=True` on SQLite — no-op, harmless.
- BackgroundTasks fire after response, on threadpool for sync funcs.
- Lifespan task cancellation on shutdown (line 195-200) — both periodic
  tasks cancelled cleanly.

Not reviewed (out of scope or unchanged since R1):
- `auto_agent.py` (tool caps already verified R1).
- Tauri client perf — R1 covered SSE backoff, reminders interval.
- `services/file_parser.py` parser timeouts.
- Web vendor chunking (MED-13, R1 deferred).

## Summary line for sentinel
3 findings: 1 HIGH (delivery_upload sync merge on event loop), 2 MED
(reindex burst amplification, partial-cleanup event-loop block).
Both R7.1 CRIT fixes verified correct. 7 R1 issues still open and
unchanged (4 HIGH, 4 MED) — those remain documented in R1, not
re-listed as new findings here.
