# R7 Round 1 — Performance audit

## Verdict
NOT CLEAN — **13 findings** (2 critical, 5 high, 6 medium). The hot polling
paths (notifications, reminders, calendar, dashboard) and the periodic
knowledge reindex are the main risks. SQLite is unconfigured (no WAL, no
busy_timeout) which will bite the moment two writers contend. Hot-path
N+1 queries on calendar/meeting/drive lists. No critical OOM risks — file
streaming is well-implemented across uploads.

---

## Hot-path issues (>1s blocking, OOM risk)

### CRIT-1. `_periodic_knowledge_reindex` blocks the event loop for tens of seconds
- **File**: `app/main.py:46-67`, `app/services/knowledge.py:300-349`
- Runs every 5 minutes in the lifespan loop. Called as a plain coroutine
  with no `run_in_executor` / `asyncio.to_thread` wrapper, so every SQL
  call and every `path.write_text()` inside `rebuild_knowledge_index`
  blocks the **entire FastAPI event loop**, freezing all in-flight SSE
  streams and HTTP requests until the rebuild finishes.
- Cost per run for a 1000-requirement project (per the scale spec):
  `_source_docs` yields one `SourceDoc` per project + requirement + chat
  message + comment + activity log row + workspace_update + meeting +
  meeting_insight + drive_file + delivery. For each yielded doc,
  `rebuild_knowledge_index` does:
  1. `path.write_text(src.content)` — sync disk write
  2. `db.query(KnowledgeDocument).filter(...).first()` — round-trip SELECT
  3. either insert or in-place UPDATE
- A project with 1k reqs / 10k chat messages / 5k activity entries / 500
  comments / 200 drive files ≈ **17k disk writes + 17k DB queries** per
  reindex, all on the event loop, every 5 minutes.
- Additionally `req_q.all()`, `comment_q.all()`, `meeting_q.all()`,
  `insight_q.all()` materialise the entire result set in memory before
  iteration (other queries correctly use `yield_per`).
- **Fix sketch**: `await asyncio.to_thread(rebuild_knowledge_index, db)`,
  switch the four `.all()` calls to `yield_per(500)`, and bulk-upsert the
  `KnowledgeDocument` rows via `INSERT OR REPLACE` instead of per-row
  SELECT+UPDATE. Also consider `MERGE`/staging into a temp table.

### CRIT-2. SQLite running in default DELETE journal mode with no `busy_timeout`
- **File**: `app/db.py` — no `PRAGMA` setup.
- Default SQLite serialises every write and **blocks all readers during a
  write**. With ~30 users polling notifications every 60s, the dashboard
  every 6s, plus background jobs writing meetings/decompositions, write
  contention will produce `database is locked` errors as soon as two
  writers collide. Background jobs that take >5s holding the writer lock
  (e.g. meeting transcription DB updates, knowledge reindex) will lock
  out every interactive read.
- Also no `busy_timeout` set → `OperationalError: database is locked`
  surfaces to the user immediately instead of waiting.
- **Fix sketch**: on engine creation, register a `connect` event that
  runs:
  ```
  PRAGMA journal_mode=WAL;
  PRAGMA synchronous=NORMAL;
  PRAGMA busy_timeout=5000;
  PRAGMA foreign_keys=ON;
  ```
  WAL alone is the single highest-ROI change in the audit.

---

## Background / cold-path issues

### HIGH-3. `meetings.finalize_meeting_upload` does ~1 GB of sync I/O in the request thread
- **File**: `app/routers/meetings.py:223-282` (also mirrored in
  `delivery_upload.py:171-335`, `project_drive.py:655-759`).
- All three finalize endpoints concatenate chunks via a sync `open()` /
  `read(1MB)` / `write(buf)` loop. `meetings.finalize_meeting_upload` is
  `def` (line 224) so FastAPI ships it to the threadpool (40 threads by
  default); `delivery_upload.finalize` is `async def` (line 172) so the
  same sync loop **blocks the event loop directly** for the duration of
  the 1 GB concatenate — every SSE consumer stalls.
- For a 1 GB upload at ~150 MB/s local disk: ~7 s of event-loop block on
  the delivery path.
- **Fix sketch**: move the merge to `asyncio.to_thread`, or kick the
  whole finalize work to a `BackgroundTask` and return 202 with the job
  id (clients already poll job status). For the meetings path, at least
  use `aiofiles` or pump through `to_thread`.

### HIGH-4. Notification "ensure due" runs on every poll, doing per-row upserts
- **File**: `app/routers/notifications.py:20-86`, called from
  `list_notifications` (line 96) which fires on **every web tab and every
  Tauri client every 60 s**.
- Each call:
  1. Joins requirements×assignments to fetch up to 200 assigned active
     requirements with `due_at <= +24h`.
  2. For each row, calls `create_notification(...)` which does a SELECT
     on `(user_id, dedupe_key)` to find an existing row to upsert.
  3. Same shape for up to 100 blocked workspaces.
- Worst case per call: ~300 dedupe SELECTs + ~300 UPDATEs, all in the
  request. Multiply by 30 users polling every 60 s = 9k extra writes/min
  → bumps the SQLite writer constantly. With the global journal-mode
  issue (CRIT-2), this is the biggest write-amplification source in the
  app.
- Also `(user_id, dedupe_key)` has no composite index (notifications
  table only has separate single-col indexes on each), so each dedupe
  SELECT does an index-scan on `user_id` then filters in memory.
- **Fix sketch**: move due-notification creation into a periodic
  background task (similar to `_periodic_knowledge_reindex` but smaller),
  not on the read path. At minimum, add composite index
  `(user_id, dedupe_key)` and `(user_id, archived_at, read_at)`.

### HIGH-5. Dashboard fires 7 parallel list endpoints every 6 s
- **File**: `web/src/pages/Dashboard.tsx:38-58`, `TICK_MS = 6000`.
- `refresh()` issues `Promise.all(7 × GET /api/requirements?status=X)`.
  Each query joins `Project + User + selectinload(assignments→user)`.
  With 30 users and visibility-pause working correctly (line 75),
  realistically ~10–15 simultaneously-open tabs → **70–105 join queries
  every 6 s** just for the dashboard.
- Visibility-pause is implemented, good. Pause-on-window-blur is not
  (only `document.hidden`).
- **Fix sketch**: collapse to a single `GET /api/requirements?statuses=...`
  multi-status endpoint, OR keep the dashboard SSE-driven (the push bus
  already broadcasts `requirement.updated` on `all`; the dashboard could
  patch-merge instead of refetching). The cheapest win is bumping to 10 s
  and adding the `archived` composite index (MED-10).

---

## Index gaps / N+1 candidates

### HIGH-6. `calendar.list_events` is N+1 on `created_by_nickname`
- **File**: `app/routers/calendar.py:68-120` + `_event_out` at line 31.
- The query at line 84 does **not** `selectinload(ScheduleEvent.created_by)`,
  yet `_event_out` reads `event.created_by.nickname` for every row. With
  the `.limit(500)`, worst case = 500 extra `SELECT users WHERE id=?`
  queries per request.
- **Fix**: `.options(selectinload(ScheduleEvent.created_by))`.

### HIGH-7. `meetings.list_meetings` is N+1 on insights
- **File**: `app/routers/meetings.py:131-142` + `_meeting_out` at line 105.
- `_meeting_out(db, row)` issues a fresh `SELECT MeetingInsight ... WHERE
  meeting_id = ?` per meeting in the list. With `.limit(100)`, that's up
  to 100 extra queries.
- **Fix**: change `_meeting_out` to accept already-loaded insights, and
  do one `selectinload(MeetingRecord.insights)` (relationship missing —
  needs to be defined on the model too).

### HIGH-8. `project_drive.drive_manifest` is O(N × depth) in queries
- **File**: `app/routers/project_drive.py:498-512` + `_drive_manifest_item`
  → `_item_path` (line 173-179).
- For each item, `_item_path` walks the parent chain calling
  `_require_item` for each ancestor — one SQL query per ancestor. For a
  project with hundreds of files nested 5 levels deep, the manifest
  endpoint alone fires **N items × ~5 ancestor queries each** = 1000+
  queries.
- Worse, `list_drive` (line 432) calls `_item_out` per row, which calls
  `_current_version` (line 110) — another per-row SELECT against
  `project_drive_versions`. ~hundreds of files → hundreds of extra
  queries on every directory listing.
- **Fix**: load the full project's items+versions in one query, build
  the parent-path map in Python.

### HIGH-9. `reminders.due_reminders` is N+1 on workspace per requirement
- **File**: `app/routers/reminders.py:62-84`.
- Called every 60 s by every Tauri client. For each of up to 200
  requirement rows, does a separate `SELECT RequirementWorkspace WHERE
  requirement_id=? AND user_id=?`. 30 users × 200 reminders / 60s =
  100/s extra workspace lookups under sustained load.
- **Fix**: add `selectinload` or a single `outerjoin` to the workspace
  table in the initial query.

### MED-10. Composite indexes missing for hot WHERE patterns
- **File**: `app/models.py`.
- Hot WHERE patterns lacking composite indexes:
  - `notifications(user_id, dedupe_key)` — used on every notification upsert.
  - `notifications(user_id, archived_at, read_at)` — `list_notifications` query.
  - `project_drive_items(project_id, parent_id, deleted_at)` — `list_drive`.
  - `requirements(project_id, status, due_at)` — `reminders.due_reminders`.
  - `requirement_workspaces(requirement_id, user_id)` — although covered by
    the `UniqueConstraint`, SQLite uses unique indexes well, so this is
    OK. But `requirement_workspaces(user_id, blocked_reason)` for the
    `_ensure_due_notifications` blocked query (notifications.py:64) has no
    coverage.
- Single-column indexes today cover the basics but force SQLite into
  multi-step intersect plans on these patterns.

### MED-11. `deliveries.list_deliveries` opens every package zip on disk per row
- **File**: `app/routers/deliveries.py:67-85`, `_zip_filelist` opens
  `package_path` and calls `inspect_zip_entries` per row.
- Every delivery has its own ZIP on disk; opening a 100MB zip reads its
  central directory record (cheap-ish) but doing this synchronously per
  row on a `def` endpoint that's called every time a requirement detail
  page opens is wasted I/O.
- The `file_count` is already stored in `deliveries.file_count` (line
  511 in models). For just the count, the disk hit can be skipped. For
  the full filelist, cache in a `delivery_file_manifest` text column at
  upload time.

### MED-12. `services/sync_manifest.build` lazy-loads `assignment.user` and `plan.items`
- **File**: `app/services/sync_manifest.py:22-146`.
- The sort key `lambda a: (..., a.user.nickname.lower())` on line 59 and
  the inline reads of `w.user.nickname` (line 79), `i.title` inside a
  `for i in sorted(plan.items, ...)` (line 118) all trigger lazy loads.
  Bounded scale (called only on claim / sync) but unnecessary churn.
- **Fix**: add `selectinload` for assignments→user, workspaces→user,
  workspaces→items, confirmed_plans→items.

---

## Bundle / client perf

### MED-13. Single-chunk Vite bundle, no vendor/manualChunks split
- **File**: `web/vite.config.ts`, no `build.rollupOptions.output.manualChunks`.
- Web bundle: `index-DRuQcNlp.js` = 395 KB single chunk. On the web
  surface (browser-only users, not the Tauri tray), a small SPA-shell
  change invalidates the whole bundle including React + lucide + router.
  Tauri client bundle = 345 KB main chunk; same shape.
- Not blocking — at the expected scale (~30 LAN users) bundle cache
  invalidation is a minor annoyance, not a perf issue. Worth a 1-line
  `manualChunks: { vendor: ['react', 'react-dom', 'react-router-dom'] }`
  before broader public exposure.

---

## Coverage

Reviewed (read-only):
- `app/db.py`, `app/main.py`, `app/models.py` (full schema)
- `app/routers/`: requirements, projects, notifications, calendar,
  meetings, project_drive, reminders, decompositions, workspaces,
  deliveries, delivery_upload, chat, auto, sync, jobs
- `app/services/`: knowledge, notifications, push_bus, workspaces,
  partial_uploads, sync_manifest, lifecycle, delivery_doc, meeting_agent,
  auto_agent
- `web/vite.config.ts`, `web/dist/assets/` (bundle sizes)
- `web/src/pages/Dashboard.tsx` (polling cadence)
- `client-tauri/src-tauri/src/sse.rs` (SSE reconnect)
- `client-tauri/src-tauri/src/reminders.rs` (60s tick)

Not reviewed in depth (out of audit scope or known-good):
- `auto_agent.py` tool implementations (MAX_TURNS=15, COMMAND_TIMEOUT=45,
  MAX_SANDBOX_BYTES=200MB caps look correct).
- `services/file_parser.py` (parser timeouts).
- `client-tauri/web-src/src/` React side — only confirmed bundle size.

Items confirmed working as documented in prior reports:
- `_refresh_project_knowledge` deletion (R7) — confirmed no in-handler
  reindex calls; only the 5-min periodic loop remains. Periodic loop
  itself is the new CRIT-1 above.
- Calendar SQL+Python double-filter dropped (R7) — confirmed SQL-only.
- Drive `_copy_item` depth/descendant caps in place.
- File upload chunk-receive paths stream from `request.stream()` with
  no `await request.body()` — no OOM risk on upload itself, only on the
  finalize merge (HIGH-3).
- `inspect_zip_entries` enforces `MAX_ZIP_ENTRY_BYTES`,
  `MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES`, compression ratio — zip-bomb safe.
- SSE backoff exponential, capped at 30 s (sse.rs:148). Good.
- Tauri reminders fixed 60s `tokio::time::interval`. Good.
- `push_bus.publish` uses `put_nowait` with queue maxsize=256 → drops
  events for slow subscribers instead of unbounded growth. Good.
