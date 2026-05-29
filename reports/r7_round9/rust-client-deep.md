# R7 Round 9 — Rust client deep audit

HEAD `2ffd641`. Scope: every file under `client-tauri/src-tauri/src/` (15 modules
+ 9 command modules) plus `Cargo.toml` / `Cargo.lock` / `capabilities/default.json`.
Goal: production robustness for an unattended Windows desktop app (tray, background
SSE + reminder polling, on-demand sync).

## Verdict: CLEAN (production-ready)

No reachable panic, crash, or resource-leak path was found. The two `expect()`
calls in the codebase are startup-only and cannot be reached by server or
filesystem data. Server-controlled JSON is parsed defensively everywhere
(`.get(...).and_then(...).unwrap_or(...)`), all `#[tauri::command]`s return
`Result` and surface errors to JS, and the failure modes of the sync loops are
skip/abort-with-error rather than panic. Two LOW-severity robustness notes
(F1, F2) are documented below; neither blocks shipping.

A scoping correction: the prompt references a "45s background drive-sync loop"
in `sync.rs`. **No such Rust-side periodic loop exists.** Drive sync runs only
on demand via the `trigger_drive_sync` command (lib.rs:98, commands/sync.rs:21);
the only Rust background loops are `reminders::spawn` (60s, reminders.rs:15) and
`sse::spawn` (long-poll w/ backoff, sse.rs:28). Any 45s cadence lives in the JS
layer driving `trigger_drive_sync`. This audit covers the actual Rust loops.

## Panic / unwrap reachability from server/fs data

Exhaustive scan for `.unwrap() / .expect() / panic! / unreachable! / array-index`
across all `src/`:

| Site | Reachable from server/fs? | Verdict |
|------|---------------------------|---------|
| `http.rs:28` `.expect("reqwest client build")` | No — ClientBuilder w/ static opts; only fails on broken TLS backend at process init | Safe (startup) |
| `lib.rs:132` `.expect("error while running yqgl client")` | No — Tauri runtime bootstrap | Safe (startup) |
| `sse.rs:109` `&line_bytes[..line_bytes.len()-1]` | Yes (SSE stream bytes) | Safe — `drain(..=pos)` guarantees `len>=1`, no underflow |
| `sync.rs:117` `10 + (80*(idx+1)/total) as u8` | Yes (manifest file count) | Safe — `idx<total` ⇒ ratio≤80, `as u8`≤80, +10≤90; `80*(idx+1)` cannot overflow `usize` for any realistic file count |
| `sync.rs:253` `(90*(idx+1)/total) as u8` | Yes (drive item count) | Safe — ≤90 |
| `reminders.rs:57,172` `.as_i64()` arithmetic (`mins.abs()`, `pct`) | Yes | Safe — all on `i64`, no slice/index, no overflow path |

There are **no** `[i]` slice-index operations on server-derived collections, no
`.unwrap()` on `Option`/`Result` carrying server or FS data, and no
`serde_json::from_*().unwrap()`. Every JSON field access goes through
`.get(k).and_then(as_str/as_i64/as_array).unwrap_or(default)` or `#[serde(default)]`.

Process-level crash semantics: `Cargo.toml` has **no** `[profile.release]`
with `panic = "abort"`, so even a hypothetical panic inside a spawned worker
task unwinds only that task — the tray, window, and other loops survive. (The
default is fine here; flagging only for completeness.)

## sync.rs failure-mode matrix

`sync_requirement` (per-requirement) and `sync_drive_download` (per-project)
share the same streaming-download pattern. Both return `Result`; the command
wrappers (`commands/sync.rs`) propagate the error to JS.

| Failure | Behaviour | Assessment |
|---------|-----------|------------|
| Manifest fetch 4xx/5xx | `.error_for_status()?` → `Err` → JS sees it | Correct |
| Manifest not JSON | `.json()?` → `Err` | Correct |
| Network drop mid-stream | `stream.next()` yields `Err(chunk?)` → fn returns `Err`; `.download` tmp left on disk | Correct abort; see F1 (tmp cleanup) |
| Server returns 500 on a file download | `.error_for_status()?` → `Err` → whole sync aborts | **Abort-all, not skip-and-continue** (see F2) |
| Disk full mid-write | `file.write_all(...)?` → `Err`; partial `.download` left | Correct abort; see F1 |
| SHA256 mismatch | tmp removed (`remove_file`), returns `Err("sha256 mismatch")` | Correct — bad data never published to the real filename |
| Partial download (truncated by server, no SHA in manifest) | If `f.sha256` is `None`, no verification; truncated file is renamed into place | Acceptable: server omitting sha256 is the trust boundary; matches Python parity |
| `.download` tmp from a prior crash | New run overwrites it via `File::create` (truncates); on success `rename` replaces target | Self-healing — no orphan accumulation across runs for the same file id |
| Path traversal in `project_slug`/`code`/`name`/drive `path` | `safe_component` / `safe_relative_path` reject `..`, `/`, `\`, `:`, absolute; `ensure_parent_inside_root`/`ensure_dir_inside_root` re-canonicalize and verify containment after mkdir | Defense-in-depth, verified GREEN in prior rounds; still GREEN |
| Off-server `download_url` | `resolve_server_url` pins scheme+host+port to configured base; rejects otherwise | Correct |
| Atomic publish | `remove_file(target)` then `rename(tmp,target)` — small non-atomic window where target is briefly absent | Acceptable for a sync mirror; a crash between the two leaves the `.download` tmp, recovered next run |

Single failed file aborts the whole sync (early `return Err`). For a mirror-sync
this is defensible (loud failure surfaced to UI) but see F2 for the trade-off.

## command error propagation

All 41 registered `#[tauri::command]`s (lib.rs:82–129) were inspected. Findings:

- **Async commands** (the majority): return `Result<T, Error>`; every HTTP call
  uses `.send().await?.error_for_status()?.json().await?`, so transport errors,
  non-2xx, and body-parse errors all become `Err` and reach JS. `Error`
  serializes to its `Display` string (error.rs:19) — JS gets a readable message,
  no silent swallow.
- **`me` (auth.rs:31)**: correctly distinguishes 401 (→ `Ok(None)`) from other
  non-2xx (→ `Err`) and from body-parse failure (→ `Err`), avoiding the
  documented "phantom logout → device-record revoke" data-loss trap. Good.
- **`register_device` / `upload_file`**: `init` response missing `upload_id`
  → `Err(Other(...))`, not a panic. Good.
- **`download_delivery` (submitter.rs:491)**: handles empty deliveries array,
  missing id, refuses to overwrite a symlink/dir at the dest path
  (`symlink_metadata` check), uses `create_new(true)`. Robust.
- **Sync/sync (synchronous, no Result)**: `update_tray_unread` and
  `stop_spec_watcher` are infallible by design — `update_tray_unread` uses
  `if let Some(tray)` + `let _ =` (tray may not exist yet), `stop_spec_watcher`
  removes from the watcher map (no-op if absent). Intentional, not a swallow.
- **`get_config` returns `Config`** (not Result) — pure in-memory read of the
  Mutex, cannot fail. Correct.
- **`open_folder` (shell.rs)**: returns `Result`; spawns `explorer`/`open`/
  `xdg-open` via `Command::arg` (single argv, no shell re-parse) only after
  rejecting metachars/`..`/control chars AND verifying the canonicalized target
  is under `sync_root`/`drive_sync_root`/config-dir. `.spawn().ok()` discards the
  spawn handle but that is correct (fire-and-forget launcher; we don't wait).

No command swallows a server error silently; no command `.unwrap()`s
server/user input.

## Concurrency / state / resource review

- **`ConfigState` (config.rs)**: `Arc<Mutex<Config>>`, cloned by Arc-bump so all
  workers + commands share one backing store. `write()` holds the
  `parking_lot::Mutex` across `recompute_url` + `save()` (atomic .tmp→rename).
  No `.await` is held across the lock (parking_lot guards aren't `Send` across
  await, and the code never tries), so no deadlock/poisoning. Reads clone out
  fast. Concurrent reminder + notification writers each take the lock
  sequentially — correct.
- **`save()` atomicity (config.rs:224)**: write `.tmp` then `rename` — crash-safe.
  Verified GREEN.
- **broken/transient config recovery (config.rs:166,256)**: parse failure backs
  up to `config.broken-{ts}.json`; transient IO failure in `from_disk` backs up
  to `config.recover-{ts}.json` and logs loudly before defaulting. No silent
  token nuke. Good.
- **`http.rs` client cell**: double-checked `RwLock<Option<Arc<Client>>>` init
  prevents the cold-start race where two workers build separate clients and one
  loses its cookie jar. Correct and well-reasoned.
- **`reminders.rs` dedup-map growth**: `prune_seen_map` caps reminders at 500 and
  notifications at 1000 entries, evicting oldest by RFC3339 timestamp string sort
  (lexicographic order == chronological for RFC3339). Unbounded growth is
  prevented. Empty-id reminders/notifications are skipped (no empty-key poisoning).
- **`spec_watch.rs` watcher map**: `WATCHERS: Lazy<Mutex<HashMap<...>>>`; `start`
  calls `stop_blocking` first to drop any prior debouncer for the same `req_id`
  (no double-watch leak); `stop` removes+drops. The notify callback canonicalizes
  each event path and checks `starts_with(folder)` before uploading, and offloads
  upload work to the async runtime so the notify thread never blocks. Map grows
  by one entry per watched requirement (bounded by user action, freed on stop).
- **`sse.rs`**: stop signal aborts both child tasks; backoff capped at 30s; chunk
  errors break the inner loop and reconnect. The byte-buffer SSE parser correctly
  handles multi-byte UTF-8 straddling chunk boundaries.
- **`delivery.rs` temp zip**: `let _ = remove_file(&zip_path)` runs on BOTH
  success and failure paths (the `?` was moved off the upload call) — no
  GB-sized temp leak on failed delivery. Symlink + out-of-base entries skipped
  during the walk.
- **Deps (Cargo.lock)**: nothing yanked or alarming. Two `reqwest` versions
  (0.12.28 used per Cargo.toml pin; 0.13.4 pulled transitively) — normal.
  `native-tls`→`openssl 0.10.80` is target-gated; on Windows `native-tls` uses
  SChannel, so openssl-sys does not compile into the shipped binary. `notify 6`,
  `zip 2.4.2`, `tokio 1.52`, `sha2 0.10` all current. `capabilities/default.json`
  is minimized (no `shell:allow-execute`, fs scoped to appdata-recursive only).

## Findings

### F1 — LOW — `.download` temp file left on disk after mid-stream failure
`sync.rs:136-156` and `sync.rs:232-252`. On network drop, disk-full, or a chunk
error during streaming, the function returns `Err` and the partially-written
`*.{idfragment}.download` temp is **not** removed (only the SHA-mismatch path at
:149/:245 cleans up). The next successful run for the same file id reuses the
deterministic temp name via `File::create` (truncate), so it self-heals and does
NOT accumulate across runs for the same file. The leak is bounded to one stale
temp per file id that started but never finished and was never retried. Cosmetic
disk-usage only; no crash, no security impact. Optional: wrap the stream loop so
the temp is removed on any early return.

### F2 — LOW — a single failing attachment aborts the entire sync
`sync.rs:114-157`: the per-file loop uses `?` / early `return Err`, so one file
that 500s, mismatches SHA, or drops mid-stream aborts the whole requirement (or
whole drive) sync — already-downloaded files in that run are kept, but
not-yet-reached files are skipped until the user retries. For a mirror this is a
defensible "fail loud" choice and matches the Python parity baseline, but for an
unattended client a skip-and-continue (collect per-file errors, surface a summary,
still ack what succeeded) would be more resilient to one bad server object
poisoning an otherwise-good batch. Not a bug; a robustness trade-off to consider
post-launch.

### Note — full-file in-memory read for SHA cache check (acceptable)
`sync.rs:121` and `sync.rs:222` do `fs::read(&target)` (whole file into RAM) to
verify the cached SHA before deciding to skip a re-download. This partially
defeats the streaming-download memory optimization for the *skip* path: a
multi-GB already-synced attachment is fully buffered just to hash it. Downloads
themselves stream correctly. Real-world attachments here are small, so this is
not flagged as a finding, but a streaming hasher (the same 64 KiB-loop pattern
already used in `spec_watch.rs::sha256_of`) would close the gap if large files
become common.

## Bottom line
The Rust client is production-ready. No panic/crash is reachable from server or
filesystem data; all commands surface errors; background loops are panic-safe and
bounded in memory; path traversal, off-server URL, symlink, and config-corruption
defenses are intact. F1/F2 are LOW polish items, not blockers.
