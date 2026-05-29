# R7 Round 20 — Backend final correctness

## Verdict: CLEAN (no P1/P2)

Fresh full read of every Python module under `app/` (4 core modules, models,
schemas, 11 services, 22 routers) at HEAD `3dcf440` (R7.17). Highest-bar pass:
Pythonic correctness, error handling, type safety, edge cases, resource
management, datetime/encoding. No P1/P2 found. A few P3 notes below, all
non-blocking on a frozen tree.

## Per-area status

**Routers — all CLEAN**
- `auth`, `requirements`, `sync`, `auto`, `chat`, `delivery_upload`,
  `attachments`, `deliveries`, `projects`, `project_drive`, `meetings`,
  `voice`, `knowledge`, `push`, `users`, `calendar`, `reminders`,
  `notifications`, `client_devices`, `comments`, `decompositions`,
  `planning`, `jobs`, `health`, `workspaces`.
- Status codes correct (201 create, 204 delete, 409 race, 410 missing-on-disk,
  413 too-large, 403/404 permission/existence). Pydantic field constraints on
  every input model (patterns, min/max, ge/le). Permission gates consistent
  via `services/permissions`; admin read-override vs write-active-project
  distinction is applied uniformly.
- Concurrency: every state mutation that can double-fire uses an atomic CAS
  (`UPDATE ... WHERE status=old`) with rollback + 409 — status, claim, submit,
  auto-process, finalize-deliver, accept, revision, plan confirm/dismiss,
  meeting-insight confirm/dismiss. Monotonic allocators (`next_seq`,
  `Delivery.round`, drive `version_no`) all use 5-try IntegrityError retry.
- SSE framing in `chat`/`push` correctly uses `splitlines()` to avoid bare-`\r`
  record-split; per-requirement stream is permission-gated; `/stream/me` uses
  the authenticated user id (not a path param) so no cross-user subscribe.

**Services — all CLEAN**
- `auto_agent`: path-prefix sandbox (`_safe_path`), command allowlist, no shell,
  null-byte arg reject, POSIX rlimits best-effort, zip ratio guards, subprocess
  off-loop via `to_thread`, per-turn + total timeout, `finally` publishes
  `ai.done`. Threat residual (network egress) documented and accepted.
- `delivery_doc`: zip-bomb defenses (entry/total size, ratio, count), path
  traversal blocked in `_safe_zip_name` + `_safe_extract_entries`, temp dir via
  context manager.
- `knowledge`: rebuild does delete-rows-then-commit-then-unlink (correct order
  so a failed commit can't resurrect a row whose file is gone); search uses rg
  with timeout + python fallback; soft-deleted projects/users excluded.
- `lifecycle`/`notifications`: template substitution via `str.replace` (not
  `.format`) to neutralize hostile `{...}` in nicknames; dedupe with
  content-change guard; threadsafe publish bridge with logged poll-delivery
  fallback.
- `presence` (RLock), `push_bus` (asyncio.Lock, bounded queue drop-on-full),
  `schema_migrations` (idempotent, FK orphan cleanup), `partial_uploads`,
  `assignments`, `schedule`, `workspaces`, `activity`, `file_parser`,
  `sync_manifest`, `task_decomposition`, `meeting_agent`,
  `drive_comment_agent`, `llm_agent`: all correct. Every `except Exception` is
  justified (LLM/JSON tolerance, best-effort cleanup, background-task settle).

**Core — CLEAN**
- `main` lifespan: ordered boot, crash-recovery sweep for stranded jobs/
  deliveries/meetings/asks, periodic reindex + partial cleanup both offloaded
  via `to_thread`, tasks cancelled on shutdown. SPA fallback won't swallow
  api/asset/download/client paths.
- `db`: SQLite WAL + busy_timeout + `foreign_keys=ON` per connection; session
  always closed in `get_db` finally.
- `auth`: itsdangerous-signed cookie, sha256 client-token, soft-deleted users
  rejected on every auth path, stream auth uses short-lived session.
- `models`/`schemas`/`config`: type hints throughout, modern syntax.

## P3 notes (non-blocking)

- `routers/voice.py:31` — `transcribe` calls `r.json()` on a 200 ASR response
  without a try/guard, unlike `list_voices` which catches `ValueError`. A 200
  with a non-JSON body would surface as a 500 instead of a clean 502. ASR is a
  trusted internal service that returns JSON, so unreachable in practice.
- `services/file_parser.py:24` — on markitdown failure, the error string is
  returned as `full` text and gets persisted/indexed as content. Intentional
  (visible error marker) but means a parse-failure marker can appear in
  knowledge search snippets. Cosmetic.
- `services/sync_manifest.py:59,89` — `a.user.nickname` / `w.user.nickname`
  accessed without None-guard. Safe under the invariant that users are only
  soft-deleted (never FK-removed), which holds project-wide; flagging only as a
  latent assumption.
