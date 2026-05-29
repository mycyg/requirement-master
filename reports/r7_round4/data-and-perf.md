# R7 Round 4 — Data integrity + Performance

## Verdict: NEEDS FIXES (1 finding: 0 P0, 0 P1, 1 P2)

All four R7.3 fixes named in the brief are correctly implemented and close the
Round-3 findings they target (P1-A orphan cleanup, P2-B residual finalize I/O,
the `_reindex_state` running-flag leak, and the auto.py no-project-filter
lookups — the last actually landed in R7, not R7.3, and is still correct).

This is **not** a fully clean round. One genuinely-new data/UX integrity finding
surfaced from re-analyzing a hot path: the R7.2 `read_at`-reset on the
notifications dedupe-update, combined with the per-poll `_ensure_due_notifications`
write, makes due/blocked notifications impossible to keep "read" — every poll
flips them back to unread even when content is unchanged (NEW-1, P2). Prior
rounds validated the read_at reset only for the content-*changed* case and never
analyzed the no-change poll case.

The two long-standing carryovers (P2-A tombstoned-owner backfill; the R1 N+1 /
unbounded-query cluster on calendar / meetings / drive-manifest / reminders)
remain exactly as documented in Round 3 — none were touched in R7.3 and none are
ship-blocking, but they are still open and must not be marked "resolved."

Net: not a clean round. 1 new P2 + carryovers unresolved.

---

## R7.3 fix verification

### Fix 1 — `schema_migrations.py` 5 idempotent orphan-FK SET NULL UPDATEs — VERIFIED, SAFE
`app/services/schema_migrations.py:631-661`. Five `UPDATE … SET <fk> = NULL
WHERE <fk> IS NOT NULL AND <fk> NOT IN (SELECT id FROM <parent>)` blocks for the
5 SET-NULL columns called out in Round 3 P1-A.

- **Re-runnable every boot?** Yes. After the first run every row's FK either
  resolves or is NULL, so the `NOT IN (...)` predicate matches zero rows on all
  subsequent boots. Truly idempotent — no state, no flag, no harm in re-running.
- **`NOT IN` NULL-trap?** SAFE. The classic footgun (`NOT IN` returns UNKNOWN
  for every outer row if the subquery yields a single NULL, silently matching
  zero rows) does NOT apply here: `requirements.id` and `meeting_records.id` are
  both `primary_key=True` → NOT NULL (`app/models.py:231,272,294,317`). The
  subquery result set can never contain NULL, so the predicate behaves correctly.
- **FK-during-UPDATE?** SAFE. These run inside `engine.begin()` on a connection
  with `PRAGMA foreign_keys=ON` (`db.py:37`). Setting a FK column TO NULL never
  violates a FK constraint, so the cleanup itself can't trip the check it exists
  to prevent.
- **Ordering?** SAFE. `Base.metadata.create_all(engine)` (`main.py:187`) runs
  before `ensure_runtime_schema(engine)` (`main.py:188`), so `requirements` /
  `meeting_records` exist when the subqueries reference them.
- **Perf on large tables?** Acceptable at this deployment's scale. `NOT IN
  (subquery)` over a NOT-NULL PK column lets SQLite materialize the parent PK
  set (or probe the PK index) — roughly one full scan of the child table per
  query, 5 queries, once per boot, all inside one transaction. At LAN scale
  (tens of thousands of rows worst case) this is sub-100ms per query. It runs
  during the lifespan startup hook BEFORE the app serves traffic, so even a
  worst-case slow pass blocks only boot, never a request. No event-loop concern.

**Concern grade: none.** Fix is correct and the perf cost is negligible at scale.

### Fix 2 — `delivery_upload.finalize` per-chunk stat + zip inspect + rmtree in to_thread — VERIFIED
`app/routers/delivery_upload.py:171-348`.

- Per-chunk `.stat().st_size` validation is now folded INTO the same
  `_validate_and_merge_sync` closure (lines 207-224) that does the hash+merge,
  dispatched via `await asyncio.to_thread(_validate_and_merge_sync)` (line 226).
  The 1000× stat syscalls no longer run on the event loop.
- `inspect_zip_entries(tmp_path)` — central-dir scan on a 1GB zip — now wrapped
  in `await asyncio.to_thread(inspect_zip_entries, tmp_path)` (line 236).
- `shutil.rmtree(pdir, True)` now `await asyncio.to_thread(shutil.rmtree, pdir,
  True)` (line 328).
- **DB session crossing the thread boundary?** NO. `_validate_and_merge_sync`
  closes only over `chunks`, `meta`, `tmp_path` (file-path objects) — it never
  references `db`. `inspect_zip_entries` and `shutil.rmtree` take only paths.
  The request-scoped `db` session is touched exclusively on the event-loop side
  (the CAS at line 250, the Delivery insert + commit at lines 295-315). No
  SQLAlchemy object is read or written inside any `to_thread` body.
- **Transaction left open across to_thread?** NO. The first `to_thread` (line
  226) runs BEFORE the CAS, so no UPDATE is pending. The CAS UPDATE (line 250)
  is followed by `os.replace` (line 288, on the loop) and then `db.commit()`
  (line 315) — all on the event loop, all before the `shutil.rmtree` to_thread
  (line 328) which runs only after the commit. So no to_thread ever executes
  while an uncommitted write is parked in the session.
- One pre-existing nuance (not a regression): `_ensure_assignee` (line 188) may
  add an assignment + set `claimed_at` (uncommitted, autoflush=False) before the
  merge to_thread. Because the session is request-scoped and the closure never
  touches it, the event loop running other handlers during the multi-second
  merge cannot observe or corrupt this session's pending state. On a merge-size
  mismatch the HTTPException unwinds and `get_db` discards the pending changes on
  close. Correct.
- `os.replace` (line 288) is still on the event loop — metadata-only on the same
  mount (<1ms); Round 3 already noted the cross-mount-misconfig degradation as a
  configuration edge, and R7.3 explicitly left it (it's not in the to_thread).
  Acceptable; same call, unchanged risk.

**Concern grade: none.** No DB session crosses the boundary; no transaction is
held open across an await; the three sync ops are correctly offloaded.

### Fix 3 — `schedule_project_reindex` worker-owned running flag — VERIFIED, leak fixed
`app/routers/project_drive.py:223-283`.

- `schedule_project_reindex` (line 275) is now a thin `background.add_task(...)`
  wrapper that touches NO shared state.
- `_reindex_project_in_background` (line 235) acquires the run-slot under
  `_reindex_lock` at the top (lines 248-253: if `running` → set `dirty`, return;
  else set `running=True`), and releases it in a `finally` (lines 268-272).
- **Leak fix proven.** The worker body is `try: while …: rebuild …  finally:
  set running=False`. Three crash paths, all safe:
  1. `rebuild_knowledge_index` raises → caught by the inner `try/except` (lines
     257-260), logged, loop continues; `running` is still cleared on normal exit.
  2. Anything else inside the `while` raises → propagates to the outer
     `finally` (lines 268-272) → `running=False`. Next schedule works.
  3. The request that *scheduled* the task crashes between `add_task` and the
     response. Previously `schedule_project_reindex` set `running=True`
     synchronously, so a cancelled BackgroundTasks dispatch could strand
     `running=True` forever, wedging all future reindexes for that project.
     Now the flag is set only INSIDE the worker — if the worker never starts,
     the flag was never set, and if it starts it owns the `finally`. Leak closed.
  Only an unrecoverable hard process kill (no `finally`) leaves `running=True`,
  and that loses the in-memory dict anyway. Acceptable.
- **Bulk-safety (50 paste → ≤2 reindexes).** Holds. The bulk endpoints
  (`paste_drive_items` line 1065, `bulk_delete_drive_items` line 1140) process
  all items in ONE request and call `schedule_project_reindex` exactly ONCE — so
  a 50-item paste queues a single background task → 1 reindex. The ≤2 coalescing
  matters for the per-item single-paste path / concurrent requests from
  different users: while worker A is mid-`rebuild`, schedule B's worker sees
  `running=True`, sets `dirty=True`, exits; A finishes, sees dirty, re-loops once
  → exactly 2 rebuilds for any burst that overlaps a single run. Correct.
- **Side benefit:** `projects.py` archive/restore/soft_delete now import and call
  `schedule_project_reindex` (`projects.py:13,139,158,176`) instead of calling
  `_reindex_project_in_background` directly — closing the Round-3 "lifecycle
  events bypass the debouncer" minor observation. Good.

**Threading note:** `_reindex_lock` is a `threading.Lock` and BackgroundTasks
dispatch on Starlette's threadpool (verified Round 2). Correct primitive; every
read/write of `_reindex_state` is under the lock. No torn reads.

**Concern grade: none.** Leak is genuinely fixed; coalescing intact.

### Fix 4 — `auto.py` removed project-active filter in `_run_and_finalize` / `_mark_auto_failed` — VERIFIED, acceptable
`app/routers/auto.py:155,280`. Both background-finalize paths now look the
requirement up by `Requirement.id` only, with no `Project.archived == False` /
`Project.deleted_at.is_(None)` join filter.

- **Data integrity?** Acceptable. The brief's hypothesis ("delivery written for a
  soft-deleted project's requirement") is fine: the requirement row still exists
  (projects are only soft-deleted, never hard-deleted — confirmed: project
  delete is a tombstone, and `requirements.project_id` is `ondelete="CASCADE"`
  but the cascade only fires on a real DELETE which never happens), so the FK
  from Delivery → requirement → project is intact. Writing the Delivery (work is
  done, files are on disk) and flipping status, or marking the job failed, is the
  correct behavior — otherwise the BackgroundJob would hang in `running` and the
  requirement in `ai_processing` with no UI recovery once an admin archives the
  project mid-AI.
- **Status-clobber guard?** Present and correct. The success path checks
  `r.status != "ai_processing"` (line 164) and short-circuits to "succeeded but
  skipped" rather than resurrecting a cancelled requirement. The failure path
  only writes `ready` if `r.status == "ai_processing"` (lines 240, 284). So a
  cancellation that races the AI is never overwritten.
- **Note (not a finding, pre-existing):** the success branch builds the delivery
  zip synchronously inside this `async def` task — `zipfile.ZipFile(...)` +
  `rglob` + `p.read_bytes()` (lines 189-197) run on the event loop. This is an
  `asyncio.create_task` background task, not a request handler, but it still
  occupies the loop during zipping. Pre-existing (landed in R7 306edbd, untouched
  by R7.3), out of scope for this fix's verification, and lower-impact than the
  delivery_upload merge since auto-process volume is low. Mentioning for the
  record; not escalating.

**Concern grade: none.** No data integrity issue; the change is correct and was
already in the tree before R7.3.

---

## Carryover re-assessment

### P2-A — tombstoned-owner backfill leaves `owner_user_id` NULL — STILL OPEN (P2, unchanged)
`app/services/schema_migrations.py:80-90` and `app/routers/projects.py:108-113`.
The backfill still matches owners with `WHERE u.deleted_at IS NULL` and has no
second pass for the `_deleted_<id8>_<original>` tombstone pattern. `_require_owner`
still falls through to `p.owner_nickname == user.nickname` when `owner_user_id IS
NULL` (`projects.py:112`). So: owner tombstoned before R7.1 deploy → their
projects keep `owner_user_id = NULL` → a re-registered "alice" who knows the
project_id inherits archive/restore/delete rights. Round-3's note that the
`list_projects` enumeration filter (R2 P2-2) is closed still holds, shrinking the
exposure to (tombstoned owner) ∧ (nickname re-registered) ∧ (knows project_id).
Not escalated — bounded corner case, still P2, identical to Round 3.

### R1 HIGH-4 — notification poll-write amplification — STILL OPEN, and now interacts badly (see NEW-1)
`app/routers/notifications.py:96-97`. `list_notifications` (a polled GET) still
calls `_ensure_due_notifications` + `db.commit()` on every request. For each due
/ blocked requirement, `create_notification` finds the dedupe row and rewrites
`updated_at` (a real UPDATE) every poll. WAL demoted the raw write-throughput
concern (per Round 1/3), so the amplification alone stays a documented carryover,
NOT re-escalated. BUT the R7.2 read_at-reset turns this same per-poll write into
a user-visible correctness bug — see NEW-1.

### R1 HIGH-6 — calendar `_event_out` N+1 on `created_by.nickname` — STILL OPEN
`app/routers/calendar.py:31` accesses `event.created_by.nickname`; the
`list_events` query (line 83) has NO `selectinload(ScheduleEvent.created_by)`.
Bounded to 500 rows (line 114) → up to 500 lazy User loads per call. Brief asked
"calendar (now fixed?)" — **NOT fixed.** The visibility filtering was moved to
SQL (no post-filter N+1), but the `created_by` lazy-load N+1 is untouched.
Carryover, not re-escalated (bounded, infrequent endpoint).

### R1 HIGH-7 — meetings `_meeting_out` insights N+1 — STILL OPEN
`app/routers/meetings.py:106-111` queries `MeetingInsight` once per meeting;
`list_meetings` (line 142) calls it per row (≤100). `uploaded_by` was already
optimized via `selectinload` (line 136), but insights weren't. 100 meetings →
100 insight queries. Carryover, unchanged.

### R1 HIGH-8 — drive_manifest O(N×depth) `_item_path` + unbounded query — STILL OPEN
`app/routers/project_drive.py:574-584`. `drive_manifest` loads ALL items for a
project with NO `.limit()` (unbounded), then `_drive_manifest_item` walks parents
one query per hop (`_item_path` lines 183-189) plus `_current_version` per item.
O(N×depth) queries on an unbounded set. `drive_changes` (line 597) is window-
bounded by `since` but unbounded on first sync. Carryover, unchanged.

### R1 HIGH-9 — reminders N+1 workspace lookup — STILL OPEN
`app/routers/reminders.py:66-70` queries `RequirementWorkspace` once per
requirement inside the loop (≤200). Polled every 60s per user. Carryover,
unchanged.

---

## New findings

### NEW-1 (P2) — due/blocked notifications can never stay "read" (R7.2 read_at-reset × per-poll write)
**Files:** `app/services/notifications.py:42-63`, `app/routers/notifications.py:20-96`

R7.2 fixed the half-state bug (P1-2) by having the dedupe-update branch
unconditionally reset `read_at = None` and `archived_at = None` whenever a
dedupe_key matches (`notifications.py:59-60`). Round 3's python-backend + data
reviews validated this for the case where the notification's *content changed*
("content updates correctly resurface as unread" — correct). What was never
analyzed is the **no-content-change** case, which is the common one for the
poll-driven `_ensure_due_notifications` path:

1. `list_notifications` is a polled GET that runs `_ensure_due_notifications`
   every time (`notifications.py:96`).
2. For a `due_soon` requirement, the dedupe_key is `due:{req.id}:soon:{due_date}`
   and the title/body are deterministic for a fixed req + due_at
   (`notifications.py:55-61`). Same for `due_overdue` (key includes `:{day}`),
   and `workspace_blocked` (key `blocked:{req.id}:{user.id}`).
3. The dedupe-update branch has **no "did anything actually change?" guard** — it
   rewrites identical title/body AND sets `read_at = None` on every match.

**Result:** a user reads "REQ-001 即将到期", and on the very next poll (seconds
later) `_ensure_due_notifications` re-fires `create_notification`, which finds the
existing row and flips `read_at` back to NULL. The notification is impossible to
dismiss by reading — it pops back to unread every poll until `due_at` passes (for
`due_soon`) or the date rolls over (for `due_overdue`) or the block clears (for
`workspace_blocked`). The unread badge sticks; "mark read" appears broken.

This is a genuine behavioral regression *introduced by* R7.2's read_at reset —
before R7.2 the dedupe-update left `read_at` alone, so a read due-reminder stayed
read. The fix for the content-changed half-state inadvertently broke the
unchanged-content steady state, because the same code path runs on every poll
with no change-detection.

**Why it wasn't caught:** Round 2 framed P1-2 as "either both stay or both clear"
and Round 3 verified "both clear" in isolation, reasoning only about the
"content mutated" scenario. Neither round connected it to HIGH-4's per-poll
`_ensure_due_notifications` write, where content is identical across polls.

**Fix sketch (one of):**
- Guard the dedupe-update to only reset `read_at` / bump `updated_at` when
  title/body/severity/target actually differ from the stored row (cheap field
  compare before the writes at `notifications.py:53-61`); identical re-emits
  become true no-ops, which ALSO removes the HIGH-4 write amplification as a
  bonus.
- OR keep `read_at` sticky and only reset `archived_at` when content changes,
  accepting that a content change to an already-read notification is shown via
  the updated-content list rather than an unread bump.

The first is strictly better — it fixes both NEW-1 and the HIGH-4 write churn in
one guard.

**Severity P2:** UX-correctness bug on a high-frequency surface (the inbox badge
every LAN user watches), no data corruption, no security impact. Not
ship-blocking, but it makes the notifications feature feel broken for the exact
users it targets (people with imminent DDLs), so it should not be left as a
silent carryover.

---

## Coverage

### R7.3 fix sites reviewed (4 of 4 verified)
- `app/services/schema_migrations.py:631-661` — 5 orphan-cleanup UPDATEs:
  idempotent, NULL-safe (`NOT IN` over NOT-NULL PK), FK-safe (NULL-out never
  violates), correct ordering (after create_all), boot-time only. CLEAN.
- `app/routers/delivery_upload.py:207-328` — stat+merge / inspect_zip / rmtree in
  to_thread: no DB session crosses the boundary, no open transaction across an
  await. CLEAN.
- `app/routers/project_drive.py:235-283` — worker-owned running flag: leak fixed
  via top-acquire + `finally`-release; bulk coalescing intact. CLEAN.
- `app/routers/auto.py:155,280` — no-project-filter lookups (actually landed in
  R7 306edbd, not a5c700e): correct, status-clobber guards present, soft-delete-
  only means FK stays valid. CLEAN.

### R7.3 diff scope confirmed
`git show a5c700e --stat` on `app/` touched only delivery_upload.py,
project_drive.py, projects.py, schema_migrations.py (data layer) + 3 TS files
(out of scope). The project_drive.py 81-line diff is exactly the reindex
flag-ownership refactor + the M8 download-hardening (security, read-only file
serving — no data integrity surface). No stray data-layer change.

### Migration idempotency — clean
Column adds gated by `PRAGMA table_info` membership; `CREATE … IF NOT EXISTS`
throughout; `UPDATE … WHERE owner_user_id IS NULL` and the 5 orphan UPDATEs all
match zero rows on re-run. The only non-converging case is the tombstoned-owner
backfill (P2-A) which silently re-attempts every boot with no resolution —
unchanged from Round 3.

### Transaction-boundary audit — clean for R7.3 paths
delivery_upload finalize: CAS → os.replace → Delivery insert → single commit,
all on the loop; to_thread bodies are pre-CAS (merge) or post-commit (rmtree).
auto.py: each SessionLocal opened/committed/closed within its own try/finally; no
session leaks across the `await auto_process(...)` boundary (separate sessions
for job-update, inputs-read, and finalize). reindex worker: opens/closes its own
SessionLocal per loop iteration (line 256-262), no session held across the lock.

### TOCTOU / lost-update audit — clean for R7.3 paths
delivery_upload uses an atomic `UPDATE … WHERE status IN (...)` CAS (line 250)
with rowcount==0 → 409; auto.py uses the same CAS pattern (line 82). reindex flag
transitions are all under `_reindex_lock`. No check-then-act race introduced.

### N+1 / unbounded-query audit — unchanged from R1/R3
The four known N+1 hot paths (calendar created_by, meetings insights, drive
`_item_path`, reminders workspace) and the unbounded `drive_manifest` query are
all still present and untouched by R7.3. No NEW N+1 introduced by R7.3.

### Event-loop sync-I/O audit — clean except pre-existing auto.py zip
delivery_upload finalize residual I/O (Round-3 P2-B) is now fully offloaded.
The only remaining loop-blocking sync I/O is the auto.py delivery-zip build
(pre-existing, low volume, noted under Fix 4). No NEW blocking I/O from R7.3.

### Carryover ledger
| Item | Status in R7.3 | Action |
|---|---|---|
| R3 P1-A orphan cleanup | FIXED (Fix 1) | closed |
| R3 P2-B finalize residual I/O | FIXED (Fix 2) | closed |
| Py P2 reindex flag leak | FIXED (Fix 3) | closed |
| R3 reindex lifecycle-bypass (minor) | FIXED (projects.py import) | closed |
| R3 P2-A tombstoned-owner backfill | OPEN | carryover, P2 |
| R1 HIGH-4 notification poll-write | OPEN + now causes NEW-1 | see NEW-1 |
| R1 HIGH-6 calendar created_by N+1 | OPEN (not fixed) | carryover |
| R1 HIGH-7 meetings insights N+1 | OPEN | carryover |
| R1 HIGH-8 drive_manifest N+1/unbounded | OPEN | carryover |
| R1 HIGH-9 reminders workspace N+1 | OPEN | carryover |

---

## Summary
R7.3 cleanly lands all four targeted data/perf fixes — the orphan cleanup is
idempotent and NULL-safe, the finalize I/O is fully off the loop with no session
crossing the thread boundary, and the reindex running-flag leak is genuinely
closed by moving flag ownership into the worker's try/finally. No data integrity
regression was introduced by the R7.3 diff.

This is **not** a clean round, by one P2: NEW-1, the read_at-reset × per-poll
write interaction that makes due/blocked notifications un-dismissable. It's a
fresh finding from re-reading the notifications hot path, traceable directly to
the R7.2 P1-2 fix being validated only for the content-changed case. A single
change-detection guard in `create_notification`'s dedupe-update branch fixes both
NEW-1 and the long-standing HIGH-4 write amplification.

For the "4 consecutive clean rounds" gate: Round 4 is **not** clean (1 P2). The
carryovers (P2-A, the R1 N+1/unbounded cluster) remain open but are unchanged and
bounded; they should stay on the ledger rather than be marked resolved.
