# R7 Round 14 — Security + Rust confirmation

## Verdict: GREEN (ship-ready)

HEAD `580754c`. Round 1 of the final 4-consecutive-clean confirmation sequence.
No new MEDIUM+ findings. The streak holds — security has been GREEN since R7.6
and stays GREEN. Only accepted residuals remain (H1 LAN-trust, M6 knowledge
cross-project, sandbox network-egress, L5–L8), none worse than documented.

The sole code delta since the last fully-clean round (R7.12 `44e1f9a` → HEAD
`580754c`) is a single `logging.debug(...)` line in `notifications.py`'s
no-loop fallback (logs only the opaque `user_id`; no PII, no behaviour change,
zero new attack surface). Rust client: byte-identical since R7.9 — `git diff
a6f8ada HEAD -- client-tauri/src-tauri/ client/src-tauri/` is empty.

## Final secret scan

- **Tracked tree:** clean. Pattern scan (`sk-…{20,}`, `AKIA…`, `ghp_…`,
  `xox[baprs]-`, `BEGIN … PRIVATE KEY`) over the whole tree (excluding lockfiles)
  → **0 real matches**. Only `sk-replace-me-with-your-deepseek-key` placeholder
  in `app/.env.example:14`. "disk-" substrings are the only `sk-`-pattern false
  positives (comments).
- **Full reachable git history (all blobs, every commit via `git rev-list
  --all`):** **0 real secrets**. Only the `replace-me` placeholder appears.
- **`scripts/server_creds.py`:** never tracked (`git ls-files` empty), never in
  history (`git log --all` empty), gitignored (`git check-ignore` confirms).
- **`visual_tmp/`:** never tracked, never in history, gitignored. No committed
  cookie/auth-token value anywhere — the only `Set-Cookie`/`cookie` history hits
  are source comments describing the cookie-jar concept, not secret values.
- `LLM_API_KEY` default is empty string in `config.py`; real key lives only in
  the gitignored `.env`.

## all-topic PII check + per-user topic correctness

**`all`-topic events audited** (the global SSE topic every Tauri client opens):

| Event | Payload | PII? |
|---|---|---|
| `delivery.doc_ready` (R7.11, delivery_upload.py:386-388, 436-438) | `{delivery_id, round, requirement_id}` | **IDs only — PII-free** ✔ |
| `requirement.updated` (many) | `{requirement_id, status}` (+ `assignees` count) | IDs/enum only ✔ |
| `requirement.ready` (auto.py:261, sync.py:81) | `{requirement_id, title, …}` | requirement **title** — pre-existing H1 LAN-trust residual, unchanged |
| `revision.requested` (deliveries.py:253) | `{requirement_id, round, reason_preview[:160], requested_by}` | reason preview + nickname — pre-existing H1 residual, unchanged |
| `drive.comment` (project_drive.py:1409) | `{project_id, folder_id, status, draft_requirement_id}` | IDs/enum only ✔ |
| `drive.changed` (project_drive.py:273-277) | metadata dict | non-PII drive sync ping ✔ |
| `meeting.ready` / `meeting.insight_confirmed` (meetings.py:337, 524) | `{meeting_id, project_id, insight_id, created_requirement_id}` | IDs only ✔ |

`delivery.doc_ready` (the round's focus) is **strictly IDs — PII-free**, exactly
as the inline comment claims. The two title/preview-bearing `all` events
(`requirement.ready`, `revision.requested`) **pre-date this round** and are the
documented H1 LAN-trust residual (acceptable on a trusted LAN; not worse).

**Per-user topic correctness — no cross-user leak:**
- `publish_notification` → `bus.publish(f"user:{row.user_id}", …)` — recipient's
  private channel only. Historical global-`all` fan-out was removed (documented
  in the docstring).
- `publish_notification_threadsafe` → same `topic = f"user:{row.user_id}"`,
  captured **before** the thread boundary; payload `model_dump`'d before crossing
  → no off-thread Session-bound ORM access. anyio `from_thread.run` primary path,
  `loop.create_task` fallback, `debug`-logged no-op terminal fallback. Correct
  per-user topic on every path. ✔
- `jobs.publish_job` → `user:{job.created_by_user_id}` — owner only. ✔
- `/api/push/stream/me` derives topic from `user.id` (authenticated cookie/worker
  identity), **never a path param** → a client cannot request another user's
  stream. `/stream/req/{id}` gated by `can_view_requirement_record`. All three
  streams require `require_stream_user` (401 if unauthenticated). ✔

## Ship-gate

**File-serve endpoints** — all enforce auth + Content-Disposition:
- `attachments.py download_attachment` / `download_chunked` — `current_user` +
  `_require_can_view_assets`; `FileResponse(filename=…)` ⇒ Starlette emits
  Content-Disposition. Stored filenames sanitized via `Path(...).name` (no
  traversal).
- `deliveries.py download_package` / `download_file_from_package` —
  `_require_can_view_assets`; zip member matched on `safe_name`; explicit
  `Content-Disposition: attachment; filename="{Path(filename).name}"` (traversal
  stripped). `:path` param can't escape the zip.
- `project_drive.py download_drive_file` — **M8 inline allowlist intact**:
  `_INLINE_SAFE_MIME_PREFIXES` excludes svg/html/xml; inline path only honoured
  for the allowlist, else `application/octet-stream`; `X-Content-Type-Options:
  nosniff` always set; `content_disposition_type` driven by `inline` flag.

**Auth/authz:** signed (`itsdangerous`) httponly cookie or SHA-256-hashed worker
token; soft-deleted users rejected; admin ops (`set_user_admin`, `delete_user`,
`delete_project`) gated by `is_admin(actor)` with last-admin protection. Path
traversal closed (upload `Path(...).name`, zip `safe_name`, deep-link sanitizer).

**Tauri capabilities** (`capabilities/default.json`): scoped to `main` window;
`fs` limited to `scope-appdata-recursive` (no arbitrary FS); **no
`shell:allow-execute`** despite `tauri-plugin-shell` being a dep — the only
process spawn is the Rust `open_folder` command (shell-metachar reject + `..`
reject + canonical-root containment + single-argv spawn, no shell re-parse). CSP
`script-src 'self'` (no inline script). Deep-link `yqgl://` host-allowlisted,
traversal-stripped, sanitized-path-only emit.

**Dependencies:** `pyproject.toml` and `Cargo.toml` unchanged this round; pinned
floors, no abandoned/known-CVE crates introduced; `reqwest` with
`default-features=false` + explicit feature set.

**Startup guards (fail-closed):** `main._validate_runtime_config()` runs in
`lifespan` before serving — when `app_env=production` it `raise RuntimeError`s
on a default/empty `COOKIE_SECRET` or wildcard `CORS_ALLOW_ORIGINS`. The
`allow_credentials=True` + `*` combination is reachable only in dev (production
rejects `*`).

## Rust production-readiness

Production-ready, **zero reachable panic from untrusted input**. Only two
panic-family calls in the entire client, both at process init and standard
idiom:
- `http.rs:28` `.expect("reqwest client build")` — only fails on a broken TLS
  backend at init; infallible on supported platforms.
- `lib.rs:132` `.expect("error while running yqgl client")` — top-level
  `tauri::run`; failure ⇒ process exit anyway.

No `.unwrap()`/`.expect()` on network responses, deep-link payloads, file reads,
or SSE frames. `open_folder` and `deep_link::handle` use `let-else`/`.ok()` for
graceful rejection. R7.9 auto-agent sandbox rlimits intact (`RLIMIT_CPU=120s`,
`RLIMIT_AS=2GiB`, `RLIMIT_FSIZE=256MiB`, `RLIMIT_NOFILE=512` via `preexec_fn`;
`shell=False`, scoped env, null-byte reject, 60s cap). `knowledge.py` `rg` call
uses `--` separator + argv list. No Rust changes since R7.9.

## Findings

**None.** No new MEDIUM+ (no new findings at any severity). Streak intact —
Round 1 of 4 is GREEN. Accepted residuals unchanged: H1 (LAN-trust: requirement
title / revision reason-preview / nickname on the `all` topic), M6 (knowledge
cross-project), sandbox network-egress (documented), L5–L8.
