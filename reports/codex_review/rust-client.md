# Codex Rust Client + Tauri Config Review

Reviewer: Architecture-strategist agent
Reviewed range: `c884b60..main` (4 Codex commits on top of v0.3.0 baseline)
Files in scope: 8 Rust sources + Cargo.toml/Cargo.lock + 2 Tauri config files + 2 install scripts + BUILD.md.
Review style: read-only, merciless, zero-tolerance for regressions of the v0.3.0 hardening.

## Summary

Codex did NOT regress the v0.3.0 hardening — `ConfigState`'s `Arc<Mutex<Config>>`, atomic `.tmp + rename` save, `config.recover-{ts}.json` IO-failure backup, streaming `bytes_stream` downloads, and the `delivery.rs` `strip_prefix` warn-skip are all intact. On top of that, Codex added genuinely strong improvements: per-component path-traversal hardening (`safe_component` / `safe_relative_path` / `ensure_*_inside_root` with full canonicalization), origin-pinned URL resolution that refuses off-server downloads, end-to-end streaming SHA256 verification with `.download` tmp + atomic rename, symlink-refusal on delivery-zip overwrite, and a tighter Tauri capability surface (devtools/shell:allow-open/process:default removed, real CSP installed).

Net direction is "harden further, not weaken." However, the changes introduce one **P0 UX/correctness regression** (the `two_way` drive-sync mode is half-removed — backend rejects it, but Onboarding/Settings UI still let users pick it, leaving the user in an error loop), one **P1 dedup edge case** in `reminders.rs` for items with empty `id`, and a handful of small concerns around `with_extension` semantics, the broader-than-needed CSP `connect-src`, and dead-code drift between the tray and the JS settings page.

---

## P0 — Regressions or critical bugs

### P0-1 — `two_way` drive sync half-removed creates user-facing dead-end
Codex removed the `two_way` menu item from the tray and made `commands::sync::trigger_drive_sync` HARD-FAIL when `drive_sync_mode == "two_way"`:

- `client-tauri/src-tauri/src/tray.rs:31` — `drive_two_way` `MenuItemBuilder` line was deleted.
- `client-tauri/src-tauri/src/tray.rs:78` — the `"drive_two_way" => set_drive_mode(...)` match arm was deleted.
- `client-tauri/src-tauri/src/commands/sync.rs:30-33` — new guard:
  ```rust
  if cfg.drive_sync_mode == "two_way" {
      return Err(Error::Other("two-way drive sync is not available in this build; use download-only mode".into()));
  }
  ```

But the React UI still offers `"two_way"` as a button:
- `client-tauri/web-src/src/routes/Onboarding.tsx:25` — `useState<"off" | "download" | "two_way">("download")`
- `client-tauri/web-src/src/routes/Onboarding.tsx:155` — renders three buttons including `"two_way"`
- `client-tauri/web-src/src/routes/Settings.tsx:121-124` — same three-button picker that calls `save({ drive_sync_mode: m, drive_sync_enabled: m !== "off" })`

User flow that breaks: pick "双向同步" in onboarding/settings → config saves `drive_sync_mode: "two_way"` → tray no longer shows a way to change it back → every drive-sync click returns the hard-coded English error string `"two-way drive sync is not available in this build"`. The error message is also not translated to Chinese, unlike the rest of the UI.

Fix: either restore the tray item + a real two-way implementation (won't happen in this PR), or also remove the `"two_way"` option from both React pickers and silently coerce any stored `"two_way"` value back to `"download"` on `Config::default()`/`load()`.

---

## P1 — Important issues

### P1-1 — `reminders.rs` notification dedup doesn't store rows for empty `id` → renotify every 60s
`client-tauri/src-tauri/src/reminders.rs:91-93,108-110`:

```rust
let notification_id = n.get("id").and_then(|v| v.as_str()).unwrap_or("");
let updated_at = n.get("updated_at").and_then(|v| v.as_str()).unwrap_or("");
let key = format!("{notification_id}:{updated_at}");
if known_map.contains_key(&key) { continue; }
// ... notification fires ...
if !notification_id.is_empty() {
    new_seen.push((key, ...));
}
```

The early `contains_key` check happens regardless of id being empty, but the `push` to persist the key is guarded by `!notification_id.is_empty()`. Result: a backend notification missing an `id` field fires its desktop toast every 60 seconds in perpetuity — the in-memory `known_map` is rebuilt fresh each tick from `state.read().known_notifications`, so nothing remembers we already shown it.

The same pattern exists in `poll_reminders` (`reminders.rs:42-44, 64-65`) but without the empty-id guard, so a reminder with empty id+due_at would dedup correctly (key `":"` would be stored). Still, the asymmetry between the two functions is a smell.

Fix: drop the `if !notification_id.is_empty()` guard (or apply it symmetrically on the read side: skip dedup for items with no stable identity).

### P1-2 — `reminders.rs` dedup map never cleared on logout / token rotation
`client-tauri/src-tauri/src/config.rs:51-55, 89-92` — `known_reminders` / `known_notifications` are persisted in `Config` and seeded to `{}` on `Default::default()`. Nothing in the new code clears them when the user signs out, swaps device-token, or migrates servers. If a user re-onboards onto the same client install, stale dedup rows from the previous identity persist and could suppress legitimate first-time notifications.

This is not strictly a Codex regression (the fields already existed pre-Codex), but Codex started actively writing into them, so it's now reachable in practice. Worth a one-line clear on logout.

### P1-3 — Tray dead-code: `drive_sync_enabled` flag now toggleable from JS but invisible from tray
The tray menu has `drive_off` and `drive_download` items; both go through `set_drive_mode(app, ..., bool)`. With `two_way` removed there's now only two selectable states in the tray, but the underlying config has three meaningful states (`off | download | two_way` × `enabled bool` × `paused bool`). The tray cannot rescue a user from a `two_way` setting saved by the UI (see P0-1). The fix in P0-1 resolves this.

### P1-4 — `safe_relative_path` doesn't normalize Unicode or block Windows reserved names
`client-tauri/src-tauri/src/sync.rs:348-369`:

```rust
pub(crate) fn safe_relative_path(raw: &str) -> anyhow::Result<PathBuf> {
    let trimmed = raw.trim().trim_start_matches(&['/', '\\'][..]);
    let mut out = PathBuf::new();
    if trimmed.contains(':') { ... }
    for part in trimmed.split(...) {
        if part == ".." { return Err(...); }
        out.push(part);
    }
    ...
}
```

This is the entry validator for drive-manifest paths (server-controlled). It rejects `..`, `:`, absolute prefix slashes — good. But on Windows it does NOT block:
- Reserved device names: `CON`, `NUL`, `AUX`, `PRN`, `COM1`-`COM9`, `LPT1`-`LPT9` (case-insensitive, with or without extension). Creating any of these as a regular file silently fails or opens the device.
- UNC-prefix tricks: `\\server\share\...` is split by `/`/`\\` into empty parts but never blocked explicitly. The leading-slash trim removes only one of the two leading backslashes; the remaining one becomes a no-op empty split component. So a server-supplied path of `\\\\evil-host\\share\\foo` would just become `evil-host\share\foo` under the sync root — not actually exploitable for filesystem escape because `out.push("evil-host")` is just a regular subdirectory creation, but the input gets silently mangled rather than rejected.
- Windows ADS streams: `foo.txt:hidden` is blocked by the `:` check (good, this was deliberate).
- Trailing-dot / trailing-space stripping: Windows silently strips these, so `foo.txt.` aliases `foo.txt` — could be used by a malicious server to overwrite a file with two different sha256 manifests. Low impact since `ensure_parent_inside_root` canonicalizes.

`ensure_parent_inside_root` and `ensure_dir_inside_root` DO call `fs::canonicalize` on both root and parent, so any actual escape via symlink/junction is caught. So this is a hardening-deeper concern, not a bypass.

### P1-5 — `with_extension` quirk drops file extension in tmp paths
`client-tauri/src-tauri/src/sync.rs:142,239`:
```rust
let tmp = target.with_extension(format!("{}.download", upload_safe_suffix(&f.id)));
```

For `target = "attachments/report.pdf"` and `f.id = "abc123"`, this produces `attachments/report.abc123.download` — the `.pdf` extension is **dropped**, not appended. After successful rename to `target` the final filename is correct, but during the download the tmp filename loses the original extension. Not a bug per se; one practical consequence is that AV scanners watching `.exe`/`.pdf` writes wouldn't trigger during the download window. The atomic rename then drops the file into its true `.pdf` name where AV will scan it. Acceptable.

A bigger concern: if two attachments share the same `f.id` prefix after `upload_safe_suffix` (16-char ASCII-alphanumeric truncation), their tmp paths collide. With UUIDs the first 16 chars are uniformly distributed so collisions are exceedingly rare, but if `f.id` is something like `req_001_attach_pdf_1` the truncation to `req001attachpdf1` plus alphanumeric-only filtering is deterministic — two attachments with `req_001_attach_pdf_1` and `req_001_attach_pdf_2` would collide on `req001attachpdf` (length 15) followed by a single different char — no collision actually, but if ids are e.g. 17+ chars of structured prefix, collision becomes plausible. Suggest using full id or a random nonce instead of truncated id.

### P1-6 — Empty `connect-src` host-pattern wider than necessary
`client-tauri/src-tauri/tauri.conf.json:31`:
```
"csp": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: asset: http://asset.localhost; font-src 'self' data:; connect-src 'self' http://*:* https://*:* ws://*:* wss://*:*"
```

The `connect-src http://*:* https://*:*` allows the webview to fetch *any* host on the user's network on any port. The client only talks to one LAN server. Since the URL pinning in `sync.rs::resolve_server_url` validates server-origin for download URLs, the practical exploit surface from the Rust side is closed; but a compromised webview (e.g. an XSS via attachment preview) could exfiltrate to any host. Tightening to `connect-src 'self' http://192.168.0.0/16 http://10.0.0.0/8` (CSP doesn't actually support CIDR, but you could pin the specific server) would help. Lower priority because the user's LAN model is "trusted."

The `style-src 'unsafe-inline'` is unavoidable for any styled React app; acceptable.

### P1-7 — `ensure_parent_inside_root` canonicalizes parent twice and over-extends I/O
`client-tauri/src-tauri/src/sync.rs:281-310` — walks each path component, canonicalizes if exists, otherwise creates dir + canonicalizes, then at the end ALSO calls `fs::canonicalize(parent).await?` and checks `parent_canon.starts_with(&root_canon)` again. The final whole-parent canonicalize is enough on its own; the per-component loop adds 2N filesystem syscalls per N path components. For drive-sync's hundreds-of-files case this is hot — each `for` iteration in `sync_drive_download` calls `ensure_parent_inside_root` (line 244 via the unique tmp path). Profile before optimizing, but the per-component canonicalize loop is defense-in-depth that probably isn't worth its IO cost.

---

## P2 — Style / minor

- `commands/sync.rs:33` — `drop(cfg)` is a no-op because `state.inner().read()` returns an owned `Config` (clone), not a `MutexGuard`. Harmless but misleading.
- `commands/submitter.rs:484, 486` — `ensure_dir_inside_root` is called both BEFORE and AFTER `std::fs::create_dir_all`. The before-call already creates missing intermediate dirs as part of its canonicalize-or-create dance, so the explicit `create_dir_all` is redundant; the after-call is a TOCTOU re-check, which is fine. Could collapse to one call.
- `commands/submitter.rs:9` — `use std::fs::OpenOptions;` added at the top, but `OpenOptions` is only used inside `download_delivery`. Local `use` would scope better.
- `reminders.rs:38` — `state.read().known_reminders` clones the entire `serde_json::Value` map on every 60s tick even when the manifest has zero items. For a user with thousands of historical reminders this is wasted work. Move the read inside the `if let Some(arr) = list.as_array()` and the inner `if !arr.is_empty()`.
- `reminders.rs:131-141` — `prune_seen_map` rebuilds an in-memory `Vec` of all entries to sort by value (the RFC3339 timestamp string). String sort happens to equal chronological sort for RFC3339, but only because the input is uniform format. Risk: if any caller ever stores a non-RFC3339 timestamp the sort silently produces nonsense ordering and prunes wrong entries. Add a comment.
- `delivery.rs:75` — `src.canonicalize()?` will fail if `src` does not exist; the previous code lazily handled this via the recursive `walk`. Should not happen in practice (caller creates the spec dir first) but worth a `?` → contextful error.
- `BUILD.md` line 71 — replaced `192.168.0.224` doc URL with `192.168.5.53`. Verify this matches the actual deployed server (memory says `192.168.0.224` is the GPU host, but the LAN-facing deployment may be on `5.53`).
- `tauri.conf.json:49` — `bundle.targets` reduced from `["msi", "nsis", "dmg", "app", "deb", "appimage"]` to `["nsis"]` only. Memory says the client is Windows-only, so this is correct, but it does silently break any out-of-tree CI that called `tauri build` expecting a `.dmg` or `.deb`. There IS a new `.github/workflows/build-macos-client.yml` (not in my scope, but noted) — that workflow will fail because the bundle target list now excludes `dmg`/`app`. Confirm and either restore those targets or delete the macOS workflow.
- `Cargo.toml:16` — removed `"devtools"` from Tauri features. Devtools are useful in debug builds. Consider `#[cfg(debug_assertions)] features = ["devtools"]` or build-profile-specific features. As-is, no dev devtools on debug builds either.
- `install-client.ps1:14-19` — switched to `-UseBasicParsing`. Good (avoids IE engine dependency). No new TLS-skip flags, no `Invoke-Expression`. Safe.
- `install-client.ps1:46-48` — sync root path changed from `D:\工作需求` to `D:\YQGL-Work` (Latin alphabet). This is a behavior change for new installs but matches no other configured default in the codebase: `config.rs:64` still hardcodes `r"D:\工作需求"` as the Rust-side default. Result: PS install writes one default into the legacy Python config; Rust client starts and reads from its own config (different default). Verify the migration path (`legacy_config_candidates` in `config.rs:181-193`) actually picks up the PS-written file and propagates `sync_root` correctly. If the PS-written file is at `%APPDATA%\yqgl\config.json` then `legacy_config_candidates` first entry hits it — OK.
- `install-client.ps1:64` — shortcut description changed from `"需求管理大师本地工作台"` to `"YQGL local workbench"`. Cosmetic.
- `install-client.sh:71-95` — the `setdefault`/`force_server` merge logic for re-running the installer is good — preserves existing user fields. The `force_server` env-var gate is a clean way to opt into "overwrite my server URL" without nuking unrelated fields. No issues.
- `install-client.sh:32-50` — macOS branch creates a `LaunchAgent` plist with `RunAtLoad=true`. No KeepAlive, no resource constraints — fine for a desktop tool. The `WorkingDirectory` and `ProgramArguments` paths are properly interpolated through HEREDOC; no shell injection. Safe.

---

## sync.rs (183-line diff) — line-by-line analysis

### Net assessment: STRONG IMPROVEMENT
Codex's `sync.rs` changes are the most security-significant of the PR, and they go strictly the right direction:

| Concern | Baseline `c884b60` | Post-Codex `main` |
|---|---|---|
| Streaming downloads (no full-buffer OOM) | YES — `bytes_stream` + `write_all` per chunk | **YES, PRESERVED** at sync.rs:138-140, 244-246 |
| `error_for_status()` on HTTP errors | YES | **YES, PRESERVED** at sync.rs:137, 235 |
| Path-traversal hardening | None (raw `join(&manifest.project_slug).join(&manifest.code)`) | **NEW** `safe_component` validator at every join site |
| Origin-pinned download URLs | None (any `http://` URL accepted) | **NEW** `resolve_server_url` refuses off-server URLs |
| Atomic file replacement | None (overwrites target in place — read+write race during scan) | **NEW** `.download` tmp + atomic rename |
| End-to-end SHA256 verification | Only cache-hit check before download | **NEW** stream-hash during download + verify on rename |

### Diff line-by-line

**Lines 1-12 (imports)**: adds `Component`, `Url`. Clean.

**Lines 79-80**: project_slug and code go through `safe_component(..., "project")?` / `safe_component(..., "requirement")?` before path join. This is the fix for the trivial `project_slug=../../../etc/passwd` server-injection bug. The fallback string `"project"` / `"requirement"` is only used when the input is empty — see the `(None, None) if !fallback.is_empty()` match arm. Sensible.

**Lines 115-116**: `safe_name = safe_component(&f.name, "attachment")?` and `target = attach_dir.join(&safe_name)`. Same fix for attachment filenames. Server CAN'T deliver `../../config.json` as a "file name."

**Line 130**: `dl_url = resolve_server_url(&state, &f.download_url)?`. Replaces the previous `if download_url.starts_with("http") { use it } else { prepend base }` which would happily follow any absolute URL the server returned. New code calls `resolve_server_url` which `Url::parse`s the candidate and compares scheme/host/port to the configured base — any divergence returns `anyhow!("refusing off-server download url: {raw}")`. This is real defense against a compromised server redirecting clients to malware-host.

**Lines 142-145**: `tmp = target.with_extension(...)` then `ensure_parent_inside_root(&attach_dir, &tmp).await?` then `fs::File::create(&tmp)`. The `ensure_parent_inside_root` uses the per-requirement `attach_dir` as root, not the user's global sync_root — that's a tighter constraint, but it's only effective against a symlink INSIDE `attach_dir`. If an attacker can place a symlink in `attach_dir` they can already write anywhere; the check is moot. The check is mostly belt-and-suspenders. OK.

**Lines 146-151**: chunked stream hash + write. `downloaded.update(&chunk)` runs in lockstep with `file.write_all(&chunk)`. Memory is bounded by reqwest's internal chunk size (~16-64KB).

**Lines 154-160**: SHA verification after stream completes, then conditional `remove_file(&target)` and `rename(&tmp, &target)`. The remove-then-rename is not atomic — Windows `rename` will fail if the target exists, so removing first is necessary. On Linux/macOS `rename` overwrites atomically; the remove adds an extra syscall but no race window. Acceptable cross-platform compromise.

If the SHA check fails: `fs::remove_file(&tmp)` (with `let _ =`), then return Err. The tmp is best-effort cleaned up; on failure (e.g. file held by AV) the tmp stays as `.download` litter. Codex hasn't added periodic cleanup of these (the v0.3.0 baseline added `cleanup_partial_*` for delivery zip tmps — verify the same exists for sync downloads).

**Lines 200**: same `safe_component` treatment for drive-sync root.

**Lines 206-210**: same `safe_relative_path` for drive-item path. `ensure_dir_inside_root` for kind=="folder" — verified.

**Lines 219-220**: `dl = resolve_server_url(...)`. Same origin pinning.

**Lines 226-258**: same atomic-rename + stream-hash pattern for drive items. Symmetric with the requirement-attachment path. Good.

**Lines 264-274 `resolve_server_url`**: implementation is correct. Uses `target.port_or_known_default()` to normalize default ports — `http://host:80/` and `http://host/` would correctly compare as equal. Subtle: if the user's `server_url` is `http://192.168.5.53:8080/` and the server returns `http://192.168.5.53/foo`, the port comparison is `Some(8080)` vs `Some(80)` → REJECT. That's correct given that the server SHOULD be returning paths/URLs that match its actual port, but if the deployment ever runs the API on a different port from the file-serving endpoint, this rejection is a foot-gun. Worth a comment in the source.

**Lines 281-310 `ensure_parent_inside_root`**: walks the relative path one component at a time, canonicalizing each. The per-component canonicalize is overkill — the final `parent_canon.starts_with(&root_canon)` check is sufficient (canonicalize follows symlinks fully, so any escape via symlink at any intermediate level shows up in the final canonical path). See P1-7.

**Lines 312-322 `ensure_dir_inside_root`**: same pattern. Correct.

**Lines 324-342 `safe_component`**: rejects any component containing `/`, `\\`, `:`. Then re-parses through `Path::new(cleaned).components()` and demands exactly one `Component::Normal`. Belt-and-suspenders against `Path` parsing quirks. The double-check guards against `Path::new(".").components()` returning `Component::CurDir` — correctly rejected. Empty input falls through to the `(None, None) if !fallback.is_empty()` fallback to use the safe default name.

**Lines 344-369 `safe_relative_path`**: see P1-4. Mostly OK; on Windows misses reserved device names and UNC tricks.

**Line 371 `upload_safe_suffix`**: see P1-5. Truncates to 16 ASCII-alphanumeric chars. Collision risk for structured-prefix ids.

---

## NEW: reminders.rs analysis

Note: `reminders.rs` is NOT a new file (it existed at c884b60). Codex added 32 lines on top of the existing 57. The analysis below covers the new dedup machinery.

### What changed
Codex added two-level dedup against `Config.known_reminders` and `Config.known_notifications` (both already-defined `serde_json::Value` fields in the persistent config). The dedup key is `format!("{id}:{timestamp}")` where timestamp is `due_at` for reminders and `updated_at` for notifications. After each poll, newly-seen keys are written back via `ConfigState::write`, and the map is pruned to a max size (500 reminders / 1000 notifications) by sorted-by-value (oldest first) eviction.

### Does it duplicate backend logic?
Server-side `/api/reminders/due` and `/api/notifications?status=unread` both presumably already track "delivered/read" state on the server. So yes — this is duplicate state in the client.

Why duplicate? The poll is `/api/reminders/due` (kind=time-based filter), not `/api/reminders/unread`. The server doesn't know whether the desktop toast already fired for a given DDL-reminder. Server-side has a generic notification "read" state but doesn't track per-channel delivery (i.e., "did the Windows desktop toast fire?"). So client-side dedup is necessary, and the chosen key `id:due_at` correctly handles reschedule (key changes when DDL moves).

For `poll_notifications` the same is less defensible — the server already has a "delivered" notion via `/api/notifications/{id}/dismiss` or similar. The client-side dedup is a safety net against backend bugs that fail to mark-as-delivered. Acceptable defense in depth.

### Race conditions
- Single ticker task → no concurrent `poll_reminders` or `poll_notifications` calls. OK.
- Between `state.read().known_reminders` (line 38) and `state.write(...)` (line 71-79) another task COULD write to `known_reminders` (e.g. a UI command for "mark all read"). The write closure re-reads `cfg.known_reminders.as_object().cloned()` and merges, so it's a per-write atomic merge. Lost-update is bounded to other paths' writes happening to OVERLAP with our window — and even then, we'd only re-fire whatever they dismissed, which is conservative. Not a correctness bug.
- The persistent disk write happens on EVERY poll that sees a new item. Polling every 60s with steady new items would write the config file 1440 times/day. `parking_lot::Mutex` is fine here; the disk concern is mostly OS-cache thrash, negligible on modern SSDs.

### Channel patterns
None — uses `tauri::AppHandle::emit` (mpsc-ish, drop-on-no-listener) and `NotificationExt::notification().builder().show()` (fire-and-forget). No channels to leak.

### Persistence
The dedup state IS persisted via `ConfigState::write` → `save()` → atomic `.tmp + rename`. So on restart the dedup survives. Good — without this, every restart would re-fire all currently-due reminders.

But on logout / nickname swap / server-URL change, the dedup state is NOT cleared. See P1-2.

### Edge cases worth flagging
- **Empty id behavior asymmetric between reminders and notifications.** See P1-1.
- **Map sort by RFC3339 string.** See P2 note on `prune_seen_map`. Works for chronological sort, but fragile to future format changes.
- **Map type juggling.** `cfg.known_reminders` is `serde_json::Value` but always treated as an object. If the JSON file is ever hand-edited or migrated from a version that stored it as an array, `as_object()` returns `None`, the `.unwrap_or_default()` silently resets to empty, and the user gets re-notified for every reminder once. Codex did NOT touch the schema, so this is inherited from the v0.3.0 baseline.

### Verdict
The dedup additions are valuable and correctly designed. The two minor issues (empty-id renotify loop in P1-1, no-clear-on-logout in P1-2) are cheap to fix.

---

## Security surface (capabilities / tauri.conf / install scripts)

### Tauri capabilities — NARROWED (improvement)
`client-tauri/src-tauri/capabilities/default.json` diff:
- REMOVED `core:webview:allow-internal-toggle-devtools` — devtools no longer toggleable from JS. Good for release builds.
- REMOVED `shell:allow-open` — JS can no longer call `shell.open()` to launch arbitrary URLs/apps. The Rust-side `commands::shell::open_folder` (which uses `std::process::Command` directly, not the shell plugin) still works for the tray + the `open_spec_folder` command. No JS code I found uses `@tauri-apps/plugin-shell`. Safe to remove.
- REMOVED `process:default` and `process:allow-exit` — JS can no longer call `process.exit()`. The Rust-side `app.exit(0)` in tray.rs:81 still works. No JS code uses `@tauri-apps/plugin-process`. Safe to remove.

The `tauri_plugin_shell::init()` and `tauri_plugin_process::init()` ARE still loaded in `lib.rs:42, 49`, so the Rust-side `dialog`/`fs`/`notification`/`os`/`store`/`window-state`/`deep-link` plugins continue to work. Removing the JS-side capability without removing the plugin init is the correct minimization (plugin functionality remains available from Rust commands, but the JS attack surface is shut).

### Tauri config — CSP added (improvement, with caveat)
`client-tauri/src-tauri/tauri.conf.json:31` — `"csp": null` → a real CSP string. Default-src 'self', script-src 'self' (no `unsafe-eval`, no `unsafe-inline`), style-src `'self' 'unsafe-inline'` (required for React), img-src includes `asset:` and `http://asset.localhost` (Tauri's local file protocols), font-src self+data. See P1-6 for the overly-broad `connect-src`.

`bundle.targets` reduced to `["nsis"]` only — see P2. Compatible with Windows-only target, but breaks the new macOS workflow Codex also added.

### Install scripts — no credential/network red flags
**`install-client.ps1`**:
- No hardcoded creds.
- `Invoke-WebRequest -UseBasicParsing` — good, no IE dep.
- Downloads from `$server` which defaults to `http://192.168.5.53:8080`. No TLS, but this is a LAN-only client by design.
- No `Invoke-Expression`, no `[ScriptBlock]::Create`, no `iex`.
- Shortcut creation uses `ExecutionPolicy Bypass` — required for local PS launch, not a security regression.
- Path changes from CJK → Latin alphabet are cosmetic. See P2 note about Rust-side default mismatch.

**`install-client.sh`**:
- `set -euo pipefail` — good.
- `curl -fsSL` — `-f` fails on HTTP errors, `-s` silent, `-L` follow redirects. Reasonable; consider `--proto =https --tlsv1.2` if you ever switch to HTTPS.
- macOS branch creates a `LaunchAgent` plist. `RunAtLoad=true` only; no `KeepAlive`. Polite.
- HEREDOC interpolation properly escapes embedded quotes via `sed 's/"/\\"/g'`. No shell injection via `$INSTALL_DIR`.
- The Python merge block uses `setdefault` to preserve existing user config — won't clobber `client_token` on reinstall. Good.

No new credentials, no TLS-skip flags, no privilege escalation. The PS script does NOT call `Start-Process -Verb RunAs` or otherwise require admin — installs to `LOCALAPPDATA` only. Clean.

---

## Cargo.toml / Cargo.lock — no surprise crates
`Cargo.toml` diff is exactly one feature flag removal (`devtools`). Nothing else.

`Cargo.lock` adds 11 entries: `file-id`, `filetime`, `fsevent-sys`, `inotify`, `inotify-sys`, `kqueue`, `kqueue-sys`, `mio 0.8`, `notify`, `notify-debouncer-full`, `urlencoding`. Every one of these is a transitive dependency of `notify = "6"` and `notify-debouncer-full = "0.3"` (already in baseline `Cargo.toml`) or `urlencoding = "2"` (also already in baseline). The baseline Cargo.lock was demonstrably stale — it didn't even contain `notify` despite the Cargo.toml declaring it. Codex's lockfile is the result of `cargo update` or `cargo build` regenerating from the existing manifest. No supply-chain surprises.

---

## Positive changes worth keeping

1. **`sync.rs` path-traversal hardening.** `safe_component` + `safe_relative_path` + `ensure_parent_inside_root` + `ensure_dir_inside_root` close the door on a compromised-server / man-in-the-middle attacker delivering `../../config.json` as a "file name" or `\\evil\share\bad.exe` as a relative path. The canonicalize check defeats symlink/junction tricks too.

2. **`resolve_server_url` origin pinning.** Refusing off-server download URLs is genuinely valuable defense. The previous `if starts_with("http")` would happily follow any absolute URL the API returned.

3. **End-to-end streaming SHA256 verification.** Hashing during the stream + verifying before atomic rename is the right design. Combined with the `.download` tmp suffix it means a half-downloaded or tampered file never appears at the canonical name.

4. **Symlink-refusal for delivery zip overwrite.** `commands/submitter.rs:530-538` — `symlink_metadata` check before `OpenOptions::new().write(true).create_new(true)` is the textbook safe-overwrite pattern. The `create_new(true)` after `remove_file` ensures any race where an attacker recreates the path as a symlink between our check and our open fails loudly rather than silently following.

5. **`delivery.rs` walk now canonicalizes + skips symlinks.** Old code just used `strip_prefix` to detect out-of-base; new code canonicalizes the entry and explicitly skips `is_symlink()` entries. Combined with the existing `EXCLUDE` list this hardens the delivery-zip pipeline against malicious symlinks in the spec folder.

6. **`spec_watch.rs` watcher filter now canonicalizes** (lines 86-92). Previously `p.starts_with(&folder_for_handler)` was string-prefix only; now it canonicalizes both sides. Same hardening applied uniformly.

7. **`config.rs` legacy migration** (`legacy_config_candidates` + `config.migrated-to-tauri.json` backup). Cleanly migrates Python-client configs into the new Tauri location without losing tokens. Backup of the old file is preserved.

8. **`config.rs` recompute_url empty-IP guard** (line 114). `if self.server_url.is_empty() && !self.server_ip.trim().is_empty()` — previously a fresh-default Config with empty `server_ip` and empty `server_url` would still compute `"http://:8080"`. Now it leaves `server_url` empty until the user enters a real IP. Good.

9. **Capability surface narrowed.** Removing `shell:allow-open`, `process:*`, `internal-toggle-devtools` is exactly the right release-time hardening.

10. **Real CSP installed.** Switching from `csp: null` to a real policy is a meaningful improvement, even with the wide `connect-src`.

11. **Install scripts split macOS/Linux properly.** The previous single-branch shell script would have written a `.desktop` file into `~/Library/LaunchAgents` on macOS. The new branching with `uname -s = Darwin` writes a proper `LaunchAgent` plist. Setdefault-merge for re-runs is also a nice safety touch.

---

## File reference summary (absolute paths)

- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\config.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\sync.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\delivery.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\spec_watch.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\reminders.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\tray.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\submitter.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\src\commands\sync.rs`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\Cargo.toml`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\Cargo.lock`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\tauri.conf.json`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\src-tauri\capabilities\default.json`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\BUILD.md`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client\install-client.ps1`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client\install-client.sh`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\routes\Onboarding.tsx` (out of scope but referenced for P0-1)
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\routes\Settings.tsx` (out of scope but referenced for P0-1)
