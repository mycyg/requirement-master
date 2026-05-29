# R7 Round 8 — Backend deep sweep

## Verdict: NEEDS FIXES (1)

HEAD `07b5760` (R7.7). Confirmed `git show --stat 07b5760` touches **no** `app/*.py`
(R7.7 = tauri.ts / ProjectDrive.tsx / SettingsDialog.tsx only), so the Python is
byte-identical to the R7 CLEAN pass. This round therefore stops re-verifying the
known-good surface and instead attacks from the angles the brief named: CAS
interleavings, full lifecycle enumeration, background-task restart safety, file
handling, and the permissions matrix.

That hard look surfaced **one real, long-standing issue** that prior rounds
under-covered: `create_drive_comment` is the **third** site that bumps
`project.next_seq` and inserts a `Requirement` against the `code` UNIQUE
constraint, but — unlike its two siblings (`create_requirement`,
`confirm_meeting_insight`) — it has **no IntegrityError retry**, and the failing
`db.flush()` is outside every `try/except`. A concurrent-classify race 500s and
**loses the user's comment row entirely**. This is pre-existing (since `7cb32ca`,
before the R7 baseline), not an R7 regression. Rated **P2** (low probability,
but worst-of-the-three failure mode + data loss + no recovery path).

Everything else is genuinely clean and the prior dispositions hold.

---

## CAS / concurrency matrix

Enumerated every status-mutating site. All but one use the strict CAS pattern
(`UPDATE … WHERE id=? AND status IN (old)` → check `rowcount==0` → rollback +
409). The exception is the next_seq race below.

| Transition | Site | Guard | Verdict |
|---|---|---|---|
| `ready→claimed` | `sync.py:138` claim | CAS `WHERE status='ready'`; rowcount→409 | ✅ winner-takes-all; loser 409s |
| `summary_ready/ready→ready` | `sync.py:59` submit | CAS `WHERE status IN(summary_ready,ready)` | ✅ idempotent dst, no double-SSE |
| generic PATCH | `requirements.py:299` update_status | CAS `WHERE status=old` + allowed-map + role/device gate | ✅ |
| `…→ai_processing` | `auto.py:82` trigger_auto | CAS `WHERE status IN(summary_ready,ready)` | ✅ one task spawned |
| `ai_processing→delivered` | `auto.py:164` finalize | **re-checks** `r.status!='ai_processing'` post-LLM → skip + rmtree + job "succeeded-skipped" | ✅ cancel-during-AI safe |
| `claimed/doing/revision→delivery_doc_pending` | `delivery_upload.py:250` finalize | CAS + full `_rollback_status` (rollback→revert-UPDATE→commit) on `os.replace`/Integrity/any exc | ✅ no permanent strand |
| `delivery_doc_pending→delivered` | `delivery_upload.py:364` _finalize_doc | `if r.status=='delivery_doc_pending'` guard | ✅ |
| `delivered→accepted` | `deliveries.py:172` accept | CAS `WHERE status='delivered'` | ✅ races request_revision; first wins |
| `delivered→revision_requested` | `deliveries.py:226` request_revision | CAS `WHERE status='delivered'` | ✅ symmetric with accept |
| `revision_requested→doing` | PATCH | CAS + allowed-map | ✅ |
| `draft→clarifying`, `→summary_ready` | `chat.py:117/188` | in-process `_chat_running` set slot (atomic add, no await between `in`+`add`) + post-LLM `status in {draft,clarifying}` re-check | ✅ |
| plan `draft→confirmed/dismissed` | `decompositions.py:176/224` | CAS `WHERE status='draft'` | ✅ no double apply_confirmed_plan |
| insight `pending→confirmed/dismissed` | `meetings.py:453/547` | CAS incl. `confirmed-but-stranded` retry arm | ✅ (R7-R1 fix retained) |
| **drive comment → new Requirement** | **`project_drive.py:1337-1355`** | **next_seq bump + flush, NO Integrity retry, NO try/except** | **❌ FINDING-1** |

Interleaving conclusions:
- **Double-click / two-tab on any transition** → second request's CAS sees
  `rowcount==0` and 409s. No double-act, no double-notification (dedupe_key also
  guards), no double Delivery row.
- **Cancel during a long async job** (AI, delivery-doc, decomposition, meeting):
  every background finaliser re-reads status and guards before writing
  (`auto.py:164/240`, `delivery_upload.py:364`, `chat.py:188`,
  `decompositions.py:276`). A `cancelled` (terminal) status is never resurrected.
- **next_seq** is bumped at three sites; SQLite WAL gives each request its own
  snapshot, busy_timeout only makes the loser *wait* for the write lock, not
  re-read — so two concurrent inserts can compute the same `SLUG-NNN`. Two of the
  three sites retry on the resulting `IntegrityError`; the drive-comment site
  does not (FINDING-1).

---

## Lifecycle state-machine enumeration

Full status set: `draft, clarifying, summary_ready, ready, claimed, doing,
ai_processing, delivery_doc_pending, delivered, revision_requested, accepted,
cancelled`.

**Entry points (creation):** `draft` ← create_requirement / confirm_meeting_insight
/ create_drive_comment.

**Reachability graph (all edges, with the writer that owns them):**
```
draft        → clarifying (chat) | summary_ready (finalize-summary admin) | cancelled (PATCH)
clarifying   → summary_ready (chat / finalize-summary) | cancelled (PATCH)
summary_ready→ ready (submit) | ai_processing (auto) | clarifying (PATCH, re-open) | cancelled (PATCH)
ready        → claimed (claim / PATCH) | ai_processing (auto) | cancelled (PATCH)
claimed      → doing (PATCH) | delivery_doc_pending (deliver) | cancelled (PATCH)
doing        → delivery_doc_pending (deliver) | cancelled (PATCH)
revision_req → doing (PATCH) | delivery_doc_pending (deliver) | cancelled (PATCH)
ai_processing→ delivered (auto success) | ready (auto failure / resume) | cancelled (PATCH)
delivery_doc_pending → delivered (_finalize_doc / resume) | cancelled (PATCH)
delivered    → accepted (accept) | revision_requested (request_revision)
accepted     → (terminal)
cancelled    → (terminal)
```

Checks:
- **No dead-ends except the two intended terminals** (`accepted`, `cancelled`).
  Every other status has at least one forward edge AND a `cancelled` escape.
- **`ai_processing` / `delivery_doc_pending` are not stranding states**: the
  owning async task always re-writes them, and on process death `_resume_stuck_jobs`
  (main.py:99) reverts `ai_processing→ready`, `delivery_doc_pending→delivered`
  for any job left `running` >15 min. No status is reachable with no owner.
- **PATCH allowed-map is a strict subset of the real graph** (requirements.py:261).
  Cross-checked: the destinations PATCH *cannot* reach (`ready`, `delivered`,
  `accepted`, `delivery_doc_pending` as a target) are exactly the ones owned by
  dedicated endpoints with their own CAS — PATCH correctly cannot shortcut them.
  `summary_ready→clarifying` (re-open for more clarification) is intentional and
  gated to the submitter.
- **Terminal-status writes cannot be clobbered**: `delivered: set()`,
  `accepted: set()`, `cancelled: set()` in the PATCH map; and the async finalisers
  all guard on the expected source status, so a mid-flight cancel wins.
- **No reachable-but-wrong edge.** e.g. you cannot `accept` anything that isn't
  `delivered`; cannot `claim` anything that isn't `ready`; cannot `deliver` from
  `delivered`.

---

## Background-task crash/restart safety

| Task | Spawn | Session hygiene | Restart recovery |
|---|---|---|---|
| `_run_and_finalize` (auto) | `asyncio.create_task` | each phase its own `SessionLocal()` in try/finally `.close()`; final block `finally: db.close()` | `_resume_stuck_jobs` reverts `ai_processing→ready`; workdir left on failure for inspection, rmtree on success/skip |
| `_finalize_doc` (delivery) | `asyncio.create_task` | single session, `finally: db.close()` | resume reverts `delivery_doc_pending→delivered` (skips AI doc, manual review still works) |
| `_process_decomposition` | `BackgroundTasks` (in-loop) | `finally: db.close()`; rollback-then-requery in except | except-arm flips plan→dismissed only `if status=='draft'` (won't orphan a confirmed plan); job→failed |
| `_process_meeting` | `BackgroundTasks` via async wrapper | `finally: db.close()`; rollback-then-requery in except | resume flips `MeetingRecord.processing→failed` >15min |
| knowledge ASK | (knowledge.py) | — | resume flips `running→failed`, appends "可以重新提问" note |
| periodic reindex (5 min) | lifespan task | `_run_reindex_sync` opens+closes its own session; whole body `asyncio.to_thread` so event loop never blocks; `except Exception` logs + retries | cancelled cleanly on shutdown (main.py:198) |
| periodic partial cleanup (6 h) | lifespan task | `cleanup_stale_partials` self-contained; `asyncio.to_thread` | cancelled cleanly on shutdown |

- **No session leaks**: every background `SessionLocal()` is paired with a
  `finally: db.close()` (or closed by the called helper). Re-confirmed across
  auto / delivery / decomposition / meeting / chat / knowledge.
- **Cross-loop bug already fixed**: `_process_meeting_background` is `async def`
  (not sync-wrapping `asyncio.run`) so `bus.publish` targets the main loop's
  queues (meetings.py:285-294). Verified still intact.
- **Mid-job restart**: `_resume_stuck_jobs` runs once at boot before periodic
  tasks start, walks `BackgroundJob/MeetingRecord/KnowledgeAskRun` for
  `running && updated_at<cutoff`, and unfreezes any driven requirement. The
  15-min cutoff means a *currently-running* job on a *just-restarted* process
  (where the old process died <15 min ago) could in theory be left if a job's
  `updated_at` was bumped within the window — but since the old process is gone,
  the job is never touched again by anyone except this sweep on the *next*
  restart; the cutoff protects against killing a genuinely-live job on a
  multi-worker deploy. For the single-worker LAN deploy this is correct.
  **ACCEPT** — matches documented intent.
- **Exception paths**: decomposition/meeting except-arms `db.rollback()` first
  then re-query (so they don't carry partial flushed state) — correct. auto.py
  failure path guards `if r.status=='ai_processing'` before reverting (won't
  resurrect a cancelled req) — correct.

Minor (P4, not counted): `meetings.finalize_meeting_upload` — if a chunk
`stat().st_size` mismatch raises mid-merge (line 264-265) the half-written
`out_path` is left on disk (the partial `pdir` is also left). It's not under
`_partial`, so `cleanup_stale_partials` won't sweep it; it lingers under
`meetings/<project>/<meeting>/`. But the MeetingRecord row rolls back (never
committed), and this requires a client sending a chunk that passed the per-chunk
size check at upload time but changed size before finalize — effectively
impossible without local tampering. Noting only; not actionable.

---

## Permissions matrix spot-checks

Verified `submitter / assignee / admin / observer × active / archived / deleted`:

- **Read paths** (`can_view_requirement_record`, `_assets`, `_ack`): admin
  bypasses BOTH relationship + project-active filters (audit intent, permissions.py
  docstring). Non-admins: project-active required, then submitter/assignee always,
  else only non-private statuses. Private statuses (`draft/clarifying/summary_ready`)
  hidden from observers. ✅
- **Write paths** (`add_attachment`, `manage_assignees`, `claim`, `work`,
  accept/revision): admin bypasses relationship filter but **still respects
  project-active** — archived/deleted ⇒ 404 (non-admin) or 409 "restore first"
  (admin, deliveries.py `_ensure_writable_project`). ✅ Archive can't be silently
  bypassed.
- **Device gate**: `worker_transition` (claim, work-state changes, cancel-by-
  non-submitter) requires `local_user is not None` (requirements.py:290). claim /
  sync / deliver use `require_local_client`. Admin does NOT bypass device safety
  (auth.py / permissions.py docstring). ✅
- **Upload owner gate**: every chunk/finalize re-checks `meta['user_id']==user.id`
  (attachments, delivery_upload, meetings) — a different authed user cannot hijack
  someone's in-flight upload. ✅
- **`finalize_summary`** admin-only bypass guarded `is_admin` (requirements.py:553);
  refuses to clobber an existing summary_ready unless override supplied. ✅
- **delete_requirement**: admin always; submitter only while private/cancelled;
  explicitly NULLs cross-refs before delete (portable across legacy NO-ACTION FK
  schemas). ✅
- **Meeting reads** (`list_meetings`/`get_meeting`/`_meeting_out`): project-scoped,
  any authed project member sees transcript+minutes+insights even if the meeting
  is *linked to a private requirement* they couldn't open directly. This is the
  **documented project-scoped design** for meetings (init enforces the
  per-requirement check at upload; reads are project-level by intent). Unchanged
  since R6, accepted by prior rounds. **ACCEPT (by design)** — flagging for
  awareness only.

DB layer (encoding / tz / NULL): `datetime.utcnow()` (naive UTC) used uniformly,
so all interval math is consistent; `ensure_ascii=False` on every JSON dump so
CJK round-trips intact; `due_at`/optional FKs all NULL-guarded at use sites;
SQLite WAL + busy_timeout=5000 + foreign_keys=ON configured per-connection. No
edge issue found.

---

## Findings (if any)

### FINDING-1 (P2) — `create_drive_comment` has no IntegrityError retry on the `code` UNIQUE race, and the failing flush is uncaught → 500 + comment lost

**File:** `app/routers/project_drive.py:1337-1355`
**Provenance:** pre-existing since `7cb32ca` (before the R7 baseline); NOT an R7
regression. Under-enumerated by prior rounds — R7-R1 data-integrity.md:157 listed
only `create_requirement` as the retry-protected `code` writer and did not name
this third `next_seq` site at all.

**The divergence.** Three endpoints bump `project.next_seq` and INSERT a
`Requirement` against the `code` UNIQUE constraint:

| Site | next_seq | IntegrityError retry? |
|---|---|---|
| `requirements.py:127` create_requirement | yes | ✅ 5-iter loop (`:118-178`) |
| `meetings.py:480` confirm_meeting_insight | yes | ✅ 5-iter loop (`:478-519`) |
| `project_drive.py:1338` create_drive_comment | yes | ❌ **none** |

In create_drive_comment the only `try/except` wraps `classify_drive_comment`
(the LLM call, `:1325-1333`). The subsequent `project.next_seq += 1` →
`db.add(draft)` → `db.flush()` (`:1338-1350`) and `db.commit()` (`:1355`) are
**outside** every guard. There is also no app-level `add_exception_handler`
(grep-confirmed), so an `IntegrityError` propagates as a raw HTTP 500.

**Race.** Two concurrent `POST /projects/{id}/drive/folders/{fid}/comments` on
the **same project**, both classified `requirement_change` by the LLM:
1. Both sessions read `project.next_seq = N` (WAL snapshot; the await on the LLM
   call widens the window before the read at `:1338`).
2. Both compute `code = SLUG-(N+1)`, both `db.add(draft)`.
3. SQLite serialises the writes; the first commits `code=SLUG-(N+1)`. The second
   waits on the lock (busy_timeout) then INSERTs the **same** `code` → `UNIQUE
   constraint failed: requirements.code` → uncaught `IntegrityError`.

**Impact (why it's worse than the siblings, hence P2 not P3):**
- HTTP 500 to the user.
- The whole transaction rolls back — including the `ProjectDriveComment` insert
  at `:1322-1323`. **The user's comment is lost**, not just the derived draft.
  (The other two sites only fail to allocate a *retryable* code; they don't
  destroy unrelated user input.)
- No recovery path: the user just sees a generic error and must retype.

**Probability:** low at LAN scale (needs two AI-as-requirement_change comments on
one project inside the LLM round-trip window). Hence P2, not P1.

**Fix shape (do NOT apply — review only):** wrap `:1337-1352` in the same
5-iteration `IntegrityError` retry the sibling sites use — re-read the project,
re-bump `next_seq`, recompute `code`, `db.flush()`, break on success / rollback +
retry on `IntegrityError`. Ideally insert the comment in its own committed step
first (so a code-allocation failure can't take the comment down with it), then
allocate the draft requirement in the retry loop. Mirrors
`confirm_meeting_insight`'s two-phase pattern.

---

### Everything else — CLEAN

No other P1/P2/P3. The CAS matrix, lifecycle graph, background-restart recovery,
chunked-upload assembly (size + name-set + sha validation, owner gate, partial
cleanup), zip handling (path-traversal `_safe_zip_name` + zip-bomb caps +
`_safe_extract_entries` realpath check), delivery packaging, permissions matrix,
and DB tz/encoding/NULL handling are all sound and match the prior CLEAN
dispositions. The single finding above is a long-standing latent race the
hard-look surfaced, not a new break.
