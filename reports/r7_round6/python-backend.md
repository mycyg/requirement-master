# R7 Round 6 — Python backend

Scope: branch `fix/r6-hardening`, HEAD `f70f3e6` (R7.5). Read-only audit; no code changed by this review. The only Python delta since the R7-R5 review (`c92b906`→`f70f3e6`) is `app/services/schema_migrations.py` — the owner_user_id backfill gained `AND u.created_at <= projects.created_at`. The R7.5 commit otherwise only adds R7-R5 report artifacts. Prior R7-R5 Python verdict was CLEAN.

(Note: the R7-R5 report tagged the three carryovers as "P2"; this task brief calls them P3. Severity disposition below is the same regardless of the label — all three are acceptable-by-design in the LAN trust model.)

## Verdict: CLEAN

Zero P1, zero P2, zero P3 new findings. The R7.5 backfill guard is correct, idempotent, and closes the recycled-nickname re-inherit hole exactly as intended. The fresh full-tree pass surfaced nothing. The three standing carryovers are re-confirmed acceptable-by-design — no fix-now defect among them. This is a genuine CLEAN round.

---

## R7.5 backfill-guard verification

The change (`schema_migrations.py:85-96`):
```sql
UPDATE projects SET owner_user_id = (
    SELECT u.id FROM users u
    WHERE u.nickname = projects.owner_nickname
      AND u.deleted_at IS NULL
      AND u.created_at <= projects.created_at   -- NEW
    ORDER BY u.created_at ASC LIMIT 1
) WHERE owner_user_id IS NULL
```

**1. Correct SQL — lexicographic == chronological. PASS.** Both `users.created_at` and `projects.created_at` derive from the *same* `TimestampMixin` (`models.py:20-24`) with `server_default=func.now()`. On SQLite `func.now()` → `CURRENT_TIMESTAMP` → fixed-width `YYYY-MM-DD HH:MM:SS` (UTC, no offset, no fractional jitter). Neither creation path overrides it: `User(...)` (`auth.py:241`) and `Project(...)` (`projects.py:61-65`) both omit `created_at`, so the DB default fires for every row. Identical zero-padded ISO-ish format on both sides ⇒ string `<=` is byte-for-byte the same ordering as datetime `<=`. No mixed app-side `datetime.utcnow()` (which would render `…THH:MM:SS.ffffff` and break the lexicographic equivalence) ever lands in these two columns.

**2. Admits the real owner, rejects a recycled nickname. PASS.** Trace the threat model:
   - *Legitimate original owner, still active:* their user row predates the project (`create_project` requires `current_user`, so the user always exists before the project) ⇒ `u.created_at <= projects.created_at` is **true**, `deleted_at IS NULL` true ⇒ admitted. Correct.
   - *Original owner soft-deleted, nickname recycled by a new account:* `delete_user` (`users.py:123-128`) sets `deleted_at` and tombstones `users.nickname` to `_deleted_<id8>_…` but does **not** touch `projects.owner_nickname` (still the plain original nick). The original owner now fails `deleted_at IS NULL`. The new same-nick account fails `created_at <= projects.created_at` (it was registered *after* the project). Both rejected ⇒ `owner_user_id` stays NULL ⇒ `_require_owner` / `_can_manage_project` fall to admin-only (`projects.py:104`, `project_drive.py:100`). The exact hole this guard targets is closed.

**3. Idempotent + boot-safe, no NULL trap. PASS.**
   - The outer `WHERE owner_user_id IS NULL` means every successfully-backfilled row is skipped on subsequent boots; rows that stay NULL re-run the same deterministic subquery with no side effect. Re-runnable every boot.
   - `ensure_runtime_schema(engine)` is invoked at `main.py:188` inside `lifespan` *before* `yield` (`:196`), so the backfill completes before the first request.
   - No NULL-comparison trap: both `created_at` columns are `nullable=False`, so both operands always exist. Even hypothetically, a NULL operand would make the predicate evaluate to NULL → row excluded from the match → fails safe (never a wrong inheritance), never an exception.
   - `ORDER BY u.created_at ASC LIMIT 1` retained: with the new guard, all candidates are ≤ project; picking the oldest is the most-likely-original tie-break (nickname is unique among active users today, so realistically ≤1 candidate anyway).

Backfill guard fully verified.

---

## Carryover P3 final disposition (fix-now vs accept)

### P3-a `_can_view_job` meeting branch missing `Project.archived` — `routers/jobs.py:33-39` — **ACCEPT (by design)**
The meeting-job branch filters only `Project.deleted_at`, not `archived`. Decision: not a fix-now defect. (i) The endpoint returns only `BackgroundJobOut` (status / progress_percent / message) — no transcript, minutes, or requirement content. (ii) It still requires an authenticated user. (iii) `archived` ≠ `deleted`: an archived project is a legitimate, still-existing read-only artifact; exposing *job progress* (not content) for it to any LAN user leaks nothing material. (iv) The requirement branch above it correctly delegates to `can_view_requirement_record`, which *does* enforce project-active for non-admins — so the inconsistency is confined to the no-stricter-membership meeting case the docstring already acknowledges. UX-consistency nicety at most; not P3-worthy enough to spend a change on.

### P3-b `list_users?include_deleted=true` open to all authed users — `routers/users.py:25,30-31,53` — **ACCEPT (by design)**
Any authenticated user can list soft-deleted users; `display_name` (`models.py:46-54`) strips the `_deleted_<id8>_` tombstone prefix and appends `（已停用）`, and `deleted_at` is surfaced. Decision: accept. In the LAN open-board model every live nickname / id / online / admin-flag is already enumerable via the default `list_users`, and there is no password or PII stored (`User` has nickname, cookie_token, availability, is_admin, deleted_at — nothing sensitive). This exposes only *deletion metadata* plus a name that was already public before deletion. Admin-gating it would be a defensible hardening nicety, but there is no confidentiality or integrity impact — not a real defect to fix now.

### P3-c `list_project_health` N+1 — `routers/health.py:18-105` — **ACCEPT (by design)**
`_health_for_project` runs once per active project: a reqs query, a blocked-count query, a change-count `ActivityLog` query, plus a lazy `req.assignments` load per active req inside the load-hours set comprehension (`:62`). O(projects × active-reqs) round-trips. Decision: accept. Pure read-only aggregation against the ≤50-project LAN target with single-digit concurrent users; no correctness or security impact. Optimizing (eager-load assignments, fold counts into grouped queries) is a perf-polish opportunity, not a defect. If the deployment ever grows past the LAN assumption it becomes worth doing, but at current scale it is genuinely acceptable.

None of the three are fix-now defects.

---

## Fresh-pass findings (if any)

**None.** Full re-read of the high-risk surface confirms the prior CLEAN baseline holds:

- **Identity ownership** (`projects.py:_require_owner` :90-105, `list_projects` archived/deleted filter :47-48, `project_drive.py:_can_manage_project` :91-100 / `_require_manage_item` :103-107): owner_user_id-only, NULL ⇒ admin-only, no nickname fallback remains. `_require_manage_item` still grants the file's own creator/deleter so contributors keep managing their own items on orphaned projects.
- **State machine + CAS** (`requirements.py:update_status` :238-351): allowed-transition map, `WHERE status=old` CAS → rollback + 409 on race, role gates (submitter-only private transitions, `can_claim`/`can_work` worker transitions), and the `worker_transition ⇒ local_user required` device guard (:285-291) all intact.
- **Submit/claim CAS** (`sync.py:submit` :59-68, `claim` :138-149): `summary_ready/ready→ready` and `ready→claimed` both CAS-gated with project-active pre-check; loser gets 409, no double SSE / claim-storm.
- **Permissions service** (`permissions.py`): admin read-bypass precedes project-active filter (audit visibility); write paths respect project-active; private-status gating consistent across view/assets/sync.
- **Backfill / lifespan ordering** (`main.py:175-203`): schema patch + backfill before `yield`; stuck-job recovery; periodic tasks cancelled in `finally`.
- **Defect-pattern sweeps:** AST parse of all 55 `app/**/*.py` — zero syntax errors. No bare `except:` (all 38 `except Exception:` are documented best-effort I/O / SSE-publish / LLM-fallback sites, none mask a DB write). No mutable default arguments anywhere. The only f-string SQL is the 3 `ALTER TABLE ADD COLUMN {name} {ddl}` lines in `schema_migrations.py`, interpolating hardcoded module-level constant dicts (not user input) — DDL can't be parameter-bound in SQLite and there is no injection surface.

---

## Coverage

| Area | Files / sites | Outcome |
|------|---------------|---------|
| R7.5 backfill guard | `schema_migrations.py:76-97`; `models.py:20-24` (shared TimestampMixin), `auth.py:241`, `projects.py:61-65` (no created_at override); `users.py:123-128` (delete tombstone); `main.py:188/196` (lifespan order) | PASS — correct SQL, admits real owner / rejects recycled nick, idempotent, no NULL trap |
| Carryover P3-a job visibility | `routers/jobs.py:14-50` | ACCEPT — progress-only, authed, archived≠deleted |
| Carryover P3-b include_deleted | `routers/users.py:21-56`, `models.py:45-54` | ACCEPT — no PII, names already public in LAN model |
| Carryover P3-c health N+1 | `routers/health.py:18-117` | ACCEPT — read-only, ≤50-project LAN scale |
| Identity ownership | `projects.py:_require_owner`+list (3 call-sites), `project_drive.py:_can_manage_project`/`_require_manage_item` | clean — owner_user_id-only, NULL⇒admin |
| State machine + CAS | `requirements.py:238-351` | clean — allowed-map, CAS 409, role+device gates |
| Submit/claim CAS | `sync.py:40-149` | clean — CAS-gated, project-active pre-check |
| Permissions service | `services/permissions.py` (all helpers) | clean — admin read-bypass vs write project-active split correct |
| Lifespan / boot | `main.py:175-203` | clean — backfill before yield, task cancel in finally |
| Swallowed exceptions | 38 `except Exception:` sites | clean — best-effort only, no masked DB write |
| Mutable defaults | tree-wide regex | clean — none |
| Raw SQL injection surface | f-string SQL sweep | clean — only constant-dict DDL |
| Syntax sanity | `ast.parse` over all 55 `app/**/*.py` | ALL PARSE OK |

### Gate note
R7-R5 was CLEAN (streak round 1). The sole Python change since (R7.5 backfill guard) is verified correct and introduces no regression. Round 6 is **CLEAN with zero new P1/P2/P3** — counts as clean-streak round 2 of 4.
