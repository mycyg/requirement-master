# R7 Round 6 — Data integrity + Performance

## Verdict: NEEDS FIXES (1)

One genuine, ship-blocking performance defect: **HIGH-8 `drive_manifest`
unbounded fetch + per-item O(depth) query walk** is NOT a cold path. The desktop
sync client polls the FULL manifest endpoint every **45 seconds per project, per
connected client**, and never uses the incremental `drive/changes` endpoint that
exists for exactly this purpose. The query count is unbounded in project size and
grows without ceiling as a drive ages. This was mischaracterized as a non-polled
sync endpoint in R1–R5; the client code shows otherwise. Fix-now with `LIMIT` +
`selectinload(versions)` + an in-memory parent-path walk.

The R7.5 `created_at` backfill guard is **correct**: it closes the recycled-
nickname re-inherit AND preserves the legitimate backfill. HIGH-7 (meetings) and
HIGH-9 (reminders) are confirmed acceptable at LAN scale. The R7.5 diff itself is
a single safe line and introduces no new defect.

HEAD verified at `f70f3e6`; working tree clean. The only code change since R5
(`8d30bc7`/`c92b906`) is the one-line `AND u.created_at <= projects.created_at`
guard in `schema_migrations.py` — confirmed by `git diff`.

---

## R7.5 backfill-guard verification

`app/services/schema_migrations.py:85-96`. The backfill now reads:

```sql
UPDATE projects SET owner_user_id = (
    SELECT u.id FROM users u
    WHERE u.nickname = projects.owner_nickname
      AND u.deleted_at IS NULL
      AND u.created_at <= projects.created_at   -- R7.5
    ORDER BY u.created_at ASC LIMIT 1
) WHERE owner_user_id IS NULL
```

**Does it close the re-inherit? YES.** The re-inherit vector (R5 P3) is: a legacy
NULL-owner project whose original owner was soft-deleted → a NEW account registers
the freed nickname (`delete_user` tombstones `users.nickname` to `_deleted_<id8>_x`
but leaves `projects.owner_nickname` as the raw `x`, models.py:82) → reboot →
backfill matches the new account by nickname. A recycled account is created
**strictly after** the original owner was deleted, which is strictly after the
project was created. So `recycled_user.created_at > project.created_at` →
the guard rejects it. The orphan stays `owner_user_id IS NULL` (admin-only on
mutation paths — the correct, R7.4-established outcome). Vector closed.

**Does it break the legitimate backfill? NO.** The genuine owner always predates
their own project:
- Both timestamps come from `TimestampMixin` `server_default=func.now()`
  (models.py:20-24) on the **same SQLite instance** — one clock, no skew.
- `create_project` (projects.py:54-64) requires an authenticated `user`, so the
  owner's `User` row already exists (and `get_or_create_user`/auth.py:241-243
  flushed it) before the `Project` INSERT in that request. Hence
  `owner.created_at < project.created_at` strictly for any self-created project.
- `<=` is correctly inclusive: it admits the (practically impossible) same-tick
  tie without rejecting a real owner. The original owner is therefore always
  admitted.

**Could it WRONGLY reject a legitimate owner? NO** for any realistically reachable
row. The only way `owner.created_at > project.created_at` is a manually
backdated/seeded project created before its owner registered — not a path this
deployment has. Even then, the failure mode is conservative (leaves the row
orphan/admin-only), never a wrong-owner assignment.

**Idempotence / convergence preserved.** `WHERE owner_user_id IS NULL` still
matches zero rows once resolved; the added predicate only ever *narrows* the
candidate set, so the UPDATE remains idempotent and terminating across boots.
The `ORDER BY u.created_at ASC LIMIT 1` tie-break is unchanged and (given unique
active nicknames) selects deterministically.

Grade: **correct and complete.** Closes the last nickname-inheritance vector with
zero legitimate-owner regression. This P3 is now resolved, not carryover.

---

## Standing N+1 cluster — FINAL disposition

### HIGH-8 — `drive_manifest` unbounded fetch + O(N×depth) walk — FIX NOW (the defect)
`app/routers/project_drive.py:570-584`, `_drive_manifest_item` :191-206,
`_item_path` :182-188, `_current_version` :119-122, `_require_item` :80-88.

**This is no longer a cold path — the R1–R5 framing is wrong.** Caller trace:
- `client/yqgl_tray.py:1157` `_drive_sync_loop` → `self.stop.wait(45)` → fires
  every **45 s** whenever drive sync is enabled and not paused.
- → `sync_all_project_drives` (:710) iterates **`client.list_projects()`** and
  calls `sync_project_drive_once` for **every** project the user can see.
- → `sync_project_drive_once` (:633) calls `client.drive_manifest(...)` = the
  FULL `GET /drive/manifest`, **never** `drive/changes`. The client stores
  `drive_sync_cursor_by_project` (:69, :704) but **never reads it** — the
  incremental endpoint that would bound the fetch is dead code on the client.

**Worst-case query count (realistic LAN project).** Per manifest call:
- 1 unbounded `SELECT … WHERE project_id = ?` (no `.limit()` — the only truly
  unbounded query in the codebase).
- per item: `_current_version` = 1 query (files only); `_item_path` walks parents,
  and each hop's `_require_item` issues **2** queries (the item SELECT **plus**
  `_require_project`, :87). An item at depth `d` ⇒ `2d` queries.
- Total ≈ `1 + Σ_items[(file?1:0) + 2·depth]`. For N items at avg depth ≈3:
  ≈ `7N + 1` queries.

Realistic worst case: a shared project drive is a synced document repository that
accrues files for the project's whole life — hundreds to low-thousands of items
is entirely plausible (specs, meeting exports, delivery zips, screenshots). At
N=500, depth 3 ⇒ ~**3,500 queries per manifest call**, every 45 s, per project,
per connected client. With 5 active syncing clients and 3 drives each that is
~50k point-reads/45 s of pure overhead — and because the fetch is unbounded it
**degrades without limit** as the drive grows. SQLite WAL point reads are cheap,
but unbounded × polled × multi-client is exactly the shape that bites in
production at 192.168.5.53, not "acceptable at LAN scale."

**Decision: FIX NOW.** Concrete fix (no behavior change for the sync client):
1. **Eliminate the parent-walk N+1.** The manifest already loads ALL of the
   project's items in `rows`. Build `by_id = {r.id: r for r in rows}` once and
   resolve `_item_path` in memory by following `parent_id` through that map —
   0 extra queries instead of `2·depth` per item. (Use `include_deleted` items;
   the manifest query already returns deleted rows.)
2. **Eliminate the per-file version N+1.** Add
   `.options(selectinload(ProjectDriveItem.versions))` and pick the row whose
   `id == item.current_version_id` from the eager-loaded `item.versions` in
   memory — collapses N `_current_version` SELECTs into 1 batched `IN (…)` load.
3. **Bound the fetch (defense-in-depth against unbounded growth).** Add a
   `.limit(N)` (e.g. 5000) so a pathological drive can never issue an unbounded
   scan; pair with the already-existing `drive/changes` incremental endpoint by
   teaching the client to call it with its stored cursor (the cursor plumbing
   already exists at :69/:704 — only the read side is missing). The incremental
   path is the real long-term fix; `LIMIT + selectinload` is the immediate one.

After (1)+(2): manifest cost drops from ≈`7N+1` to **2 queries total** (the item
fetch + one batched versions load), independent of depth.

### HIGH-7 — meetings `_meeting_out` insights N+1 — ACCEPT
`app/routers/meetings.py:105-111`, called per row by `list_meetings` (:142, capped
`.limit(100)` at :139; `uploaded_by` already `selectinload`ed at :136).
- **Not polled.** No caller in `client/yqgl_tray.py` or the desktop client; this
  is a UI-triggered, on-demand project view opened by a human.
- Bounded: ≤100 meetings/project; per-meeting `MeetingInsight` lookup is an
  indexed (`ix_meeting_insights_meeting_id`) read. Worst case ≤100 extra indexed
  SELECTs on a single user click. No multiplier, no cadence.
- **Decision: ACCEPT at LAN scale.** (Trivial future cleanup if desired:
  `selectinload(MeetingRecord.insights)`.) Not ship-blocking.

### HIGH-9 — reminders workspace N+1 — ACCEPT
`app/routers/reminders.py:66-70`, per row in a loop over `rows` (capped `.limit(200)`
at :59), endpoint `GET /reminders/due` polled every **60 s** per user by
`_reminder_loop` (client/yqgl_tray.py:1176).
- Polled, yes — but the row set is heavily pre-filtered: `due_at <= now+24h` AND
  `status IN ACTIVE_STATUSES` AND (submitter OR claimer OR assignee = me) AND
  project not archived/deleted (:43-57). The realistic N is single digits to low
  tens — one user almost never has 200 distinct requirements all due within 24 h.
  The 200 cap is a ceiling, not the expected value.
- Each per-row lookup is an indexed point read on
  `uq_requirement_workspace_user (requirement_id, user_id)`. Worst-case ≤200
  indexed reads / 60 s / user — comfortably inside WAL headroom on a LAN team.
- **Decision: ACCEPT at LAN scale.** (Trivial future cleanup:
  `WHERE requirement_id IN (…) AND user_id = me` batch.) Not ship-blocking.

**Why HIGH-8 is different from 7/9:** HIGH-7 isn't polled; HIGH-9 is polled but
its N is small-by-construction and bounded at 200. HIGH-8 is polled (45 s),
multiplied across all projects × all clients, has a per-item multiplier of
~7×depth, and is **unbounded** — so it is the only one whose cost has no ceiling
and grows with data. That combination is a real production risk, not LAN-noise.

---

## Fresh-pass findings

No NEW data-integrity or performance defect introduced since R5. The sole code
delta is the one-line backfill guard (verified safe above).

- **Backfill clock/skew check** — clean. Single-instance SQLite clock; insert
  ordering guarantees owner-predates-project (auth flush before project insert).
- **Migration idempotence/convergence** — clean. The added predicate only narrows
  candidates; UPDATE still converges and re-runs as a no-op once resolved. The 5
  R7.3 orphan-FK SET-NULL cleanups (schema_migrations.py:643-667) re-verified
  unchanged, NULL-safe, idempotent.
- **`drive_manifest` dangling `parent_id`** — the in-memory-map fix (recommended
  above) would also harden against `_require_item` 500-ing on a dangling parent;
  today the R7.3 orphan-FK cleanup + `parent_id … ON DELETE CASCADE`
  (schema_migrations.py:190) defend it, so not a separate finding.
- **Transaction boundaries / TOCTOU / lost-update** — no new windows; the only
  changed statement is a boot-time DDL/UPDATE inside `engine.begin()`
  (schema_migrations.py:48), atomic and pre-request.
- **Event-loop sync I/O** — unchanged; the R7.5 delta touches only the boot
  migration, no request-path I/O added.

---

## Coverage

### R7.5 delta (1 of 1)
- `app/services/schema_migrations.py:85-96` — `created_at` backfill guard: closes
  recycled-nickname re-inherit (recycled account postdates project ⇒ rejected),
  preserves legitimate backfill (owner predates project ⇒ admitted), idempotent
  and convergent. CORRECT. P3 resolved.

### Standing cluster — final dispositions
- HIGH-8 `drive_manifest` (project_drive.py:570-584 / 182-206 / 80-122):
  **FIX NOW** — polled 45 s × per-project × per-client; ≈`7N+1` queries; UNBOUNDED.
  Fix: in-memory parent-path map + `selectinload(versions)` + `LIMIT` (and wire
  the existing `drive/changes`+cursor incremental path on the client).
- HIGH-7 meetings insights (meetings.py:105-142): **ACCEPT** — not polled, ≤100,
  indexed.
- HIGH-9 reminders workspace (reminders.py:59-84): **ACCEPT** — polled 60 s but
  N small-by-filter, ≤200 ceiling, indexed point reads.

### Caller-cadence audit (the decisive evidence)
- `client/yqgl_tray.py:1157-1161` drive sync loop = 45 s; `:710-717`
  `sync_all_project_drives` iterates every project; `:633` calls full
  `drive_manifest`, never `drive/changes`; `:69/:704` cursor stored-but-unread.
- `client/yqgl_tray.py:1171-1176` reminder loop = 60 s → `/reminders/due`.
- No client caller for `/projects/{id}/meetings` → confirmed on-demand/cold.

### Models / timestamp semantics
- `TimestampMixin` (models.py:20-24) server-default `func.now()`; `User`/`Project`
  both inherit ⇒ both `created_at` always populated, same clock. Underpins the
  guard's soundness.

### Scope confirmation
- `git diff c92b906 f70f3e6 -- app/ client/ src/ src-tauri/` = the single
  schema_migrations line. No other code changed since R5. Working tree clean at
  `f70f3e6`.

---

## Summary
The R7.5 `created_at` backfill guard is correct: it rejects a later recycled-
nickname account while always admitting the genuine owner (who provably predates
their own project on one shared clock), and it stays idempotent/convergent — the
last nickname-inheritance vector (R5 P3) is closed.

But this round is **NEEDS FIXES (1)** because the standing HIGH-8 `drive_manifest`
item is a real production defect, not LAN-acceptable: the desktop client polls the
FULL, unbounded manifest every 45 s for every project (never using the incremental
`drive/changes` endpoint), and each call costs ≈`7N+1` queries that grow without
ceiling as the drive ages. Realistic worst case (N≈500, depth 3) is ~3,500 queries
per call × every 45 s × per project × per client. Fix now with an in-memory
parent-path map + `selectinload(ProjectDriveItem.versions)` (collapses ≈`7N+1` → 2
queries) plus a `LIMIT`, and ideally activate the already-half-built incremental
`changes`+cursor sync on the client. HIGH-7 (meetings, not polled, ≤100) and
HIGH-9 (reminders, polled but small-N/≤200/indexed) are confirmed accept.
