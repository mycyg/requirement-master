# R7 Round 3 — TypeScript

## Verdict

**NEEDS FIXES — 5 findings (0 P0, 1 P1, 4 P2).**

R7.2 (commit `d50bf12`) correctly fixed the Round-2 P1 (Tauri-client timezone skew) and P2-4 (RequirementDetail refresh race). Both the new `parseServerDate` helper and the 10 call-site swaps are clean and load cleanly off `@yqgl/shared`.

But re-reading the surface with fresh eyes turns up one P1 the prompt explicitly asked about — `parseServerDate` is missing the `NaN` validation that the *original* `web/src/pages/RequirementDetail.tsx` helper had (line 67: `Number.isNaN(date.getTime()) ? null : date`). Without that, a malformed `due_at` returns an Invalid Date object that's *truthy* but `getTime()`-NaN, so consumers like `Calendar.tsx:77` (which uses `?? new Date(0)` to fall back) print `"NaN:NaN"` on screen instead of cleanly hiding the bad event. Easy one-line fix.

Plus the four carryover P2s from Round 2 (P2-3 URL recompute, P2-5 FileAttachRail alive-guard, P2-6 Hub/Knowledge/Inbox tab-switch race) are all still unfixed because R7.2's scope was P1 + RequirementDetail only. And during the fresh pass I noticed **four additional `new Date(server)` sites in the WEB tree** that have the same naive-UTC bug R7.2 just fixed for the Tauri client — different surface, same skew. Belongs in the same sweep.

## R7.2 fix verification

### Fix 1: `shared/src/api/time.ts` `parseServerDate` helper — ALMOST CORRECT (see P1-4 below)

```ts
export function parseServerDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  if (typeof value !== "string") return null;
  // Already has a timezone marker → trust it.
  if (/Z$|[+-]\d\d:?\d\d$/.test(value)) return new Date(value);
  return new Date(value + "Z");
}
```

Edge-case audit:
- `""` → `!value` short-circuits → `null` ✓
- `undefined` → `!value` short-circuits → `null` ✓
- `null` → `!value` short-circuits → `null` ✓
- `"2026-05-29T10:00:00"` (the actual backend shape) → no zone marker → appends `Z` → parsed as UTC ✓
- `"2026-05-29T10:00:00Z"` (idempotent) → matches `Z$` → trusted ✓
- `"2026-05-29T10:00:00+08:00"` → matches `[+-]\d\d:\d\d$` → trusted ✓
- `"2026-05-29T10:00:00+0800"` → matches `[+-]\d\d\d\d$` → trusted ✓
- `"2026-05-29T10:00:00.123456"` (Python isoformat with microseconds) → no zone → appends `Z` → `"2026-05-29T10:00:00.123456Z"` → JS happily parses (millisecond rounding, microseconds truncated; correct enough) ✓
- `"abc"` → no zone → `"abcZ"` → **Invalid Date returned, NOT null** ⚠ — this is P1-4.

Regex is correct otherwise. Doesn't accidentally match a trailing `+0800` if someone shoves it on a *non*-date string (the surrounding `new Date(...)` would return Invalid Date in that case anyway).

The shared-export path (`shared/src/api/index.ts:3 export { parseServerDate } from "./time";`) is wired cleanly. Both `web/src/` and `client-tauri/web-src/src/` resolve it via the `@yqgl/shared` workspace alias.

### Fix 2: Tauri-client call-site swaps — ALL CORRECT

All 10 call-sites verified against the diff:

- `client-tauri/web-src/src/components/TaskCard.tsx:13` — `const due = parseServerDate(req.due_at);` replaces raw `new Date(req.due_at)`. Downstream `overdue` check and `dueTone` ternary read `due.getTime()` correctly (UTC-anchored). The fallback in line 60 `due.toLocaleString("zh-CN", { hour12: false }).slice(5, 16)` is now correct — formatted in viewer's local TZ from a properly-anchored UTC Date.
- `client-tauri/web-src/src/routes/TaskDetail.tsx:153` — `parseServerDate(req.due_at)?.toLocaleString(...)`. Optional chaining keeps the JSX safe on null.
- `client-tauri/web-src/src/routes/TaskDetail.tsx:493` — same pattern for `u.created_at` in the workspace updates list.
- `client-tauri/web-src/src/routes/MyWorkload.tsx:116` — `parseServerDate(r.due_at)?.toLocaleString(...)`. Clean.
- `client-tauri/web-src/src/routes/Inbox.tsx:129` — `parseServerDate(n.created_at)?.toLocaleString(...)`. Clean.
- `client-tauri/web-src/src/routes/Calendar.tsx:67` — `parseServerDate(e.end_at)` for the day-bucket filter. Now correct (previously bucketed events into wrong days near UTC-midnight).
- `client-tauri/web-src/src/routes/Calendar.tsx:77` — `parseServerDate(e.end_at) ?? new Date(0)`. **Pattern relies on `parseServerDate` returning null for invalid input — see P1-4 below; current helper returns Invalid Date instead, defeating this `??` fallback.**
- `client-tauri/web-src/src/routes/Calendar.tsx:89` — `ed.getHours()` etc. on `ed` from line 77.
- `client-tauri/web-src/src/routes/Calendar.tsx:127` — `parseServerDate(e.end_at)?.toLocaleString(...)`. Clean.

The `anchor`/`days[]` Date objects in Calendar.tsx (line 30, 47-51) are *local-clock* Dates for the calendar grid, not server-emitted — they correctly stay as raw `new Date()` and don't need Z appending. Verified.

### Fix 3: `web/src/pages/RequirementDetail.tsx` refresh token guard — CORRECT

```ts
const refreshTokenRef = useRef(0);
const refresh = async () => {
  if (!id) return;
  const myToken = ++refreshTokenRef.current;
  const isCurrent = () => refreshTokenRef.current === myToken;
  try {
    const r = await api.getRequirement(id);
    if (!isCurrent()) return;
    setReq(r);
    setLoadErr(null);
    const [nextAttachments, ...] = await Promise.all([...]);
    if (!isCurrent()) return;
    setAttachments(nextAttachments); ...
  } catch (e: any) {
    if (!isCurrent()) return;
    setLoadErr(String(e));
  }
};
```

Three things done right:
- Pre-increment `++refreshTokenRef.current` *before* the first await, so concurrent callers can't collide on the same token. (`x++` would have given them both the same value first then incremented — classic off-by-one.)
- Three guard points: after `getRequirement`, after `Promise.all`, and inside the catch. The catch guard matters — without it a stale 404 from refresh-A could flip `setLoadErr` and trip the early-return error UI on the page that's already rendering refresh-B's good data.
- `isCurrent` re-reads the ref via closure, so it always sees the *latest* `refreshTokenRef.current`, not a stale snapshot.

**Verified for the SSE-triggered refresh case that prompt asked about:**
- `useEffect(() => { refresh(); }, [id])` → fires refresh-1 on /r/A mount.
- `useEffect(() => { if (latestStatus) refresh(); }, [latestStatus])` → fires refresh-2 when SSE pushes `requirement.updated` while refresh-1 still in flight.
- refresh-1 holds `myToken=1`; refresh-2 bumps `refreshTokenRef.current` to 2 and holds `myToken=2`.
- Whichever resolves first wins its write; the other's later `isCurrent()` returns false and aborts. Correct ordering preserved: the *last-launched* refresh's data wins, which is what users expect since the SSE event is what triggered refresh-2.
- Burst of 5 SSE events in 200ms: tokens 2,3,4,5,6 launch in order; only 6's writes land. Correct.

**One minor wastage** (not a bug): the in-flight `getRequirement` / `Promise.all` HTTP requests aren't aborted via `AbortController`; the guard just discards their results. For LAN this is fine. If wanted later, plumbing an `AbortController.signal` through `api.getRequirement` would clean it up.

## Prior unfixed P2 status

### P2-3 `client-tauri/web-src/src/lib/tauri.ts:99-102` `new URL()` recomputed per `clientFetch` — STILL UNFIXED

```ts
if (cfg.baseUrl) {
  const base = new URL(cfg.baseUrl);              // ← recomputed every call
  const target = new URL(input, base);
  canAttachClientToken = target.origin === base.origin;
  url = /^https?:\/\//i.test(input) ? input : target.toString();
}
```

Unchanged since R6. Documented-but-not-blocking nit. URL parse is microseconds; only worth caching if profiling shows a hotspot.

### P2-5 `client-tauri/web-src/src/components/FileAttachRail.tsx:72-86` listener handler missing inner `alive` guard — STILL UNFIXED

```ts
useEffect(() => {
  let alive = true;
  let off: (() => void) | undefined;
  listen<UploadProgress>("upload-progress", (p) => {
    if (p.req_id !== reqId) return;
    setProgress(p);                    // ← no alive guard
    if (p.phase === "done") {
      setProgress(null);               // ← no alive guard
      refresh();                       // ← no alive guard, fires backend call after unmount
    }
  }).then((d) => {
    if (!alive) d(); else off = d;
  });
  return () => { alive = false; if (off) off(); };
}, [reqId, refresh]);
```

Same shape as in Round 2. The R7.1 fix to `ProjectDrive.tsx` added `if (!alive) return;` inside the handler body — that's the gold-standard pattern. FileAttachRail is its sibling and still missing the same guard. Race window: between cleanup running and `dispose()` actually firing on the Rust side, an in-flight Tauri event will call `setProgress`/`refresh` on an unmounted component.

Round 2 noted the race window is narrow (only during an active upload, not during normal navigation) — true; that's why it's still P2. But it's the same 3-line copy/paste fix as ProjectDrive got.

### P2-6 `client-tauri/web-src/src/routes/Hub.tsx:20-46` tab-switch race — STILL UNFIXED

Verified by re-reading `Hub.tsx`, `HubDispatch.tsx`, `Knowledge.tsx`, `Inbox.tsx`:

**Hub.tsx (the worst case):**
```ts
const refresh = async () => {
  setErr(null);
  try {
    let list: Requirement[];
    if (tab === "public") { list = await invoke<...>("list_public_pool"); ... }
    else if (tab === "mine") { list = await invoke<...>("list_my", {assignedToMe:true}); ... }
    // ... 5 branches, each with its own await
    setItems(list);                  // ← uses outer `tab` (correct) but writes blindly
  } catch ...
};
useEffect(() => { refresh(); }, [tab]);
```
Fast mash `public→mine→active→public` fires 4 overlapping refreshes; whichever IPC resolves last wins, regardless of which tab is currently selected. Could show "public" items under the "active" header for a few seconds until next refresh.

**Inbox.tsx (`view` toggle):**
```ts
const refresh = async () => {
  try {
    const list = await clientJson<Notif[]>(`/api/notifications?status=${view}`);
    setItems(Array.isArray(list) ? list : []);
  } catch { setItems([]); }
};
useEffect(() => { refresh(); }, [view]);
```
Same shape — fast `unread→all→unread` toggle can leave the wrong list rendered. Inbox is hit harder because each SSE `notification.created` event also fires `refresh()` (line 39-41) on TOP of the view-toggle refreshes — three concurrent fetches all converging on `setItems`. Network-jittery LAN could surface this.

**Knowledge.tsx (`doSearch`):**
```ts
const doSearch = async () => {
  if (!q.trim()) return;
  setBusy(true); setHits(null);
  try {
    const r = await clientJson<{ hits?: Hit[] }>(`/api/knowledge/search?q=...`);
    setHits(Array.isArray(r?.hits) ? r.hits : []);
  } catch { setHits([]); }
  finally { setBusy(false); }
};
```
The sibling `doAsk` (line 51-80) already has a `askTokenRef` token guard — `doSearch` doesn't. User clicks search, types more, clicks again before first resolves → stale results may overwrite fresh ones.

**HubDispatch.tsx:** I re-checked — this one is *fine*. `refresh()` fires only once in `useEffect(...,[])`, and the tab filtering is purely client-side via `useMemo([all, current])`. No race. Round 2 correctly flagged this as "less acute"; on re-read it's actually clean. **Strike from the P2-6 list.**

Fix is the same monotonic-token pattern R7.2 just applied to RequirementDetail.

## New findings

### P1-4 `parseServerDate` returns Invalid Date (not null) for malformed input — breaks `??` fallback in Calendar.tsx

```ts
// shared/src/api/time.ts:12-18 — current
export function parseServerDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  if (typeof value !== "string") return null;
  if (/Z$|[+-]\d\d:?\d\d$/.test(value)) return new Date(value);
  return new Date(value + "Z");
}
```

The original `web/src/pages/RequirementDetail.tsx:63-68` local helper (the one R7.2 hoisted from) included a final `Number.isNaN(date.getTime()) ? null : date` validation step. The new shared helper drops it.

Why this is load-bearing: `client-tauri/web-src/src/routes/Calendar.tsx:77` reads

```ts
const ed = parseServerDate(e.end_at) ?? new Date(0);
const overdue = ed < new Date() && e.event_type === "requirement_due";
// ...
<div className="font-medium">
  {ed.getHours().toString().padStart(2, "0")}:{ed.getMinutes().toString().padStart(2, "0")}
</div>
```

The `?? new Date(0)` fallback was clearly written assuming `parseServerDate` returns `null` on bad input. But with the current implementation:
- Bad `e.end_at` (e.g. `"oops"`) → `parseServerDate("oops")` → `new Date("oopsZ")` → `Invalid Date` object (NOT null).
- `Invalid Date` is **truthy**, so `??` doesn't fall back.
- `ed < new Date()` → comparison of `NaN` to a real Date → false; `overdue` becomes false silently.
- `ed.getHours()` → `NaN` → `"NaN".padStart(2,"0")` → `"NaN"`.
- UI shows literal `"NaN:NaN"` for the time. (The day-bucket filter on line 67-68 quietly drops the event entirely because `Invalid Date.toDateString() === "Invalid Date"` won't match any day key.)

Other call-sites are more forgiving:
- `TaskCard.tsx:14` `due.getTime() < Date.now()` → `NaN < N` → false → `overdue=false` (silent miscategorization of a malformed-due requirement).
- `TaskCard.tsx:60` / `TaskDetail.tsx:153` / `MyWorkload.tsx:116` / `Inbox.tsx:129` / `TaskDetail.tsx:493` — all use `?.toLocaleString(...)`. On Invalid Date, that's `"Invalid Date"` literal in the UI. Ugly but not crashy.

**Why P1, not P2:** the bug is silent (no console error, no crash) and surfaces as "NaN:NaN" / "Invalid Date" strings in production UI. Bad backend rows (a corrupted `end_at` from a botched migration, or a partial write) become an obvious user-visible glitch instead of a quiet skip. And the Calendar.tsx site's `??` fallback was specifically written assuming `null` semantics — that's not a defensive read, that's a coded contract being broken.

**Fix:** one-line addition to `shared/src/api/time.ts`:

```ts
const d = /Z$|[+-]\d\d:?\d\d$/.test(value) ? new Date(value) : new Date(value + "Z");
return Number.isNaN(d.getTime()) ? null : d;
```

Mirror of what the local helper in `web/src/pages/RequirementDetail.tsx:63-68` already does. Update the JSDoc comment to document the null-on-invalid contract so callers don't redundantly check.

### P2-7 (NEW) Four more naive-UTC `new Date(server)` sites in WEB tree — same skew bug R7.2 just fixed for Tauri client

`grep -nE 'new Date\((?!.*\+ "Z")' web/src/**/*.{ts,tsx}` (filtered to server-emitted timestamps, excluding `datetime-local` form inputs and `Date.now()`/literal arithmetic) turns up:

1. **`web/src/pages/NotificationsPage.tsx:95`**
   ```ts
   <span className="text-xs text-stone-400">{new Date(row.created_at).toLocaleString("zh-CN", { hour12: false })}</span>
   ```
   Same exact bug TaskCard had pre-R7.2. Every notification timestamp on the web admin view shows 8h early for CN users.

2. **`web/src/pages/PlanningPage.tsx:124`**
   ```ts
   {req.due_at && <span><CalendarClock className="mr-1 inline h-3 w-3" />{new Date(req.due_at).toLocaleString("zh-CN", { hour12: false })}</span>}
   ```
   Planning view shows every requirement DDL 8h early.

3. **`web/src/components/AILiveView.tsx:33`**
   ```ts
   const t = new Date(ev.at).toLocaleTimeString("zh-CN", { hour12: false });
   ```
   The AI-processing live event timeline shows event times 8h off. Less critical because it's a live feed and "wrong relative ordering" doesn't apply (events arrive in real time), but the absolute hour is still wrong.

4. **`web/src/components/AssigneeSelector.tsx:26`**
   ```ts
   const seenAt = new Date(user.last_seen_at).getTime();
   if (Number.isNaN(seenAt)) return "离线";
   const diff = Math.max(0, Date.now() - seenAt);
   if (diff < 60_000) return "刚刚在线";
   if (diff < 60 * 60_000) return `${Math.max(1, Math.round(diff / 60_000))} 分钟前`;
   // ...
   ```
   `Date.now() - seenAt` is wrong by exactly 8 hours (CN). A user who was online 30 seconds ago shows as "8 小时前" because the parsed `last_seen_at` is rounded as if it were CN-local. Every offline-presence indicator on the web is broken in the same direction.

Web-side already uses three different patterns for the SAME problem:
- `web/src/pages/CalendarPage.tsx:17-19` — local `eventDate()` helper with `+ Z` (correct).
- `web/src/pages/Dashboard.tsx:217,250` — inline `new Date(r.created_at + "Z")` (correct, manual).
- `web/src/pages/ProjectMeetings.tsx:13`, `web/src/pages/ProjectDrive.tsx:25` — local one-liner with `+ Z` (correct, duplicated).
- `web/src/pages/ProjectView.tsx:175`, `web/src/components/CommentsPanel.tsx:38`, `web/src/components/ActivityTimeline.tsx:59`, `web/src/components/DeliverablesTab.tsx:73` — inline `+ "Z"` (correct, manual).
- `web/src/pages/RequirementDetail.tsx:63-68` — local `parseServerDate` (correct, validated).
- **The 4 above — raw `new Date(server)` with NO `Z` (WRONG).**

R7.2 hoisted the helper to `@yqgl/shared`. The natural follow-up is to swap all of WEB's ad-hoc patterns AND the four broken sites to use the shared helper. Two birds, one tree.

**Why P2 not P1:** the original P1 was load-bearing because the Tauri client is everyone's primary work surface — wrong DDLs hit every user immediately. The web tree is the secondary admin/dashboard surface; same bug, lower blast radius. But it's a literal regression vs. the rest of the web tree (which already handles UTC correctly inline), and AssigneeSelector's "8小时前" lie is especially confusing.

**Fix:** import `parseServerDate` from `@yqgl/shared` in the four files, swap. While there, also swap the 5 ad-hoc `+ "Z"` sites to use the shared helper for consistency (kills the local duplicates in CalendarPage / ProjectMeetings / ProjectDrive and the RequirementDetail local helper since they all do the same thing).

### P2-8 (NEW) `client-tauri/web-src/src/routes/Calendar.tsx:32-44` anchor-change race

```ts
useEffect(() => {
  const start = startOfWeek(anchor);
  const end = new Date(start);
  end.setDate(end.getDate() + 7);
  const qs = new URLSearchParams({ start: start.toISOString(), end: end.toISOString(), mine: "true" });
  clientJson<Event[]>(`/api/calendar/events?${qs}`)
    .then((rows) => setEvents(Array.isArray(rows) ? rows : []))
    .catch(() => setEvents([]));
}, [anchor]);
```

Same shape as P2-6 Hub/Inbox. Fast `← 上周 / 下周 →` clicks fire overlapping fetches; whichever HTTP resolves last wins the `setEvents`, regardless of which week the user is currently viewing. Easy to repro on a slow LAN.

Lower severity than Hub because (a) most users don't mash week navigation, (b) the calendar grid still labels the correct dates (those come from `anchor`, not from `events`) — only the *event bubbles* could be from the wrong week. Same fix.

## Coverage

Read every TS/TSX file in scope this round (104 files), with extra focus on:

- **R7.2 changes** — the new `shared/src/api/time.ts` helper, the 10 call-site swaps in client-tauri, and the `RequirementDetail.tsx` token-guard fix. All correct except for P1-4 (helper missing NaN validation).
- **All `new Date(...)` occurrences** in scope — 65 sites across 24 files (per ripgrep `new Date\\(`). Sorted into 3 buckets:
  - Local-clock construction (`new Date()`, `new Date(Date.now() + ms)`, `new Date(anchor)`, `new Date(start)` etc.) — 32 sites, all correct (they're for client-side date math, not parsing server timestamps).
  - Server-timestamp parsing with explicit `+ "Z"` or matching helper — 23 sites, all correct.
  - **Server-timestamp parsing WITHOUT zone handling — 4 sites (P2-7) plus 10 sites already fixed in R7.2.** All 4 are in the web tree.
  - Test-only synthetic data (`new Date().toISOString()` etc. inside `web/tests/e2e/*.spec.ts`) — 22 sites, fine (they generate well-formed `Z`-suffixed strings via `.toISOString()`).
- **All `setItems` / `setRows` / similar in async-resolution sites** — Hub, Inbox, Knowledge, Calendar (client) all need the monotonic-token fix from RequirementDetail. ProjectPulse, HubDispatch, FileAttachRail's main `refresh` (the file uses `useCallback([reqId])` so each id change cancels stale closures via React's reconciliation), ProjectDrive, AdminPanel, Onboarding, Settings — all clean.
- **All listener subscriptions via `listen()` from `@/lib/tauri`** — App.tsx uses `useEvent` (guarded). ProjectDrive uses the gold-standard alive-flag pattern (R7.1 fix). FileAttachRail still missing inner-handler guard (P2-5). TaskDetail, Inbox use `useEvent` (guarded). Useless to check `useChatStream`/`useReqStream` again — they correctly cancel via `reader.cancel()` + `AbortController.abort()` per Round 1/2.
- **All `any` usage** — 11 `catch (e: any)` (standard), 1 `__TAURI_INTERNALS__` (existing nit, intentional), 1 `(document as any).startViewTransition` (polyfill), 1 `(window as any).__YQGL_MOCK_INVOKE__` (test hook), 1 `useState<any>(null)` for the Tauri window API in `TitleBar.tsx:7`. Same as Round 2. Zero `// @ts-ignore`. Zero `// @ts-expect-error`.
- **Auth surface** — `clientFetch` origin guard intact. `withCommon` (web) still passes `credentials: "include"` + token header gated on same-origin. Public endpoints (`/api/downloads/manifest`, `/api/voice/*`) explicitly bypass. No regressions vs. Round 2.
- **Modal/Drawer/Toast/Combobox edge cases** — no changes vs. Round 2. Known carry-over: ProjectDrive preview modal (web, line 685) is still a hand-rolled dialog without ESC/lock/trap; documented in-file as intentional. Not raising again.

### What I specifically verified clean this round

- **`shared/src/api/index.ts` export** — `parseServerDate` is properly re-exported; resolves cleanly via the `@yqgl/shared` alias in both `client-tauri/web-src/tsconfig.json` and `web/tsconfig.json`. No circular-import risk (`time.ts` has zero imports).
- **No new `as any` casts in the R7.2 diff.** TaskCard/TaskDetail/MyWorkload/Inbox/Calendar imports are clean named imports from `@yqgl/shared` — no type narrowing tricks needed because `parseServerDate` returns `Date | null`.
- **R7.2's `refresh()` token guard correctness under StrictMode** — React 18 dev StrictMode double-mounts effects, which means `refresh()` would fire twice in dev. First mount sets token=1, cleanup runs (no-op), second mount sets token=2. Token 1's promises complete with `isCurrent()=false` → harmless discard. Token 2 lands. Production single-mount → token=1 lands. Both paths correct.
- **No prop-drilling of stale closures** through `useEvent`. The handlerRef pattern (R5 fix) is intact and the new R7.2 changes don't touch it.

### Files re-read this round

Full 104. The TS surface didn't grow in R7.2 — only the 7 files in the diff changed shape, plus the 1 new `shared/src/api/time.ts`. Same module structure as Round 2.
