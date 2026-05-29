# R7 Round 14 — Frontend confirmation

HEAD `580754c`, tree clean. Round 1 of the final 4-consecutive-clean
confirmation sequence. No frontend code changed since R13 (R13 reviewed only
backend + the SSE-handler audit; the last frontend touch was R7.11, verified
in R12 frontend.md). This is a fresh from-scratch re-derivation, not a
re-read of prior verdicts — I re-walked every hook, effect, listener, timer,
form, and SSE consumer in `shared/` + `web/` + `client-tauri/web-src/`.

## Verdict: CLEAN

## tsc results (3 packages)

Each surface compiled with its own strict tsconfig (`strict`,
`noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`):

- `shared` — `tsc -p tsconfig.json --noEmit` → **exit 0**, no diagnostics.
- `web` — `tsc -b` (project refs pull `shared`) → **exit 0**.
- `client-tauri/web-src` — `tsc -p tsconfig.json --noEmit` (include glob also
  type-checks `../../shared/src`) → **exit 0**.

0 type errors across all three.

## Full-surface re-sweep (each angle: status)

- **useEffect cleanup / stale closures / dep arrays (both trees)** — PASS.
  All overlay listeners (`Modal`, `Drawer`, `Combobox`, `DropdownMenu`,
  `CommandMenu` ×2, `SpaceSwitcher`, `WelcomeTour`, `ProjectStateConfirm`,
  `SettingsDialog`) add+remove their `keydown`/`mousedown` symmetrically.
  App-level `keydown` (Ctrl+1/2) removed in cleanup. The
  `refresh()`-on-`[id]`/`[tab]`/`[view]` eslint-disabled effects are the
  established intentional pattern (refresh is recreated each render but
  re-running on id-change only is the desired behavior). `Clarify` autostart
  and `SpeakButton` autoplay effects are ref-guarded against re-fire, so the
  omitted `stream`/`speak` deps are safe. The two module-singleton handlers
  (`useTheme` matchMedia `change`, App `_badgeTimer`) are registered once per
  page load on app-lifetime singletons — not per-mount, cannot leak.
- **Async handlers: error surfacing / double-submit / busy** — PASS. Every
  mutation handler I checked sets a `busy`/`setBusy` (or per-action busy key)
  and clears it in `finally`, and surfaces failures via `toast`/`setErr`/
  `console.warn`. `QuestionCard.submit` has an explicit `if (busy) return`
  re-entry guard plus disabled-until-valid buttons. `DeliveryWizard.start`
  gates the button with `loading={busy}`. `Hub.claim/startDoing`,
  `TaskDetail.*`, `Inbox.markRead/readAll`, `Clarify.saveAssignees`,
  `NewRequirement.goNext` all guard + report. No silent swallow found.
- **SSE consumers (leak / reconnect / cleanup)** — PASS.
  `useReqStream` + `useChatStream` are single-sourced in `shared` (web copies
  are 1-line re-exports). `useReqStream`: `alive` flag guards
  setState-after-unmount, `reader.cancel()` + `ctrl.abort()` on cleanup,
  events capped at last 200. `useChatStream`: `abortRef` aborts prior run and
  aborts on unmount, `reader.cancel()` in `finally`. `useNotificationToasts`
  (web `/stream/me`) + `Dashboard` (`/stream`): both reconnect with capped
  exponential backoff (1s→30s, reset on successful connect), abort+cancel on
  cleanup, CRLF-stripped per-line `data:` framing, JSON.parse wrapped.
  Dashboard also pauses its 6s poll on `visibilitychange`. All Tauri
  `useEvent` consumers (App ×4, Hub, TaskDetail, Inbox, DeliveryWizard ×2,
  ProjectDrive) ride the `useEvent` helper, which holds the handler in a ref
  (no stale closure) and handles the unmount-before-`listen()`-resolves race
  (`if (!alive) d()`). All push-driven refreshes are read-only/token-guarded —
  no event→refresh→event loop.
- **List keys** — PASS. 5 `key={i}` usages (`Avatar` group, `ProjectPulse`
  risk bullets, `AILiveView` SSE log, `Skeleton` placeholders, `Knowledge`
  citations) are all display-only or append-only — none reorderable/splice-able.
  Every dynamic data list uses a stable id (`r.id`, `n.id`, `it.id`, etc.).
- **Forms: validation / disabled-until-valid / submit** — PASS.
  `NewRequirement` validates per step with inline error messages and a busy
  guard during draft creation; `QuestionCard` disables submit on
  `busy || !value.trim()`; `DeliveryWizard` defaults+confirms the folder.
- **Timezone** — PASS. `parseServerDate` (Z-append + NaN→null guard) is used
  for the nullable/displayed server dates. The inline `new Date(x + "Z")` uses
  (Dashboard, ProjectView, DeliverablesTab) are all on the non-nullable,
  always-valid `created_at` field, and `toLocalInput` carries its own NaN
  guard — matching the brief's "safe inline +Z" allowance. Pre-existing, no
  double-Z risk (backend emits naive UTC).
- **a11y** — PASS. Icon-only buttons carry `aria-label` (TitleBar min/max/
  close, SpeakButton play/stop, error icon). Decorative icons are
  `aria-hidden`. `Modal` traps Tab focus, closes on ESC, restores focus on
  close, `role="dialog"`/`aria-modal`; `Drawer`/menus close on ESC.
- **Memory: listeners / intervals / timeouts / readers** — PASS. Dashboard
  interval + visibility listener cleared; `ProjectMeetings` interval cleared
  with `alive` flag; `AdminPanel`/`AssigneeSelector` debounce timers cleared;
  `SpeakButton` revokes object URLs (single module-level audio); all stream
  readers cancelled. The only un-cleared `setTimeout` (RequirementDetail:536
  re-poll after createTaskPlan) is a deliberate fire-and-forget into a
  setState-guarded parent refresh — P3 at most, pre-existing, unchanged.
- **Type safety: no new `any`, no `@ts-ignore`** — PASS. Zero
  `@ts-ignore`/`@ts-expect-error`/`@ts-nocheck` in source. All `any` are
  pre-existing and bounded (`catch (e: any)`, `useEvent<any>` push payloads,
  SSE `data: any`, runtime-detect `(window as any).__TAURI_INTERNALS__`).
  No frontend file changed since R13, so no new `any` could have been
  introduced. The eslint-disable lines are exclusively the reviewed
  refresh-on-id and autoplay patterns.

## Findings

None. CLEAN.

Re-derived the entire frontend surface from every requested angle (effects,
async error/busy/double-submit, all SSE/event consumers, list keys, forms,
timezone, a11y, memory, type safety) and ran `tsc` to 0 errors on all three
packages. No defect found and no regression from the R12/R13 baseline. The
surface remains as clean as it has been since R7.5. Streak intact (R14 = clean).
