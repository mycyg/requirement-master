# R7 Round 2 — Security

Scope: HEAD `9b735b5` on `fix/r6-hardening` (R7.1 hardening commit). Re-audited
the four R7.1 fixes (H2, M3, M4, M5), re-checked the unfixed H1/M6 against
their stated trade-off, then swept the codebase for new issues across the
permission, soft-delete, path-traversal, SSRF, XSS, ZipSlip, and dependency
axes. Threat model is unchanged from Round 1 (LAN deployment, nickname
identity, no per-project ACL).

## Verdict

**YELLOW — 1 new MEDIUM, 2 new LOW. All four R7.1 fixes verified.**

R7.1 closes the four MEDIUM findings cleanly. One new MEDIUM (M7) is a
direct regression of the M5 fix scope: `Project.owner_user_id` is now used
by `_require_owner` in `projects.py`, but `project_drive.py`'s sibling
authoriser (`_can_manage_project`) was not updated and still matches on
`owner_nickname`. The fix is one line. The remainder are nits.

---

## R7.1 fix verification (H2, M3, M4, M5)

### H2 — `open_folder` Tauri command — **PASS** (with two minor caveats)

`client-tauri/src-tauri/src/commands/shell.rs:24-88`. Validator now:
- Rejects empty paths (line 26-28).
- Rejects shell metacharacters (`|;&<>"$\``), control chars, NUL, ESC (line 31-36).
- Rejects any path containing `..` segments (line 41-43).
- Requires canonical target to be under canonical `sync_root` / `drive_sync_root`
  / `config_dir()` (line 45-65).
- Spawns with `Command::arg(arg)` so even if a metachar slipped through, the OS
  file opener doesn't re-parse (line 73-85).

Edge-case walk-through:

1. **Empty roots**: `cfg.sync_root.trim().is_empty()` skips that root (line 47, 50);
   if both are empty AND `config_dir()` errors, `roots` is empty and `roots.iter().any(...)`
   returns false → reject. Safe.
2. **Non-existent target**: `target.canonicalize().unwrap_or_else(|_| target.clone())`
   (line 60) falls back to the raw user-supplied path. Compared via
   `starts_with` against the canonical root. **Edge case**: if a malicious
   symlink at `<sync_root>/link` points outside, and the user passes
   `<sync_root>/link/notyetexisting`, the raw target wins and starts_with
   succeeds against canonical root. The actual `explorer.exe` invocation
   would then follow the symlink. Reaching this requires (a) write
   access to sync_root to plant the symlink (drive sync only writes
   parsed files; Rust client doesn't create symlinks via Tauri commands)
   and (b) JS-side execution to call `open_folder` with the crafted
   path. Both are non-trivial; the LAN-trust model already grants write
   access to admins. Not worth fixing unless XSS surface widens. **L9 below.**
3. **Symlinks pointing into sensitive locations**: existing-file path
   case canonicalises through the symlink, so the comparison sees the
   real target and correctly rejects. Safe.
4. **Windows case sensitivity**: `Path::starts_with` is case-sensitive in
   Rust but Windows FS isn't. Canonicalisation normalises both root and
   target to `\\?\C:\...`, so existing-file case is fine. Non-existent
   targets where the user typed a different drive-letter case will be
   rejected (UX papercut, security-safe).
5. **Drive-letter root mis-config**: `sync_root = "C:"` (no slash)
   canonicalisation may fail; fallback compares "C:" against `C:\Windows...`
   which `starts_with` considers a prefix at component level. So if an
   admin mis-configures `sync_root` to just a drive letter, anything on
   that drive becomes openable. Doc-only concern; the default
   `D:\工作需求` is correct.
6. **macOS / Linux launchers**: Validator does not reject `.app` (macOS),
   `.desktop` (Linux), `.lnk` (Windows). `xdg-open foo.desktop` on Linux
   DOES execute the `Exec=` key — but only if foo.desktop already lives
   inside sync_root. Drive sync would have to deliver such a file (admin
   only). Not actionable without LAN-trust violation.

**Verdict on H2**: the fix correctly closes the original RCE vector
(`open_folder("cmd.exe /c …")` is now rejected at three layers). The
residual symlink/extension nuances above are documented as L9 (low) and
do not warrant a Round-3 block.

### M3 — `list_projects` soft-deleted leak — **PASS**

`app/routers/projects.py:37-57`. Non-admins are filtered to `owner_nickname == user.nickname`
when querying `state in {archived, deleted, all}` (line 54-55). Verified:
- `state=active` is unrestricted (the open dispatch board needs this).
- `state=archived` / `deleted` / `all` → admin sees everything;
  non-admin sees only their own.

Slight nuance: the filter uses `owner_nickname`, NOT `owner_user_id`. A
recycled nickname WILL see archived/deleted projects from the previous
owner. This is purely a "what you can list" leak; the M5 fix on
`_require_owner` (uses `owner_user_id`) correctly blocks them from
actually mutating those projects. Net result: a recycled nickname can
read the metadata of a tombstoned-user's archived projects, but can't
restore/archive/delete them. Acceptable.

### M4 — SSE per-requirement permission gate — **PASS**

`app/routers/push.py:63-92`. New code:
- Rehydrates the `User` from `StreamUser.id` (line 79-80).
- Loads the requirement (line 81); 404 if missing.
- Calls `can_view_requirement_record(req, user)` (line 84); 403 if denied.
- Closes the DB session BEFORE returning the StreamingResponse so the
  long-lived generator doesn't hold a connection (line 86-87).

Correctness against the threat model: `can_view_requirement_record`
short-circuits to True for admins, otherwise requires
`requirement_project_is_active` AND (is_submitter OR is_assignee OR
status NOT in PRIVATE_REQUIREMENT_STATUSES). This is exactly what
`comments.list_comments` uses for the REST endpoint, so the SSE
channel and the REST endpoint now have consistent visibility.

Verified `stream_me` / `stream_all` are unchanged and correct:
- `stream_me` scopes to `f"user:{user.id}"` — can't request another user's
  topic (the cookie-derived id is in the topic name).
- `stream_all` is the global tray feed (`requirement.ready` /
  `requirement.updated`); those events were already designed for global
  fan-out so no per-req gate applies.

### M5 — recycled-nickname project ownership — **PASS** (within `projects.py`)

`app/models.py:71-90`: `Project.owner_user_id: Mapped[Optional[str]]` added.
`app/services/schema_migrations.py:34-91`: new column added in
`PROJECT_COLUMNS`; backfill query joins on `users.nickname` AND
`deleted_at IS NULL`, ordered by `created_at ASC` to deterministically
pick the original owner when a nickname has been re-registered after a
deceased account; new index `ix_projects_owner_user_id`.
`app/routers/projects.py:71-72` writes `owner_user_id=user.id` on
create; `_require_owner` (line 97-113) prefers the column when present
and rejects on mismatch, falling back to nickname only for un-backfilled
legacy rows.

**Caveat for the backfill**: if a project was created by `alice`,
`alice` was hard-deleted (impossible per current code; soft-delete only)
and a new `alice` registered before the migration ran, the backfill
would assign `owner_user_id` to the new user. Since this requires a
hard delete that the code does NOT do, the only realistic path is
"old alice was soft-deleted (nickname tombstoned to `_deleted_<id>_alice`)
+ new alice registered + migration runs". In that case the JOIN
`u.nickname = projects.owner_nickname` matches BOTH the tombstoned old
alice AND the new alice; the `deleted_at IS NULL` filter eliminates
the tombstoned one; ORDER BY created_at picks the oldest live one,
which is new alice. Net result: ownership transfers to new alice. This
matches the original M5 vulnerability. **However**, this is only a
risk at migration time on existing databases — going forward,
`owner_user_id` is set on create, so no further drift. The backfill is
a one-shot; admins reviewing the upgrade should re-audit any pre-existing
soft-deleted users whose nicknames now resolve. Worth a release note
but not a blocker.

---

## R7 unfixed status (H1, M6)

### H1 — `/api/auth/identify` nickname takeover — **accepted residual risk**

`app/auth.py:227-244`, `app/routers/auth.py:41-60`. Behaviour unchanged
from Round 1. User has documented acceptance: LAN trust model means
anyone reaching the server port has full impersonation of every account,
and the existing onboarding UX requires nickname-only login to keep
device-switching painless. No code change requested.

Deploy guidance from Round 1 still applies:
- Do not expose this server to VPN / multi-tenant Wi-Fi without first
  hardening identify (admin approval gate, per-user shared secret, or SSO).
- Cookie secret is enforced strong in production (main.py:163), but the
  server happily mints valid cookies on demand, so secret strength is
  a defense in depth, not a primary control.

### M6 — knowledge corpus cross-project leak — **accepted within LAN model**

`app/services/knowledge.py:67-80`. Behaviour unchanged. Per-project ACL
absence means drive files, meetings, and project descriptions ARE
intentionally cross-visible. Documented in Round 1 as consistent with
"open dispatch board" model; not actionable in Round 2 without changing
the data-visibility contract.

---

## New findings

### M7 — `project_drive` ownership still keyed on nickname (M5 fix incomplete)

`app/routers/project_drive.py:91-99`

```python
def _can_manage_project(project: Project, user: User) -> bool:
    return is_admin(user) or project.owner_nickname == user.nickname
```

The R7.1 commit added `Project.owner_user_id` and updated
`projects.py:_require_owner` to use it, but the SIBLING authoriser in
`project_drive.py` was NOT updated. `_can_manage_project` is called from
`_require_manage_item` (line 95-99), which gates every drive mutation
(rename / move / delete / paste / copy). Consequence:

- Alice creates project "foo", uploads `secret.pdf` to its drive.
- Admin soft-deletes Alice; her nickname is tombstoned to
  `_deleted_<id>_alice`, freeing "alice" for re-registration.
- Bob registers nickname "alice". `_require_owner` (project mutation)
  correctly REJECTS Bob (uses `owner_user_id`).
- But `_can_manage_project` (drive item mutation) ACCEPTS Bob —
  `project.owner_nickname` is still "alice" and Bob's
  `user.nickname == "alice"`. Bob can now rename, delete, move, copy
  any drive item in foo, including downloading `secret.pdf` via paste
  to a folder he creates elsewhere.

Severity: MEDIUM. Same shape as the original M5 finding, just in the
adjacent module. Drive items can carry sensitive parsed-text content
that's much more leaky than project metadata.

**Recommendation**: change `_can_manage_project` to mirror
`_require_owner`'s logic — prefer `owner_user_id`, fall back to
nickname only when the column is unset (legacy rows). Two lines.

### L9 — `open_folder` non-canonical fallback when target doesn't exist

`client-tauri/src-tauri/src/commands/shell.rs:60`. `canonicalize` falls
back to the RAW path when the target doesn't yet exist. If an attacker
plants a symlink anywhere inside sync_root that points outside, and
calls `open_folder("<sync_root>/<link>/<nonexistent>")`, the comparison
operates on the un-canonicalised target and is bypassed; `explorer.exe`
then follows the symlink at OS level.

Exploit chain requires (1) write access to sync_root to plant a symlink
(drive sync doesn't write symlinks; admin would have to via OS tools
outside this app), and (2) JS-side `invoke('open_folder', …)`. Both are
non-trivial absent prior compromise.

**Recommendation**: refuse non-existent targets (return error) OR walk
each component of `target` and verify none is a symlink that escapes
the root. Low priority.

### L10 — `planning.py` exposes raw tombstoned nicknames

`app/routers/planning.py:106`. `nickname=user.nickname` instead of
`user.display_name`. A user soft-deleted by admin still appears in
workload reports with the raw `_deleted_<id8>_originalname` tombstone
string, which leaks the prefix format and the deleted user's id-prefix.

`requirements.py`, `users.py`, `meetings.py` correctly use `display_name`
masking. This is the only laggard.

**Recommendation**: change to `user.display_name`. One line.

---

## Coverage

| Area | Files / endpoints reviewed | Outcome |
|------|----------------------------|---------|
| H2 validator | `client-tauri/src-tauri/src/commands/shell.rs` | PASS with L9 noted |
| M3 list_projects gate | `app/routers/projects.py` | PASS |
| M4 SSE gate | `app/routers/push.py` | PASS |
| M5 ownership identity | `app/models.py`, `app/services/schema_migrations.py`, `app/routers/projects.py` | PASS within projects.py; **M7 in project_drive.py** |
| Project-drive mutation auth | `project_drive.py` `_can_manage_project`, `_require_manage_item`, paste / copy / cut / patch / delete | **M7** |
| Soft-delete leaks | `users.py`, `notifications.py`, `requirements.py`, `planning.py`, `attachments.py` | L10 tombstone leak in planning.py only |
| Path traversal / ZipSlip | `app/services/delivery_doc.py` `_safe_zip_name` + `_safe_extract_entries`, `app/routers/attachments.py` `_safe_filename`, `project_drive.py` `_safe_filename`, `client-tauri/src-tauri/src/sync.rs` `safe_component` / `safe_relative_path` | Clean (L5 from Round 1 — Windows reserved names — still unresolved, accepted) |
| Permission gaps per endpoint | `requirements.py` (status / planning / schedule / assignees), `sync.py` (submit / sync-manifest / sync-ack / claim), `delivery_upload.py` (init / chunk / finalize), `chat.py` (list_messages), `comments.py` (list / create / activity), `decompositions.py` (create / confirm / dismiss), `meetings.py` (init / chunk / finalize / patch / confirm / dismiss insight), `jobs.py` (_can_view_job), `notifications.py`, `knowledge.py` (search / ask / runs / reindex), `voice.py` (transcribe / tts / voices / asr-health), `workspaces.py` | Clean — admin override correctly bypasses relationship checks only on READ; writes respect project-active filter; CAS on every state transition |
| Chunked upload owner pinning | `attachments.py`, `meetings.py`, `delivery_upload.py`, `project_drive.py` | All `meta['user_id'] != user.id` checks present; chunk-index bounds-checked before path interpolation |
| SSE topic scoping | `push.py` `/stream`, `/stream/req/{id}`, `/stream/me` | All three scoped correctly post-M4 |
| Auth surfaces | `auth.py` `current_user` / `optional_current_user` / `require_local_client` / `optional_local_client` / `require_stream_user`, `client_devices.py` register / revoke | Cookie verification, worker-token hashing, soft-delete suppression all correct |
| CORS / CSP | `app/main.py:160-166`, `app/main.py:205-211`, `client-tauri/src-tauri/capabilities/default.json`, `client-tauri/src-tauri/tauri.conf.json` | Production CORS / cookie_secret enforced; capability set minimal; fs scope = appdata-recursive only |
| Tauri commands | `auth.rs`, `config.rs`, `delivery.rs`, `requirements.rs`, `shell.rs`, `submitter.rs`, `sync.rs`, `workspace.rs`, `deep_link.rs` | shell.rs hardened (this round); deep_link.rs host-whitelist + path-strip correct; others are HTTP proxies that re-use the server's auth |
| XSS surfaces | React JSX renders strings; no `dangerouslySetInnerHTML` / `innerHTML` / `outerHTML` / `insertAdjacentHTML` anywhere in `web/src` or `client-tauri/web-src`; no markdown library (markdown rendered as `<pre>`); CSP `script-src 'self'` blocks inline JS | Clean |
| SSRF | `voice.py` (ASR/TTS upstream), `meetings.py` `_transcribe_or_decode`, `services/delivery_doc.py` Anthropic upstream | All call `settings.*_base_url` (server-config only); no user-controlled URLs reach `httpx` / `AsyncAnthropic` |
| Dependencies | `app/pyproject.toml` (fastapi 0.115+, sqlalchemy 2.0+, pydantic 2.9+, anthropic 0.39+, markitdown, pillow 11+), `client/requirements.txt` (httpx, pystray, pillow 10+, plyer, pywebview 5+), `web/package.json` (react 18.3.1, react-router 6.27, vite 5.4.10, tailwind 3.4.14), `client-tauri/Cargo.lock` (tauri 2, reqwest 0.12/0.13, tokio 1.52.3, openssl 0.10.80, zip 2.4.2, url 2.5.8, idna 1.1.0) | All pinned versions are recent (Nov 2024+) and beyond known CVE windows. zip 2.4.2 contains the post-CVE-2024-23613 path-traversal fix; vite 5.4.10 contains the CVE-2024-31207 fix; pillow 11.x post-CVE-2024-28219; pywebview 5+ post-CVE-2024-44081 |

---

## Round-3 verification checklist

To close one CLEAN round:
- Fix M7: `project_drive.py:_can_manage_project` use `owner_user_id`.
- (Optional) Fix L10: `planning.py:106` use `display_name`.
- (Optional) Fix L9: `shell.rs` reject non-existent targets, or walk components for symlinks.
- H1 + M6 + L5–L8 from Round 1 remain accepted residual risk per LAN model.
