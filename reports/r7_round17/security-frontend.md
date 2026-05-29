# R7 Round 17 — Security + frontend freeze confirmation

HEAD `f360bef` (R7.16) · branch `fix/r6-hardening` · working tree clean.

## Verdict: GREEN/CLEAN (ship-ready) | BLOCKERS (0)

No MEDIUM+ / P2+ findings. tsc clean ×3, git history secret-clean, all
ship-gate controls intact, no R7.16/R7.15 regression. **Ship-ready** for
prod (192.168.5.53) + GitHub push. One P3 (dead-code no-op in the R7.16
SpeakButton change) listed below — non-blocking.

## tsc (3 packages)

| Package | Command | Result |
|---|---|---|
| shared | `tsc -p tsconfig.json --noEmit` | **0 errors** (exit 0) |
| web | `tsc -b` | **0 errors** (exit 0) |
| client-tauri (web-src) | `tsc -p web-src/tsconfig.json --noEmit` | **0 errors** (exit 0) |

All three configs are `strict: true` + `noUnusedLocals` + `noUnusedParameters`
+ `noFallthroughCasesInSwitch`. The tauri config's `include` covers
`src` + `../../shared/src` (verified via `--listFilesOnly`: 60+ project files
type-checked, shared resolved through the path alias). No type holes.

## Secret scan + ship-gate

- **Tree scan**: zero real secrets. Only `sk-replace-me-with-your-deepseek-key`
  placeholder in `app/.env.example`; `COOKIE_SECRET=change-me-…` placeholder.
  Other matches are benign test fixtures (`e2e-cookie-secret` in
  `web/playwright.config.ts`, `mock-client-token` in two `.spec.ts`).
- **Full git history** (`git log -p --all -S`): no real `sk-`/`AKIA`/`ghp_`/
  PRIVATE KEY ever committed. `scripts/server_creds.py` and `visual_tmp/`
  NEVER tracked (`git log --all` empty). No committed cookie.
- **Local sensitive files**: `scripts/server_creds.py` + `visual_tmp/` present
  locally, both confirmed ignored (`git status --ignored` → `!!`,
  `git check-ignore` matches incl. `app/.env`). Cannot be accidentally staged.
- **file-serve Content-Disposition + M8 inline allowlist** (`project_drive.py`
  L940–981): INTACT. `_INLINE_SAFE_MIME_PREFIXES` excludes svg/html/xml;
  non-allowlisted `inline=1` falls back to `application/octet-stream`;
  `X-Content-Type-Options: nosniff` set; default `attachment` disposition.
  `attachments.py download_attachment` uses `FileResponse(filename=…)` →
  Starlette emits `attachment`. `deliveries.py` L144 explicit
  `attachment; filename="{Path(name).name}"`.
- **auth/authz**: signed cookies (itsdangerous; tampering → None), httponly +
  samesite=lax + secure-from-config; client tokens SHA-256 at rest;
  soft-deleted users excluded from every auth path; cookie rotation on
  delete/logout. `bulk-download` re-checks `_require_project` per distinct
  project (no cross-project zip leak). INTACT.
- **SSE per-user topic isolation** (`push.py`): `/stream/me` topic is
  `user:{user.id}` from the authenticated cookie — NOT a path param; `/stream/req`
  gated by `can_view_requirement_record`. Publish side (`notifications.py`,
  `jobs.py`) uses `user:{row.user_id}` / `{job.created_by_user_id}` —
  server-derived only. No cross-user leak.
- **deep-link** (`deep_link.rs`): host allowlist `[r,p,inbox,settings,me]`;
  `.`/`..`/empty segments stripped; only sanitized path emitted (never raw
  URL with query/fragment). INTACT.
- **Tauri capabilities** (`default.json`): minimal — window controls, dialog
  open/save/message, fs scoped `appdata-recursive` (no broad fs scope), notify,
  os, deep-link, store. No `shell:allow-execute`, no `fs:scope-…` widening.
- **production startup guards** (`main.py:_validate_runtime_config`): in
  `app_env=production` rejects default/empty `COOKIE_SECRET` and wildcard
  `CORS_ALLOW_ORIGINS`. Runs first in `lifespan`. INTACT.
- **Rust**: zero changes since R7.9 (`git log a6f8ada..HEAD -- *.rs Cargo.toml`
  empty; `git diff --stat` empty). Production-ready, unchanged.
- **XSS/injection/traversal**: no `dangerouslySetInnerHTML`/`innerHTML`/
  `eval`/`document.write` anywhere in frontend. SQL is ORM-parameterized; the
  only f-string DDL (`schema_migrations.py`) uses hardcoded module-level column
  dicts, zero user input.

## R7.16/R7.15 frontend regression check

- **R7.16 SpeakButton `aliveRef`** — autoplay + supersede logic NOT broken.
  The load-bearing supersede guard is `myGen !== playGeneration` (monotonic
  claim, line 52/66), which is unchanged and intact. Autoplay path
  (`useEffect` → `speak()`) unaffected. **However**, see P3-1: the `aliveRef`
  was added as a guard (`|| !aliveRef.current`, line 66) but the unmount
  effect (lines 92–94) never sets `aliveRef.current = false` — so the guard
  never fires. The change is a **no-op**: its stated goal (don't play a clip
  whose fetch resolved after unmount) is NOT actually achieved, but it
  introduces **zero regression** — behavior is identical to pre-R7.16.
- **R7.16 upload-merge orphan guards (3 backend)** — `attachments.finalize_upload`,
  `attachments.upload_simple`, `project_drive.finalize_drive_upload` got the
  pre-validate + try/except-BaseException-unlink guard. No security surface
  (DB rows uncommitted at merge time → always rolled back). Pure disk-leak fix.
  Consistent with the now-guarded disk-full residual.
- **R7.15 7 token guards** — all intact and correctly wired (last-write-wins):
  - **VoiceButton hot-mic** (real P2): `wantRecordingRef` press-intent set true
    synchronously pre-await, re-checked after `getUserMedia` (closes mic if
    released mid-prompt); `stop()` handles no-recorder-yet; unmount effect
    DOES set `wantRecordingRef.current = false` + releases tracks. Solid.
  - **SpeakButton overlapping voices** (real P2): `playGeneration` supersede +
    stop-before-assign + unmount stop-if-mine. Intact.
  - **AdminPanel reqTokenRef** (real P2): token captured at request start, both
    `.then`/`.catch` gated on `token === reqTokenRef.current`. Correct.
  - Parity sweep (TaskDetail, KnowledgePage, PlanningPage, ProjectView,
    ProjectMeetings, Clarify, Dashboard): monotonic-token staleness guards
    present (grep-confirmed across the file set). No regression.

## P3 notes (non-blocking)

- **P3-1 (NEW, R7.16): SpeakButton `aliveRef` is dead code / unfulfilled fix.**
  `web/src/components/SpeakButton.tsx` — `aliveRef = useRef(true)` (L46) is read
  in the bail (`|| !aliveRef.current`, L66) but is never assigned `false`. The
  unmount `useEffect` (L92–94) only calls `stopCurrent()`. Because the Audio
  object isn't created until *after* the fetch resolves (L69–72), at unmount-
  mid-fetch `myAudioRef.current` is still `null`, so neither the dead aliveRef
  guard NOR the unmount `stopCurrent` catches that case → the R7.16-intended
  "don't play on a dead component" scenario is still not handled. Impact is
  cosmetic only: a one-shot TTS clip may briefly play after navigating away
  mid-fetch (the same pre-R7.16 behavior; no leak, no second voice — the
  module singleton + `playGeneration` still prevent overlap, and the next
  `speak()`/`stopCurrent()` reclaims it). Compare VoiceButton, whose unmount
  effect correctly sets `wantRecordingRef.current = false`. One-line fix
  (`useEffect(() => () => { aliveRef.current = false; … })`). **Does not block
  ship** — no security/data impact, no regression vs. prior rounds.

— No other P3s. No P2+/MEDIUM+ anywhere. **GREEN — ship-ready.**
