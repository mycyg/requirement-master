# R7 Round 3 — Rust client

Reviewer: architecture-strategist (read-only, fresh-eyes pass)
HEAD: `d50bf12 R7.2: address R7 Round 2 multi-agent review findings`
Scope: every `client-tauri/src-tauri/src/**.rs` + `Cargo.toml` + `Cargo.lock` + `capabilities/default.json` + `tauri.conf.json` + the two JS callers of `open_folder`, with extra focus on `canonicalize_with_existing_ancestor` edge cases.

## Verdict

**NEEDS NOTHING — 0 P0, 0 P1.** R7.2 closes R2's P1 cleanly and the new `canonicalize_with_existing_ancestor` helper survives a thorough edge-case audit. No new P1/P0. Three P3-grade hygiene items remain (one is brand-new code-debt from R7.2, two are persisted from prior rounds). All R1/R2 P2s remain at P2 — none have been reclassified P1.

Round 3 → CLEAN modulo cosmetics. Recommend marking this rotation closed and starting the 4-consecutive-CLEAN clock at Round 3.

---

## R7.2 fix verification

### `canonicalize_with_existing_ancestor` — CORRECT under all edge cases I could construct

The helper is at `client-tauri/src-tauri/src/commands/shell.rs:66-90`. It is called once for the target (line 92) and once per root in the `roots.iter().any(...)` predicate (line 95).

**Edge-case audit (every case fails closed when it cannot succeed):**

| Case | Behaviour | Verdict |
|---|---|---|
| Target = `D:\工作需求\proj\REQ-1`, only `D:\工作需求` exists | Pops twice, canonicalizes `D:\工作需求` → `\\?\D:\工作需求`, re-appends `proj/REQ-1` tail → `\\?\D:\工作需求\proj\REQ-1`. Root canon = `\\?\D:\工作需求`. `starts_with` ✓ | CORRECT (this is the primary R2 regression and is now fixed) |
| Target = `D:\` (drive root, exists) | `canonicalize("D:\\")` succeeds → `\\?\D:\`. tail empty. Returns `\\?\D:\` | CORRECT |
| Target = `""` (empty) | Guarded upstream by `trimmed.is_empty()` check at line 26 | N/A — never reached |
| Target = `Z:\nonexistent` where `Z:` drive does not exist | Pops to `Z:\` → canon fails → `pop()` on `Z:\` returns false AND `file_name()` of `Z:\` is None → falls into "ran off the top" → returns raw `Z:\nonexistent`. Root canon will not match → REJECT | CORRECT (fails closed) |
| Target = `\\server\share\nonexistent` (UNC, server reachable) | UNC root `\\server\share` canonicalizes to verbatim UNC `\\?\UNC\server\share`. tail appended. Matches root iff root canonicalizes to same UNC prefix | CORRECT |
| Target lives under a symlinked root | Both target's walked-up ancestor AND root canonicalize THROUGH the symlink → same resolved prefix → `starts_with` ✓ | CORRECT (this is also a feature) |
| Path component case differs from on-disk case | Windows `canonicalize` is case-insensitive but returns on-disk case; comparison uses `Path::starts_with` which is component-based → mixed cases in the not-yet-existing tail are tolerated by `starts_with` (it compares the canonical prefix only) | CORRECT |
| Race: directory created during walk-up | canonicalize succeeds earlier than expected, fewer tail segments appended. Final path is still canonical | CORRECT (TOCTOU-benign) |
| Path with `..` segment | Rejected upstream by `Component::ParentDir` check (line 41) | N/A — never reached |
| Relative path `foo` | Pops to `""`, file_name None, returns raw `foo`. Root canon is absolute. `starts_with` → false → REJECT | CORRECT (fails closed) |
| Path with permission-denied intermediate | canonicalize fails (perm), pops past it, canonicalizes parent. Treats perm-denied dir as if non-existent. Final path passed to `explorer.exe` will then fail at the OS level. No security escape (root containment still enforced via the canonicalized ancestor) | ACCEPTABLE |
| Both target and root non-existent (typo'd `cfg.sync_root` AND mismatched target) | Both walk up, both either reach the same drive root or both fall through to raw. If both fall through, byte-identical raw strings → `starts_with` true (harmless because `explorer.exe` then fails). If only one falls through → mismatch → REJECT | ACCEPTABLE |

**The `if !existing.pop() || file_name.is_none()` guard** at line 80 is the correct termination condition:
- `existing.pop()` is called once and mutates `existing` — both sides are evaluated even if pop returns true (Rust short-circuits `||` but `pop` is the first operand so always runs).
- `file_name` is captured BEFORE pop, so it reflects the segment we just popped.
- The guard is "if there was nothing to pop, OR there was no name to remember, give up". Both clauses are individually sufficient; together they're defensive but correct.

**Subtle correctness check on tail re-application:** the loop pushes `file_name` (a `OsString` containing no separators) onto `tail` per iteration. When we re-apply via `out.push(seg)`, each seg is a simple component name — `PathBuf::push` of a relative segment correctly appends without replacing the existing path. **No risk of absolute-path replacement** because `file_name()` cannot return a name with a prefix or root.

### Wiring verification

- Helper is defined inline inside `open_folder` (lines 66-90). Not exposed elsewhere, no other call sites. Scope is correct.
- Called for target at line 92 and for each root at line 95. Both use the SAME function so prefix-form symmetry is guaranteed.
- The R2 P1-NEW-1 verbatim-prefix mismatch is fully resolved.

### Call-site impact verification

- `web-src/src/routes/TaskDetail.tsx:124-126` `openLocal` — calls `open_folder` with a path that may not yet exist. R7.2 fix makes this work. ✓
- `web-src/src/components/ActionRailDispatch.tsx:115-124` `openDeliveryFolder` — same pattern. R7.2 fix makes this work. ✓
- `commands/submitter.rs:484-488` `open_spec_folder` — `create_dir_all` is called before `open_folder`, so the target always exists at call time. R7.2 fix is a no-op for this path (and was already working). ✓

**Conclusion:** R7.2 is correct and complete for what it set out to do.

---

## Prior unfixed P2 status

| ID | Title | Status | Re-assessment |
|---|---|---|---|
| R1-P2-1 | `Config::default()` doesn't call `normalize_drive_mode` | NOT FIXED | **Accept (P3)**. Defaults produce `"download"` which is in the allowlist. Dead defensive call. |
| R1-P2-2 | `clear_dedup_state` wipes likely-dead `known_reqs` / `known_revision_requests` | NOT FIXED | **Accept (P3)**. No reader; preserving the wipe is correct-by-default. |
| R1-P2-3 | `commands/sync.rs::trigger_drive_sync` misleading `drop(cfg)` | NOT FIXED | **Accept (P3)** — same pattern appears now ALSO in `commands/shell.rs:56` (new code in R7.1, persisted in R7.2). Single comment fix or wholesale delete; pure hygiene. |
| R1-P2-4 | `sse.rs` stop signal busy-poll + leaked sender | NOT FIXED | **Accept (P3)**. Dead-code path; 4 wakeups/sec is negligible. |
| R1-P2-5 | `delivery.rs::zip_dir` silently produces empty zip | NOT FIXED | **Cheap fix recommended (P2)**. `zip_dir` already returns `Result<usize>`; caller discards the count. ~3 lines to reject empty. |
| R1-P2-6 | `spec_watch.rs` canonicalizes folder on every event | NOT FIXED | **Cheap fix recommended (P2)**. Hoist `folder_for_handler.canonicalize()` once outside the closure. ~5 lines. |
| R1-P2-7 | `tauri.conf.json` `connect-src http://*:*` etc. | NOT FIXED | **Accept (P3)** with the documented LAN-trust rationale. |
| R2-P2-NEW-1 | `set_config` whitespace-sensitive identity check | NOT FIXED | **Accept (P3)**. Trivial to fix but unlikely in practice. |
| R2-P2-NEW-2 | `cookie_token` not in `identity_changed` | NOT FIXED | **Accept (P3)**. Backend rotates cookie + client_token together; misalignment is theoretical. |
| R2-P2-NEW-3 | `me()` may hit new server with stale cookie | NOT FIXED | **Accept (P3)**. Recovery path works (re-onboarding); `http::refresh` exists for the manual-clean-state case if needed. |
| R2-P2-NEW-4 | `delivery.rs::zip_dir` canon failure unclear error | NOT FIXED | **Accept (P3)**. Triggered only by USB-disconnect mid-call. Cosmetic. |
| R2-P2-NEW-5 | `prune_seen_map` non-deterministic tie-break | NOT FIXED | **Accept (P3)**. Functional impact zero. |
| R2-P2-NEW-6 | `set_drive_mode("off")` doesn't clear `drive_sync_paused` | NOT FIXED | **P2 still** — user-visible footgun: pause + off + back-to-download leaves stuck-paused. Worth a 2-line fix in tray.rs. |
| R2-P2-NEW-7 | `open_spec_folder` double-validates | NOT FIXED | **Accept (P3)**. Defensive over redundant. |

**Net change vs R2:** zero items reclassified up; none reclassified down. R2-P2-NEW-6 (tray paused-state) is the highest-impact hygiene item still outstanding. R1-P2-5 (empty zip rejection) and R1-P2-6 (canonicalize hoist) remain the cheapest wins.

---

## New findings

### P2-NEW-1 — `commands/shell.rs::open_folder` carries the same misleading `drop(cfg)` pattern as `trigger_drive_sync`

- Location: `client-tauri/src-tauri/src/commands/shell.rs:45-56`
- `state.read()` returns an owned `Config` clone (see `ConfigState::read` at `config.rs:289`), not a `MutexGuard`. The `drop(cfg)` at line 56 is a no-op — the clone goes out of scope at the end of the function anyway, and no lock is being released.
- This is the same pattern flagged in R1-P2-3 for `commands/sync.rs:34`. R7.1 introduced new code that replicates it.
- Impact: zero functional cost. Code-reader misleading. Future maintainer might think there's lock contention here when there isn't.
- Fix: delete `let cfg = ... drop(cfg);` and inline-shadow with let bindings, OR add a comment `// `cfg` is an owned clone, not a guard — drop is for readability only` to match the doc on `owned_state` at `submitter.rs:34`.

### P3-NEW-1 — `commands/shell.rs:118` `let _ = Path::new("");` is now dead defensive code

- Location: `client-tauri/src-tauri/src/commands/shell.rs:118`
- Comment claims "suppress unused-import warning when only one cfg branch compiles". But the R7.1+R7.2 changes added `fn canonicalize_with_existing_ancestor(p: &Path)` which uses `Path` directly (line 66). So `Path` is unconditionally referenced and the suppressant is unnecessary on any target.
- Impact: zero. Cosmetic.
- Fix: delete the line and its comment.

### P3-NEW-2 — `tauri-plugin-autostart` is declared in Cargo.toml but never used in Rust source

- Location: `client-tauri/src-tauri/Cargo.toml:23`
- Grep for `autostart` in `src/` returns no matches. Not initialized in `lib.rs`'s `Builder`. No JS-side `@tauri-apps/plugin-autostart` import either (would need verification at frontend level but the Rust side never wires it).
- Impact: ~few hundred KB of binary bloat from the unused plugin's compiled code + permission scaffolding. No runtime cost.
- Fix: remove the dependency line OR wire the plugin and expose start-on-boot toggle in Settings. Decision is product-level, not architectural.

### P3-NEW-3 — `lib.rs` `Box::leak(Box::new(_sse_stop))` is permanent-leak by design, but doc only on line 68

- Location: `client-tauri/src-tauri/src/lib.rs:69`
- Confirms R1-P2-4 finding: the SSE stop signal is intentionally leaked because there is no "shutdown SSE without killing the process" path today. The single-line comment at line 68 mentions keeping the handle alive but doesn't note that the leak makes the entire `stop_rx.try_recv()` busy-loop in `sse.rs:50-56` dead code.
- Impact: zero. Just hygiene.
- Fix: either rip out the stop machinery (mark `spawn` to return `()` instead of `Sender`) or document at both the leak site AND the receiver site that "stop is unreachable; busy-poll is harmless".

---

## Coverage

| File | Status | Notes |
|---|---|---|
| `commands/shell.rs` | reviewed (focus) | R7.2 helper correct; P2-NEW-1 (drop cfg), P3-NEW-1 (dead suppressant) |
| `commands/submitter.rs` | reviewed | `open_spec_folder` unaffected by R7.2 (always pre-creates); call-site OK |
| `commands/auth.rs` | reviewed | R7.1 fix intact; no changes |
| `commands/config.rs` | reviewed | `identity_changed` + `clear_dedup_state` intact |
| `commands/sync.rs` | reviewed | R1-P2-3 still present |
| `commands/requirements.rs` | reviewed | thin wrappers, OK |
| `commands/workspace.rs` | reviewed | thin wrappers, OK |
| `commands/delivery.rs` | reviewed | thin wrapper, OK |
| `commands/mod.rs` | reviewed | OK |
| `config.rs` | reviewed | All R7/R7.1 hardening intact |
| `reminders.rs` | reviewed | dedup + skip-empty-id correct |
| `sync.rs` | reviewed | path hardening intact (`ensure_parent_inside_root` is the template that R7.2 helper mimics in spirit) |
| `delivery.rs` | reviewed | canonicalize-symlink-skip intact; R1-P2-5 still open |
| `spec_watch.rs` | reviewed | per-event canonicalize still present (R1-P2-6) |
| `http.rs` | reviewed | double-checked lock + cookie-jar singleton intact; `refresh` still dead-code |
| `sse.rs` | reviewed | UTF-8 byte-buffer correct; stop machinery still dead (P3-NEW-3) |
| `tray.rs` | reviewed | `set_drive_mode("off")` still doesn't clear `paused` (R2-P2-NEW-6) |
| `notify.rs` | reviewed | trivial wrapper, OK |
| `deep_link.rs` | reviewed | whitelist + traversal filter intact |
| `error.rs` | reviewed | thiserror variants OK |
| `upload.rs` | reviewed | `read_exact` chunked upload correct |
| `window.rs` | reviewed | platform cfg correct |
| `lib.rs` | reviewed | plugin init order OK; intentional `Box::leak` on sse_stop |
| `main.rs` | reviewed | trivial entry, OK |
| `Cargo.toml` | reviewed | `tauri-plugin-autostart` declared but unused (P3-NEW-2) |
| `Cargo.lock` | reviewed | tauri 2.11.2, reqwest 0.12.28 + 0.13.4 (transitive via tauri), tokio 1.52.3, chrono 0.4.44, openssl 0.10.80 — all recent and patched |
| `capabilities/default.json` | reviewed | minimal surface; no shell:allow-open, process:*, devtools toggle |
| `tauri.conf.json` | reviewed | CSP wide `connect-src` accepted per R6 decision (R1-P2-7) |
| `web-src/src/routes/TaskDetail.tsx` | reviewed | `openLocal` works with R7.2 fix |
| `web-src/src/components/ActionRailDispatch.tsx` | reviewed | `openDeliveryFolder` works with R7.2 fix |

---

## Summary

R7.2 lands cleanly: `canonicalize_with_existing_ancestor` survives every edge case I could construct (drive roots, UNC, missing drives, symlinked ancestors, permission-denied intermediate, relative paths, race-during-walk, case mismatches). The two JS callers that motivated the fix — `TaskDetail.openLocal` and `ActionRailDispatch.openDeliveryFolder` — work correctly under the new logic. No new P0/P1.

Three brand-new P3-grade hygiene items surfaced (`drop(cfg)` in shell.rs, dead `Path::new("")` suppressant, `tauri-plugin-autostart` unused dep), all cosmetic. The Round 1 and Round 2 P2 backlog is unchanged: zero items have escalated to P1 in light of R7.2. The two highest-value cheap-fixes remain R2-P2-NEW-6 (tray paused-state clear) and R1-P2-5 (empty-zip reject).

**Recommendation:** declare R7.2 the start of the 4-consecutive-CLEAN clock for the Rust client surface. The remaining P2/P3 items can be batched into a single hygiene commit at any time without blocking the clock.

---

## File reference (absolute paths)

- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\shell.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\submitter.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\sync.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\auth.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\config.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\config.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\reminders.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\http.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\sse.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\sync.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\delivery.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\spec_watch.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\tray.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\lib.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\Cargo.toml`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\Cargo.lock`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\capabilities\default.json`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\tauri.conf.json`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\routes\TaskDetail.tsx`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\components\ActionRailDispatch.tsx`
