# R7 Round 10 — Frontend + simplicity final

Range reviewed: `c884b60..a6f8ada` (R7 → R7.9), filtered to `*.py *.ts *.tsx *.rs *.md` excluding `reports/`.
Web typecheck: `tsc --noEmit -p web/tsconfig.json` → EXIT 0 (clean). client-tauri/web-src deps not installed in this worktree (build artifact); useEvent fix reviewed by hand.

## Verdict: SHIP-READY

The R7 fixes are clean, minimal, and internally consistent. No correctness regressions found in the
frontend or in the R7-introduced backend code. The items below are all P3/cosmetic cleanups — none
block ship. The single genuinely-dead path (`_item_path` + the no-map fallback) is harmless (it's a
correct fallback that simply has no live caller) and could be deferred to a post-ship sweep.

---

## R7 fixes: over-engineering / dead-code / duplication audit

### Dead code — CONFIRMED (P3, the prompt's suspicion is correct)
`app/routers/project_drive.py`
- `_item_path` (line 182, the per-ancestor DB-walk) is referenced in exactly ONE place: line 223,
  the `else` branch of `_drive_manifest_item` that fires only when `item_map is None`.
- Both live callers of `_drive_manifest_item` (lines 650 `drive_manifest`, 679 `drive_changes`)
  ALWAYS pass `item_map=` and `version_map=`. There is no other caller.
- Therefore the `item_map is None` fallback inside `_drive_manifest_item` (line 222
  `version = _current_version(db, item)` and line 223 `_item_path(db, item)`) is unreachable in
  practice, and `_item_path` itself is effectively dead.
- This is defensive-fallback over-engineering: the maps were made `Optional` "just in case" but no
  caller exercises the None path. Minimal cleanup would be to make `item_map`/`version_map`
  required params and delete `_item_path` + the `if version_map is not None` branch. Low priority —
  the dead branch is correct, just unused, and `_current_version` is still used by 6 other sites so
  only `_item_path` actually goes away. Safe to defer.

### Over-engineering — the additions are justified, NOT over-built
- `_build_manifest_maps` (2 queries replacing ≈(depth+1)×N per 45s poll): proportionate to a real
  measured hot path (commit msg cites ~3500 queries/poll/client on a 500-file drive). Cycle guard in
  `_item_path_from_map` is a one-liner (`seen` set) — appropriate, not gold-plating.
- `_MANIFEST_MAX_ITEMS = 50000` log-only ceiling: correct call to LOG rather than silently LIMIT
  (truncating would drop files from sync). Minimal.
- `schedule_project_reindex` / `_reindex_project_in_background` debounce (running/dirty flags): this
  is the heaviest new abstraction. It IS more than a bare `background.add_task(rebuild...)`, but the
  coalescing is warranted — bulk paste/delete fans out 50 schedule calls per request and an
  un-debounced reindex would run the full index rebuild 50× per burst. The worker-owns-`running`
  design correctly avoids the sticky-flag leak it documents. Verdict: justified, not YAGNI.
- `_sandbox_rlimits` / `_set_rlimit` (R7.9): two small helpers, each does one thing, `import resource`
  guarded for Windows dev. The `_set_rlimit` hard-cap clamp (`min(value, hard)`) is necessary
  correctness, not embellishment. Fine.
- Notification content-change guard: a flat boolean OR of 6 field comparisons — the simplest form
  that fixes the "badge never clears" bug. Not over-built.

### Duplication — the 3 next_seq retry loops (P3, real but low-value to fix)
Three structurally-identical `for _ in range(5): proj.next_seq += 1; code = f"{slug}-{n:03d}";
db.add(Requirement(...)); try: db.flush()/break except IntegrityError: db.rollback()` loops now exist:
- `app/routers/requirements.py:118` (`create_requirement`)
- `app/routers/meetings.py:~471` (`confirm_meeting_insight`)
- `app/routers/project_drive.py:~1360` (`create_drive_comment`, added R7.8)

R7.8 deliberately *mirrored* the existing two rather than extracting a helper, and the commit message
calls this out explicitly ("the same 5-try IntegrityError retry the other two next_seq writers use").
A shared `allocate_requirement_code(db, project_id, build_requirement_fn) -> Requirement` helper would
remove ~30 lines of triplication AND guarantee the 3 sites can't drift. BUT each loop also does
site-specific post-flush work (assignments+notifications in requirements; insight linkage in meetings;
comment upgrade in drive) inside or around the loop, so the extraction isn't a clean lift. Reasonable
to ship as-is and refactor later; flagging as the single best post-ship simplification.

### parseServerDate — consolidation done well, adoption partial (P3, pre-existing)
- R7 correctly extracted the duplicated inline `parseServerDate` (was a private copy in
  RequirementDetail.tsx) into `shared/src/api/time.ts` and adopted it in the 4 R7.6-touched files
  (ActivityTimeline, CommentsPanel, DriveHome via RequirementDetail, ChatHistory). Good de-dup, and
  the shared version is NaN-safe + idempotent on `Z`/offset values.
- However 4 OTHER files still use the raw `new Date(x + "Z")` inline form:
  `web/src/pages/Dashboard.tsx` (×2), `web/src/pages/ProjectView.tsx`, `web/src/components/DeliverablesTab.tsx`.
  These were NOT touched by R7 (verified `git diff --stat` empty), so this is pre-existing
  inconsistency, not an R7 regression. The inline form isn't NaN-safe, but it's only ever applied to
  `created_at` (always populated), so practical risk is nil. Worth a one-line sweep to finish the
  migration, but out of R7 scope.

---

## Error-state pattern consistency (the 4 R7.6 fixes)

The 4 fixes (ActivityTimeline, CommentsPanel, DriveHome, ChatHistory-in-RequirementDetail) are
consistent *in intent* (every async read now has a `.catch` that surfaces a distinct error instead of
masquerading as empty/loading) but use **two deliberate shapes**, matched to the host component:

- **alive-guarded effect + reloadTick retry**: ActivityTimeline, DriveHome. Both use
  `let alive = true; …; return () => { alive = false; }` plus a `reloadTick` state bumped by 「重试」
  that is an effect dependency. Identical pattern, identical 「…加载失败：{err}」+ underlined 重试 button.
- **refresh()-closure + retry calling refresh()**: CommentsPanel. It already had a `refresh()` used by
  the send flow, so the retry reuses it rather than introducing a tick. Sound — reusing the existing
  refresh is simpler here than bolting on a tick.
- **alive-guard, no retry button**: ChatHistory. Shows 「对话加载失败：{err}」with no 重试. This is the
  one inconsistency: the other three offer retry, ChatHistory doesn't. Minor — ChatHistory is a small
  read-only sub-panel and re-opening the tab re-runs the effect — but for strict parity a 重试 here
  would cost one line. P3.

Assessment: this is *coherent variation*, not 4 random patterns. The alive-guard is uniform; the
retry affordance differs by 1 of 4 (ChatHistory). All four use the same red text + 失败 phrasing.
Acceptable to ship. The only nit is ChatHistory's missing 重试.

Note: DriveHome's catch sets `err` but NOT `items=[]`, whereas ActivityTimeline sets both `err` and
`items=[]`. Both render correctly (err branch wins the JSX), so this is harmless asymmetry, not a bug.

---

## Stale-comment check

Spot-checked every R7-added explanatory comment against final code — all accurate:
- `create_drive_comment` "Commit the pending_llm row BEFORE the multi-second LLM call": correct —
  `status="pending_llm"` is set at line 1320 before `db.commit()` at line 1332.
- "Phase 1: persist the comment as 'posted' NOW" / "Phase 2: allocate … 5-try retry": matches the
  two-commit structure exactly; the `draft_id is None` path correctly leaves status "posted" and logs.
- "Re-load the comment (rollback in the loop expires ORM state); it was committed in phase 1 so it
  always exists": accurate — phase-1 commit guarantees the row.
- `_item_path_from_map` docstring ("walks an in-memory map … cycle guard"): matches the `seen`-set impl.
- `_build_manifest_maps` "two queries total": matches (1 items query + 1 conditional versions query).
- `useEvent` comment "If the component unmounted before listen() resolved, dispose immediately":
  matches `if (!alive) d(); else dispose = d;`.
- SettingsDialog ESC "matching the backdrop-click affordance already present": verified — line 84 has
  `onClick={onClose}` on the backdrop div. Accurate.
- ProjectStateConfirm ESC "only when not mid-submit": matches `if (e.key === "Escape" && !busy)`.
- auto.py `_run_and_finalize` / `_mark_auto_failed` no-project-filter rationale: accurate and the
  asymmetry vs. the filtered `trigger_auto` is intentional and documented at both sites.
- notifications.py change-detection-guard comment: matches the 6-field OR + early `return existing`.
- `_sandbox_rlimits` comment (RLIMIT_NPROC omitted, network not blocked): consistent with the actual
  4 `_set_rlimit` calls and `prompts/auto_agent.md`.

No stale comments found.

---

## Final frontend correctness scan

- **R7.7 useEvent (tauri.ts)**: fix is correct. The `listen().then((d) => { if (!alive) d(); else
  dispose = d; })` closes the unmount-before-resolve leak; `handlerRef.current` indirection means the
  effect needn't re-subscribe on handler identity change. Matches FileAttachRail/ProjectDrive pattern.
- **R7.7 ProjectDrive 刷新**: `.catch((e) => setErr(String(e)))` added; `setErr(null)` cleared before
  the call. Correct, mirrors initial-load guard.
- **R7.7 SettingsDialog voices**: `voicesLoaded` set in `finally` (alive-guarded) cleanly separates
  "loading" from "loaded-but-empty". Reset to false on each open. Correct.
- **R7.8 modal ESC**: SettingsDialog guards `if (!open) return` and depends on `[open, onClose]`;
  ProjectStateConfirm (conditionally rendered, no `open` prop) guards `!busy` and depends on
  `[busy, onCancel]`. Both add+remove the listener correctly. No double-fire risk (only one modal
  mounted at a time). NicknameDialog intentionally excluded (documented). Correct.
- **R7.8/R7.9 RequirementDetail token guard**: `refreshTokenRef` bump + `isCurrent()` checks after
  each await (getRequirement, Promise.all, and in catch) correctly prevent a stale /r/A fetch from
  clobbering /r/B state. Sound — the ref is the right tool (survives renders, no re-render churn).
- **parseServerDate**: regex `/Z$|[+-]\d\d:?\d\d$/` correctly detects existing zone markers; NaN
  guard returns null for invalid input as the docstring claims. Callers use `?.toLocaleString(...)`
  so a null renders as empty string — acceptable.
- No `useEffect` missing-cleanup, no obvious stale-closure, no unhandled-rejection introduced by R7.
- `web` project typechecks clean (EXIT 0).

## Findings

| # | Sev | Location | Finding |
|---|-----|----------|---------|
| 1 | P3 | `project_drive.py` `_item_path` (182) + `_drive_manifest_item` None-fallback (222-223) | Dead in practice: only caller is the unreachable `item_map is None` branch. Make maps required, delete `_item_path`. Safe to defer. |
| 2 | P3 | `requirements.py:118`, `meetings.py:~471`, `project_drive.py:~1360` | 3 near-identical 5-try next_seq/code allocation loops. Extractable to one helper (~30 LOC saved) but each has site-specific surrounding work; defer to post-ship refactor. |
| 3 | P3 | `RequirementDetail.tsx` `ChatHistory` | Only one of the 4 R7.6 error states lacks a 重试 button. One-line parity fix. |
| 4 | P3 | `Dashboard.tsx`, `ProjectView.tsx`, `DeliverablesTab.tsx` | Pre-existing (not R7) inline `new Date(x+"Z")`; could adopt the now-shared `parseServerDate` to finish the migration. |

None are ship-blockers. R7 work is clean, minimal, and ship-ready.
