# R7 Round 2 — Rust client

Reviewer: architecture-strategist (read-only, fresh-eyes pass)
HEAD: `9b735b5 R7.1: address R7 Round 1 multi-agent review findings`
Scope: every `client-tauri/src-tauri/src/**.rs` + `Cargo.toml` + `capabilities/default.json` + `tauri.conf.json`, plus the two JS callers of `open_folder`

## Verdict

**NEEDS FIXES — 0 P0, 1 P1, 6 P2.** R7.1 successfully closed the P1 from Round 1 (`register_device` now clears dedup state). The `open_folder` hardening is correct in spirit but introduces a subtle Windows-only regression in its canonicalize-fallback policy that will break the two existing callers (`TaskDetail.openLocal`, `ActionRailDispatch.openDeliveryFolder`) on the very-first-time-before-sync flow. None of the R1 P2s were addressed but most are still acceptable.

---

## R7.1 fix verification

### Fix 1: `register_device` clears dedup state — CORRECT

`commands/auth.rs:95-98` now writes both `client_token` and `clear_dedup_state()` inside the same `state.write` closure. The closure runs under the `Mutex<Config>` lock, so the two mutations are atomic from any concurrent reader's perspective (no torn read where the token rotated but dedup state still belongs to the previous identity). The accompanying comment correctly explains why this duplicates `set_config`'s `identity_changed` logic. Closes R1-P1-1.

### Fix 2: `open_folder` validation — CORRECT for the threat model, but the canonicalize-fallback policy breaks real callers

`commands/shell.rs::open_folder` now takes `State<'_, ConfigState>` (signature change propagated to `submitter.rs:488` correctly) and enforces three checks:

1. **Char filter** (lines 31-36): rejects NUL, CR/LF, `| ; & < > " ` $ ESC`. Correct. Note: misses backslash `\\` (intentional — Windows uses it as separator), single-quote `'`, parens `()`, brace `{}`, question `?`, asterisk `*`. For *folder opening on the OS file browser*, this is adequate because the path is passed as a single argv arg via `Command::arg`, not joined into a shell string. The threat model documented at lines 11-22 is correct.
2. **`..` segment filter** (lines 41-43): uses `Component::ParentDir`, which correctly catches `..` even when other segments are valid. `Path::components()` normalizes redundant separators but PRESERVES literal `..`, so the check is accurate.
3. **Root-containment check** (lines 45-71): this is where the regression lives — see P1-NEW-1 below.

**The `submitter.rs:488` call-site update** (`open_folder(state, path.to_string_lossy().to_string())`) is correct: `open_spec_folder` already holds `State<'_, ConfigState>` and `std::fs::create_dir_all(&path)` runs immediately before the call, so the target exists by the time `open_folder` canonicalizes it — this particular caller is unaffected by P1-NEW-1.

---

## P1 findings

### P1-NEW-1 — `open_folder` rejects valid not-yet-existing paths on Windows due to asymmetric verbatim-prefix canonicalization

- Location: `client-tauri/src-tauri/src/commands/shell.rs:58-71`
- Two JS callers do NOT pre-create the directory before calling `open_folder`:
  - `web-src/src/routes/TaskDetail.tsx:122-126` `openLocal` — constructs `${sync_root}\${project_slug}\${code}` and calls directly.
  - `web-src/src/components/ActionRailDispatch.tsx:115-124` `openDeliveryFolder` — constructs `${sync_root}\${project_slug}\${code}\deliveries` and calls directly.
- On Windows, `Path::canonicalize` returns the **verbatim/extended-length** form (`\\?\D:\…`). The current code does this:
  ```rust
  let canon_target = target.canonicalize().unwrap_or_else(|_| target.clone());
  // ...per root:
  let canon_root = root.canonicalize().unwrap_or_else(|_| root.clone());
  canon_target.starts_with(&canon_root)
  ```
- Flow for "open task folder before sync ever ran":
  1. `target` = `D:\工作需求\proj-foo\REQ-1` (folder does not yet exist).
  2. `target.canonicalize()` fails with `ERROR_FILE_NOT_FOUND` → fallback to raw `D:\工作需求\proj-foo\REQ-1`.
  3. `root` = `D:\工作需求` (from `default_sync_root`, exists).
  4. `root.canonicalize()` succeeds → `\\?\D:\工作需求`.
  5. `D:\工作需求\proj-foo\REQ-1`.starts_with(`\\?\D:\工作需求`) → **FALSE** (different prefix forms).
  6. User sees `"open_folder: path is not under any configured workspace root"` and the OS file browser never opens.
- This is the primary user flow for first-time-on-a-task; it currently does not work on Windows.
- The Linux/macOS path is also affected when the root is a symlink (canon_root resolves through the symlink while canon_target stays as the un-resolved literal).
- Fix options (any of these):
  - Symmetric canonicalize: if `target` doesn't exist, walk UP to the nearest existing ancestor, canonicalize that, then re-append the missing tail. This is what `sync.rs::ensure_parent_inside_root` already does (lines 280-313).
  - Strip the `\\?\` prefix from `canon_root` before comparison via `dunce::simplified` (already not in Cargo.toml; one-line dep) or by manual prefix stripping when both sides differ in verbatim-ness.
  - `std::fs::create_dir_all(&target)?` before canonicalize — only safe when the path is already proven to live under a configured root, which is what we're trying to verify. So this option re-introduces the very TOCTOU hole the fix was meant to close. Skip.
  - Best fix: copy the `ensure_dir_inside_root` pattern — walk up to the existing ancestor, canonicalize THAT against the canon_root, then validate the remaining tail has no escaping components.

This is **P1, not P0**, because there's no security regression (the over-strict check FAILS CLOSED — it rejects legitimate paths, not malicious ones). But it ships broken user flows.

---

## R7 R1 unfixed P2 status (P2-1 through P2-7)

| ID | Title | Status | Recommendation |
|---|---|---|---|
| R1-P2-1 | `Config::default()` doesn't call `normalize_drive_mode` | NOT FIXED | **Accept**. `default_drive_sync_mode()` returns `"download"` which is already in the allowlist; the defensive call would be a no-op. Re-confirm dead-state to remove this item permanently. |
| R1-P2-2 | `clear_dedup_state` wipes `known_reqs` / `known_revision_requests` (likely dead fields) | NOT FIXED | **Accept**. `Grep` for `known_reqs|known_revision_requests` in `src/**/*.rs` finds only the `Config` definition (config.rs:47-49), the `clear_dedup_state` body, and the legacy Python migration path. No reader in the Rust client. Wiping is correct-by-default for any future feature that adopts them; deletion would require schema migration so leaving in place is cheaper. |
| R1-P2-3 | `commands/sync.rs::trigger_drive_sync` misleading `drop(cfg)` | NOT FIXED | **Cheap win — fix**. `state.read()` returns owned `Config`, not a guard. Either delete the `drop(cfg)` (the cfg goes out of scope at end-of-scope anyway) or replace with a comment matching `submitter.rs::owned_state`. Hygiene. |
| R1-P2-4 | `sse.rs` stop signal is busy-polled AND the sender is leaked | NOT FIXED | **Accept** (or delete dead code). `Box::leak(Box::new(_sse_stop))` at `lib.rs:69` means the sender is never dropped → `stop_rx.try_recv()` returns `Empty` forever → 250ms busy-loop runs for the entire app lifetime. CPU cost is negligible (4 wakeups/sec on a process that's already wired into 60s timers and SSE keepalive). Either rip out the stop machinery entirely or rewrite with `tokio::select!`. Code-cleanliness only. |
| R1-P2-5 | `delivery.rs::zip_dir` silently produces empty zip | NOT FIXED | **Fix recommended (cheap)**. `zip_dir` returns `Result<usize>` already; `start_delivery` discards the count. Add `if count == 0 { return Err(Other("no files to deliver".into())) }` before the upload. ~3 lines. |
| R1-P2-6 | `spec_watch.rs` canonicalizes on every event | NOT FIXED | **Fix recommended (cheap)**. Hoist the `folder_for_handler.canonicalize()` to once-per-watcher (line 70 area, before constructing the closure). Stash the canonical path in a `let` and capture it into the closure. ~5 lines. |
| R1-P2-7 | `tauri.conf.json` `connect-src http://*:*` etc. | NOT FIXED | **Accept with documentation**. The R6 review chain already decided this is acceptable for a LAN-only client where the server URL is user-configurable at runtime. CSP cannot do CIDR. The only correct alternatives are (a) regenerate CSP at install time from the configured server URL (requires installer plumbing), or (b) accept the LAN-trust assumption. Add a single-line comment in tauri.conf.json explaining the trade-off so the next reviewer doesn't waste cycles. |

---

## New findings

### P2-NEW-1 — `set_config` does not normalize whitespace / case on identity fields, so `identity_changed` fires spuriously

- Location: `client-tauri/src-tauri/src/commands/config.rs:19-23`
- The comparison `v != cfg.nickname` is byte-exact. If JS sends `" mycyg"` (leading space from a paste) the check fires `identity_changed=true`, dedup state is wiped, and on next reminder poll the user gets re-toasted for items they already saw.
- Impact: low, requires unlucky paste from the user. Recommend `v.trim() != cfg.nickname.trim()` (or normalize on write).

### P2-NEW-2 — `Config::is_complete` checks `cookie_token` which `set_config` does NOT include in `identity_changed`

- Location: `client-tauri/src-tauri/src/config.rs:153` vs `commands/config.rs:19-23`
- `is_complete` requires nickname + cookie_token + client_token. `identity_changed` checks nickname + server_ip + server_url + client_token, but NOT `cookie_token`. A backend session rotation that delivers a fresh cookie_token via `set_config({cookie_token: ...})` is treated as a non-identity change — dedup state survives. In practice this is fine because the backend rarely rotates cookies without also rotating the client_token, but worth aligning the two sets.

### P2-NEW-3 — `commands/auth.rs::me` 401-vs-other branch can lose a freshly-arrived dedup-reset event

- Location: `commands/auth.rs:31-52`
- Not actually a bug; the 401 vs success branch is correct (good catch in the R6 hardening). But I noticed `me()` is called on every App.tsx mount. If the user has switched servers via Settings (`set_config({server_url})`), the in-memory `CLIENT_CELL` reqwest Client is shared and still holds the OLD server's cookie jar. `me()` will hit the new server but send the old cookie, get 401, App.tsx will route to onboarding, and then onboarding flow will write a new cookie. End state is correct, but `http::refresh` (which exists at `http.rs:34` but is marked `#[allow(dead_code)]`) was specifically designed for this case and is never called. Adding `http::refresh(&state)` to the `set_config` identity-change path would clear the stale cookie jar proactively. Optional polish.

### P2-NEW-4 — `delivery.rs::zip_dir` `canonicalize` of `src` requires `src` to exist with read permission

- Location: `client-tauri/src-tauri/src/delivery.rs:76`
- `start_delivery` accepts a user-chosen `folder: PathBuf`. If the user selects a folder via the dialog and then it disappears (USB drive unplugged) between dialog and call, `src.canonicalize()` returns Err and the error string is "io error: …" — the user has no idea their USB drive was the culprit. Wrap with a context message: `.map_err(|e| Error::Other(format!("delivery source unreadable: {e}")))?`.

### P2-NEW-5 — `reminders.rs::prune_seen_map` sorts by timestamp-string equality which is NOT a stable LRU under tied timestamps

- Location: `client-tauri/src-tauri/src/reminders.rs:138-145`
- Two reminders observed at the exact same RFC3339 second (cheap chrono::Utc::now() resolution is microsecond, so collisions are rare but possible with retries) get sorted in arbitrary key-order. Under heavy churn the pruner could evict newer-but-tied entries before older ones. Functional impact: zero (any pruned entry just gets re-toasted once and re-dedupped on next poll). Code-cleanliness: use a tuple `(timestamp, key)` sort to be deterministic.

### P2-NEW-6 — `tray.rs::set_drive_mode("off", false)` does NOT clear `drive_sync_paused`

- Location: `client-tauri/src-tauri/src/tray.rs:115-122`
- If user pauses sync, then sets mode to Off, then later re-enables Download mode, the `drive_sync_paused = true` from the earlier action survives. The next download cycle is no-op'd by the `paused` check in `trigger_drive_sync` (sync.rs:28). User sees "sync should be on" but nothing happens. Workaround: hit the pause-toggle again. Recommendation: reset `drive_sync_paused = false` whenever `drive_sync_mode` transitions from `"off"` → anything, OR when explicitly entering `"download"` mode. ~2 lines.

### P2-NEW-7 — `commands/submitter.rs::open_spec_folder` double-calls `ensure_dir_inside_root`

- Location: `commands/submitter.rs:484-486`
- The pattern `ensure_dir_inside_root(...)?; std::fs::create_dir_all(...)?; ensure_dir_inside_root(...)?;` is defensive but the FIRST call creates the dir if missing (line 281 in sync.rs), so the second `create_dir_all` is redundant and the second `ensure_dir_inside_root` re-validates a path that we just verified. Same pattern at `download_delivery` (lines 525-527). Cosmetic; the TOCTOU window is genuine in principle but a local symlink attack would require the attacker to win between two `canonicalize` calls in the same process which is realistically uninteresting on a desktop client.

---

## Coverage

| File | Status | Notes |
|---|---|---|
| `config.rs` | reviewed | R7 + R7.1 changes intact; no new regressions |
| `commands/config.rs` | reviewed | `identity_changed` whitespace-sensitive (P2-NEW-1) |
| `commands/auth.rs` | reviewed | R7.1 `clear_dedup_state` correct |
| `commands/shell.rs` | reviewed | **P1-NEW-1 verbatim-prefix canonicalize regression** |
| `commands/submitter.rs` | reviewed | call-site update to open_folder correct; double-validate pattern (P2-NEW-7) |
| `commands/sync.rs` | reviewed | `two_way` hard-fail safety net retained; R1-P2-3 unfixed |
| `commands/requirements.rs` | reviewed | thin wrappers, OK |
| `commands/workspace.rs` | reviewed | thin wrappers, OK |
| `commands/delivery.rs` | reviewed | thin wrapper, OK |
| `commands/mod.rs` | reviewed | OK |
| `reminders.rs` | reviewed | empty-id skip + prune correct; P2-NEW-5 cosmetic |
| `sync.rs` | reviewed | path hardening intact; `ensure_parent_inside_root` is the correct template for fixing P1-NEW-1 |
| `delivery.rs` | reviewed | canonicalize symmetry intact; R1-P2-5 unfixed; P2-NEW-4 |
| `spec_watch.rs` | reviewed | per-event canonicalize unfixed (R1-P2-6) |
| `http.rs` | reviewed | double-checked lock correct; `refresh` dead-code (P2-NEW-3) |
| `sse.rs` | reviewed | byte-buffer UTF-8 safety intact; R1-P2-4 unfixed |
| `tray.rs` | reviewed | `set_drive_mode` doesn't clear paused (P2-NEW-6) |
| `notify.rs` | reviewed | trivial wrapper, OK |
| `deep_link.rs` | reviewed | whitelist + `..`/`.`/empty filter present, OK |
| `error.rs` | reviewed | thiserror variants comprehensive, OK |
| `upload.rs` | reviewed | `read_exact` correct, chunked upload OK |
| `window.rs` | reviewed | platform cfg correct, OK |
| `lib.rs` | reviewed | shared ConfigState plumbing OK; intentional Box::leak of sse_stop |
| `main.rs` | reviewed | trivial entry, OK |
| `Cargo.toml` | reviewed | no devtools feature in release; no `dunce` (relevant for P1-NEW-1 fix) |
| `capabilities/default.json` | reviewed | minimal surface; no shell:allow-open / process:* / devtools toggle |
| `tauri.conf.json` | reviewed | wide connect-src unfixed (R1-P2-7); document the LAN-trust decision |
| `web-src/src/routes/TaskDetail.tsx` | reviewed | caller of open_folder; affected by P1-NEW-1 |
| `web-src/src/components/ActionRailDispatch.tsx` | reviewed | caller of open_folder; affected by P1-NEW-1 |

---

## Summary

R7.1 delivers what it promised: `register_device` no longer leaks dedup rows across device-token rotations, and `open_folder` is no longer an unbounded `Command::spawn`. The R7.1 `open_folder` design has the right shape but the canonicalize-fallback is asymmetric on Windows when target doesn't exist — and that case is the primary user flow.

**Recommend one R7.2 commit addressing:**

1. **MUST fix** P1-NEW-1 — copy the walk-up-to-existing-ancestor pattern from `sync.rs::ensure_parent_inside_root`, or add a `dunce::simplified` normalization. Without this, "open local folder" is broken on Windows for any not-yet-synced task.

2. **CHEAP wins** R1-P2-3 (`drop(cfg)` cleanup), R1-P2-5 (empty-zip rejection), R1-P2-6 (hoist canonicalize), P2-NEW-1 (trim nickname), P2-NEW-6 (clear paused on mode transition).

3. **DOCUMENT and accept** R1-P2-1, R1-P2-2, R1-P2-4, R1-P2-7, P2-NEW-3, P2-NEW-4, P2-NEW-5, P2-NEW-7 — all are either no-op-today or hygiene-only.

After P1-NEW-1 is fixed, the Rust client surface is ready to compound CLEAN rounds.

---

## File reference (absolute paths)

- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\shell.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\auth.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\submitter.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\config.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\sync.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\config.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\reminders.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\http.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\sse.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\delivery.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\spec_watch.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\sync.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\tray.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\lib.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\tauri.conf.json`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\routes\TaskDetail.tsx`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\components\ActionRailDispatch.tsx`
