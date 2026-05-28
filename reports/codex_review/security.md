# Codex Security Audit

Scope: `c884b60..main` (4 commits: e1c008c, 90ae89d, 9eaf346, b453f3c).
Reviewer worktree: `claude/amazing-chebyshev-c20123` @ 5450fc2 (read-only).

## Verdict

**GREEN with two MEDIUM findings.** Codex's changes are net-positive for security: v0.3.0 hardening was preserved or strengthened, tombstone/soft-delete coverage was broadened across ~10 router surfaces, a real Tauri CSP was added, several risky capabilities were dropped, and a path-traversal hardening pass landed in the Rust sync layer. No regressions to access control. Two issues warrant attention before ship; none block.

---

## Critical (block ship)

_None._

---

## High (fix before next release)

_None._

---

## Medium

### M1 — `paste_drive_items` copy-mode skips per-item ownership check
`D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\app\routers\project_drive.py:907-918`

Codex added `_require_manage_item` to the move branch of paste but NOT to the copy branch. The copy branch only calls `_require_project(project_id)` (line 905) and validates `item.project_id == project_id` (line 908) — meaning any project member can duplicate any drive item in the same project, even items they did not create and where they are neither admin nor project owner. The single-item endpoint `copy_one_drive_item` at line 982 has the same gap (no `_require_manage_item`).

Compare to the move branch (lines 921-927) which iterates `for item in items: _require_manage_item(db, item, user)`. Codex documents in `_require_manage_item` (line 95) that this gate exists to limit drive mutation to "the project owner, admins, or the file owner" — that constraint is inconsistent across copy vs move.

Impact: LOW exploitability (still confined to same project, no read access bypass — only creates a duplicate file row under the requester's name). MEDIUM consistency bug: lets a non-owner sidestep delete-ownership by copying-then-deleting-original (delete is owner-gated but the new copy is created with `created_by_user_id = user.id`, giving the requester full management over it).

Fix: apply `_require_manage_item(db, item, user)` in the copy branch of `paste_drive_items` AND in `copy_one_drive_item`.

### M2 — `identify` enables nickname enumeration via 409 oracle
`D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\app\routers\auth.py:42-55`

New logic: if a nickname already exists and the caller's cookie does not match that user, return `HTTP 409 "nickname already registered"`. If the nickname is free, the call succeeds and issues a cookie for a newly-created user.

The 409 vs 200 distinction is an unauthenticated user-enumeration oracle. An attacker on the LAN can iterate candidate nicknames and learn the membership list (and create dummy accounts for every nickname that doesn't yet exist as a side-effect of probing — small DoS on the user table).

This is a deliberate trade-off (Codex's nickname-takeover defense replacing the prior silent `get_or_create_user`), and is documented in REVIEW_REPORT.md as P0 fix. But on an open LAN where every team member knows everyone else's nickname anyway, the oracle is largely cosmetic. **Acceptable for now; revisit when adding any kind of external network exposure.**

Suggested mitigation (optional, non-blocking): collapse both branches to identical 202-style responses with the actual user creation happening via an admin-approved flow; or rate-limit `/api/auth/identify` per source IP.

---

## Low

### L1 — Tauri CSP `connect-src http://*:* https://*:* ws://*:* wss://*:*` is wide
`client-tauri/src-tauri/tauri.conf.json:31`

Codex replaced `"csp": null` with a real policy — strong improvement. But `connect-src` allows fetch/WebSocket to **any host/port over http or https**. This is intentional (server IP is user-configured at runtime via Onboarding/Settings, so the policy cannot be pinned at build time), but it means a compromised webview script can exfiltrate to arbitrary hosts. Same risk as before the CSP change (no regression), and the rest of the policy (`script-src 'self'` with no `unsafe-eval`, `default-src 'self'`) blocks the most common XSS vectors.

No fix recommended — this is the price of runtime-configurable server. Note for the threat model.

### L2 — Knowledge corpus `_source_docs` removed `User` table join filter for chats only
`app\services\knowledge.py:135-142`

The chat-corpus query is correctly outerjoined on `User` and filters `User.deleted_at.is_(None)`, matching the documented intent ("skip chats authored by users in requirements whose submitter is soft-deleted"). However, this is the **only** corpus source filtered by submitter-tombstone. Comments (line 178), activity (190), workspace updates (200), meetings (215), drive versions (252), and deliveries (282) are filtered by *project* tombstone but NOT by *submitter/author* tombstone.

If your tombstone privacy invariant is "any content authored by a tombstoned user should be hidden from knowledge search", this is incomplete. If the invariant is narrower ("only the AI clarify dialog reveals the user's private thought process and must be hidden"), this is correct as documented. I'll defer to your privacy model — the comment in the file aligns with the narrower invariant, so this is informational only.

### L3 — `safe_relative_path` allows backslash-separated paths even on POSIX
`client-tauri/src-tauri/src/sync.rs:355-374`

`safe_relative_path` splits on both `/` and `\\`. On Linux/macOS, that means a server-supplied path like `evil\..\..\secret` would be treated as a single segment by the OS file APIs but split into `..` components by this normalizer — which then correctly rejects it. Behavior is *safer* than the raw OS, but the trim of `&['/', '\\\\'][..]` at the start could let a Windows-formatted absolute path like `C:\\foo` through if it starts with letters — except the `if trimmed.contains(':')` check (line 359) catches it. Defense in depth holds.

No fix needed; noting because the dual-separator handling is unusual enough to be worth documenting.

### L4 — `download_delivery` uses `create_new` + symlink rejection but no canonicalize on dest
`client-tauri/src-tauri/src/commands/submitter.rs:535-545`

Codex added `OpenOptions::new().write(true).create_new(true)`, symlink rejection via `symlink_metadata`, and `ensure_parent_inside_root` before write. This is solid. The only gap: the existence check uses `symlink_metadata` then `remove_file`, then `create_new` — there's a tiny TOCTOU window where an attacker (with write access to the user's sync_root, which already requires the box being compromised) could race a symlink in between `remove_file` and `create_new`. `create_new` itself prevents writing through a symlink target on POSIX (`O_EXCL`), so this is fine on Linux/macOS. Windows behavior is fuzzier but the practical exploit requires local write access to `sync_root`, which already implies game-over.

Not exploitable in our threat model; noted for completeness.

---

## Soft-delete / tombstone integrity check

File-by-file pass/fail. **All pass.**

| File | Check | Status |
|------|-------|--------|
| `app/services/permissions.py` | Centralized `requirement_project_is_active` helper; `can_*` checks fail closed when project soft-deleted/archived; admin override still applies but only AFTER project-active gate (correct semantics for tombstoned project) | PASS |
| `app/routers/requirements.py` | `_display_nickname` still masks `_deleted_<id8>_originalname` → `"已删除用户"` (line 80). `_ensure_requirement_project_active` raises 404 across 7 endpoints. The v0.3.0 "soft-deleted project mutation refusal" was *replaced* by the new helper which is stricter (404 not 400) | PASS — refactored, not regressed |
| `app/routers/attachments.py` `_require_req` | Project-active join filter added | PASS |
| `app/routers/comments.py` `_require_req` | Project-active join filter added | PASS |
| `app/routers/chat.py` `_require_req` + LLM finalize path | Project-active join filter added inside the streaming closure too — prevents an in-flight LLM run from re-activating a tombstoned requirement | PASS |
| `app/routers/sync.py` `_active_requirement_query` | Soft-deleted/archived filter added to submit / sync-manifest / sync-ack / claim | PASS |
| `app/routers/auto.py` | Filter added to trigger + `_run_and_finalize` + `_mark_auto_failed` (background paths) | PASS |
| `app/routers/decompositions.py` | `requirement_project_is_active` checked at confirm/dismiss AND inside background `_process_decomposition` (twice — before and after the LLM call, the second guards against project being deleted mid-analysis) | PASS — excellent defense-in-depth |
| `app/routers/calendar.py` | List query filters event.project_id + event.requirement_id through joins; per-row visibility re-checked. Create/patch validate links AND check `can_view_requirement_record` | PASS — actually a security strengthening |
| `app/routers/notifications.py` | `_ensure_due_notifications` joins Project for soft-delete filter on both assigned + blocked queries. List endpoint outerjoins on Notification.project_id with `is_(None) OR (not archived AND not deleted)` | PASS |
| `app/routers/reminders.py` | Existing `Project.deleted_at.is_(None)` retained; `Project.archived == False` added | PASS — strengthened |
| `app/routers/workspaces.py` | `requirement_project_is_active` check added to `_require_req` and `_require_item` | PASS |
| `app/routers/health.py` | Added `deleted_at.is_(None)` to both list and per-project endpoints (was only checking `archived == False`) | PASS — strengthened |
| `app/routers/planning.py` | Workload query joins Project and filters tombstone | PASS |
| `app/routers/project_drive.py` `_require_project` | Both archived AND deleted_at checked; raises 404 (not 400) for tombstoned projects across ALL drive endpoints | PASS |
| `app/routers/project_drive.py` `_require_item` | Calls `_require_project(item.project_id)` after item lookup, so soft-deleted-project items raise 404 transparently | PASS — strengthening |
| `app/routers/meetings.py` `_require_meeting` | Calls `_require_project` after meeting lookup | PASS |
| `app/services/knowledge.py` `_source_docs` | All 8 corpus sources (requirements, chats, comments, activity, workspace_updates, meetings, meeting_insights, drive_versions, deliveries) join Project and filter tombstone. Chat query additionally filters `User.deleted_at.is_(None)` on submitter | PASS |
| `app/services/knowledge.py` `search_knowledge` | Outer-joins Project and filters tombstone on document rows (preserves project-less knowledge docs via `or_(project_id.is_(None), ...)`) | PASS |
| `app/services/knowledge.py` `rebuild_knowledge_index` | Now tracks `seen` set and deletes stale `KnowledgeDocument` rows + corpus files for sources no longer in the active query — fixes the v0.3.0 issue where tombstoned content lingered in the corpus | PASS — strengthening |
| `app/routers/projects.py` | `rebuild_knowledge_index` invoked on archive/restore/soft-delete, ensuring corpus reflects new tombstone state | PASS |
| `app/routers/jobs.py` `GET /jobs/{id}` | Now restricted to `job.created_by_user_id == user.id or is_admin(user)` — was open to any authenticated user | PASS — strengthening |

`bulk_download_drive` per-item project access check: **PASS** (lines 780-784 retained, project access verified per unique project_id in the request).

`paste_drive_items` `old_state` recording for undo: **PASS** (line 952, both parent_id and name recorded in the same dict).

`_ensure_no_cycle` depth cap 100 + soft-deleted ancestor inclusion: **PASS** (line 326, `include_deleted=True` on `_require_item` for ancestor walk).

`_copy_item` depth cap 32 + descendants cap 2000: **PASS** (lines 370, 383-386).

`reindex_knowledge` admin-only: **PASS** (`app/routers/knowledge.py:63-67`, `if not is_admin(user): raise 403 "admin only"`).

`_source_docs` no longer reindexes on every search: **PASS** (`search_knowledge` line 364 comment explicitly removes the self-DoS path; reindex now lives in mutation callsites + `_periodic_knowledge_reindex` background task).

---

## Permission decorator coverage diff

**Gained protection (positive):**

- `GET /api/jobs/{job_id}` — was open to any authenticated user; now job-owner or admin only.
- `POST /api/calendar/events` create + `PATCH /api/calendar/events/{id}` — `_validate_links` now requires `can_view_requirement_record` on the linked requirement, blocking calendar-link as a side-channel to confirm private requirement existence.
- `GET /api/calendar/events` list — filters out events whose underlying project/requirement is tombstoned OR private-to-other-user.
- `POST /api/projects/{id}/drive/upload/finalize` replace path — `_require_manage_item` now enforced on `existing` before overwriting.
- `PATCH /api/drive/items/{id}` — `_require_manage_item` enforced.
- `POST /api/projects/{id}/drive/paste` (move branch only) — per-item `_require_manage_item`.
- `POST /api/drive/items/{id}/cut`, `/delete`, `/restore` + `POST /api/drive/bulk-delete` — `_require_manage_item`.
- `POST /api/meetings/{id}/insights/{insight_id}/confirm` — `_require_project` re-check after status transition; commits CAS before drafting requirement (prevents the insight from reverting to pending if requirement-code allocation later fails).

**Lost protection:** None observed.

**Inconsistency (see M1):** `paste_drive_items` mode=copy and `copy_one_drive_item` did NOT receive `_require_manage_item` while the move/delete counterparts did. The copy path remains gated only by project-membership equivalence (`_require_project`), which on this LAN tool effectively means "any authenticated user with project visibility can clone any file in that project". Not a regression (the v0.3.0 baseline was also project-gated only), but an asymmetry against Codex's own newly-introduced policy.

---

## Client capability widening check

**Tauri `capabilities/default.json` — NARROWED (good):**

Removed:
- `core:webview:allow-internal-toggle-devtools` — kills the in-app DevTools shortcut. Reduces post-XSS introspection.
- `shell:allow-open` — kills `shell.open()` from JS, removing a path to arbitrary URL/file launches via the OS shell.
- `process:default` + `process:allow-exit` — JS can no longer terminate the process or invoke process APIs.

Kept (unchanged): fs scopes are `fs:scope-appdata-recursive` only (no widening), dialog still requires user gesture, notification + os + deep-link defaults unchanged.

**`tauri.conf.json` — CSP TIGHTENED:**

`"csp": null` → real policy:
```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data: asset: http://asset.localhost; font-src 'self' data:;
connect-src 'self' http://*:* https://*:* ws://*:* wss://*:*
```

- `script-src 'self'` (no `unsafe-inline` / `unsafe-eval`) — best-in-class XSS mitigation.
- `style-src 'self' 'unsafe-inline'` — needed for the design system; acceptable trade-off, common.
- `img-src` allows `data:` + the Tauri asset protocol; reasonable.
- `connect-src` is wide (`http://*:* https://*:* ws://*:* wss://*:*`) — see L1.

Bundle targets narrowed from `["msi", "nsis", "dmg", "app", "deb", "appimage"]` to `["nsis"]`. Not a security impact, just a release-engineering decision (macOS now built via the new GitHub Actions workflow).

**Install scripts (`client/install-client.ps1`, `client/install-client.sh`) — net safe:**

- No hardcoded credentials. The server URL defaults to `http://192.168.5.53:8080` (LAN intranet, plain HTTP — same as v0.3.0).
- `Invoke-WebRequest -UseBasicParsing` added to PS1 — neutral (avoids IE engine dependency, no security delta).
- `curl -fsSL` used for downloads (fail on HTTP error, silent, follow redirects). `-fsSL` is appropriate; no `-k` / `--insecure` anywhere.
- Default `sync_root` changed from `D:\工作需求` to `D:\YQGL-Work` on Windows (avoids non-ASCII path issues on stripped-locale machines). Linux/macOS: derived from `$HOME`. Neither is a security delta.
- macOS launchd plist generated by Codex installs `RunAtLoad=true` for `$INSTALL_DIR/launch.sh` — the install dir is per-user `~/.local/share/yqgl-client`, no privilege escalation. Heredoc properly escapes `$INSTALL_DIR` via `printf '%s' ... | sed`.
- The Python here-doc that writes `config.json` now reads the existing config first and uses `setdefault` to avoid clobbering user settings on re-install. Bug fix, not security delta.
- **No `iwr | iex`-style remote-execution pipelines in `install-client.ps1` itself.** Note: `scripts/smoke_client_install.ps1` DOES use `iwr -UseBasicParsing "$env:YQGL_SERVER/client/install.ps1" | iex` — but only against a local Python HTTP server bound to `127.0.0.1` for the smoke test. Acceptable in a dev/CI smoke script; would be a major flag if pushed into user docs.

**Client Rust (`sync.rs`, `delivery.rs`, `commands/submitter.rs`, `spec_watch.rs`) — STRENGTHENED:**

This is the most security-substantive change in Codex's diff. New defenses:

- `safe_component()` rejects any string with `/`, `\\`, `:`, or `..`. Used for `project_slug`, `requirement_code`, and attachment names everywhere paths are joined.
- `safe_relative_path()` normalizes server-supplied drive paths, rejecting `..` components and `:`-prefixed Windows roots. Replaces the previous `path.trim_start_matches('/')` which would have happily accepted `..\\..\\Windows\\System32`.
- `ensure_parent_inside_root()` / `ensure_dir_inside_root()` canonicalize the resolved path and verify `starts_with(root_canon)` — catches symlink escapes by canonicalizing AFTER `mkdir`.
- `resolve_server_url()` rejects `download_url` fields that point outside the configured server origin (scheme + host + port). Prevents a malicious manifest from redirecting the auth-bearing client GET to an attacker-controlled host (which would leak the `X-YQGL-Client-Token` cookie). This is a genuine SSRF/credential-leak hardening.
- Download paths now: write to `.{upload_safe_suffix}.download` temp file → verify sha256 → atomic `rename` over target. Replaces the previous "stream straight to final path" pattern. Eliminates a window where a partial / wrong-content file could be observed.
- `delivery.rs zip_dir`: now canonicalizes `src` once and per-entry, skips symlinks explicitly, and double-checks `resolved.starts_with(base)` before zipping. Defends against a worker dir containing a symlink pointing into `/etc` or `~/.ssh`.
- `submitter.rs download_delivery`: refuses to overwrite symlinks; uses `OpenOptions::create_new` to prevent race-replacement of the dest file with a symlink between check and write.

**`client-tauri/web-src/src/lib/tauri.ts` — STRENGTHENED:**

`clientFetch` now strips the `X-YQGL-Client-Token` header and switches `credentials: omit` for any URL whose origin differs from the configured `baseUrl`. Plain XSS or a misuse of `clientFetch("https://attacker/")` no longer leaks the local-client token cookie.

**`shared/src/api/client.ts` — STRENGTHENED:**

`isDesktopRuntime()` now requires both the `yqgl_runtime=desktop` flag AND the presence of `window.__TAURI_INTERNALS__`. `localClientToken()` early-returns null when not in desktop runtime. Prevents the browser web app from accidentally reading and shipping a stale `yqgl_client_token` from localStorage to the server, which would have allowed cross-origin browser sessions to acquire `require_local_client` privileges.

---

## REVIEW_REPORT.md security claims fidelity

Codex added a `2026-05-29 UI / 客户端 / 数据流复核` block to `REVIEW_REPORT.md`. Claims checked against actual diff:

| Claim | Verdict |
|-------|---------|
| "归档或软删除项目后，子需求的澄清对话、评论和活动入口会直接返回 404" | **TRUE** — verified across `chat.py`, `comments.py`, `requirements.py`. The 404 is from the `_require_req` join filter, not a 403, matching the claim. |
| "澄清流后台生成 summary 时再次确认父项目仍处于 active 状态" | **TRUE** — `chat.py:170-178` re-queries with the project-active filter before transitioning to `summary_ready`. |
| "Tauri fresh config 不再把空 IP 计算成 `http://:8080`" | **TRUE** — `config.rs:111-115` adds `&& !self.server_ip.trim().is_empty()` guard. |
| "客户端 Onboarding 移除"双向同步"可选项" | **TRUE** — `Onboarding.tsx:30,162` only offers `off` and `download`. `Settings.tsx:121` matches. Also enforced server-side in Rust (`commands/sync.rs:32-34` rejects `two_way`). |
| "Tauri 默认打包目标从 ... 收敛为 ... NSIS" | **TRUE** — `tauri.conf.json:49` is `["nsis"]`. macOS DMG path moved to separate CI workflow. |
| Earlier bullets in the "本轮已修复" section (claimed to be from prior rounds) — production cookie/CORS guard, partial cleanup, attachment access control, chunk integrity etc. | **NOT INTRODUCED BY CODEX** — these were already present at `c884b60` (your v0.3.0 baseline) and Codex's diff does not touch the relevant files (`auth.py`, `config.py`, `main.py`). The bullets are accurate descriptions of the codebase state, but the "本轮" framing slightly inflates Codex's contribution. Important: Codex did NOT regress any of them. |

No fabricated or self-aggrandizing security claims. The `2026-05-29` block is a faithful summary of Codex's actual contribution; the older "本轮已修复" list correctly describes the codebase but predates Codex.

---

## Summary of strengths vs gaps

**What Codex did well:**

1. Centralized tombstone-check helper (`requirement_project_is_active`) and threaded it through ~20 endpoints + background tasks. Defense-in-depth, hard to bypass.
2. Real CSP on Tauri webview, narrowed capability surface (no devtools / shell / process from JS).
3. Path-traversal hardening in Rust sync layer with proper canonicalization, symlink rejection, and same-origin URL guard for credential-bearing requests.
4. Token / credential leakage prevention in `clientFetch` (origin check) and `shared/client.ts` (runtime guard).
5. Atomic write pattern (`tmp.download` → sha256 verify → rename) for downloads.
6. Knowledge corpus now garbage-collects rows for tombstoned sources (prevents stale leakage).
7. Job-detail endpoint scoped to creator/admin.

**What needs follow-up:**

1. **M1** (asymmetric `_require_manage_item` on paste/copy) — easy fix.
2. **M2** (nickname enumeration via 409) — acceptable on LAN, document the threat-model decision.
3. **L1** (wide `connect-src`) — structural, accept and document.
4. **L2** (per-source tombstone-author filter only on chats) — confirm intended invariant.

Overall: **ship it after addressing M1.**
