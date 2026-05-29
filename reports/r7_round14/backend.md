# R7 Round 14 — Backend confirmation

HEAD `580754c`. Round 1 of the final 4-consecutive-clean confirmation sequence
(R14–R17, no code changes planned). Fresh full-`app/` pass against the actual
source — not a re-read of prior reports. Verified all `app/*.py` AST-parse clean.

## Verdict: CLEAN

No P1/P2 found. The backend is genuinely defect-free for ship. Every area in the
prompt's checklist was re-derived from source this round, not trusted from prior
rounds. The streak holds.

## R7.13 log-line check

The only change since R13 (`app/services/notifications.py`) is correct and a
strict no-behavior-change:

- `import logging` is present at module top (line 3) — the log call resolves.
- The change replaces the fallback `except RuntimeError: pass` (line 135) with
  `logging.getLogger(__name__).debug("threadsafe notification publish could not
  reach an event loop for user %s; falling back to poll-delivery", row.user_id)`.
- It is in the **fallback** branch only (the `loop.create_task` path's
  `get_running_loop()` failure). The primary `anyio.from_thread.run` path
  (lines 126-129) and its `except Exception: pass` are untouched.
- `row.user_id` is a plain scalar captured on the already-committed row; reading
  it in the except block triggers no lazy-load / DB I/O (expire_on_commit=False).
- Severity is `debug`, lazy `%s` formatting — no overhead on the hot path, no PII
  beyond a user id. Matches the async sibling `flush_status_notifications`'s
  intent (observable instead of silently swallowed). No control-flow change: the
  function still returns normally and the row is still poll-delivered. Correct.

## Full-surface re-sweep (each area: status)

**Status-transition CAS paths — CLEAN.** All 11 mutating paths use a row-count-
guarded compare-and-swap (`sql_update(...).where(id, status==expected)` →
`if cas.rowcount == 0: rollback + 409`), re-verified by enumerating every
`sql_update`/`rowcount` site:
- claim `sync.py:139`, submit `sync.py:60`, generic PATCH `requirements.py:311`,
  finalize-deliver `delivery_upload.py:251` (+ revert CAS 276), accept
  `deliveries.py:173`, revision `deliveries.py:227`, auto-process trigger
  `auto.py:85`, decomposition confirm/dismiss `decompositions.py:177/225`,
  meeting-insight confirm/dismiss `meetings.py:454/548`.
- `update_status` allowed-transitions table is closed (`delivered`/`accepted`/
  `cancelled` → `set()`); role gates fire before the CAS; `worker_transition`
  correctly requires a local client. No double-act window: a lost CAS rolls back
  and 409s with the current status. The `delivered`/`accepted` timestamp writes
  are `not r.x`-guarded (idempotent).
- Background writers that flip status without a CAS (`auto.py` finalize, delivery
  `_finalize_doc`, decomposition/meeting/knowledge workers) all re-check
  `r.status == <expected>` before writing, so a user-cancel mid-LLM cannot be
  clobbered — verified at `auto.py:166,242`, `delivery_upload.py:364,426`,
  `chat.py:188` (summary only on draft/clarifying).

**Background tasks reach terminal state on every path — CLEAN.** `auto._run_
and_finalize` (try/except → `_mark_auto_failed`, status-aware so a late error
after commit won't clobber `delivered`), `_finalize_doc` (→ `_recover_stranded_
delivery` → startup sweep backstop), `_process_decomposition`, `_process_
meeting`, `_process_knowledge_ask` all rollback-then-requery on exception and
settle both the job and the owning record. `main._resume_stuck_jobs` is the
crash backstop: job-driven recovery (`ai_processing`→ready, `delivery_doc_
pending`→delivered) PLUS the no-job `delivery_doc_pending` sweep, plus meetings/
asks. No zombie path found.

**3 next_seq/code allocation sites — CLEAN, family-closed.** All three carry the
5-try `IntegrityError`→rollback→re-read retry on the `code` UNIQUE constraint:
`requirements.create_requirement:118-189`, `meetings.confirm_meeting_insight:
478-519`, `project_drive.create_drive_comment:1369-1389`. Each re-loads ORM
state after rollback and exhausts to a 409/safe-state, never a silent 500 with
lost user input (the drive-comment + meeting-insight rows are committed *before*
the allocation loop; create_requirement's `notes_to_publish` resets per attempt).

**Auth/permission matrix — CLEAN.** `permissions.py`: admin READ bypass precedes
the project-active filter (audit any archived/deleted project); admin WRITE paths
respect project-active (must restore first). Submitter/assignee/observer gates
consistent across view/assets/claim/work/manage. `deliveries._ensure_writable_
project` gives admins the explicit "restore first" 409 on write to an
archived/deleted project; non-admin gets a 404 (no existence leak). `auth.py`
treats soft-deleted users as nonexistent on every path and avoids holding the
SQLite writer lock open in the worker-token fallback. Projects enumeration is
identity-scoped (NULL-owner orphans admin-only).

**LLM-output parse sites — CLEAN, fail-closed.** `llm_agent._safe_parse_json`
(None on malformed/wrong-action → 1 retry → `error` event), `task_decomposition.
analyze_requirement` (`except Exception` → `_fallback`), `meeting_agent.analyze_
meeting` (→ `_fallback`), `drive_comment_agent.classify_drive_comment` (raises
RuntimeError, and the sole caller `create_drive_comment:1336-1349` catches it and
marks the comment `review_failed`). Every parse validates the discriminant
(`action`/`kind`/`item_type`) and defaults out-of-range values.

**No transaction held across an await (LLM calls) — CLEAN.** `chat_step` closes
`db_sync` before the SSE stream; the per-turn write uses a fresh `db2` after the
stream. `create_drive_comment` commits the `pending_llm` row BEFORE `await
classify_drive_comment` (the documented SQLite single-writer rationale). All
background workers `db.commit()` before each `await analyze_*/auto_process/
answer_from_hits` and before every `await publish_*`. `auto_agent.py` touches no
DB session at all (verified by grep), so the sandboxed LLM run holds nothing.

**No swallowed exception that hides a failure — CLEAN.** Every `except …: pass`
audited: temp-file unlink cleanup (real error already raised), rollback-before-
reroute in worker handlers (logged via `logger.exception` immediately prior),
best-effort `stat()`/reindex reads (item skipped, not lost), the threadsafe-bridge
primary path (fallback runs next; now logged), ASR/decode fallback chain (returns
a clear placeholder), and the drive.changed best-effort publish (row committed,
poll fallback). None mask a failure that loses data or strands a record.

**Migration safety / FK integrity — CLEAN.** `schema_migrations.ensure_runtime_
schema` is fully idempotent (PRAGMA-check before ADD COLUMN, `CREATE … IF NOT
EXISTS`, `INSERT OR IGNORE`, `CREATE INDEX IF NOT EXISTS`). owner_user_id backfill
has the `created_at <=` guard against recycled-nickname inheritance. Boot-time
orphan null-out covers all 5 cross-refs so `PRAGMA foreign_keys=ON` writes pass
on legacy schemas. `delete_requirement` archives notifications + nulls the 4
cross-references in app code before delete (portable across old NO-ACTION FK
schemas). `db.py` sets WAL + busy_timeout=5000 + foreign_keys=ON +
expire_on_commit=False.

**N+1 on hot/polled paths — CLEAN.** Drive manifest/changes (45s client poll) use
`_build_manifest_maps` (2 queries total, in-memory path-walk). Requirement list/
detail use `selectinload(assignments→user)`. The only residual lazy-load is
`_ensure_due_notifications`'s `ws.requirement.project_id` inside the `blocked`
loop — bounded by `limit(100)` and only when blocked workspaces exist (rare); a
pre-existing accepted-minor, not a new P1/P2.

## Findings (if any)

**None.** Backend is CLEAN. R14 is a clean round — streak continues toward the
4-consecutive target.
