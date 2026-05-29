# R7 Round 7 — Python + data

## Verdict: CLEAN

HEAD `94f7ff0` (R7.6). The only Python delta since the R6-baseline (`f70f3e6`) is
`app/routers/project_drive.py` (+75/-5) — the drive-manifest N+1 fix the R6
Data+Perf round demanded (HIGH-8). It is **correct, equivalent to the old output
on normal trees, more robust on corrupt rows, and introduces zero regression**.
The fresh full-tree pass surfaced no new P1/P2/P3. The standing carryovers
(meetings insights N+1, reminders workspace N+1, health N+1,
`list_users?include_deleted`, jobs archived-filter) are unchanged and remain
accept-by-design at LAN scale. This is a genuine CLEAN round.

Scope confirmed: `git diff f70f3e6..94f7ff0 -- 'app/**/*.py'` = `project_drive.py`
only (no schema_migrations change in R7.6; the R7.5 `created_at` backfill guard was
already verified clean in R6). `ast.parse` of `project_drive.py` OK; no bare
`except:` anywhere in `app/`.

---

## R7.6 drive_manifest regression check

All four sub-claims in the brief verified PASS.

### `_item_path_from_map(item, item_map)` — :191-206 — CORRECT
- **Path order root→leaf:** builds `names=[item.name]`, appends each ancestor by
  following `parent_id` through the map, then `"/".join(reversed(names))`.
  Identical construction to the old `_item_path` (:182-188). Simulated
  `docs/specs/readme.md` for a 3-level tree → matches exactly.
- **Cycle guard terminates:** `seen={item.id}` seeded, loop condition
  `parent_id and parent_id in item_map and parent_id not in seen`. Simulated
  self-cycle (`s→s`) → returns `self` immediately; 2-node cycle (`a→b→a`) →
  returns `B/A` then stops on `a in seen`. No infinite loop on any corrupt chain.
- **Matches old output on normal trees:** YES. The only behavioral *difference*
  is on a **dangling** ancestor (`parent_id` set but not in the map): old
  `_item_path` would 500 via `_require_item`'s 404→`_require_project`; the new
  walk silently stops (renders the partial path). This is strictly *more robust*
  and was explicitly flagged as a hardening win in R6 (dangling-parent 500). Not
  reachable on healthy data — `_build_manifest_maps` loads ALL project rows incl.
  soft-deleted, so every real ancestor is present.

### `_drive_manifest_item(db, item, *, item_map=None, version_map=None)` — :209-237 — CORRECT
- **Both paths produce identical output:**
  - version: fast path `version_map.get(item.current_version_id) if
    item.current_version_id else None`; fallback `_current_version(db, item)`.
    Old `_current_version` (:119-122) returns `None` for non-files OR falsy
    `current_version_id`; for a file it SELECTs by `current_version_id`. The map
    `.get` returns the same row (versions are keyed by `id`) and `None` when the
    id is falsy (folder) OR absent (stale id pointing at a deleted version) —
    byte-for-byte equivalent to the old SELECT-returns-None.
  - path: fast path `_item_path_from_map`, fallback `_item_path` — equivalent
    per above.
- **`version_map.get(item.current_version_id)` matches old `_current_version`:**
  YES for files. Subtle: the old `_current_version` *also* gated on
  `item.kind != "file"` (returns `None` for folders even if a stray
  `current_version_id` were set). The new fast path keys only on
  `current_version_id` being truthy — but a folder never has a populated
  `current_version_id` (only `finalize_drive_upload`/`_copy_item` set it, both on
  `kind=="file"`), AND folders carry no `current_version_id` in the map, so
  `.get` returns `None` anyway. Same result. Manifest `size_bytes`/`mime`/`sha256`
  for folders stay `None` exactly as before.
- **Mixed-map case never occurs:** both real callers (drive_manifest :650,
  drive_changes :679) pass BOTH maps together. The one-map-only branch is purely
  defensive dead-on-arrival code, not a live path.

### `_build_manifest_maps(db, project_id, rows)` — :246-263 — CORRECT, 2 queries
- **Query 1 fetches ALL project items** — `filter(project_id == project_id)` with
  **no `deleted_at` filter** → includes soft-deleted rows. This is required: a
  changed file in `drive_changes` may have unchanged (and possibly tombstoned)
  ancestors absent from `rows`; ancestor walking needs the full tree. Matches the
  old `_item_path`'s `include_deleted=True`.
- **Query 2 fetches only referenced versions** — `version_ids = [r.current_version_id
  for r in rows if r.current_version_id]` then `WHERE id IN (...)`. Skips the
  query entirely when no row has a version (empty `version_ids`). One batched
  `IN` load, not N point reads.
- **Exactly 2 queries** (1 when no versions referenced). Collapses the old
  ≈(depth+1)×N — verified the per-hop `_require_item` (2 queries each via
  `_require_project`) and per-file `_current_version` are gone from the manifest
  path.

### `drive_manifest` + `drive_changes` rewiring — :627-680 — CORRECT
- **drive_changes still returns only changed rows:** query (:663-671) filters
  `updated_at > since OR deleted_at > since`, ordered `updated_at asc`; rendering
  iterates `rows` (the changed subset). The full-tree map is used **only** for
  path resolution, not for what gets emitted. Cursor semantics unchanged.
- **50000 cap only LOGS, no truncation:** :636-641 `logger.warning(...)`; the
  `rows` query has NO `.limit()`. An oversized drive surfaces in logs but every
  item is still returned — sync never silently drops files. `logger` is defined
  (:52) before use.
- Both endpoints remain pure GET reads — no `db.commit()`, no mutation, no new
  transaction boundary.

### Non-manifest call sites unaffected
`_current_version` is still used by `_item_out`, `list_drive` sort, `_copy_item`,
download, and preview (:119/135/222/529/592/925/986/1001) — none touched. The old
`_item_path` survives only as the `_drive_manifest_item` fallback. No dead code,
no behavior change outside the two polled endpoints.

---

## Hot-path N+1 final sweep

Cross-checked every polled cadence against its backend endpoint. **No remaining
N+1 on any hot path.**

| Cadence | Caller | Endpoint | N+1? |
|---|---|---|---|
| 45 s | `client/yqgl_tray.py:1157` `_drive_sync_loop` → `sync_project_drive_once:633` → **`drive_manifest`** (full; never `drive_changes`, cursor stored :704 but unread :69) | `GET /drive/manifest` | **FIXED** — now 2 queries total |
| 60 s | `yqgl_tray.py:1176` `_reminder_loop` → `/reminders/due` | `reminders.py:59-84` | per-row workspace lookup, but pre-filtered to single-digit N, ≤200 cap, indexed point reads — **ACCEPT** (R6 disposition holds) |
| 6 s | web `Dashboard.tsx:38` `TICK_MS` → fan-out `listRequirements({status})` per `DASHBOARD_STATUSES` | `requirements.py:182-219` | **NONE** — single JOIN for slug+submitter, `selectinload(assignments→user)` batched, `.limit(500)`; tab-hidden pause guard |
| SSE | `stream_events` / web `/api/push/stream` | push bus | event-driven, no per-row DB walk |

The 45 s drive poll (the only unbounded-and-multiplied path R6 flagged) is now
the cheapest of the three. The 6 s dashboard poll — the highest-frequency one —
was already batched and is unchanged. Reminders is polled but small-by-filter.
No new polled endpoint was added in R7.6.

---

## Fresh-pass findings

**None.** Full re-read of the high-risk surface confirms the prior CLEAN
baseline holds with the manifest fix layered on top.

- **CAS / state machine** (`requirements.py:update_status`, `sync.py:submit/claim`):
  untouched by R7.6; allowed-transition map + `WHERE status=old` CAS → 409,
  role/device gates intact. No state-machine dead-end introduced (the manifest
  endpoints are stateless reads).
- **Transaction boundaries:** R7.6 touches only two GET handlers — zero commits,
  zero new TOCTOU/lost-update windows. The maps are read once per request from
  the request-scoped session; no cross-request caching, no staleness risk.
- **Swallowed exceptions hiding writes:** the new code has no `try/except` at all;
  it cannot mask a write. Tree-wide: no bare `except:`; the 38 `except Exception:`
  sites remain best-effort I/O / SSE-publish / LLM-fallback (re-confirmed,
  unchanged), none wrap a DB write.
- **Auth / project-active filter consistency:** both manifest endpoints still
  front-load `_require_project` (archived+deleted filter, :629/661) before any
  data access, and require `current_user`. The map build runs *after* the project
  gate, so an unauthorized/archived project 404s before any item fetch — no leak.
- **Cycle / unbounded-walk safety:** the new `_item_path_from_map` adds a cycle
  guard the old query-walk lacked (old `_item_path` had no depth cap, unlike
  `_ensure_no_cycle`/`_breadcrumbs`); corrupt `parent_id` chains can no longer
  spin. Net safety improvement.
- **Dict key-type soundness:** `ProjectDriveItem.id` / `.parent_id` /
  `.current_version_id` and `ProjectDriveVersion.id` are all `str` (models.py
  170/172/176/196); the `dict[str, ...]` maps and `.get(...)` lookups are
  type-consistent — no `None`-key or int/str mismatch.

---

## Coverage

### R7.6 delta (1 file, the only Python change)
- `app/routers/project_drive.py:191-263` (`_item_path_from_map`,
  `_drive_manifest_item` maps params, `_MANIFEST_MAX_ITEMS`,
  `_build_manifest_maps`) + `:627-680` (manifest/changes rewiring): **CORRECT** —
  path order, cycle guard, version equivalence, all-items+referenced-versions
  fetch, changed-rows-only emission, log-not-truncate cap all verified. ≈(depth+1)×N
  → 2 queries. HIGH-8 resolved.

### Hot-path cadence audit
- `client/yqgl_tray.py` poll loops: `stop.wait(45)` drive (:1161),
  `stop.wait(60)` reminders (:1176), SSE backoff (:469) — enumerated, mapped to
  endpoints above.
- `web/src/pages/Dashboard.tsx:38-84` 6 s tick → `list_requirements`
  (`requirements.py:182-219`) confirmed single-query + selectinload + limit 500.

### Equivalence / safety simulations
- Path-from-map vs `_item_path`: normal 3-level tree, dangling ancestor,
  self-cycle, 2-node cycle — all behave correctly (script run).
- `version_map.get` vs `_current_version`: folder→None, file→row, stale id→None —
  equivalent.

### Standing carryovers (unchanged, re-confirmed ACCEPT)
- meetings insights N+1 (`meetings.py:105-142`) — not polled, ≤100, indexed.
- reminders workspace N+1 (`reminders.py:59-84`) — polled 60 s but small-N/≤200/indexed.
- health N+1 (`health.py:18-117`) — on-demand read-only, ≤50-project LAN.
- `list_users?include_deleted` (`users.py:21-56`) — no PII, names already public.
- jobs archived-filter (`jobs.py:14-50`) — progress-only, authed.

### Sweeps
- `ast.parse` `project_drive.py` — OK.
- bare `except:` across `app/**/*.py` — NONE.
- `git diff f70f3e6..94f7ff0 -- 'app/**/*.py'` — `project_drive.py` only.

### Gate note
R6 Python was CLEAN (clean-streak round 2). R7.6's sole Python change is the
verified-correct manifest N+1 fix with zero regression. Round 7 is **CLEAN with
zero new P1/P2/P3** — clean-streak round 3.
