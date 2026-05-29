# R7 Round 8 — Frontend deep sweep

HEAD `07b5760` (R7.7). Trees audited: `web/src`, `client-tauri/web-src/src`, `shared/src`.

## Verdict: CLEAN

No P0/P1/P2 found. Three P3 consistency notes only (all pre-existing, none
regressions, none ship-blocking). The R7.7 fixes are correct and complete.

---

## R7.7 regression check (3 items) — ALL VERIFIED CORRECT

**N1 — `client-tauri/web-src/src/lib/tauri.ts` `useEvent` (lines 46-59):** PASS.
`listen(...).then((d) => { if (!alive) d(); else dispose = d; })` with cleanup
`() => { alive = false; if (dispose) dispose(); }`. No double-dispose path:
- unmount-before-resolve → `!alive` branch disposes `d` immediately; cleanup
  already ran with `dispose === null` (no-op). Subscription closed. ✓
- normal lifecycle → `dispose = d`; cleanup calls it exactly once. ✓
`dispose` is never reassigned after being set, and `d()`/`dispose()` are never
both reachable for the same `d`. Leak closed, idempotency intact. This helper
backs every `useEvent` caller (App, Inbox, TaskDetail, DeliveryWizard) — the
fix is correctly load-bearing.

**N2 — `client-tauri/web-src/src/routes/ProjectDrive.tsx` 刷新 button (lines 187-192):**
PASS. `onClick` now does `setErr(null)` then
`invoke(...).then((d) => setItems(d.items ?? [])).catch((e) => setErr(String(e)))`.
Failed manual refresh now surfaces to the `{err && ...}` banner (line 221)
instead of being a console-only unhandled rejection. Matches the guarded
initial-load effect (lines 62-72). ✓

**N3 — `web/src/components/SettingsDialog.tsx` `voicesLoaded` flag:** PASS.
Flag is reset to `false` at the top of the `[open]` effect (line 37) and set
`true` in `finally` with an `alive` guard (lines 63-67). Because reset lives
inside the `[open]`-keyed effect, it correctly re-initializes on every re-open.
Empty-after-load renders "暂无可用音色"; still-loading renders "加载中…"
(line 180). The permanent-spinner bug is gone. ✓

---

## useEffect / async / list / form / memory / a11y deep audit

**useEffect cleanup & deps — CLEAN.** Every async-subscription effect uses the
`alive`/`dispose` (or AbortController + reader.cancel) pattern:
- `shared/hooks/useChatStream.ts` — `abortRef` aborted on new run AND on unmount
  (line 123); reader cancelled in `finally` (line 111). ✓
- `shared/hooks/useReqStream.ts` — `alive` guard in `flush`, reader.cancel +
  ctrl.abort on cleanup (lines 68-75). ✓
- `web/pages/Dashboard.tsx` — visibility-gated interval with idempotent
  start/stop + cleanup (lines 60-84); SSE reconnect loop with exponential
  backoff, abort + reader.cancel on unmount (lines 86-135). ✓
- `client-tauri/components/FileAttachRail.tsx` — gold-standard: outer+inner
  `alive` guards, watcher auto-stop effect, `Promise.allSettled` batch upload. ✓
- `web/pages/ProjectMeetings.tsx` — job-poll interval gated on
  `status === "processing"`, alive guard + clearInterval (lines 45-64). ✓
- `client-tauri/components/AssigneeSelector.tsx` + `AdminPanel.tsx` — debounced
  search with `clearTimeout` + alive guard. ✓
No stale-closure risks: `useEvent` holds `handlerRef.current` so `[event]`-only
deps still dispatch to the live closure (documented at tauri.ts:37-44).

**Async handlers — CLEAN.** Every mutating handler I traced surfaces errors and
guards busy state: TaskDetail (claim/start/reSync/save/addItem/addUpdate all
try/catch → toast, `loading={busy}`), Inbox (markRead/readAll log + `finally`
refresh, monotonic `reqTokenRef` race guard), FileUpload, DeliveryWizard.start,
SettingsDialog status save (`if (statusBusy) return` re-entry guard). Sampled
all `.then(` chains across `*.tsx` — each has a `.catch` (AdminPanel:69/181,
NewRequirement:92, ProjectDrive client:59/70/92, Home/CommentsPanel/etc).

**List renders — CLEAN.** All list keys are stable domain IDs (`it.id`, `n.id`,
`u.id`, `w.id`, `o.value`, `s.key`), never array index. Reorder-safe.

**Forms — CLEAN.** Disabled-until-valid is consistent (NicknameDialog
`!value.trim()`, ProjectStateConfirm typed-name match, AdminPanel slug regex
+ warn toast, MyWorkspace 记一笔 `disabled={!newUpdate.trim()}`,
NewRequirement per-step `validateStep`). Enter-to-submit present where it makes
sense (NicknameDialog, MyWorkspace add-item, Combobox/CommandMenu). The wizard
flows (DeliveryWizard, NewRequirement) reset state on open.

**Memory — CLEAN.** No uncleaned listeners/intervals/timeouts/readers:
- Modal/Drawer/Combobox/DropdownMenu/SpaceSwitcher/WelcomeTour/CommandMenu
  keydown & mousedown listeners all removed in cleanup.
- Toast (`shared/ui/Toast.tsx`) clears every pending timer on host unmount
  (lines 76-80) and pops itself off `pushStack`.
- App.tsx `_badgeTimer` is a singleton trailing-edge debounce (cleared on each
  re-entry) — bounded to one live timer, not a leak.
- `shared/hooks/useTheme.ts` module-level `mm.addEventListener("change")`
  (lines 32-37) is a deliberate page-lifetime singleton (bound once at module
  load, drives global `data-theme`), NOT per-mount — does not accumulate. The
  per-component `listeners` Set is correctly add/delete'd. Acceptable.

**a11y — CLEAN.** Every icon-only button I found has an accessible name:
ProjectStateConfirm close (`aria-label="关闭"`), SettingsDialog close
(`aria-label="关闭设置"`), Toast close (`aria-label="关闭"`), AssigneeSelector
chip-remove (`aria-label={移除 ${nickname}}`), FileAttachRail Switch
(`aria-label="文件夹监听"`). Decorative icons carry `aria-hidden`. Shared
`Modal` implements ESC-to-close + Tab focus trap (both directions) + focus
restoration to the trigger (lines 51-86); `Drawer`/`WelcomeTour`/`CommandMenu`
inherit it. WelcomeTour progress dots use `role="tab"`/`aria-selected`.

---

## Findings

### P2+
None.

### P3 (consistency / polish — not regressions, not ship-blocking)

- **P3-1 — Bespoke web modals lack ESC/focus-trap that shared `Modal` provides.**
  `web/src/components/SettingsDialog.tsx`, `NicknameDialog.tsx`, and
  `ProjectStateConfirm.tsx` are hand-rolled overlays (own `fixed inset-0`),
  not the shared `Modal`. They have backdrop-click-to-close (Settings) /
  X-button (Settings, ProjectStateConfirm) but no Escape-to-close and no Tab
  focus trap, unlike every Modal-based dialog in the app. (NicknameDialog is a
  first-run gate so "no close" is intentional; the focus-trap gap is the only
  note there.) Low impact, keyboard-a11y consistency only. Pre-existing.

- **P3-2 — `MyWorkspace` local form state does not re-sync when `ws` prop
  changes.** `client-tauri/web-src/src/routes/TaskDetail.tsx:351-355` seeds
  `phase/pct/note/blocked` from `ws.*` via `useState` with no resync effect and
  no `key={ws.id}` on `<MyWorkspace>`. An SSE-driven `refresh()` that returns a
  changed workspace won't update the visible fields. This is the *viewer's own*
  workspace (sole writer), so it's arguably correct (avoids clobbering an
  in-progress edit) — flagging only because the divergence is implicit, not
  documented. Pre-existing.

- **P3-3 — `shared/ui/CommandMenu.tsx` keydown effect re-binds every render.**
  Deps `[open, flat, idx, onClose]` include `flat` (a fresh array each render),
  so the window keydown listener is removed/re-added on every keystroke.
  Functionally correct and cleaned up; only a micro-churn. `flat.indexOf(it)`
  inside the render map (line 104) is O(n²) but lists are tiny. Pre-existing.

---

## Conclusion

R7.7 closed the three carryover blemishes correctly and introduced no
regressions. The fresh full-tree pass — probing useEffect cleanup, async error
handling, list keys, form validation, memory (listeners/intervals/timeouts/
readers/AbortControllers), and a11y (icon-button names, focus trap, Esc) across
both web and client-tauri plus shared — surfaced nothing above P3. The defensive
patterns (alive guards, monotonic tokens, abort+cancel, toast/setErr surfacing,
busy gates, shared Modal focus management) are applied consistently.

**CLEAN.** The clean-streak holds.
