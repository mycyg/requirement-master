# R7 Round 1 — Rust client review

Reviewer: architecture-strategist (read-only, zero-tolerance)
Scope: every `client-tauri/src-tauri/src/**.rs` + `Cargo.toml` + `capabilities/default.json` + `tauri.conf.json`
HEAD: `306edbd R7: revert Codex P0/P1 regressions`

## Verdict

**NEEDS FIXES — 0 P0, 2 P1, 7 P2.** No ship-blockers. The R7 fixes (`normalize_drive_mode`, `clear_dedup_state`, `identity_changed`, reminders empty-id skip) are all wired correctly and protect against the regressions they were targeted at. The remaining issues are dedup-state gaps and small hygiene items that should be addressed before deploy but do not block.

---

## R7 fix verification

### `config.rs::normalize_drive_mode` — CORRECT
- Coerces any value other than `"off" | "download"` to `"download"`. The whitelist (not blacklist) approach correctly handles future stale strings, not just `"two_way"`.
- Wired into every Config entry point I could find:
  - `load()` line 173 — legacy-config migration branch
  - `load()` line 193 — normal parse branch
  - `commands/config.rs::set_config` line 44 — after applying the patch
- NOT wired in `Config::default()` (line 84). Acceptable because defaults never produce `"two_way"`, but a defensive `normalize_drive_mode()` after recompute_url at line 107 would be cheap belt-and-suspenders.
- NOT called inside `ConfigState::from_disk()` directly — it's called via `load()`, which is correct (single source).
- Bypass-path check: is there any way to set `drive_sync_mode` without going through these gates?
  - `tray.rs::set_drive_mode` only writes `"off" | "download"` (lines 76, 77) — safe.
  - `commands/config.rs::set_config` applies the patch THEN calls `normalize_drive_mode`. So a malicious JS caller could pass `"two_way"`, but the normalize call immediately coerces it back. Good.
  - Direct `state.write(|cfg| cfg.drive_sync_mode = ...)` calls — none found other than tray.
- Verdict: **CORRECT**.

### `config.rs::clear_dedup_state` — CORRECT but with one gap
- Clears all four `known_*` maps to `{}`. Good.
- Wired in `commands/config.rs::set_config` line 46, gated on `identity_changed`.
- **Gap (P1-1 below)**: `commands/auth.rs::register_device` line 88 writes `cfg.client_token` directly via `state.write`, bypassing `set_config` entirely. On the re-onboarding path (cookie expired, same nickname, new token) the dedup state survives across identities. Onboarding.tsx happens to call `set_config({nickname})` first, but if nickname is identical, the identity-changed detector returns false and the subsequent token rotation in `register_device` writes without clearing.

### `commands/config.rs::set_config` `identity_changed` — CORRECT
- Detects new value vs current cfg BEFORE applying the patch — necessary so the comparison is meaningful.
- Checks four fields: `nickname`, `server_ip`, `server_url`, `client_token`.
- Uses `is_some_and(|v| v != cfg.nickname)` — fires only if the patch key is present AND value differs. Correct.
- Edge cases:
  - Setting `nickname` to empty string `""` when it was non-empty → fires. Correct (this is effectively a logout).
  - Setting `server_port` or `server_scheme` does NOT fire identity_changed, but those clauses force `server_url.clear()` (lines 26-27). The next patch that includes a `server_url` would fire identity_changed against the post-clear empty value, which is correct (new effective server).
  - Bypass: `tray.rs::set_availability`, `set_drive_mode`, `toggle_pause` all use `state.write` directly. None of these are identity fields, so this is fine.
- Verdict: **CORRECT** with the `register_device` gap noted above.

### `reminders.rs` empty-id skip — CORRECT
- Both `poll_reminders` (lines 42-47) and `poll_notifications` (lines 98-104) symmetrically `continue` on empty id with a clear rationale comment.
- The R7 diff also REMOVED the previous asymmetric write-side guard (`if !notification_id.is_empty()` → just always push) — correct, because the skip is now on the read side.
- Re-notify-loop check: with empty id skipped before the toast/emit, no notification fires and no dedup row is added. Next 60s tick sees the same item again, skips again. Zero toasts, zero state. **Protected.**
- Verdict: **CORRECT and symmetric.**

---

## P0 findings

**None.** All four R7-targeted regressions are correctly fixed.

---

## P1 findings

### P1-1 — `register_device` bypasses `clear_dedup_state`
- Location: `client-tauri/src-tauri/src/commands/auth.rs:88`
- Flow: `register_device` is called from `Onboarding.tsx:69` AFTER `set_config({nickname})`. If the user re-onboards with the SAME nickname (e.g. cookie expired, fresh re-register, same identity), `set_config`'s `identity_changed` returns false (nickname unchanged), then `register_device` writes a new `client_token` via raw `state.write` — skipping `clear_dedup_state`.
- Impact: dedup rows from the previous device-token survive the rotation. Practical effect is low because most dedup keys are tied to per-server data (`requirement_id:due_at`); they'd just be ignored if the new token sees different items. But on the same server with the same nickname, today's already-toasted reminders are silently suppressed until the dedup is rotated out by the 500/1000-entry cap.
- Fix: change `register_device` to either go through `set_config` patch shape, or call `cfg.clear_dedup_state()` alongside the `client_token` write. One-line change:
  ```rust
  state.write(|cfg| {
      cfg.client_token = token.clone();
      cfg.clear_dedup_state();  // device rotation = identity change
  })?;
  ```

### P1-2 — `lib.rs` background workers never see `clear_dedup_state` mid-poll
- Location: `client-tauri/src-tauri/src/reminders.rs:36, 92` and `lib.rs:67-70`
- The `reminders::spawn` task holds a `ConfigState` clone (cheap Arc-bump) so it correctly sees any `cfg.known_reminders` write via `state.write`. **However**, between the `state.read().known_reminders` snapshot (line 36) and the subsequent processing of the array, another task COULD call `clear_dedup_state` via `set_config`. The current poll would then re-add the cleared rows on its post-loop `state.write` (line 74-81: builds map from `cfg.known_reminders.as_object()` AT WRITE TIME, then merges `new_seen`).
- Verdict: actually NOT a bug — the merge correctly uses the CURRENT cfg state inside the closure, not the snapshot. So if a clear happened during the poll, the merge happens against the cleared (empty) map plus only the truly-new keys from this tick. That's the desired behavior (any item that was previously toasted and is still in the API response will be re-toasted exactly once, then dedupped).
- BUT: there's a subtle window — between line 36's `state.read()` and the loop, items could be re-checked against pre-clear dedup, suppressing what should be re-toasted. Single 60s tick lag, recovers next tick. Acceptable.
- Action: no fix needed; document the recovery latency in a comment.

---

## P2 findings

### P2-1 — `Config::default()` doesn't call `normalize_drive_mode`
- Location: `client-tauri/src-tauri/src/config.rs:84-110`
- Defaults always produce `"download"`, so no actual bug today. But if `default_drive_sync_mode()` ever changes or someone adds a non-default-produced state, the invariant breaks silently. One-line `c.normalize_drive_mode();` after `c.recompute_url();` (line 107) closes this without runtime cost.

### P2-2 — `clear_dedup_state` also wipes `known_reqs` / `known_revision_requests`
- Location: `client-tauri/src-tauri/src/config.rs:135-140`
- These two maps are written by code I cannot find in this review (no `.known_reqs` / `.known_revision_requests` mutation anywhere in the current Rust src). Likely legacy state from the Python client or reserved for future. Wiping them on identity change is correct *if* they're identity-scoped, which they should be by name. Add a code comment confirming the intent. If they truly are dead, drop the fields from `Config`.

### P2-3 — `commands/sync.rs::trigger_drive_sync` `drop(cfg)` is misleading
- Location: `commands/sync.rs:34`
- `state.inner().read()` returns an owned `Config` clone, not a `MutexGuard`, so `drop(cfg)` is a no-op. Same observation as Codex round. Comment exists in `submitter.rs::owned_state` explaining the clone semantics — propagate that wisdom here, or just delete the `drop`.

### P2-4 — `sse.rs` stop signal uses busy-poll instead of `select!`
- Location: `client-tauri/src-tauri/src/sse.rs:49-56`
- The outer task `try_recv()`s `stop_rx` every 250ms forever. Idiomatic tokio would `tokio::select!` between the stop_rx and a join_all of the child handles. Current code wastes CPU wakeups (negligible) and never actually receives the stop signal because `_sse_stop` is leaked in `lib.rs:69` and the sender never fires.
- Verdict: the leak means stop is permanently unreachable; the busy-poll is harmless but should be `select!{ _ = &mut stop_rx => ... }` for clarity. Or just delete the stop machinery since it's never used.

### P2-5 — `delivery.rs::zip_dir` silently produces empty zip on no input
- Location: `client-tauri/src-tauri/src/delivery.rs:75-85`
- If `src` has no files (all excluded, all symlinks, all unreadable), the zip is created and finalized with zero entries. The caller `start_delivery` then uploads the empty zip and the backend accepts it. Worth surfacing `count == 0` as an error before upload so the user gets a clear "no files to deliver" toast instead of a silent success.

### P2-6 — `spec_watch.rs` filter canonicalizes on every event
- Location: `client-tauri/src-tauri/src/spec_watch.rs:88-94`
- The closure calls `folder_for_handler.canonicalize()` inside the per-event filter, ON EVERY EVENT. For a chatty editor (vim atomic-save fires 4-5 events per save) this is wasteful. Hoist the canonicalize once outside the filter and reuse.

### P2-7 — `tauri.conf.json` `connect-src` still allows `http://*:*` / `https://*:*` / `ws://*:*`
- Location: `client-tauri/src-tauri/tauri.conf.json:31`
- Same finding as Codex review P1-6. For a LAN-only client this is a defense-in-depth opportunity. Since CSP cannot do CIDR, the cleanest fix is template-substitute the configured server origin into the CSP at build/install time, or accept the LAN trust assumption and leave it. Document the decision.

---

## Coverage

| File | Status | Notes |
|---|---|---|
| `config.rs` | reviewed | R7 changes correct; P2-1 / P2-2 minor |
| `commands/config.rs` | reviewed | `identity_changed` correct; ok |
| `reminders.rs` | reviewed | empty-id skip symmetric; correct |
| `commands/auth.rs` | reviewed | P1-1: `register_device` bypasses dedup clear |
| `commands/sync.rs` | reviewed | `two_way` hard-fail still present (P0-5 dead path safety net); P2-3 |
| `commands/submitter.rs` | reviewed | path hardening intact; OK |
| `commands/delivery.rs` | reviewed | thin wrapper, OK |
| `commands/requirements.rs` | reviewed | thin pass-through, no `.unwrap` on Results |
| `commands/workspace.rs` | reviewed | thin pass-through, OK |
| `commands/shell.rs` | reviewed | spawn().ok() swallows errors but no user input flows in |
| `commands/mod.rs` | reviewed | OK |
| `sync.rs` | reviewed | path hardening intact; `safe_relative_path` Windows reserved-name concern noted in Codex review still present, see P1-4 there |
| `delivery.rs` | reviewed | canonicalize + symlink skip intact; P2-5 |
| `spec_watch.rs` | reviewed | canonicalize filter present; P2-6 |
| `http.rs` | reviewed | double-checked lock correct; cookie jar singleton; OK |
| `sse.rs` | reviewed | byte-buffer UTF-8 safety intact; P2-4 |
| `tray.rs` | reviewed | `two_way` removal complete; menu state mirrors config; OK |
| `notify.rs` | reviewed | trivial wrapper; OK |
| `deep_link.rs` | reviewed | whitelist + `..`/`.`/empty filter present; OK |
| `error.rs` | reviewed | variants comprehensive; thiserror derive correct; OK |
| `upload.rs` | reviewed | `read_exact` correct; OK |
| `window.rs` | reviewed | platform cfg correct; OK |
| `lib.rs` | reviewed | plugin init order, single-instance, deep-link wired; `Box::leak` of sse_stop is intentional dead-code (see P2-4) |
| `main.rs` | reviewed | trivial entry; OK |
| `Cargo.toml` | reviewed | no devtools feature in release builds; OK |
| `capabilities/default.json` | reviewed | minimal surface; no `shell:allow-open`, `process:*`, devtools toggle; OK |
| `tauri.conf.json` | reviewed | CSP installed; bundle.targets `["nsis"]` only (consistent with macOS workflow having been deferred); P2-7 |

---

## Summary

R7 lands clean for what it set out to do — the three new helpers (`normalize_drive_mode`, `clear_dedup_state`, `identity_changed`) are correctly wired and cover the documented failure modes. The one gap worth fixing before deploy is the `register_device` bypass of `clear_dedup_state` (P1-1, one-line fix). Everything else is hygiene.

Recommend one quick follow-up commit addressing P1-1 (mandatory) and P2-1, P2-3, P2-6 (cheap wins), then this file is clean for Round 2.

## File reference (absolute paths)

- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\config.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\reminders.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\config.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\auth.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\sync.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\sse.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\delivery.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\spec_watch.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\lib.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\tauri.conf.json`
