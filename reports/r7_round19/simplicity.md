# R7 Round 19 — Simplicity / dead-code final

Scope: cumulative diff `c884b60..HEAD` (HEAD `3dcf440`, R7.17), `*.py *.ts *.tsx *.rs`,
excluding `reports/` + `screenshots/`. 93 files, ~+2948/-568. Read in full the
high-churn structural files (project_drive.py, delivery_upload.py, meetings.py,
requirements.py, auto.py, auto_agent.py, notifications.py, main.py, jobs.py,
SpeakButton/VoiceButton/useNotificationToasts/Hub/tauri.ts, shared time.ts).

## Verdict: CLEAN (0 structural findings)

The frozen tree is internally consistent. Every R7-added code path I traced is
reachable or an explicitly-documented defensive default; no contradictory logic;
no stale comment that a later round superseded; the four parallel-fix families
each use one consistent shape. Nothing rises to a P2. Notes below are pure-style
(P3, non-blocking).

## Dead-code audit

- **`_drive_manifest_item` map-less fallback (project_drive.py:222-226)** — NOT
  dead. Both `_drive_manifest_item` callers (lines 653, 682) pass the maps, so
  the `else` branches (`_current_version` / `_item_path`) are unreached *today*,
  but the function keeps `db` + a `None` default precisely so a future
  single-item caller works without building maps. The comment says exactly this
  and is accurate. `_current_version` / `_item_path` themselves remain live (3
  other callers: lines 532, 595, 959/1020/1035). Acceptable defensive default,
  not dead code.
- **`_set_rlimit` (auto_agent.py)** — live. Called by `_sandbox_rlimits`, which
  is wired as `preexec_fn` on the `subprocess.run` in `_tool_run_command`
  (guarded `if resource is not None`). The `resource = None` Windows fallback is
  exercised on the dev box. Functional end-to-end.
- **SpeakButton `aliveRef` (R7.17 headline)** — now FUNCTIONAL. R7.16 added the
  ref but never flipped it; R7.17 added the unmount `useEffect(() => () => {
  aliveRef.current = false; ... })` and the mid-fetch bail `if (myGen !==
  playGeneration || !aliveRef.current) return`. Both `playGeneration` and
  `aliveRef` are now read on the resolve path. No leftover no-op.
- **VoiceButton `wantRecordingRef` / `streamRef`** — both read and written across
  start/stop/unmount; the "released mid-prompt" branch in `stop()` is genuinely
  reachable (getUserMedia can resolve after release). Live.
- **`_recover_stranded_delivery` (delivery_upload.py)** — reachable: invoked from
  `_finalize_doc`'s `except` block, which can fire on commit OperationalError /
  disk-full. Not dead.
- **`create_drive_comment` "comment vanished" guard (project_drive.py:~1364)** —
  the comment honestly labels it "unreachable in practice, guard anyway so
  `_comment_out` never gets None." This is defensive-by-design, self-documented,
  and cheap; not flagged.
- **`parseServerDate` extraction** — clean. The local copy was deleted from
  web/RequirementDetail.tsx and moved to `shared/src/api/time.ts`; all 14
  call-sites import from `@yqgl/shared`. No orphan duplicate remains.
- No leftover from a superseded fix found. The `update_status` project-deleted
  block was *replaced* (not duplicated) by `_ensure_requirement_project_active`;
  old inline `proj = ...` check is gone.

## Duplication / consistency assessment

- **IntegrityError retry loops: FOUR (not five).** Sites:
  `requirements.py:118` (create, next_seq), `meetings.py:486` (insight confirm,
  next_seq), `project_drive.py:1400` (drive-comment, next_seq),
  `project_drive.py:859` (drive-upload, version_no). All share ONE shape:
  `for _ in range(5)` → build row → `db.flush(); break` → `except IntegrityError:
  db.rollback()` + reload the ORM anchor object. Consistent. A shared helper
  would have to parameterize (a) the row-builder closure, (b) which object to
  reload after rollback, (c) the commit/post-success work — the four bodies
  diverge enough (different anchors, different commit boundaries, drive-comment
  + meeting also commit a phase-1 row first) that extraction would add a
  callback abstraction heavier than the duplication. Site-specific repetition is
  the right call here. NON-BLOCKING.
- **Upload-orphan try/except guards: consistent.** drive-upload finalize,
  meeting finalize both use `try: merge … except BaseException: path.unlink
  (missing_ok=True); raise`. delivery-upload uses tmp+`os.replace` (immune by
  design) plus `_rollback_status()` on the post-CAS window. The comments in each
  cross-reference the others ("delivery_upload uses tmp+os.replace and is already
  immune"). One coherent family, intentional shape variance keyed to the actual
  failure mode. CLEAN.
- **Token / staleness guards (TS): one idiom, two legitimate variants.**
  (a) Monotonic `reqTokenRef`/`searchTokenRef`/`refreshTokenRef`/`playGeneration`
  for out-of-order async resolution (Hub, AssigneeSelector, web+tauri
  RequirementDetail, Knowledge search, SpeakButton). (b) `let alive = true`
  effect-cleanup flag for unmount (useEvent, FileAttachRail, Calendar,
  ChatHistory, SpeakButton/VoiceButton unmount). Same mental model; the
  ref-counter vs boolean split tracks "supersede" vs "unmount" correctly. The
  `canAttachClientToken` in tauri.ts is a *different* concept (credential
  scoping, not request ordering) and is correctly named to avoid confusion.
  Consistent.

## Stale-comment check

No stale comments found. Spot-checked the spots most at risk of being
superseded across 17 sub-rounds:

- `confirm_meeting_insight` for/else: comment "Retry on next_seq race…" still
  matches; the new `except Exception` (non-IntegrityError) re-raises immediately
  and does NOT break the `for…else` "could not allocate code" path — verified the
  control flow, no contradiction.
- delivery `_finalize_doc` exception comment accurately describes "this task
  carries NO job_id, restart sweep can't reach it" — and `main._resume_stuck_jobs`
  does now have the matching jobless `delivery_doc_pending` sweep the comment
  refers to. Comment and code agree across the two files.
- `auto.py` `_mark_auto_failed` comments ("status-aware… won't clobber the
  delivered requirement") match the actual `if r.status != "ai_processing"`
  branch added in the same round. The old "Same cancel-aware guard as the inline
  failure path above" line was correctly *removed* when the logic changed.
- notifications.py change-detection comment matches the `content_changed`
  computation field-for-field.

## P3 / style notes (non-blocking)

- `from sqlalchemy.exc import IntegrityError` is imported function-locally inside
  `finalize_drive_upload` and `create_drive_comment` (project_drive.py), while
  delivery_upload.py imports it module-top. Harmless (lazy import avoids an
  unused top-level symbol in a large module) but inconsistent. Pure style.
- `import threading as _threading` placed mid-file (project_drive.py:~152)
  rather than with the top imports. Deliberate co-location with the reindex
  debounce state it supports; readable, just unconventional. Pure style.
- The `_reindex_state` debounce (running/dirty flags + lock) is the single most
  elaborate R7 addition. I checked it for over-engineering: the coalescing IS
  justified (bulk paste/delete fire `schedule_project_reindex` per-item; without
  it 50 items = 50 full reindexes). The worker-owns-`running` design correctly
  avoids the sticky-flag leak its own docstring calls out. Not over-built for
  the stated bulk-op reality. No change recommended.
- `_download_entry` / multi-platform manifest (main.py) is more general than the
  current 2 platforms, but the generality is load-bearing (Windows + macOS
  entries already use every parameter incl. the external-fallback path for
  macOS). Not speculative. Fine.

Conclusion: the R7 series lands clean. Recommended action for the frozen tree:
**proceed — no structural change warranted.**
