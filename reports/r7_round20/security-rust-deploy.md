# R7 Round 20 — Security + Rust + deploy readiness (final gate)

## Verdict: GREEN (ship-ready) | BLOCKERS (0)

Frozen tree at HEAD `3dcf440` (R7.17), working tree clean (only untracked
`reports/r7_round18..20/`). Every ship-gate control re-verified against source.
**No MEDIUM+/P2+ findings. The tree is ship-ready for the 192.168.5.53 prod
deploy and the GitHub push.** R7.17's only delta (SpeakButton aliveRef) carries
no security surface — confirmed unchanged elsewhere.

## Exhaustive secret scan (tree + history)

Triple-confirmed clean across (a) the working tree, (b) `git grep` over **all
refs/commits**, and (c) an exhaustive per-object dump of **all 2766 blobs** in
reachable history:

- **API keys**: the only real `sk-` value anywhere (tree or any historical
  blob) is the placeholder `sk-replace-me-with-your-deepseek-key`
  (`app/.env.example:14`). Every other `sk-` hit is prose fragment noise
  (di**sk-**leak, ta**sk-**detail, a**sk-**poll, …) in prior round reports.
  Zero real `sk-[A-Za-z0-9]{20,}` keys in any commit.
- **Private keys**: zero `BEGIN … PRIVATE KEY` / `OPENSSH` blobs in tree or
  history. The history grep "hits" are prior security-report prose describing
  their own scans (`…BEGIN … PRIVATE KEY blobs | none in tree`), not keys.
- **Passwords**: no real `SSH_PASS`/`SUDO_PASS`/`password=` in any commit —
  only `your-…`/`change-me` placeholders in `scripts/server_creds.example.py`.
- **Cookies / tokens / bearer**: zero committed `Set-Cookie`/`session=`/Bearer
  values in history. Only `COOKIE_SECRET: "e2e-cookie-secret"` (Playwright
  test config) and `cookie_token: "session"` (a config *key-name* flag in
  `App.tsx`, not a value) — both benign.
- **`scripts/server_creds.py`**: gitignored ✔, untracked ✔, **never committed
  in any ref** ✔ (history shows only `server_creds.example.py`). Present on
  local disk only.
- **`visual_tmp/`**: gitignored ✔, untracked ✔, **absent from all history** ✔.
- **Deploy host `192.168.5.53`**: appears only as a documented LAN default in
  install scripts, onboarding placeholder, and E2E config. A private RFC1918
  IP with no attached credential is not a secret — intentional, acceptable.

Verdict: **safe for a public-ish GitHub push.**

## Ship-gate controls

| Control | Status | Evidence |
|---|---|---|
| File-serve Content-Disposition | ✔ | `attachments.py:360` `FileResponse(filename=)` → forced `attachment`; `deliveries.py:144` explicit `attachment`; `project_drive.py:971-979` disposition-controlled |
| M8 inline allowlist (svg/html/xml excluded) | ✔ | `project_drive.py:944-946` `_INLINE_SAFE_MIME_PREFIXES` excludes svg/html/xml; non-allowlisted inline → forced `application/octet-stream` (974) |
| nosniff | ✔ | `project_drive.py:980` `X-Content-Type-Options: nosniff` on drive download |
| Auth on every mutating + read endpoint | ✔ | Balanced-paren parse of all 27 routers: every route carries an auth `Depends`, except `voice.asr-health` / `voice.voices` (read-only upstream health probes — no input, no mutation, no per-user data; mutating `transcribe`/`tts` ARE gated) |
| SSE per-user topic isolation | ✔ | `push.py:95-104` `/stream/me` topic = `user:{auth_user.id}` (not a path param); `/stream/req` gated by `can_view_requirement_record` (84); sensitive job/notify data never on global `all` (jobs.py:72-75) |
| Deep-link host allowlist + traversal strip | ✔ | `deep_link.rs:9` allowlist `r/p/inbox/settings/me`; 23-26 strips `.`/`..`/empty; emits sanitized path only (never raw URL w/ query) |
| Tauri capabilities minimal | ✔ | `capabilities/default.json` — no `shell:*`, no `process:*`, no devtools perm; `fs:` scoped to appdata; only window/dialog/notification/os/deep-link/store |
| Production startup guards fail-closed | ✔ | `main.py:180-191` `_validate_runtime_config()` in lifespan → `raise RuntimeError` on default/empty `COOKIE_SECRET` or `*` in CORS (incl. the .env.example placeholder) |
| CSP present | ✔ | `tauri.conf.json` `script-src 'self'` (no unsafe-inline/eval for scripts); webview is the security-critical surface where deep-links/previews execute |

`open_folder` (shell.rs) — the only process-spawn — is a guarded Rust command,
not a JS-reachable shell cap: rejects shell metachars/NUL/control chars,
rejects `..`, confirms canonical target is under a configured root, spawns with
a single argv arg (no shell re-parse). Delivery zip-member download matches on
pre-computed `safe_name` + `Path(filename).name` (traversal-safe).

## Rust production-readiness

- **Reachable panics from server/fs data: zero.** Only two `.expect()` — both
  init-time: `http.rs:28` (reqwest client build at startup) and `lib.rs:132`
  (top-level Tauri `run()`). No `.unwrap()` on server/fs data, no
  `panic!`/`unreachable!`, no raw numeric indexing on dynamic buffers.
- **Slicing audited safe**: `sse.rs:108` `drain(..=pos)` (pos from `position()`,
  in-bounds); `sse.rs:109` `[..len-1]` (only after `\n` found ⇒ non-empty);
  `spec_watch.rs:205` `[..n]` (n from `read()`, ≤ buf len).
- **Config parsing fail-safe**: malformed config on disk → backup + `Config::
  default()`, `.unwrap_or(0)` for timestamps. No crash on hostile config.
- **Origin pin intact**: all requests built via `url(state, path)` against the
  user-configured `base_url` only; auth token (`X-YQGL-Client-Token`) injected
  from local config, never reflected from server responses.
- **Sandbox/path-traversal intact**: `shell.rs` root-confinement + `..` reject;
  `spec_watch.rs:93` / `sync.rs:282` / `delivery.rs:76,104` canonicalize +
  `starts_with(root)`.
- **Cargo.lock consistent**: `cargo metadata --locked` resolved cleanly (lock
  in sync with manifest). Version `0.2.0` matches `tauri.conf.json`.
- **Buildable**: `cargo check --locked` → **exit 0**.

## Deploy readiness (systemd / scripts / .env)

- **systemd**: `yqgl-web.service` has `--workers 1` + a thorough inline comment
  documenting it as MANDATORY (SSE bus / presence / chat-slot / dedup are
  in-process singletons; 2nd worker = silent split-brain). `EnvironmentFile`
  set, `Restart=on-failure`. ASR/TTS also `--workers 1`, bound `127.0.0.1`.
  DEPLOY.md:89 documents the same mandate + Redis-broker prerequisite to scale.
- **deploy_web.py**: true atomic swap — stage to `dist.new`, `mv` to timestamped
  release, `ln -sfn … && mv -Tf` (atomic rename), keep last 5 for rollback,
  smoke-check health+root+SPA. No broken-page window.
- **deploy.py**: `.env` excluded from default tree push (won't clobber server
  secret); `--env` uploads it mode `0o600`; restart + health-check. App push is
  rsync-style over a brief restart cycle — acceptable for the single LAN backend
  (atomic-swap requirement targets the user-facing static assets, which are
  handled).
- **.env.example**: `APP_ENV=production`, `COOKIE_SECRET=change-me-…`
  (placeholder ⇒ startup guard fails closed), `COOKIE_SECURE=false` with clear
  HTTP-on-LAN rationale (a Secure cookie over plain HTTP is dropped → silent
  login break). Sane.
- **Dependencies**: zero manifest changes since R7.1 (`git diff 9b735b5..HEAD`
  on requirements.txt / Cargo.toml / package.json = empty). No new pins.

## P3 notes (non-blocking)

- `voice.asr-health` + `voice.voices` are unauthenticated read-only upstream
  health/capability probes. Harmless on LAN (accepted H1 trust), but adding
  `Depends(current_user)` for parity with the rest of the surface is a trivial,
  optional hardening if a future deploy leaves LAN trust.
- Web-side (nginx-fronted SPA) CSP is not emitted by the API server; CSP is
  enforced at the Tauri webview (the security-critical preview/deep-link
  surface). If the browser SPA is ever exposed beyond LAN, add a CSP header at
  the reverse proxy. P3.
