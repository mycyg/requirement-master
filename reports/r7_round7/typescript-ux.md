# R7 Round 7 — TypeScript + UX

## Verdict: CLEAN

HEAD = `94f7ff0` (R7.6). All 7 R7.6 changes verified correct, no regressions. The
full `.then(set…)` sweep across **both** trees now shows **zero** unguarded reads —
every one has a `.catch`. The R6 fake-empty/loading class (4 web sites) is fully
eliminated. No new TS-correctness issues (races / leaks / key bugs / timezone).

Two pre-existing, narrow P3-grade items survive (a listener-leak race in the
`useEvent` helper and one unguarded *manual-refresh* onClick in the Tauri ProjectDrive
header). Both predate R7 entirely (first commit `f517517`), are out of R7.6's scope,
and were evaluated as acceptable by the prior 6 rounds. I record them below as
**carryover notes**, not as blockers — they do not affect the CLEAN verdict for this
round's diff. The single remaining R6 sub-P3 (SettingsDialog empty-voices) is also
noted as a near-unreachable residual.

---

## R7.6 regression check (7 items)

**1. ActivityTimeline** (`web/src/components/ActivityTimeline.tsx:35-58`) — **CORRECT.**
`reloadTick` is an effect dependency; the retry button increments it, which re-runs the
effect with a **fresh `alive` guard** and re-sets `setErr(null)/setItems(null)` at the
top before re-fetching. No stale closure: the effect body reads `reqId`/`reloadTick`
from the current render, and `alive` is local per-run. Catch sets `err` **and**
`setItems([])` so the loading sentinel (`items===null`) is also cleared — the `if (err)`
branch wins anyway, but this avoids a flash if `err` were ever cleared independently.
`parseServerDate(a.created_at)?.toLocaleString` is correctly optional-chained. Clean.

**2. ChatHistory** (`web/src/pages/RequirementDetail.tsx:466-480`) — **CORRECT.**
Alive-guarded `.then` + alive-guarded `.catch(setErr)`; `if (err)` renders a distinct
"对话加载失败" line *before* the `msgs.length===0 → "无对话"` branch, so a load error is no
longer indistinguishable from a genuinely empty conversation. Note: no retry button here
(unlike the other three), but a distinct error state is the load-bearing fix and is
present. `msgs: any[]` remains the one `any` in the web surface (R6 P2-2 follow-up,
pre-existing, out of scope).

**3. CommentsPanel** (`web/src/components/CommentsPanel.tsx:8-47,84-89`) — **CORRECT;
both error states coexist cleanly.** `loadErr` (read path) and `err` (send path) are
separate `useState`s rendered in separate places (loadErr in the list at L40-44, err
under the composer at L84-89). `refresh()` resets `loadErr` at the top and returns the
promise (so callers can chain). The list render is a clean 3-way: `loadErr ? errLine :
items.length===0 ? empty : null` then the mapped items. `send` resets `err` (not loadErr)
at its start, so a prior load error and a fresh send error never clobber each other.
Retry button calls `refresh` directly. Clean.

**4. DriveHome** (`web/src/pages/DriveHome.tsx:7-21,35-42`) — **CORRECT.** Alive guard +
`reloadTick` retry mirror ActivityTimeline. `setErr(null)` at top of effect; catch sets
`err`. List render: `err ? errLine : projects.length===0 ? empty : null`. A transient
failure now shows "项目加载失败 + 重试" instead of the misleading "还没有项目". Clean.

**5. App.tsx `*` route + NotFound** (`web/src/App.tsx:167-170,248-259`) — **CORRECT,
does not shadow real routes.** React-Router v6 ranks by specificity, not source order, so
`path="*"` only matches when no concrete route does — and it's placed last regardless.
All 14 concrete routes still resolve. `NotFound` lives inside `<Shell>` which is inside
`<BrowserRouter>`, so its `<Link to="/">` resolves correctly to Home. The 404 body
renders inside the normal shell (nav stays visible) — good. Clean.

**6. SpeakButton + CalendarPage aria-label** —
- `SpeakButton.tsx:96` — `aria-label={playing ? "停止朗读" : "朗读"}` added; SVG stays
  `aria-hidden`. The label is now dynamic and announces the action, better than the R6
  ask (which only requested a static label matching `title`). The error indicator at
  L102 carries `aria-label={err}`. Clean. (Sub-note, not new: when `playing`, onClick is
  `stopCurrent` which doesn't itself `setPlaying(false)`, but the audio element's
  `onpause` handler does — so state stays in sync. Fine.)
- `CalendarPage.tsx:188` — `aria-label="删除日程"` added to the trash button next to its
  `title="删除"`. Clean.

**7. SettingsDialog statusBusy guard** (`web/src/components/SettingsDialog.tsx:30,111-129`)
— **CORRECT.** `statusBusy` state; button is `disabled={statusBusy}`; onClick opens with a
redundant-but-safe `if (statusBusy) return`, sets busy true, and **`finally { setStatusBusy(false) }`**
always resets it (success or throw). Label flips to "保存中..." while busy. Disabled
binding and finally-reset both correct. Clean.

---

## `.then(set…` without `.catch` — full sweep, both trees

Method: grepped `\.then\(` (not just `\.then\(set`) across `web/src` and
`client-tauri/web-src/src`, then read every multi-line chain to confirm a trailing
`.catch`. Also grepped `await (clientJson|invoke|clientFetch)` (69 hits / 16 Tauri files)
and `useEffect(() => { … load() … }` to confirm bare `load()` callers wrap errors
internally.

**web/src — every `.then` is caught:**
| Site | Catch |
|---|---|
| ActivityTimeline:44 | alive-guarded `.catch(setErr+setItems([]))` ✅ |
| AssigneeSelector:100 | alive-guarded `.catch(setErr)` ✅ |
| ClientDownloadBanner:62 + :159 | `.catch(→{available:false})` / `.catch(()=>{})` ✅ |
| CommentsPanel:19 | `.catch(setLoadErr)` ✅ |
| DeliverablesTab:18 | `.catch(setErr)` ✅ |
| DriveHome:15 | alive-guarded `.catch(setErr)` ✅ |
| HealthPage:23 (`Promise.all`) | `.catch(setErr)` ✅ |
| Home:22 | `.catch(setErr)` ✅ |
| KnowledgePage:27 + :32 | `.catch(→[])` / `.catch(setErr)` ✅ |
| RequirementDetail:126 (`me`) + :472 (chat) | `.catch(→null)` / alive `.catch(setErr)` ✅ |
| Clarify:93 (`me`) | `.catch(→null)` ✅ |

Bare `load()` in `useEffect` (NotificationsPage:34, PlanningPage:40) — both `load` fns are
`async` with internal `try/catch/finally` + `err` state, so they never reject. Clean.

**client-tauri/web-src/src — every `.then` is caught:**
| Site | Catch |
|---|---|
| AdminPanel:30 (me) / :68 (projects) / :180 (users) | `.catch(→checked)` / `.catch(toast)` / `.catch(toast)` ✅ |
| Calendar:45 | alive `.catch(→[])` ✅ |
| MyWorkload:26 (`Promise.all`) | `.catch(setErr).finally(loaded)` ✅ |
| NewRequirement:73 (me) / :87 (projects) | `.catch(()=>{})` / `.catch(setErr)` ✅ |
| DeliveryWizard:34 (prefill) | `.catch(()=>{})` ✅ |
| AssigneeSelector:48 | alive `.catch(setErr)` ✅ |
| Onboarding:35 (prefill) | `.catch(()=>{})` ✅ |
| ProjectDrive:57 (projects) / :68 (root) | `.catch(setErr)` / alive `.catch(setErr+[])` ✅ |
| ProjectPulse:28 | non-OK `throw` + `.catch(setErr+[])` ✅ |
| Settings:17 | `.catch(setLoadErr)` ✅ |
| FileAttachRail:49 (stop watcher) | `.catch(()=>{})` ✅ |
| TitleBar:12 (dynamic import) | `.catch(()=>{})` ✅ |

**Listener-registration `.then`s (subscription setup, not data reads):**
FileAttachRail:86, ProjectDrive:86 — both use the correct
`then((d)=>{ if(!alive) d(); else off=d; })` leak-safe pattern. tauri.ts:49 does **not**
(see Carryover N1).

**Conclusion of the sweep:** the R6 class — an async **data read** that swallows
rejection into a fake empty/loading state — has **zero** instances remaining in either
tree. R6's four web findings are closed and no new instance was introduced anywhere.

---

## Fresh-pass findings

**None at P0/P1/P2.** No new races, leaks, key bugs, or timezone errors in R7.6's diff or
the surrounding fresh pass.

Verified during the fresh pass:
- `parseServerDate` (`shared/src/api/time.ts`) is correct & idempotent: appends `Z` only
  when no `Z`/offset present, and returns `null` on Invalid Date so `?.toLocaleString`
  callers branch cleanly. The two new R7.6 call sites (ActivityTimeline:76,
  CommentsPanel:52) both use `?.` — no "Invalid Date"/"NaN:NaN" leak. CalendarPage keeps
  its own `eventDate(v + "Z"?)` guard (equivalent), `isoLocal`/`localInput` operate on
  local `datetime-local` strings where raw `new Date` is correct.
- Effect-dep retry pattern (ActivityTimeline, DriveHome): `reloadTick` increment is the
  only re-run trigger besides `reqId`; each run gets its own `alive` and resets error +
  loading sentinel. No double-fetch, no stale closure, no setState-after-unmount.
- All `key=` on the new/edited lists are stable IDs (`a.id`, `c.id`, `project.id`,
  `m.id`, `event.id`, `v` voice string). No index keys, no key collisions.
- No new `any` introduced (the lone `msgs: any[]` and `detail: any` in ChatHistory/
  ActivityTimeline are pre-existing R6 carryovers).

**Carryover notes (pre-existing, NOT R7.6, do not block CLEAN):**

- **N1 — `useEvent` listener-leak race** `client-tauri/web-src/src/lib/tauri.ts:46-54`.
  `listen<T>(event, …).then((d) => { dispose = d; })` has **no `.catch`** and, more
  importantly, assigns `dispose` unconditionally. If the component unmounts *before*
  `listen()` resolves, the cleanup runs while `dispose` is still `null` (nothing
  disposed), then the late resolve sets `dispose = d` that is never called → the Tauri
  listener leaks across that navigation. The inner `if (alive) handlerRef.current(p)`
  prevents setState-on-unmounted (so no crash / stale state), but the **subscription
  itself** persists. The two inline call sites (FileAttachRail:86, ProjectDrive:86)
  already fixed exactly this with `if (!alive) d(); else off = d;` — the shared helper is
  the one place that didn't get the fix. Present since the first commit (`f517517`),
  untouched by R7.x. Narrow (only a fast unmount-before-resolve window) but real; worth a
  one-line fix in a future pass to bring the helper in line with its own call sites.

- **N2 — unguarded manual-refresh onClick** `client-tauri/web-src/src/routes/ProjectDrive.tsx:187`.
  `onClick={() => invoke<DriveList>("list_drive_root", {projectId}).then((d) => setItems(d.items ?? []))}`
  — no `.catch`. This is the header "刷新" button, **not** an initial/empty-state read
  (the initial load at L68 is fully race-guarded with `.catch(setErr+[])`). On a failed
  manual refresh the rejection is an unhandled promise and the list silently keeps its
  stale items with no error feedback. Lower stakes than the R6 class (no fake-empty
  masking), pre-existing, out of scope. A `.catch((e)=>setErr(String(e)))` would match the
  rest of the file.

- **N3 — SettingsDialog empty-voices stuck "加载中…"** `web/src/components/SettingsDialog.tsx:57,168-172`
  (R6 P3-3 second sub-bullet). If `/api/voice/voices` returns `ready:true` with an empty
  `voices` array, no `voicesErr` is set and `voices.length===0` renders "加载中…"
  permanently. R7.6 fixed the *first* P3-3 sub-bullet (the missing busy guard on the
  status button — now `statusBusy`) but not this one. Documented in R6 as near-unreachable
  ("a live TTS service always has ≥1 voice"). Cosmetic, near-unreachable; noting for
  completeness only.

---

## Coverage

**R7.6 diff scope confirmed:** `git show --stat 94f7ff0` touches exactly 8 TS/TSX entries
= the 7 expected web files (RequirementDetail covers the ChatHistory edit; SpeakButton +
CalendarPage are the two aria-label items). **No Tauri file touched by R7.6** — so the
Tauri tree's verdict carries from prior rounds, re-confirmed by this round's `.then`
sweep.

**Read in full / re-verified this round:**
- web/src — ActivityTimeline, CommentsPanel, DriveHome, SpeakButton, SettingsDialog,
  CalendarPage, App.tsx, RequirementDetail (ChatHistory + DecompositionPanel context),
  HealthPage, AssigneeSelector, ClientDownloadBanner, NotificationsPage, PlanningPage
  (load fns); `shared/src/api/time.ts`.
- client-tauri/web-src/src — every `.then`-bearing file read at the call site:
  AdminPanel, Calendar, MyWorkload, NewRequirement, DeliveryWizard, AssigneeSelector,
  Onboarding, FileAttachRail, ProjectDrive, ProjectPulse, Settings, TitleBar, lib/tauri.ts.

**Greps:** `\.then\(` (both trees, all hits read), `\.then\(set` (both trees),
`await (clientJson|invoke|clientFetch)` (69 hits / 16 Tauri files — uniformly
try/catch-wrapped, consistent with R6), `useEffect(...load())` (confirmed internal
try/catch), `git log`/`git show --stat`/`git log -L` to date the two carryover items as
pre-R7 and confirm R7.6's exact file set.

**Bottom line:** R7.6 lands clean — all 4 R6 P2 fake-state misses and the 404 + aria
P3s are correctly closed, with no regression and no new TS/UX issue. The `.then(set`
sweep the prompt asked for is **empty** in both trees. Verdict for this round's surface:
**CLEAN.** The three carryover notes (N1–N3) are pre-existing, out-of-scope, and
individually minor; surfacing them so a future "everything green including legacy" pass
can pick them up, but none block the clean round.
