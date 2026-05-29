# R7 Round 7 — Security + Rust + ship gate

HEAD: `94f7ff0` (R7.6) · branch `fix/r6-hardening` · target prod 192.168.5.53
Scope: verify R7.6 manifest-map change, final pre-ship secret sweep, ship-gate
checklist, Rust buildability. NO code written/edited.

## Verdict: GREEN (ship-ready)

All R7.6 changes verified safe. No real secrets in tree. All ship-gate items
pass. Rust client builds clean (`cargo check` succeeded). No dependency manifest
changes since R7.1. This branch is ship-ready for squash-merge to main and prod
deploy.

---

## R7.6 manifest-map security check — PASS

The only R7.6 backend code change is `app/routers/project_drive.py` (+176/-… vs
R7.5). New helpers: `_item_path_from_map`, `_build_manifest_maps`,
`_MANIFEST_MAX_ITEMS`, and a fast-path branch in `_drive_manifest_item`.

**No cross-project leak.** `_build_manifest_maps` (lines 240–263) builds the
`{id: item}` map from `db.query(ProjectDriveItem).filter(project_id == project_id)`
— strictly scoped to the single project. The `{version_id: version}` map is
built only from `version_ids = [r.current_version_id for r in rows ...]` (rows
of THIS project) via `ProjectDriveVersion.id.in_(version_ids)`. Neither map can
contain another project's data.

**`drive_changes` still returns only changed rows.** The `items=[...]` list
(line 679) iterates `rows` only — the `since`-filtered changed set. `item_map`
is consumed solely by `_item_path_from_map` for in-memory ancestor path
resolution (a changed file's unchanged ancestors must be resolvable), and is
never appended to the response. Confirmed by reading the full function: the map
is a path-lookup table, not part of the output schema.

**`download_url` unchanged + still gated.** `_drive_manifest_item` line 236 is
byte-identical to pre-R7.6:
`f"/api/drive/files/{item.id}/download" if item.kind == "file" and not item.deleted_at else None`.
That URL routes to `download_drive_file` (line 915) which is `Depends(current_user)`
+ `_require_item` → `_require_project` (404s on tombstoned/archived/inaccessible
projects). Folders and soft-deleted items get `download_url=None`.

**Cycle guard correct.** `_item_path_from_map` uses a `seen` set and bounds the
parent walk to `parent_id in item_map and parent_id not in seen` — a corrupted
cyclic parent chain terminates instead of spinning. `_MANIFEST_MAX_ITEMS=50000`
is a *log-only* warning, not a silent LIMIT (rows are not truncated), so an
oversized manifest surfaces rather than silently dropping files.

## Final secret scan — PASS

- **No real `sk-` keys.** `git grep -E "sk-[a-zA-Z0-9]{20,}"` over tracked code:
  zero matches. Only occurrence of the prefix is the placeholder
  `sk-replace-me-with-your-deepseek-key` in `app/.env.example:10`.
- **No hardcoded credentials.** `git grep` for `(password|secret|api_key|token)=`
  literals in `app/**/*.py`: zero matches.
- **`scripts/server_creds.py` NOT tracked.** `git ls-files | grep server_creds`
  returns only `scripts/server_creds.example.py` (placeholders only:
  `your.server.ip.or.hostname` / `your-ssh-username` / `your-ssh-password`).
  The real file exists on disk, `.gitignore:35` lists `scripts/server_creds.py`,
  and `git check-ignore scripts/server_creds.py` confirms it is ignored.
- **`192.168.5.53`** appears only as a LAN default/placeholder in client
  installers (`client/install-client.{sh,ps1}`, `client/yqgl_tray.py`), an
  onboarding UI placeholder, and E2E test fixtures — all env/arg-overridable.
  It is a private LAN address (the documented deploy target), not a secret.
  None of these files changed since R7.1.
- **`app/.env.example`** carries only `COOKIE_SECRET=change-me-to-a-long-random-string`
  and the `sk-replace-me` placeholder — both are values the production guard
  rejects (see below).

## Ship-gate checklist

| Item | Status | Evidence |
|------|--------|----------|
| Prod startup guard: COOKIE_SECRET | PASS | `main.py:166-167` raises RuntimeError if cookie_secret in {"", "dev-change-me", "change-me-…"} when `app_env=="production"` |
| Prod startup guard: CORS | PASS | `main.py:168-169` raises if `"*" in cors_allow_origins` in production |
| Guard actually invoked | PASS | `_validate_runtime_config()` called first in `lifespan` (`main.py:174`) |
| Default config rejected in prod | PASS | `config.py` defaults `cookie_secret="dev-change-me"`, `cors_allow_origins=["*"]` — both caught by guard |
| File-serve: drive download | PASS | `download_drive_file` always sets `filename=` + explicit `content_disposition_type` + `X-Content-Type-Options: nosniff` (project_drive.py:937-947) |
| M8 inline allowlist | PASS | `_INLINE_SAFE_MIME_PREFIXES` (910-912) excludes svg/html/xml; non-inline forces `application/octet-stream` for non-allowlisted mimes |
| File-serve: attachments | PASS | `attachments.py:352` passes `filename=` → Starlette emits `Content-Disposition: attachment` (default); gated by `_require_can_view_assets` |
| File-serve: deliveries | PASS | `deliveries.py:117,141` serve as `attachment` (zip/octet-stream); zip-member uses `safe_name` match + `Path(filename).name` (no traversal) |
| File-serve: bulk download | PASS | `bulk_download_drive` re-checks `_require_project` per distinct project before zipping (959-968) |
| Static `/client/{name}` | PASS | allowlisted `CLIENT_FILES` dict — no path param traversal (main.py:262) |
| Tauri capabilities minimal | PASS | `capabilities/default.json` — window/dialog/notification/os/store/deep-link + fs limited to `scope-appdata-recursive`; no shell-execute, no broad fs/http |
| Deep-link host whitelist | PASS | `deep_link.rs:9` ALLOWED_HOSTS = r/p/inbox/settings/me; strips `.`/`..`/empty segments; emits only sanitized path |
| No dependency manifest changes since R7.1 | PASS | diff of requirements*.txt / package*.json / Cargo.{toml,lock} / pyproject.toml: empty |
| SSE isolation | PASS | `push.py` all 3 streams `Depends(require_stream_user)`; `/stream/req/{id}` gates `can_view_requirement_record`; `/stream/me` topic = `user:{user.id}` (not path param) |
| Path traversal (Rust open_folder) | PASS | rejects metachars/control/NUL, rejects `..` ParentDir, containment check vs canonicalized roots, single-argv spawn |
| Auth/authz on drive endpoints | PASS | all 21 `@router` drive endpoints carry `current_user`/`require_stream_user` (auto-scan: 0 unauthenticated) |
| `_can_manage_project` identity-based | PASS | NULL owner_user_id is admin-only; no nickname fallback (project_drive.py:91-100) |

## Rust — PASS (buildable, minimal change since R7.1)

- **Only `shell.rs` changed since R7.1** (`9b735b5..94f7ff0`): +36/-5. `config.rs`
  had no commits in this window. No other `.rs`, no `Cargo.toml`/`Cargo.lock`
  change → lock is consistent with manifest.
- **`shell.rs` change reviewed — security-neutral bug fix.** New
  `canonicalize_with_existing_ancestor` walks up to the nearest existing ancestor,
  canonicalizes it, then re-appends the non-existent tail (so "Open Folder" works
  before a task folder is synced). Because the `..` ParentDir rejection (line 41)
  runs *before* canonicalization, the re-appended tail can only descend — the
  `starts_with(canon_root)` containment check (94-97) remains sound. All four
  defense layers intact: metachar reject, `..` reject, root containment,
  single-argv spawn. Removed line was a dead `Path::new("")` warning-suppressor.
- **`cargo check --offline` succeeded** — `yqgl-client v0.2.0` compiled clean,
  all 628 locked deps resolved offline (Cargo.lock self-consistent). Finished dev
  profile with no errors.

## Fresh-pass findings

None. No new issues surfaced in this round.

Notes (informational, not blockers — all unchanged from R6 GREEN posture):
- `attachments.py:352` relies on Starlette's default `content_disposition_type="attachment"`
  (it passes `filename=` but no explicit nosniff). Functionally safe because the
  default disposition is `attachment` so the browser downloads rather than
  in-origin renders; the stricter drive-download path adds explicit nosniff. Not
  a regression and not introduced this round.
- `192.168.5.53` LAN default in client installer scripts is intentional and
  overridable; documented deploy target, not a secret.

## Ship statement

GREEN — ship-ready. R7.6 manifest optimization introduces no security
regression (no cross-project leak, output rows unchanged, download_url still
gated). No real secrets in the tracked tree; `server_creds.py` correctly
gitignored and untracked. Production startup guards, file-serve hardening,
minimal Tauri capabilities, deep-link whitelist, SSE isolation, and path/authz
controls all intact. Rust builds clean with a consistent Cargo.lock. Clear to
squash-merge to main and deploy to prod.
