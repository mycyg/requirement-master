# R7 Round 6 — Security + Rust

Scope: HEAD `f70f3e6` (R7.5) on `fix/r6-hardening`. Combined Security + Rust
audit. Round 2 of the fresh "consecutive GREEN" streak. Verified the R7.5
`git filter-branch` cookie scrub (N1, the only R7-R5 LOW), re-checked that the
recycled-nickname ownership-inheritance family is now fully closed across BOTH
the runtime path (R7.4) and the boot backfill (R7.5), then swept the whole
codebase fresh. Threat model unchanged: LAN-deployed FastAPI + Tauri 2.x client,
nickname+cookie auth, admin the only RBAC role.

Read-only. No code written or edited.

## Verdict: GREEN

**Zero MEDIUM+ findings. Zero new LOW findings. N1 (the only R7-R5 LOW) is
RESOLVED.** The recycled-nickname ownership-inheritance family is now fully
closed on every path (runtime + backfill). All accepted residuals (H1, M6,
L5–L8) unchanged and none worse. This is a clean GREEN.

---

## N1 cookie-scrub verification — RESOLVED

R7.5 ran `git filter-branch` to scrub `visual_tmp/` from all history, dropped
`refs/original`, expired the reflog, and `gc --prune=now`'d. Verified:

| Check | Command | Result |
|---|---|---|
| Blob gone from ALL reachable history | `git rev-list --all --objects \| grep -i visual_tmp` | **empty (EXIT 1)** — gone |
| No `cookie`-named blob anywhere | `git rev-list --all --objects \| grep -i cookie` | **empty (EXIT 1)** |
| `refs/original` removed | `ls .git/refs/original` | **absent (EXIT 2)** |
| Reflog expired | `git reflog \| wc -l` | **0 entries** |
| Dir now gitignored | `.gitignore:53` | `visual_tmp/` present |
| No `cookies.txt` / loose `.txt` added in history | `git log --all --name-only --diff-filter=A` | only `*/requirements.txt` (pip manifests) |

The leaked `visual_tmp/cookies.txt` blob is no longer reachable from any branch,
tag, or the reflog. The signing secret never leaked (R7-R5 confirmed it was not
signed with either default secret), so no NEW cookies could ever have been
minted from it; and now the leaked value itself is unrecoverable from this
repo's history.

**Residual (non-issue):** the file still exists in the LOCAL working tree as an
untracked scratch artifact (`visual_tmp/cookies.txt`, a single `127.0.0.1`
localhost session). `git ls-files visual_tmp/` → empty (untracked);
`git check-ignore -v` → matched by `.gitignore:53`; `git status --porcelain
visual_tmp/` → empty. It is ignored and can never re-enter the repo. This is a
local-disk artifact only, outside git's reach — not a finding. (Optional hygiene:
rotate that test user's `cookie_token` via any re-identify, and `rm -rf
visual_tmp/` locally; neither is a code or release action.)

**N1 is RESOLVED.** The scrub is complete and verified.

## Secret scan (whole tree + reachable history)

| Scan | Result |
|---|---|
| `sk-` API-key pattern, tracked tree | Only `app/.env.example:10` = `sk-replace-me-with-your-deepseek-key` (the placeholder). One false positive: a screenshot filename token in `web/tests/e2e/client-spaces.spec.ts:162`. |
| `sk-[a-zA-Z0-9]{16,}` across ALL reachable history blobs | **none** (only `replace-me` placeholder) |
| Generic `password\|secret\|token\|api_key\|private_key`, tracked | All hits are env-var-driven config (`config.py`), hashing (`auth.py` `sha256`/`token_urlsafe`), header/column names, or doc references. No hardcoded credential VALUE. |
| `BEGIN … PRIVATE KEY` blobs | **none** in tree |
| Tracked `.env` files | Only `app/.env.example` (template). No real `.env`. |
| Deploy host `192.168.0.224` / real DeepSeek key | **not leaked**. Only the public endpoint `https://api.deepseek.com/anthropic` (a URL, not a secret) appears, in config/docs/test scripts. |

Defense confirmed at `app/main.py:163-169` (`_validate_runtime_config`): in
`production`, startup hard-fails if `cookie_secret` is still a default
(`""`/`dev-change-me`/`change-me-to-a-long-random-string`) or if CORS contains
`*`. `cookie_secret` defaults to `dev-change-me` and `llm_api_key` to `""`
(env-driven). Token handling is `secrets.token_urlsafe` + sha256-at-rest
(`auth.py:33-42`). **Only the documented placeholder exists. Clean.**

## Ownership-inheritance family — fully closed?

**YES — closed on every path.** The recycled-nickname takeover family is now
sealed at three layers; all four sub-paths verified:

1. **Runtime authz (R7.4, intact):** `_require_owner` (`projects.py:104`) and
   `_can_manage_project` (`project_drive.py:100`) use `owner_user_id == user.id`
   ONLY. A NULL `owner_user_id` (orphaned project, owner deleted) → 403 for every
   non-admin, and is filtered out of `list_projects` archived/deleted/all
   (`projects.py:48`). No raw `owner_nickname == user.nickname` fallback remains
   anywhere (repo-wide grep: `owner_nickname` appears only as display/construction
   in `projects.py:21,63`, `schemas.py:23`, and the M6-residual index body in
   `knowledge.py:100`).

2. **delete_user tombstone (`users.py:123-132`):** soft-deletes (`deleted_at`),
   drops admin, rotates `cookie_token`, revokes all `ClientDevice` rows, AND
   rewrites the nickname to `_deleted_<id8>_<orig>`. So the project's stored
   `owner_nickname` no longer matches any LIVE user. A re-registered "Alice"
   (`auth.py:241`) gets a brand-new `user.id`.

3. **Boot backfill (R7.5, the new guard):** `schema_migrations.py:85-96` now
   carries `AND u.created_at <= projects.created_at` (plus `u.deleted_at IS NULL`
   and `WHERE owner_user_id IS NULL`). This is the closing piece: previously the
   UPDATE ran every boot and could re-inherit a legacy NULL-owner project to a
   NEWLY-registered recycled-nickname account. Now, since a recycled account is
   created strictly AFTER any pre-existing project, it can never satisfy
   `u.created_at <= projects.created_at`. Only the genuine original owner — who by
   definition predates their own project — can match. The runtime fallback was
   removed in R7.4; this closes the last write path.

**Is there ANY remaining way a recycled nickname gains ownership? NO.**
- New projects always set `owner_user_id=user.id` atomically at creation
  (`projects.py:61-65`) — never NULL for a normally-created project, so the
  backfill never touches them.
- NULL-owner rows exist only for legacy pre-column projects whose owner predates
  the project; the `created_at <=` guard admits only that original owner and
  rejects every later recycled account.
- The only edge worth ruling out — a recycled-nickname user created BEFORE a
  NULL-owner project — is impossible: projects can only be created with a
  non-NULL owner (line 64), so a NULL-owner project is always a legacy row that
  predates any recycled account. The guard is sound.

Submitter/assignee authz (checked again) is entirely ID-based
(`permissions.py`, `assignments.py`, router `*_user_id` guards);
`submitter_nickname` is display-only. No parallel nickname-inheritance vector.

## Fresh-pass findings

**None.** Source delta `01ed232`(R7.4)`..f70f3e6`(R7.5) is just
`schema_migrations.py` (+12 lines, the backfill guard analyzed above) and a
`.gitignore` line — everything else is reports/screenshots. Fresh sweep of every
attack surface came back clean:

- **File-serve endpoints** — all resolve paths from DB rows keyed by
  server-generated UUIDs, never user-supplied paths:
  - `download_drive_file` (`project_drive.py:844-877`): byte-identical to the
    R7.3 GREEN version. `path=Path(version.storage_path)` (DB-sourced);
    `_INLINE_SAFE_MIME_PREFIXES` allowlist (no svg/html/xml) + octet-stream
    collapse for non-allowlisted/attachment + `content_disposition_type` +
    `X-Content-Type-Options: nosniff`. M8 inline-XSS still closed.
  - `client_file` (`main.py:260-268`): fixed allowlist dict
    (`CLIENT_FILES.get(name)`) — `name` maps only to hardcoded filenames, no
    traversal.
  - Siblings (attachments, deliveries ×2, voice, bulk-zip, main idx) unchanged;
    Round-4/5 disposition-safe verdicts stand.
- **Path traversal** — `_safe_filename` (`project_drive.py:315-317`) collapses to
  `Path(name).name` (strips dir components); `_drive_file_path` /
  `_full_text_path` build from UUID IDs; `_safe_path` (`auto_agent.py:148-154`)
  enforces `.resolve()` + parents containment for the LLM tool sandbox.
- **XSS DOM sinks** — repo-wide grep for `dangerouslySetInnerHTML` / `innerHTML` /
  `outerHTML` / `document.write` / `insertAdjacentHTML` / `eval(` / `new Function(`
  across ts/tsx/js/jsx/vue/svelte: **zero matches**.
- **SSE isolation** (`push.py:53-104`): `stream_one` gated by
  `can_view_requirement_record`; `stream_me` topic derived from `user.id`
  (auth-derived, NOT a path param) — no cross-user subscription; all require
  `require_stream_user`. Unchanged.
- **Deep-link** (`deep_link.rs`): `ALLOWED_HOSTS.contains(host)` whitelist +
  `..`/`.`/empty-segment filter. Intact (empty diff since R7.1).
- **Tauri capabilities** (`capabilities/default.json`): minimal — `fs` limited to
  appdata-recursive + read/write-text/mkdir/read-dir/exists; dialog/notification/
  os/deep-link/store defaults. **No `shell:allow-open`, no `process:*`, no
  eval/devtools.** Empty diff since R7.1.
- **Injection** — no `shell=True` / `os.system` / `os.popen` in backend; the two
  `subprocess.run` sites (`auto_agent.py:279`, `knowledge.py:391`) are argv-list
  (no shell). SQL f-string interpolation occurs only in
  `schema_migrations.py:55/63/74` `ALTER TABLE … ADD COLUMN {name} {ddl}` where
  both operands come from hardcoded module-level dicts — server-controlled DDL
  identifiers, no user input. The backfill UPDATE uses no interpolation.
- **Dependency manifests** — `git diff 9b735b5..HEAD` over package.json /
  package-lock / Cargo.toml / Cargo.lock / pyproject / requirements*.txt is
  **empty**. Nothing new to audit.
- **Rust** — only source change across R7.1→HEAD is `shell.rs` (R7.2/R7.3,
  reviewed GREEN in prior rounds). HEAD adds zero Rust diff. `open_folder`
  metachar/`..`/canonical-root-containment/single-argv/fail-closed intact.

## Coverage

| Area | Files / endpoints | Outcome |
|---|---|---|
| N1 cookie scrub | `git rev-list --all --objects` + refs/original + reflog + .gitignore | **RESOLVED** — blob gone from all reachable history; local file untracked+ignored |
| Secret scan (tree) | `sk-` / generic creds / private keys / `.env` / deploy host | **Clean** — only `sk-replace-me…` placeholder |
| Secret scan (history) | per-commit `git grep` for `sk-[…]{16,}` | **Clean** — no real key in any reachable blob |
| Ownership family — runtime | `projects.py:48,104`, `project_drive.py:100` | **Closed** — `owner_user_id` only, NULL=admin-only |
| Ownership family — tombstone | `users.py:123-132` | **Closed** — nickname→`_deleted_…`, fresh id for recycled |
| Ownership family — backfill (R7.5) | `schema_migrations.py:85-96` | **Closed** — `created_at <=` guard rejects later recycled account |
| Ownership family — submitter/assignee | `permissions.py`, `assignments.py`, router guards | **All ID-based**; nickname display-only |
| File-serve / M8 inline XSS | `project_drive.py:844-877`, `main.py:260-268`, siblings | **Closed** — allowlist+octet+nosniff+Disposition; DB-sourced paths |
| Path traversal | `_safe_filename`, `_drive_file_path`, `_safe_path` | **Safe** — name-only + UUID + resolve-containment |
| XSS DOM sinks | repo-wide ts/tsx/js/jsx/vue/svelte grep | **Zero matches** |
| SSE isolation | `push.py:53-104` | **Safe** — stream_one gated, stream_me auth-derived topic |
| Deep-link | `deep_link.rs` | **Safe** — host whitelist + `..` filter (unchanged) |
| Tauri capabilities + conf | `capabilities/default.json`, `tauri.conf.json` | **Safe** — minimal fs, no shell/process/eval (unchanged) |
| Injection (shell/SQL) | backend `subprocess` / `text(f"…")` | **Safe** — argv-list, hardcoded DDL identifiers |
| Dependency manifests | package/Cargo/pyproject/requirements lockfiles | **No change** since R7.1 |
| Rust source delta | `shell.rs` (R7.2/R7.3); HEAD adds 0 Rust | **GREEN** — unchanged, prior verdicts stand |

## Accepted residuals (unchanged, none worse)

| ID | Title | Status |
|---|---|---|
| H1 | `/identify` LAN nickname trust (`auth.py:236-237`) | Unchanged. LAN-trust model. |
| M6 | Knowledge cross-project leak (incl. `owner_nickname` in index body) | Unchanged. |
| L5 | Windows reserved names in `_safe_filename` | Unchanged. Local-DoS only. |
| L6 | `list_users?include_deleted=true` open to all | Unchanged (`display_name` masks tombstone). |
| L7 | `cookie_secure=False` default | Unchanged. Deploy-checklist; prod guard at `main.py:166-169`. |
| L8 | Install scripts over plain HTTP | Unchanged. |

## Round-6 outcome

**GREEN.** Zero MEDIUM+, zero new LOW. N1 — the only R7-R5 LOW — is RESOLVED:
the `visual_tmp/cookies.txt` blob is scrubbed from all reachable history
(`refs/original` dropped, reflog expired), confirmed unreachable; the leftover
local file is untracked + gitignored and can never re-enter the repo. The whole
tree and full reachable history contain only the documented
`sk-replace-me-with-your-deepseek-key` placeholder — no real keys, passwords,
tokens, private keys, or the deploy host. The recycled-nickname
ownership-inheritance family is fully closed on all three layers (R7.4 runtime
authz + delete_user tombstone + R7.5 `created_at <=` backfill guard) with no
remaining write path. The fresh whole-codebase sweep — file-serve, XSS sinks,
path traversal, auth/authz, SSE isolation, deep-link, Tauri capabilities,
injection, dependency manifests, Rust — is clean. Accepted residuals (H1, M6,
L5–L8) unchanged and none worse.
