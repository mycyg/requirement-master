# R7 Round 5 — Data integrity + Performance

## Verdict: CLEAN

No new data-integrity or performance findings. All three R7.4 fixes named in the
brief are correctly implemented and close Round-4 NEW-1 (the key one) plus the two
carryovers they targeted. The long-standing N+1 / unbounded-query cluster is
unchanged, bounded, and stays on the ledger as carryover (not re-escalated, not
resolved). HEAD verified at `8d30bc7`; the R7.4 data-layer fixes landed in
`c9d5e89`.

This is **Round 1 of the fresh "4 consecutive CLEAN rounds" streak — and it is
CLEAN.**

One sub-P3 hardening note is recorded under the P2-A re-assessment (the boot
backfill can re-inherit a legacy NULL-owner project to a recycled nickname). It
is a pre-existing property of the R7.1 backfill, strictly narrower than the
runtime fallback R7.4 just removed, not a regression, and not blocking. Flagged
for the record only — it does not change the CLEAN verdict.

---

## R7.4 fix verification

### Fix 1 — NEW-1: `create_notification` content-change guard — VERIFIED COMPLETE (the key one)
`app/services/notifications.py:48-76`.

The dedupe-update branch now early-returns `existing` unchanged unless content
actually differs, and only then resets `read_at`/`archived_at` + bumps
`updated_at`. This breaks the per-poll un-read loop NEW-1 described.

**Completeness — does the compare cover ALL fields callers set?** YES. I audited
every one of the 8 `create_notification` call sites and mapped each to its
dedupe_key namespace:

| Call site | type | dedupe_key shape |
|---|---|---|
| notifications.py:38 | due_overdue | `due:{req}:overdue:{day}` |
| notifications.py:51 | due_soon | `due:{req}:soon:{date}` |
| notifications.py:75 | workspace_blocked | `blocked:{req}:{uid}` |
| requirements.py:157 | assigned | `assigned:{req}:{uid}` |
| requirements.py:462 | assigned | `assigned:{req}:{uid}` |
| requirements.py:505 | due_changed | `due_changed:{req}:{uid}:{date}` |
| decompositions.py:300 | decomposition_ready | `decomposition:{plan}` |
| knowledge.py:131 | knowledge_answer | `knowledge:{run}` |
| lifecycle.py:145 | spec["type"] (6 values) | `{new_status}:{req}:{actor}` |

The compare set is `{title, body, severity, target_url, project_id,
requirement_id}` (`notifications.py:56-62`). The fields a caller passes but the
compare does NOT include are `type`, `dedupe_key`, `user_id`:

- **`type` — not compared, and that is provably correct.** For any fixed
  dedupe_key the `type` is invariant. The dedupe lookup is keyed on
  `(user_id, dedupe_key)`; the namespaces are prefix-disjoint, so a given key is
  only ever emitted with one `type`. The two `assigned:{req}:{uid}` sites
  (requirements.py:157 and :462) both use `type="assigned"`. The lifecycle
  `delivered` and `delivery_doc_pending` specs both map to
  `type="requirement.delivered"` but carry DISTINCT key prefixes
  (`delivered:…` vs `delivery_doc_pending:…`), so they never collide on one row.
  Conclusion: `type` could never differ on the update path, so omitting it from
  the compare can never miss a real change. (The branch also never writes
  `existing.type`, which is fine for the same reason.)
- **`dedupe_key`** is the lookup predicate — by definition identical on a match.
- **`user_id`** is in the lookup filter (`notifications.py:45`) — identical.

So the compare covers every mutable display field. **No caller sets a field that
can change yet escapes detection.** A real content change (e.g. the two
`assigned` sites have different body/severity; a blocked-reason edit; a
decomposition body change) trips `content_changed` and correctly resurfaces.

**Does the early `return existing` (no flush) hand back a stale/None id?** NO.
`existing` was loaded from the DB via the dedupe SELECT, so it is a fully
persisted row with a real `id`, `read_at`, `created_at`, etc. — not a pending
insert. `notification_out(existing)` and `publish_notification(existing)` both
work (`lifecycle.flush_status_notifications` reads `row.id`; `notify_users`
publishes after commit). With `autoflush=False` (`db.py:42`) the dedupe SELECT
does not autoflush, and the early return adds NO dirty state, so the caller's
later `db.commit()` (e.g. `notifications.py:97`) persists nothing extra and there
is no orphaned half-write. Side-effect-clean.

**Bonus:** the early return on the unchanged path also eliminates the HIGH-4
per-poll write amplification — identical re-emits are now true no-ops (no UPDATE,
no SSE re-push). Confirmed: SSE re-push of an already-read unchanged notification
is exactly what we want suppressed.

**Grade: complete and correct.** This is the genuine fix for NEW-1.

### Fix 2 — P2-A ownership: drop owner_nickname fallback for NULL owner — VERIFIED, backfill exhaustive for active users
`app/routers/projects.py:104` (`_require_owner`), `:48` (`list_projects`),
`app/routers/project_drive.py:100` (`_can_manage_project`). All three now use
`owner_user_id`-only with an `is_admin` override; no `owner_nickname ==`
permission fallback survives anywhere (grep-confirmed across `app/`).

**Are there orphaned (NULL-owner) projects a legitimate active user can no
longer manage?** NO. I traced every path that sets `owner_user_id`:
- **Create** (`projects.py:64`) always sets `owner_user_id=user.id`. Post-column
  projects are never NULL.
- **Boot backfill** (`schema_migrations.py:80-90`) sets `owner_user_id` from the
  active (non-deleted) user whose `nickname` matches `owner_nickname`.
- **Nickname immutability:** there is NO rename/update-nickname endpoint
  (grep on users.py/auth.py — the only `User.nickname =` write is the tombstone
  in `delete_user`, users.py:128). `get_or_create_user` reuses by exact nickname.
  So an active user's `nickname` is frozen at registration and equals the
  `owner_nickname` on every project they created → the backfill matches them.

Therefore NULL `owner_user_id` after boot ⟺ the original owner was **deleted**
(their `User.nickname` is now `_deleted_<id8>_alice` while the project's
`owner_nickname` stays the raw `alice`, so the match fails). Making those
orphans admin-only is the correct call — no active owner is locked out. The
restriction is applied only on **mutation** paths (archive/restore/soft_delete
projects.py:123/143/162; drive mutations project_drive.py:105); reads are
unaffected, so an orphan project's collaborators still see it. (The drive
item-level path also lets the item's own `created_by_user_id`/`deleted_by_user_id`
manage it — identity-based, not nickname, so not re-exploitable.)

**Backfill exhaustiveness: YES for every still-active owner.** See the P2-A
re-assessment below for the one residual edge (backfill re-inheritance of a
legacy NULL row to a recycled nickname) — pre-existing, narrower, P3.

### Fix 3 — Calendar N+1: `selectinload(created_by)` — VERIFIED, no cartesian/duplicate
`app/routers/calendar.py:87`.

- `ScheduleEvent.created_by` (`models.py:266`) is a plain to-one `relationship()`
  to `User`. `selectinload` is the right strategy and emits exactly ONE extra
  `SELECT … FROM users WHERE id IN (…)` regardless of row count — the
  `_event_out` `created_by.nickname` access (calendar.py:31) is now served from
  the identity map. Up to 500 lazy User loads → 1. N+1 resolved.
- **No cartesian / duplicate-row interaction with the existing aliased
  outerjoins.** `selectinload` runs as a SEPARATE second query; it does NOT add
  a JOIN to the main `q`, so it cannot multiply rows. Independently, the three
  existing `outerjoin`s (`event_project`, `Requirement`, `req_project`,
  calendar.py:88-90) are all many-to-one from `ScheduleEvent` → each event
  matches at most one row per join → no row multiplication. `assigned_exists`
  (line 79) is a correlated EXISTS, not a join. So `.limit(500)` still counts
  distinct events; the `selectinload` changes nothing about the result set.

**Grade: correct.** No duplicate rows, no double-counting against the limit.

---

## New findings

**None.** No lost update, TOCTOU-on-status, transaction-boundary,
event-loop-blocking sync I/O, or migration-safety defect was found in the R7.4
diff scope or the adjacent hot paths re-read this round.

Inverse-failure check on the NEW-1 guard (does the change-detection now WRONGLY
suppress a notification that SHOULD resurface?): No.
- `due_overdue` embeds `:{day}` in the key → a new calendar day yields a new
  (unread) row, so the daily overdue nag still fires.
- `due_soon`/`due_changed` embed the date in the key → a DDL change yields a new
  key, not a silent update.
- `workspace_blocked` (stable key): a real blocked-reason edit changes `body` →
  resurfaces correctly. A clear-then-re-block with identical reason stays read,
  but that's the pre-existing absence of stale-notification deletion, untouched
  by R7.4 — not a finding.
- `title[:256]` truncation is applied symmetrically (the guard compares against
  `new_title = title[:256]`, matching the new-row store), so an over-length title
  does not falsely trip `content_changed` every poll. This is why `new_title`
  exists — correct.

---

## Carryover re-assessment

### P2-A — orphaned-owner handling — RUNTIME FALLBACK FIXED; one residual P3 edge in the backfill
The runtime nickname fallback (the actual exploitable surface) is now closed in
all three decision sites (Fix 2). What remains is a property of the **boot
backfill itself**, not the request path:

`schema_migrations.py:80-90` runs every boot with `WHERE owner_user_id IS NULL`
and matches `owner_nickname` against any active user with that nickname. Because
`delete_user` tombstones `User.nickname` but NOT `projects.owner_nickname`
(models.py:82 keeps the raw value), the sequence (legacy NULL-owner project whose
owner was deleted) → (a NEW user registers the freed nickname) → (reboot) lets
the backfill assign that orphan project to the **new** user. This re-enters the
recycled-nickname inheritance through the migration rather than the runtime
check R7.4 removed.

Why this is NOT escalated and does NOT block CLEAN:
- It is **strictly narrower** than the runtime fallback just removed. It only
  touches rows that are `owner_user_id IS NULL`, which can ONLY be **legacy
  pre-column** rows (create always sets owner_user_id since the column exists).
  Any project created after the column never qualifies, even if its owner is
  later deleted and the nickname recycled.
- It is **pre-existing** — the backfill has behaved this way since R7.1; R7.4
  neither introduced nor worsened it. R7.4 strictly reduced exposure.
- On this young deployment the population of pre-column NULL-owner rows is
  plausibly zero.
- Clean structural fix (P3): tombstone `owner_nickname` in `delete_user` too, OR
  gate the backfill to a one-shot (run-once flag) instead of every boot.

Status: P2-A runtime surface CLOSED; residual backfill edge = P3 hardening,
carryover. Not blocking.

### R1 HIGH-4 — notification poll-write amplification — RESOLVED as a side effect of NEW-1 fix
`notifications.py:64-65`. The unchanged-content early return makes the per-poll
`_ensure_due_notifications` re-emit a true no-op (no UPDATE, no `updated_at`
bump, no SSE re-push). The write-amplification that Round 1/3 carried is now
gone for the steady state. Effectively closed by Fix 1.

### R1 HIGH-6 — calendar `_event_out` created_by N+1 — RESOLVED (Fix 3)
`calendar.py:87`. selectinload added; up to 500 User loads → 1. Closed.

### R1 HIGH-7 — meetings `_meeting_out` insights N+1 — STILL OPEN, severity unchanged
`meetings.py:106-111` queries `MeetingInsight` per meeting; `list_meetings`
(line 142) calls it per row (≤100). `uploaded_by` is already `selectinload`ed
(line 136); insights are not. Per-project, non-polled, bounded at 100.
Carryover; not re-escalated. (Fixable via `selectinload(MeetingRecord.insights)`.)

### R1 HIGH-8 — drive_manifest O(N×depth) + unbounded query — STILL OPEN, highest-priority carryover
`project_drive.py:573-584`. `drive_manifest` loads ALL project items with NO
`.limit()` (the only truly UNBOUNDED query in the cluster), then per item
`_drive_manifest_item` → `_item_path` (lines 182-188) walks parents one
`_require_item` query per hop + `_current_version` per item. O(N×depth). It is a
sync-client manifest endpoint, not a hot polled path, and the LAN dataset is
small, so severity holds at carryover — but if any one item in this cluster is
fixed, this is the one (unbounded fetch). `drive_changes` (line 596) is
`since`-windowed except on first sync. Note: `_require_item` would 500 the
manifest on a dangling `parent_id`, but the R7.3 boot orphan-FK SET-NULL cleanup
defends that; not a new finding.

### R1 HIGH-9 — reminders N+1 workspace lookup — STILL OPEN, severity unchanged
`reminders.py:66-70` queries `RequirementWorkspace` once per row inside the loop
(≤200), polled every 60s/user. The lookup is an indexed `(requirement_id,
user_id)` point read; bounded and low-cadence under WAL. Carryover; not
re-escalated. (Fixable via one `WHERE requirement_id IN (…) AND user_id = me`
batch query.)

---

## Coverage

### R7.4 fix sites reviewed (3 of 3 verified)
- `app/services/notifications.py:48-76` — content-change guard: compare covers
  ALL caller-set mutable fields; `type` provably invariant per key (8 sites
  audited); early-return hands back a persisted (non-None-id) row; no orphaned
  half-write under autoflush=False. COMPLETE.
- `app/routers/projects.py:48,104` + `app/routers/project_drive.py:100` —
  owner_user_id-only ownership: backfill exhaustive for every active owner
  (nickname is immutable, no rename endpoint); orphans admin-only on WRITE paths
  only; reads unaffected; no nickname fallback survives anywhere. CLEAN.
- `app/routers/calendar.py:87` — selectinload(created_by): separate query, no
  cartesian, no duplicate rows, to-one relationship, N+1 resolved. CLEAN.

### Call-site audit for NEW-1 completeness
All 8 `create_notification` call sites enumerated and mapped to dedupe_key
namespaces (table above). Namespaces are prefix-disjoint → `type` invariant per
key → safe to omit from compare. Compare set = every mutable display field.

### Transaction-boundary audit — clean
notifications: dedupe lookup + (conditional) flush, single `db.commit()` at the
list endpoint (notifications.py:97); early return adds no dirty state.
projects: ownership checks are pure reads, no transaction interaction. calendar:
selectinload is a read-only eager load. No session held across an await; no
write parked across a thread boundary in any touched path.

### TOCTOU / lost-update audit — clean
No check-then-act window introduced. Ownership decisions read `owner_user_id`
(stable identity), not a mutable nickname. The notification guard reads-then-
conditionally-writes within one request session with no concurrent-writer race
that could corrupt state (worst case: a duplicate no-op on two overlapping
polls, both idempotent).

### N+1 / unbounded-query audit — one resolved (calendar), no new ones
calendar created_by N+1 RESOLVED. meetings-insights, drive_manifest (+unbounded),
reminders-workspace remain as documented carryovers, all bounded except
drive_manifest's fetch. No NEW N+1 or unbounded query introduced by R7.4.

### Event-loop sync-I/O audit — clean for R7.4 scope
R7.4 touched only ORM read/compare logic (calendar selectinload, projects filter,
notifications compare) — no sync filesystem/network I/O added. The pre-existing
auto.py delivery-zip build on the loop (noted Round 4 Fix-4, low volume) is
untouched and out of scope. No NEW blocking I/O.

### Migration safety — clean, one P3 note
The owner backfill (schema_migrations.py:80-90) is idempotent (`WHERE
owner_user_id IS NULL` matches zero rows once resolved) and the 5 R7.3 orphan-FK
SET-NULL cleanups remain idempotent + NULL-safe (re-verified unchanged). The only
non-converging behavior is the recycled-nickname re-inheritance edge documented
under P2-A (P3, pre-existing).

### Carryover ledger
| Item | Status in R7.4 | Action |
|---|---|---|
| R4 NEW-1 notification read_at loop | FIXED (Fix 1) | closed |
| R1 HIGH-4 notification write amplification | FIXED (side effect of Fix 1) | closed |
| R3/R2 P2-A recycled-nickname runtime fallback | FIXED (Fix 2) | closed |
| P2-A backfill re-inheritance edge | OPEN (pre-existing, narrower) | carryover, P3 |
| R1 HIGH-6 calendar created_by N+1 | FIXED (Fix 3) | closed |
| R1 HIGH-7 meetings insights N+1 | OPEN | carryover (bounded ≤100) |
| R1 HIGH-8 drive_manifest N+1 + unbounded | OPEN | carryover (highest priority) |
| R1 HIGH-9 reminders workspace N+1 | OPEN | carryover (bounded ≤200) |

---

## Summary
R7.4 cleanly lands all three targeted fixes. NEW-1 — the key one — is COMPLETE:
the content-change guard compares every mutable field a caller sets, `type` is
provably invariant per dedupe_key (verified across all 8 call sites), and the
unchanged-content early return both fixes the un-read loop AND retires the HIGH-4
write amplification, with no stale-id or half-write hazard. The P2-A runtime
nickname-fallback is closed in all three decision sites and the backfill is
exhaustive for every still-active owner (nickname is immutable here), so no
legitimate user loses management of their project. The calendar selectinload
resolves the created_by N+1 with no cartesian interaction.

No new data-integrity or performance findings. The remaining N+1 cluster
(meetings insights, drive_manifest+unbounded, reminders workspace) is unchanged,
bounded (except drive_manifest's fetch), and stays on the ledger as carryover.
The one residual edge — the boot backfill re-inheriting a *legacy* NULL-owner
project to a recycled nickname — is pre-existing, strictly narrower than what
R7.4 removed, and a P3 hardening, not a blocker.

**Round 5 is CLEAN. This is clean Round 1 of the fresh 4-round streak.**
