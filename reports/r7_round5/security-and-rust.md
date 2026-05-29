# R7 Round 5 — Security + Rust

Scope: HEAD `8d30bc7` on `fix/r6-hardening`. Combined Security + Rust audit.
Round 1 of the fresh "4 consecutive CLEAN/GREEN" streak. Verified the R7.4
recycled-nickname ownership fix (a–d), re-checked M8 after R7.4 touched
project_drive.py, reviewed the named Rust helpers, then swept the whole
codebase fresh. Threat model unchanged: LAN-deployed FastAPI + Tauri 2.x
client, nickname+cookie auth, admin the only RBAC role.

Read-only. No code written or edited.

## Verdict: YELLOW (1)

**1 NEW finding — N1 (LOW): a localhost session cookie was committed to git
history in commit `c9d5e89` (`visual_tmp/cookies.txt`).** The file is removed
from HEAD's tree and now gitignored, but the cookie value persists in that
commit. It is a `127.0.0.1` (local test instance) session, not the production
LAN server, and forging a *new* cookie needs the server's `cookie_secret` —
but the leaked value itself is a usable bearer credential for whatever instance
issued it until that user's `cookie_token` is rotated. LOW severity, not a
release blocker, but it should be scrubbed and the test user re-identified.

Everything substantive is GREEN: the R7.4 ownership fix correctly closes the
P2-A takeover vector without locking out legitimate owners (a–d all pass), M8
is byte-for-byte intact and still closed, and the named Rust helpers are safe.
No P1/MEDIUM+ code finding. Accepted residuals (H1, M6, L5–L8) unchanged and
none got worse.

---

## R7.4 ownership-fix verification (a–d)

Fix sites (diff confirmed, commit `c9d5e89`):
- `projects.py:104` `_require_owner` → `if p.owner_user_id is None or p.owner_user_id != user.id: 403`
- `projects.py:48` `list_projects` archived/deleted/all filter → `q.filter(Project.owner_user_id == user.id)`
- `project_drive.py:100` `_can_manage_project` → `return project.owner_user_id is not None and project.owner_user_id == user.id`

All three dropped the old `owner_nickname == user.nickname` fallback-on-NULL.

**(a) Is the takeover vector closed? YES.**
`delete_user` (`users.py:123-133`) soft-deletes (`deleted_at` set) AND tombstones
the nickname to `_deleted_<id8>_<orig>` (line 127-128). The boot backfill
(`schema_migrations.py:80-90`) only matches `u.nickname = projects.owner_nickname
AND u.deleted_at IS NULL` — a tombstoned/deleted owner can never re-match, so the
orphaned project's `owner_user_id` stays NULL forever. With the fallback gone, a
NULL `owner_user_id` now yields 403 for every non-admin (manage) and is filtered
out of `list_projects` (visibility). A re-registered "Alice" gets a fresh
`user.id` (`auth.py:241` `User(nickname=…, cookie_token=…)`), which never equals
the old project's stored NULL → she cannot manage or even see the tombstoned
owner's archived/deleted project. Vector closed on both the manage and the
enumerate paths.

**(b) Does it lock out a LEGITIMATE owner? NO.**
- New projects: `create_project` (`projects.py:61-65`) always sets
  `owner_user_id=user.id`. Never NULL for a normally-created project.
- Legacy/pre-column projects: the backfill UPDATE runs **unconditionally on
  every boot** (it sits at `schema_migrations.py:80`, *outside* the
  `if name not in project_existing` column-add loop at lines 72-74), and the
  `WHERE owner_user_id IS NULL` clause makes it idempotent. So on every startup,
  any project whose owner is still an active user (live nickname) gets
  `owner_user_id` populated. A normal, still-active owner therefore always has a
  non-NULL `owner_user_id` matching `user.id` → passes `_require_owner`,
  `_can_manage_project`, and the `list_projects` filter. The ONLY rows left NULL
  are genuinely orphaned (owner deleted), which is exactly the intended
  admin-only state. No false lockout. (Enumeration of `Project(` constructions
  confirms `create_project` is the sole non-test creation site and it sets the id.)

**(c) Other endpoints still doing raw `owner_nickname == user.nickname` authz? NONE.**
Repo-wide grep for `owner_nickname` / `== user.nickname` / nickname authz:
- `projects.py:21,63`, `schemas.py:23` — **display/construction only**
  (`_to_out`, `create_project` writes the column, `ProjectOut` field). Not authz.
- `knowledge.py:100` — `owner_nickname` interpolated into the indexed doc body
  (display string). M6 accepted residual; not authz.
- `schema_migrations.py:84` — the backfill SELECT, correctly gated on
  `u.deleted_at IS NULL`. Not an authz decision at request time.
- `auth.py:237` — `/identify` nickname lookup, filtered `deleted_at IS NULL`.
  This is the H1 accepted residual, unchanged.
No remaining request-time authz branch compares a raw `owner_nickname` to the
caller's nickname. The three fixed sites were the complete set.

**(d) Same shape for `submitter_nickname` / assignee nickname authz? NONE.**
`submitter_nickname` appears only in **display output** (`schemas.py:260`,
`requirements.py:56/106/217`, `sync_manifest.py:64`) — never in an authz compare.
All requirement/assignee/submitter access control is ID-based: `permissions.py`
(`is_submitter` → `req.submitter_user_id == user.id`, `is_assignee` via
`assignments.py` `a.user_id == user.id` / `claimed_by_user_id`), and the router
guards (`auto.py:72`, `chat.py:113/227`, `decompositions.py:87/166/214`,
`calendar.py:159/190` `created_by_user_id != user.id`). No nickname-based authz
anywhere in the requirement/assignment surface.

---

## M8 still-closed check

R7.4 touched `project_drive.py` only at lines 90-100 (`_can_manage_project`) —
far from the download endpoint. `download_drive_file` + `_INLINE_SAFE_MIME_PREFIXES`
(`project_drive.py:836-877`) are byte-for-byte identical to the R7.3 fix verified
GREEN in Round 4:
- `_INLINE_SAFE_MIME_PREFIXES` (jpeg/png/gif/webp/bmp/x-icon/vnd.microsoft.icon,
  `audio/`, `video/`, `application/pdf`, `text/plain`) — unchanged.
- `safe_mime` collapses any non-allowlisted mime to `application/octet-stream`
  for `inline=1`, and ALL mimes to octet-stream for download — unchanged.
- `content_disposition_type=disposition` (always sends `filename=item.name` so
  Starlette emits Content-Disposition) — unchanged.
- `headers={"X-Content-Type-Options": "nosniff"}` — unchanged.
SVG/HTML therefore still render as octet-stream + nosniff + Disposition → no
in-origin script execution. M8 remains closed. Sibling byte-serving endpoints
(attachments, deliveries ×2, voice, main ×2, bulk-zip, SSE) were unchanged this
round; their Round-4 disposition-safe verdicts stand.

---

## Rust verification

**Re the prompt's premise:** the git history does NOT show any R7.4 Rust change
to `config.rs` / `commands/config.rs`. Commit `c9d5e89` (R7.4) modified zero Rust
files; HEAD `8d30bc7` is a `.gitignore`-only chore. The named functions
(`normalize_drive_mode`, `clear_dedup_state`, the `identity_changed` wiring) were
last touched in the R7 base commit `306edbd`, not in R7.4. Across the entire
R7.1→HEAD span the ONLY Rust source diff is `shell.rs` (R7.2 helper + R7.3
dead-line removal). I reviewed the named functions anyway, as asked:

- **`clear_dedup_state` on identity change** (`config.rs:135-140`, wired in
  `commands/config.rs:19-47`): sets the four `known_*` JSON objects (reqs /
  revision_requests / reminders / notifications) to `{}`. These are purely
  client-side toast-dedup caches — no secrets, no tokens, no path data, no authz
  bearing. Clearing them when nickname/server_ip/server_url/client_token change
  is the *secure* direction (prevents one identity's dedup rows suppressing
  another identity's first-time notifications, and stops stale notification IDs
  from a prior server install carrying over). Detection compares the incoming
  patch value against current config BEFORE applying — correct ordering. Worst
  case of over-clearing is a duplicate cosmetic toast. **No security downside.**
- **`normalize_drive_mode` coercion** (`config.rs:125-129`): any
  `drive_sync_mode` not exactly `"off"` or `"download"` is forced to
  `"download"`. This is a fail-safe allowlist — an unknown/stale string (e.g. the
  removed `"two_way"`) can never escalate to a more privileged sync direction;
  it collapses to the read-only download mode. Fixed string compare, no
  injection/traversal surface. **Safe.**

**`shell.rs` (`open_folder`)** — the one real Rust change. Re-read fully
(`shell.rs:24-119`): metachar/control/NUL rejection (lines 31-36), `..`
ParentDir rejection (line 41), canonical-root containment via
`canon_target.starts_with(canon_root)` over the user's configured roots
(sync_root / drive_sync_root / config_dir), single-argv `Command::arg` spawn.
`canonicalize_with_existing_ancestor` walks to the nearest existing ancestor,
canonicalizes it, re-appends the non-existent tail — preserving the `\\?\` prefix
so `starts_with` matches; fail-closed (empty roots → not allowed → error).
Unchanged since R7.3; R3's exhaustive edge-case audit stands.

**Tauri capabilities + `tauri.conf.json`:** `git diff 9b735b5..HEAD` is empty —
unchanged since R7.1. Minimal `fs` (appdata-recursive + read/write-text/mkdir/
read-dir/exists), no `shell:allow-open`, no `process:*`, no devtools/eval.
**deep_link.rs:** host whitelist + traversal-segment filter, intact (no diff).

**Rust verdict: GREEN — 0 P0/P1.** Both named helpers safe; the only actual
source change (`shell.rs`) is correct and unchanged this round.

---

## New findings

### N1 (LOW) — session cookie committed to git history
- **Where:** `visual_tmp/cookies.txt`, added in commit `c9d5e89` (R7.4).
- **What:** a libcurl cookie jar containing one live `yqgl_id` cookie:
  `IkIzUjMyak…XfYBwuXZPb813UBslNdWOIscxGs`, scoped to `127.0.0.1`, browser-side
  expiry 2027-05-29 (max-age 1 year per `auth.py:51`). HttpOnly. The cookie is
  the `itsdangerous` `URLSafeSerializer`-signed wrapper of a user's
  `cookie_token` (`auth.py:24,47`).
- **Exploitability / why LOW:**
  - It is a `127.0.0.1` local-test session, not the production LAN server
    (`192.168.0.224`). Blast radius is whatever instance generated it.
  - It is NOT signed with either default secret (`dev-change-me` /
    `change-me-to-a-long-random-string`) — verified via itsdangerous; so the
    *secret* did not leak and an attacker cannot mint NEW cookies for arbitrary
    users from this file.
  - But the leaked value is itself a usable bearer credential for the issuing
    instance until that user's `cookie_token` is rotated (re-identify / logout /
    `delete_user` all rotate it — `auth.py:248-250`, `users.py:129`).
  - The file is already removed from HEAD's working tree and `visual_tmp/` is
    gitignored (HEAD chore `8d30bc7`), so it won't recur — but the value lives on
    in the `c9d5e89` commit object.
- **Recommendation (not a code change for this branch):** rotate the test user's
  `cookie_token` (any re-identify does it), and scrub `visual_tmp/cookies.txt`
  from history before this branch is pushed/merged to a shared remote (e.g.
  `git filter-repo` / interactive rebase to drop the blob from `c9d5e89`). No
  product-code change required. Not a release blocker for the LAN deploy.

**No P1/MEDIUM+ code finding.** All R7.4 source changes are security-neutral:
- `notifications.py:46-66`: content-change guard before resurfacing a deduped
  notification. No authz/output change; `title[:256]` truncation only.
- `calendar.py:85`: `selectinload(ScheduleEvent.created_by)` (N+1 perf). The
  existing relationship-based visibility filter (`calendar.py:81,101-102,121`)
  is unchanged. Security-neutral.
- `tauri.ts` clientFetch: caches the parsed base `URL` object; the
  security-critical `target.origin === base.origin` gate on attaching the client
  token is preserved verbatim, cache invalidated wholesale on settings change so
  `baseObj` can't diverge from `baseUrl`. No worker-token cross-origin leak.
- FileAttachRail / Hub / Inbox / Knowledge / Calendar TS: alive-guard /
  monotonic-token race fixes. No new DOM sinks (repo-wide grep clean).
- `RequirementDetail.tsx`: imports the shared `parseServerDate` (identical incl.
  NaN guard). Output flows to React-escaped text nodes.

---

## Coverage

| Area | Files / endpoints | Outcome |
|---|---|---|
| R7.4 ownership fix (a) takeover | `projects.py:48,104`, `project_drive.py:100` vs `users.py:123-133` + backfill | **Closed** — NULL owner = admin-only, recycled nickname blocked |
| R7.4 ownership fix (b) lockout | backfill `schema_migrations.py:80-90` (runs every boot) + `create_project:61-65` | **No lockout** — active owners always non-NULL |
| R7.4 ownership fix (c) other nickname authz | repo-wide `owner_nickname` / `== user.nickname` grep | **None** — only display/H1; 3 fixed sites were complete |
| R7.4 ownership fix (d) submitter/assignee authz | `permissions.py`, `assignments.py`, router guards | **All ID-based**; `submitter_nickname` display-only |
| M8 drive inline XSS | `project_drive.py:836-877` | **Still closed** — byte-identical to R7.3; allowlist+octet+nosniff intact |
| M8 sibling byte-serving endpoints | attachments, deliveries×2, voice, main×2, bulk-zip, SSE | Unchanged; Round-4 disposition-safe verdicts stand |
| Rust `clear_dedup_state` (identity change) | `config.rs:135-140`, `commands/config.rs:19-47` | **Safe** — client-side toast caches only, no secrets/authz |
| Rust `normalize_drive_mode` | `config.rs:125-129` | **Safe** — fail-safe allowlist, no escalation/injection |
| Rust `shell.rs` open_folder | `shell.rs:24-119` | PASS — metachar/`..`/canonical-root containment, single-argv, fail-closed |
| Tauri capabilities + conf + deep_link | `capabilities/default.json`, `tauri.conf.json`, `deep_link.rs` | **Unchanged since R7.1** (empty diff) |
| XSS DOM sinks (frontend) | repo-wide `dangerouslySetInnerHTML`/`innerHTML`/`outerHTML`/`document.write`/`insertAdjacentHTML`/`eval`/`new Function` | **Zero matches** in any ts/tsx/js/jsx/vue/svelte |
| SSE cross-user leak | push.py / chat.py (unchanged this round) | Round-4 verdict stands (stream_one gated, stream_me cookie-derived) |
| Dependency manifests | package.json / Cargo.toml / Cargo.lock / pyproject.toml / lockfiles | **No change since R7.1** — nothing new to audit |
| Committed secrets | git history scan for cookie/token/env files | **N1 LOW** — `visual_tmp/cookies.txt` in `c9d5e89` (localhost test cookie) |
| Source delta since R7.3 GREEN | 11 files (4 py + 7 ts) | All reviewed — security-neutral except N1 (a committed artifact, not code) |

---

## Accepted residuals (unchanged, none worse)

| ID | Title | Status |
|---|---|---|
| H1 | `/identify` LAN nickname trust (`auth.py:237`) | Unchanged. LAN-trust model. |
| M6 | Knowledge cross-project leak (incl. `owner_nickname` in index body) | Unchanged. |
| L5 | Windows reserved names in `safe_component` | Unchanged. Local-DoS only. |
| L6 | `list_users?include_deleted=true` open to all | Unchanged (display_name masks tombstone). |
| L7 | `cookie_secure=False` default | Unchanged. Deploy-checklist; prod guard at `main.py:166`. |
| L8 | Install scripts over plain HTTP | Unchanged. |

---

## Round-5 outcome

YELLOW (1): one LOW finding (N1) — a localhost test-session cookie left in the
`c9d5e89` commit history. It's already removed from the tree and gitignored, the
signing secret did not leak, and it targets `127.0.0.1` not production; scrub the
blob + rotate the test user before pushing to a shared remote. No code change
needed on this branch.

On the substance the round is clean: the R7.4 recycled-nickname ownership fix is
correct and complete (a–d all verified — takeover closed, no legitimate lockout,
no other nickname-authz site, submitter/assignee authz fully ID-based); M8 is
still closed byte-for-byte; both named Rust helpers are safe; the only real Rust
change (`shell.rs`) and all Tauri config are unchanged and correct; zero XSS
sinks, zero dependency changes, zero new P1/MEDIUM+ code findings.
