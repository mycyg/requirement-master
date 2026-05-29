# R7 Round 10 — Backend final / production-readiness

HEAD `a6f8ada` (R7.9). Last line of defense before prod (192.168.5.53) + GitHub.

## Verdict: NEEDS FIXES (1)

One real P2 blocker: two detached background tasks (`_run_and_finalize`,
`_finalize_doc`) have an **uncaught exception window in their post-LLM
finalization DB block** — a commit failure / disk-full there leaves the
requirement stuck (`ai_processing` / `delivery_doc_pending`) with no terminal
state until the next process restart. Everything else is production-ready. The
three R7.9 fixes are all correct. WAL + busy_timeout makes the trigger less
likely but not impossible, and a disk-full zip write is a deterministic
non-DB trigger. This is exactly the "no zombie jobs on every path" requirement.

---

## R7.9 fix verification (3 items) — ALL CORRECT

### 1. `auto_agent.py` sandbox rlimits + to_thread — CORRECT ✔
- **preexec_fn won't break exec on Linux:** caps only CPU(120s) / AS(2 GiB) /
  FSIZE(256 MiB) / NOFILE(512). `RLIMIT_NPROC` correctly **omitted** (per-UID,
  would risk failing `fork`/exec on a busy multi-tenant box). No `chroot`/
  `unshare` that could fail. `_set_rlimit` reads the existing `hard` limit and
  `min()`s against it (line 261-263) so it never tries to *raise* a limit
  (which would `EPERM` for a non-root process) — it only lowers, always
  permitted. Wrapped in `try/except (ValueError, OSError): pass` (line 264) so
  any platform quirk is a no-op, never a failed run. ✔
- **resource guard correct on Windows:** `import resource` is POSIX-only;
  guarded `try/except ImportError → resource = None` (line 20-24). Both
  `_set_rlimit` and `_sandbox_rlimits` early-return when `resource is None`,
  and the `subprocess.run` passes `preexec_fn=... if resource is not None else
  None` (line 325). On Windows, `preexec_fn` is **always None** — correct,
  since CPython rejects a non-None `preexec_fn` on Windows with `ValueError`.
  Imports clean on win32 (confirmed by commit's own validation). ✔
- **to_thread wrapping correct, no race:** `_tool_run_command` is now
  `await asyncio.to_thread(_tool_run_command, workdir, args, cwd, timeout_s)`
  (line 479-485). Args are passed positionally in signature order — verified
  against `def _tool_run_command(workdir, args, cwd=".", timeout_s=None)`.
  `workdir` is a read-only `Path`; `args`/`cwd`/`timeout_s` are per-call
  locals. The only shared surface is the per-requirement sandbox filesystem
  (isolated per `req_id`); `(workdir/".tmp").mkdir(exist_ok=True)` is
  idempotent. No shared mutable state between concurrent invocations → no
  race. This also fixes the real event-loop block (subprocess.run up to 60s
  was inline, freezing all SSE/health). ✔
- **rlimit values sane:** 120 CPU-s is a backstop above the 60s wall-clock
  per-command cap (line 314) — legitimate pytest/tsc/node runs finish well
  under both. 2 GiB AS, 256 MiB single-file, 512 FDs comfortably exceed any
  legit python/node/pytest run while still bounding a mem-bomb / disk-fill /
  fd-leak. Won't reject legitimate runs. ✔

### 2. `project_drive.py create_drive_comment` — CORRECT ✔
`project_drive.py:1314-1408`. R7.9 moved the `pending_llm` `db.commit()` to
**line 1332, BEFORE** `await classify_drive_comment(...)` (line 1334).
- **No transaction held across the await:** the writer/connection is released
  at line 1332; the multi-second LLM round-trip runs with no open txn. Matches
  the meeting/decomposition pattern. The S2 finding (SQLite writer pinned for
  full LLM latency, throttling all app-wide writes) is closed. ✔
- **Comment never lost:** committed `pending_llm` at 1332. On classify failure
  (1335-1343) re-query by `comment_id` → `review_failed` + commit. On
  `requirement_change`, phase-1 `posted` commit at 1354 BEFORE the racy code
  alloc; if all 5 retries fail the comment stays `posted` (logged, not 500'd,
  line 1391-1397). On `posted` branch, single commit at 1400. All 3 branches
  re-query by id and commit a terminal status. ✔
- **R7.8 two-phase code-race retry intact:** the 5-try `IntegrityError`
  loop (1363-1383) + post-rollback re-query (1386) survive verbatim. ✔
- **Minor (not a blocker):** the classify-failure path at 1336-1343 has a
  defensive `if comment:` but the final `return _comment_out(comment)` (1343)
  is reached even if `comment` were None → `_comment_out` would `AttributeError`
  on None (no None-guard, line 155). Unreachable in practice (phase-0 committed
  at 1332 so `.first()` always returns the row), but the guard is misleading —
  either drop it or `return` inside it.

### 3. `prompts/auto_agent.md` — CORRECT ✔
Rule 3 no longer asserts "network access is unavailable." It now states "There
is no shell" (enforced: `shell=False`), "capped CPU/memory/file-size/
file-descriptors" (enforced: rlimits), and frames network as an *instruction*
("must not be assumed reachable" / "Do not depend on the network") rather than
a false capability claim. "package installs are blocked" is accurate (line
296-297 in code). No remaining false assertion. ✔ The S1 residual (a
`python -c` one-liner still has `socket`/`urllib`; no netns) is now an
honestly-documented accepted risk under the trusted-LAN, authenticated-author
threat model — consistent with DEPLOY.md ("适合内网；上公网前必须加密+HTTPS").

---

## Startup/shutdown + config guards

**Lifespan (`main.py:172-203`) — solid.**
- Migrations: `Base.metadata.create_all` + `ensure_runtime_schema(engine)` run
  before any task starts (line 187-188). All data dirs created idempotently.
- Crash recovery: `_resume_stuck_jobs()` (line 99-160) awaited synchronously at
  boot (line 191) before serving — fails any `running` BackgroundJob / `processing`
  meeting / `running` ask older than 15 min, and reverts the driven requirement
  (`ai_processing`→`ready`, `delivery_doc_pending`→`delivered`). Wrapped in
  try/except+log, commits once. This is the backstop for the P2 below.
- Periodic tasks: reindex (5 min, first run +60s) and partial cleanup (6 h,
  first +10 min) both created as tasks (line 193-194), both run their body in
  `to_thread` (off-loop), both wrap each iteration in try/except+`_logger.
  exception` so one failure never kills the loop. ✔
- Graceful shutdown: both tasks `.cancel()` + awaited in `finally` (line
  198-203), swallowing `CancelledError`/`Exception`. Clean. ✔

**Config fail-closed in `APP_ENV=production` (`main.py:163-169`):**
- `COOKIE_SECRET` in {"", "dev-change-me", default} → **RuntimeError, boot
  aborts.** ✔
- `"*"` in `CORS_ALLOW_ORIGINS` → **RuntimeError, boot aborts.** ✔
- `COOKIE_SECURE` — **NOT enforced** (only wired into `set_cookie` at
  auth.py:54). This is *correct by design*: prod target is HTTP on a LAN
  (`http://192.168.5.53:8080`, DEPLOY.md line 202), where a Secure cookie would
  be dropped by the browser and silently break login. See Finding F2 — the
  `.env.example` ships `COOKIE_SECURE=true`, which is the actual footgun.

## Concurrency-under-load final check

- **Single SQLite writer is properly tuned** (`db.py:30-39`): WAL +
  `synchronous=NORMAL` + `busy_timeout=5000` + FK on. Readers never block the
  writer; writers wait up to 5s instead of instant `SQLITE_BUSY`. This is the
  right config for the 7-read-fanout-every-6s dashboard + 60s reminder polling.
- **LLM calls no longer pin the writer:** create_drive_comment fixed (R7.9);
  meeting/decomposition/knowledge/auto agents all run the model with no open
  txn. No endpoint holds a transaction across an `await` on the network now.
- **next_seq / code allocation:** 3 sites, all 5-try IntegrityError retry —
  family confirmed closed (R8/R9, re-verified the drive-comment site here).
- **Residual under-load risk → Finding F1:** when many writers contend (e.g.
  the 5-min reindex writing the corpus + concurrent auto-process finalizations
  + a meeting commit), a write can exceed busy_timeout(5s) and raise
  `OperationalError`. In `_process_meeting`/decomposition/knowledge/ask that's
  caught and turned into terminal `failed`. In the two finalization blocks
  (F1) it is **not** caught.

## Findings

| # | Sev | Area | Summary | Locus |
|---|-----|------|---------|-------|
| F1 | P2 | auto / delivery | Detached background tasks have an **uncaught-exception window in the post-LLM finalization DB block**. `_run_and_finalize` wraps setup+`auto_process()` in try/except→`_mark_auto_failed`, but the delivery-registration block (zip write, `db.commit()`, `flush_status_notifications`, `bus.publish`) has only `finally: db.close()` — **no `except`**. An `OperationalError` (busy_timeout exceeded under contention) or a disk-full zip write (line 189) escapes the detached task uncaught (asyncio default handler only logs it), leaving the requirement in `ai_processing` and the BackgroundJob in `running` until the 15-min `_resume_stuck_jobs` sweep on the **next restart**. `_finalize_doc` has the identical gap (lines 357-385) and is worse: it carries **no job_id**, so the only recovery is restart→`delivery_doc_pending`→`delivered`, silently dropping the delivery doc + the "等你验收" notification. Fix: wrap each finalization block in try/except that re-queries and writes terminal state + fails the job — i.e. mirror `_process_meeting`'s except branch. | `auto.py:148-269`; `delivery_upload.py:357-387` |
| F2 | P3 | config | `.env.example` ships `COOKIE_SECURE=true` (line 5) but the documented prod deploy is plain HTTP on a LAN (DEPLOY.md:202). Copying the example verbatim sets the Secure flag on an HTTP origin → browser silently drops the session cookie → login appears to "work" (200) but the user is never authenticated on the next request. Not a code bug; a deploy footgun. Fix: ship `COOKIE_SECURE=false` in `.env.example` with a comment "set true only behind HTTPS", or add it to `_validate_runtime_config` keyed on whether the public URL is https. | `app/.env.example:5` |
| F3 | nit | drive comment | `create_drive_comment` classify-failure path has a misleading `if comment:` guard whose `return _comment_out(comment)` would still crash on `None` (no None-handling in `_comment_out`). Unreachable (phase-0 commit guarantees the row), but the guard implies a None path it doesn't handle. | `project_drive.py:1336-1343` |

### Confirmed CLEAN (not re-flagged)
- R7.9 sandbox rlimits / to_thread / prompt — all 3 correct (above).
- R7.8 two-phase drive-comment commit + post-rollback re-query — correct.
- `_process_meeting` / decomposition / knowledge-ask — full try/except→terminal
  `failed` + rollback + re-query; the correct pattern F1 should copy.
- All 6 LLM-output parse sites — fail-closed / fallback, no stuck jobs (R9).
- SQLite WAL+busy_timeout+FK; lifespan migrations + crash sweep + graceful
  task cancel; production fail-closed on COOKIE_SECRET + CORS wildcard.
- Best-effort swallows (temp-file unlink, bus.publish, rlimit, queue-full) all
  either log or re-`raise` the real error — none hide a state-mutation failure.
- Tool-layer path traversal / symlink escape blocked by `_safe_path.resolve()`;
  LLM key scrubbed from sandbox child env.

### Recommendation
Ship F1 before prod (it is the one true "zombie job on a real path" gap the
brief asks to be the last line of defense on). F2/F3 are deploy-doc / cosmetic
and can ride along. With F1 fixed, declare **PRODUCTION-READY**.
