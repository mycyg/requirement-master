# R7 Round 4 — Security + Rust

Scope: HEAD `a5c700e` (R7.3) on `fix/r6-hardening`. Combined Security + Rust-client
audit. Verified the R7.3 M8 stored-XSS fix (incl. every other byte-serving
endpoint), verified the R7.3 Rust micro-change, then swept the whole codebase
fresh for any P1/MEDIUM+ issue. Threat model unchanged: LAN-deployed FastAPI +
Tauri 2.x client, nickname+cookie auth, admin is the only RBAC role.

Read-only. No code written or edited.

## Verdict: GREEN

**0 new P1/MEDIUM+ findings. M8 (the R3 cross-round blocker) is fully closed and
verified empirically. The R7.3 Rust micro-change is correct. The Rust client
surface is byte-for-byte identical to R3's "NEEDS NOTHING" audit minus one dead
line. No dependency manifest changed since R7.1. All other R7.3 code changes
(delivery_upload, projects reindex consolidation, schema_migrations FK cleanup,
frontend parseServerDate hardening) are security-neutral.**

This is a clean/green round. H1, M6, L5–L8 remain accepted residuals per the LAN
trust model and are unchanged (none got worse).

---

## M8 fix verification (incl. other inline endpoints)

**Fix location:** `app/routers/project_drive.py:837-878` (`download_drive_file` +
`_INLINE_SAFE_MIME_PREFIXES`).

### The fix does three things, all confirmed correct:

1. **Always passes `filename=item.name`** → Starlette's `FileResponse.__init__`
   now always sets `Content-Disposition` (it only sets it when `filename is not
   None`). Verified against the installed Starlette 1.0.0 source: the
   `if self.filename is not None:` branch builds
   `f'{content_disposition_type}; filename="..."'` and `setdefault`s it.

2. **`content_disposition_type="inline"|"attachment"`** is an explicit, valid
   Starlette param (default `attachment`). Confirmed in the installed signature.

3. **Inline MIME allowlist** (`_INLINE_SAFE_MIME_PREFIXES`): jpeg/png/gif/webp/
   bmp/x-icon/vnd.microsoft.icon, `audio/`, `video/`, `application/pdf`,
   `text/plain`. For `inline=1` a mime is passed through ONLY if it `startswith`
   one of these; otherwise it collapses to `application/octet-stream`. Non-inline
   (download) requests also collapse to `application/octet-stream`.

4. **`X-Content-Type-Options: nosniff`** is added via the `headers=` kwarg.

### Empirical header proof

I instantiated the real `FileResponse` with the exact arguments the router
computes and dumped `raw_headers`:

| Case (uploaded file) | Content-Type emitted | Content-Disposition | nosniff |
|---|---|---|---|
| `pwn.svg`, mime `image/svg+xml`, `inline=1` | `application/octet-stream` | `inline; filename="pwn.svg"` | yes |
| `note.txt`, mime `text/plain`, `inline=1` | `text/plain; charset=utf-8` | `inline; filename="note.txt"` | yes |
| any file, download (no `inline`) | `application/octet-stream` | `attachment; filename=...` | yes |

### Answers to the explicit verification questions

- **Is SVG truly blocked from inline?** YES. `image/svg+xml` is not in the
  allowlist → served as `application/octet-stream` + `Content-Disposition:
  inline` + nosniff. With octet-stream and nosniff the browser will not parse it
  as SVG/XML, so the `<svg onload=...>`/`<script>` never executes. The mime is
  user-controlled at upload (`mime=meta.get("mime")` line 781 / `payload.mime`
  line 681), but the download path ignores attacker mime for the render decision.

- **Could `text/plain` with `<html><script>` be sniffed as HTML by old
  browsers?** NO. `nosniff` is emitted on the FileResponse (proven above) and
  forbids the browser from reinterpreting a declared `text/plain` as `text/html`.
  All browsers that honor nosniff (IE8+, every modern engine) display the bytes
  as literal text. The pre-nosniff IE6/7 era is out of scope for this LAN deploy.

- **Is the nosniff header actually emitted on FileResponse?** YES, confirmed by
  the raw-header dump above — `x-content-type-options: nosniff` appears on every
  variant. Starlette's `init_headers(headers)` merges the custom header before
  setting the defaults; it is not dropped.

### Comprehensiveness — ALL other byte-serving endpoints checked

I enumerated every `FileResponse` / `StreamingResponse` / raw `Response` in
`app/` and classified each by disposition + mime control:

| Endpoint | File:line | Disposition | Mime | XSS risk | Verdict |
|---|---|---|---|---|---|
| Drive inline/download | `project_drive.py:846-878` | inline allowlist / attachment | controlled→octet for unsafe | none | **FIXED (M8)** |
| Drive bulk zip | `project_drive.py:924` | implicit attachment (filename + zip) | `application/zip` | none | PASS |
| Attachments download | `attachments.py:352` | attachment (filename, default type) | user mime, but attachment | none (downloads) | PASS |
| Delivery package | `deliveries.py:117` | attachment (filename) | `application/zip` | none | PASS |
| Delivery file-in-zip | `deliveries.py:141` | explicit `attachment` | `application/octet-stream` | none | PASS |
| TTS audio | `voice.py:61` | none | `audio/wav` (server-forced) | none — server-synthesized, not user-uploaded | PASS |
| SSE streams | `push.py`, `chat.py` | n/a | `text/event-stream` | none | PASS |
| `/client/{name}` | `main.py:268` | none (filename None) | guessed | none — hardcoded whitelist, not user-uploaded | PASS |
| SPA fallback | `main.py:375` | none | `text/html` | none — trusted build artifact | PASS |

- **Attachments** (`/api/files/{id}`): always `attachment` (filename passed,
  default `content_disposition_type`), so even a poisoned `a.mime` cannot render
  inline. Lacks nosniff (defense-in-depth gap only) but is safe by disposition.
  Not a finding — same posture R3 accepted.
- **Delivery downloads**: both force attachment; the per-member route forces
  `octet-stream` + explicit `Content-Disposition: attachment`. Safe.
- **Meeting media**: there is NO endpoint that serves meeting audio bytes back to
  a browser. `meetings.py` only streams audio server-to-server to ASR
  (`meetings.py:357-375`). No inline vector.
- **Drive preview** (`project_drive.py:927`): returns JSON metadata, not bytes.
  HTML preview returns `render_url=.../download?inline=1`; for an `.html` upload
  that URL now yields octet-stream + nosniff. The frontend HTML iframe also has
  `sandbox=""` (`ProjectDrive.tsx:709`) — double-safe. The PDF preview iframe
  (`:708`) renders `application/pdf` (allowlisted) with no sandbox attr; browser
  PDF viewers run PDF-JS in their own sandbox and cannot touch the embedding
  origin's cookies/DOM — pre-existing, not a finding.

**Conclusion: M8 is comprehensively closed.** The one-line root fix plus the
allowlist plus nosniff cover the reported drive vector AND every sibling
byte-serving endpoint is independently safe by disposition.

---

## Rust verification

**R7.3 micro-change:** removed the dead `let _ = Path::new("");` line (was
`shell.rs:118`). Diff confirms exactly one line deleted, nothing else.

- `canonicalize_with_existing_ancestor` still compiles and is unchanged — it is
  the entire body of lines 66-90, untouched by R7.3.
- `Path` is still referenced unconditionally: imported at line 1
  (`use std::path::{Component, Path, PathBuf}`) and used in the helper's
  signature `fn canonicalize_with_existing_ancestor(p: &Path)` at line 66. So the
  removed "suppress unused-import warning" line was genuinely dead (the import is
  used on every cfg branch). No `unused_imports` warning is reintroduced. The
  P3-NEW-1 hygiene item from R3 is now resolved.
- The helper's edge-case correctness (drive roots, UNC, missing drives, symlinked
  ancestors, perm-denied intermediates, relative paths, race-during-walk, case
  mismatches, fail-closed `starts_with`) was exhaustively validated in R3 and is
  byte-identical here. No re-audit needed; nothing changed.

**Whole Rust surface vs R7.1:** the ONLY Rust source change across all of R7.1→
R7.3 is in `shell.rs` (the R7.2 helper + this R7.3 one-line deletion). Verified
via `git diff`. `capabilities/default.json` and `tauri.conf.json` are unchanged
since R7.1.

Fresh confirmation of the items the prompt called out:
- **`sync.rs` path traversal** (`sync.rs:280-368`): `ensure_parent_inside_root`
  canonicalizes each component and rejects any that doesn't `starts_with`
  `root_canon` (resolves symlinks); non-`Normal` components rejected.
  `safe_component` rejects `/`, `\`, `:`, empty, `.`, `..`. `safe_relative_path`
  rejects `..` and drive-letter `:`. Correct.
- **`deep_link.rs`**: host whitelist `["r","p","inbox","settings","me"]`; path
  split, empty/`.`/`..` segments filtered; only the sanitized path emitted on
  `navigate`/`deep-link`, never the raw URL/fragment/query. Intact.
- **Tauri capabilities**: minimal — no `shell:allow-open`, no `process:*`, no
  devtools/eval. `fs` limited to `appdata-recursive` + read/write-text/mkdir/
  read-dir/exists. Unchanged.

Rust verdict: **GREEN — 0 P0/P1.** R3's "NEEDS NOTHING" stands; the dead line is gone.

---

## New findings

**None.** No P1/MEDIUM+ (and no new P2) issue surfaced in the fresh whole-codebase
sweep. The R7.3 collateral code changes are all security-neutral:

- `delivery_upload.py`: chunk-size validation moved into the worker thread and
  folded into the merge (perf). Validation logic preserved; still raises 400 on
  mismatch (now via `ValueError`→`HTTPException`). `digest_hex` used directly
  after removing the `_Digest` shim. No authz/traversal change.
- `projects.py`: `_reindex_project_in_background` deduplicated into
  `project_drive.schedule_project_reindex`; the worker now owns the `running`
  flag (fixes a sticky-flag leak race). Callers (archive/restore/soft_delete) are
  the same already-authorized admin/owner handlers. No new surface.
- `schema_migrations.py`: idempotent orphan-FK NULL-out with hardcoded SQL, no
  user input. Safe.
- `shared/src/api/time.ts` + 3 web pages: `parseServerDate` now returns `null`
  for `Invalid Date`. Output flows into text nodes (React-escaped). No XSS.

---

## Accepted residuals (unchanged)

| ID | Title | Status this round |
|---|---|---|
| H1 | `/identify` LAN nickname trust (`auth.py:237`) | Unchanged. LAN-trust model. Not worse. |
| M6 | Knowledge cross-project leak | Unchanged. LAN-trust model. |
| L5 | Windows reserved names in `safe_component` | Unchanged. Local-DoS only. |
| L6 | `list_users?include_deleted=true` open to all | Unchanged. Tombstone format masked by `display_name`. |
| L7 | `cookie_secure=False` default | Unchanged. Deploy-checklist concern. |
| L8 | Install scripts over plain HTTP | Unchanged. Supply-chain on hostile LAN. |

Confirmed only three nickname-comparison authz sites repo-wide
(`auth.py:237`, `projects.py:53` legacy fallback, `project_drive.py:101` M7-fixed
fallback) — no new nickname-trust authz introduced.

Rust P2/P3 backlog (R1/R2/R3) unchanged and non-blocking; R3-P3-NEW-1 (dead
`Path::new("")`) is now resolved by R7.3.

---

## Coverage

| Area | Files / endpoints | Outcome |
|---|---|---|
| M8 fix (drive download) | `project_drive.py:837-878` | **PASS — empirically verified headers** |
| M8 — other inline endpoints | attachments, deliveries(×2), voice, main(×2), push/chat SSE, bulk-zip | All PASS (attachment-by-disposition or non-user-bytes) |
| Meeting media serving | `meetings.py` | No byte-serving endpoint exists — N/A |
| Drive preview iframe | `ProjectDrive.tsx:708-709` | HTML iframe `sandbox=""`; PDF iframe renders allowlisted `application/pdf` |
| Rust micro-change | `shell.rs` dead-line removal | PASS — `Path` still referenced, helper intact |
| `canonicalize_with_existing_ancestor` | `shell.rs:66-90` | Unchanged since R7.2; R3 exhaustive audit stands |
| Rust path traversal | `sync.rs:280-368` (`safe_component`/`safe_relative_path`/`ensure_*_inside_root`) | PASS (L5 accepted) |
| Deep-link sanitization | `deep_link.rs` | PASS — host whitelist + traversal filter |
| Tauri capabilities | `capabilities/default.json` | PASS — minimal, unchanged since R7.1 |
| Tauri CSP | `tauri.conf.json` | Unchanged (R1-P2-7 LAN-trust accepted) |
| XSS frontend (DOM sinks) | repo-wide `dangerouslySetInnerHTML`/`innerHTML`/`document.write`/`insertAdjacentHTML`/`outerHTML` | Clean — zero matches in any `.ts/.tsx/.js/.jsx` |
| XSS — markdown render | preview `content` → `<pre>` (React-escaped) | PASS — no markdown lib, no raw-HTML render |
| SSE cross-user leak | `push.py` stream_all/one/me | PASS — `stream_one` gated by `can_view_requirement_record`; `stream_me` uses cookie-derived `user.id`, not path param |
| Auth/authz — nickname trust | repo-wide nickname-comparison grep | Only 3 known sites; H1 + M7-fixed fallback + legacy filter. No new. |
| R7.3 collateral changes | delivery_upload, projects, schema_migrations, time.ts + 3 pages | All security-neutral |
| Dependency manifests | pyproject.toml, web/client/shared package.json, Cargo.toml, Cargo.lock | **No change since R7.1** (empty diff) — nothing new to audit |
| Rust source (all files) | `client-tauri/src-tauri/src/**` | Only `shell.rs` changed since R7.1; rest identical to R3 |

---

## Round-4 outcome

GREEN on both axes. M8 (the only cross-round CLEAN-blocker) is closed and
verified down to the emitted HTTP headers. The Rust micro-change is correct and
even retires an R3 P3 hygiene item. No new P1/MEDIUM+ issues. Accepted residuals
(H1, M6, L5–L8) are unchanged and none got worse. This round counts toward the
4-consecutive-clean gate.
