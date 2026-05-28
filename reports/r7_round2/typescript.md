# R7 Round 2 — TypeScript review

## Verdict

**NEEDS FIXES — 3 findings (0 P0, 1 P1, 2 P2).**

R7.1 (commit `9b735b5`) correctly fixed both P1s from Round 1. Re-reading the 104-file TS surface with fresh eyes turned up one P1 that earlier rounds (and the Codex pass) missed entirely: every timestamp display in the Tauri client is read as local time when the backend emits naive UTC, causing an 8-hour skew for all China users. Plus the two carryover P2s from Round 1 (`new URL()` recompute and RequirementDetail `refresh` race) are still unfixed because R7.1 only addressed the explicit P1 list.

Nothing here blocks the build itself — types compile, the apps render — but the timezone bug will hit users on day one. Recommended to fix P1-3 before the deploy.

## R7.1 fix verification

### Fix 1: Onboarding port guard (`client-tauri/web-src/src/routes/Onboarding.tsx:46-51`) — ✅ CORRECT

```ts
const portNum = Number(port);
if (!Number.isFinite(portNum) || portNum < 1 || portNum > 65535) {
  toast({ title: "端口必须是 1–65535 的整数", tone: "error" });
  return;
}
```

Mirrors `Settings.tsx:158-163` exactly. Three things done right:
- Uses parsed `portNum` for the subsequent `set_config` call (line 54), not the string `port` — so even if a slightly-different rendering of the same number sneaks through, we send a clean integer to Rust.
- `Number.isFinite` rejects both `NaN` and `Infinity` (the latter would have been a corner case for `1e1000`-style paste attacks; `Number(...)` happily produces `Infinity` for that).
- Toasts before the `set_config` invoke, so no garbage hits `config.json`.

No new bugs introduced. The asymmetry with Settings I called out in Round 1 is resolved.

### Fix 2: ProjectDrive listener alive-flag (`client-tauri/web-src/src/routes/ProjectDrive.tsx:75-91`) — ✅ CORRECT

```ts
useEffect(() => {
  let alive = true;
  let off: (() => void) | undefined;
  listen<UploadProgress>("drive-upload-progress", (p) => {
    if (!alive) return;
    setProgress(p);
    if (p.phase === "done") setTimeout(() => { if (alive) setProgress(null); }, 600);
  }).then((d) => {
    if (!alive) { d(); return; }
    off = d;
  });
  return () => { alive = false; if (off) off(); };
}, []);
```

This is **better than FileAttachRail's pattern** because it ALSO guards the handler body with `if (!alive) return`, AND guards the 600ms setTimeout payload. Round 1 specifically called out the setTimeout leak — this fix kills it cleanly via the second `if (alive)` check on line 85. The setTimeout itself isn't cancelled but its closure is gated on `alive`, so any setState call after unmount short-circuits.

Note: FileAttachRail's listener (lines 75-86, the original "good" pattern Round 1 cited) is actually MISSING the `if (!alive) return` guard inside its handler body, leaving a narrow race where an in-flight event firing between cleanup and the .then resolving would call `setProgress(null)` and `refresh()` on an unmounted component. ProjectDrive's fix is the new gold standard; FileAttachRail should be brought up to match it (see P2-5 below).

## R6→R7 unfixed P2 status

### P2-3 `client-tauri/web-src/src/lib/tauri.ts:98-103` — STILL UNFIXED

```ts
if (cfg.baseUrl) {
  const base = new URL(cfg.baseUrl);              // <-- recomputed every call
  const target = new URL(input, base);
  ...
}
```

No changes since R6. As noted in Round 1, this is a nit (URL parse is microseconds). Caching `baseUrlObj` alongside `_cfgCache` is the documented fix; not load-bearing.

### P2-4 `web/src/pages/RequirementDetail.tsx:96-119` — STILL UNFIXED

```ts
const refresh = async () => {
  if (!id) return;
  try {
    const r = await api.getRequirement(id);
    setReq(r);
    ...
    const [nextAttachments, ...] = await Promise.all([...]);
    setAttachments(nextAttachments);
    ...
  } catch (e: any) { setLoadErr(String(e)); }
};
useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [id]);
useEffect(() => { if (latestStatus) refresh(); }, [latestStatus]);
```

No changes. Round 1 documented this as low-impact because the race window is < 200ms on LAN; not a release blocker but a code-hygiene nit. I now notice an additional risk in the `[latestStatus]` effect (line 128) — every SSE `requirement.updated` event triggers a fresh `refresh()` with no in-flight protection, so rapid SSE bursts (e.g. a worker rapidly toggling status fields) could pile up overlapping `Promise.all`s. Same fix would cover both call sites.

## New findings

### P1-3 Tauri client uses local-time parsing for naive-UTC server timestamps — visible 8-hour skew

**Affects every `due_at` / `created_at` / `end_at` / `updated_at` display in the client-tauri webview.**

Backend timestamps are produced via `datetime.utcnow()` (see `app/main.py:108`, `app/auth.py:164`, `app/routers/auto.py:211`, and ~30 other locations) and serialized by SQLAlchemy without a `Z` suffix. The web frontend handles this with an explicit Z-append helper:

```ts
// web/src/pages/CalendarPage.tsx:17-19 — the CORRECT pattern
function eventDate(value: string): Date {
  return new Date(value + (value.endsWith("Z") ? "" : "Z"));
}
// web/src/pages/RequirementDetail.tsx:63-68 — also correct
function parseServerDate(value?: string | null): Date | null {
  if (!value) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const date = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}
```

But **the Tauri client has zero Z-suffix handling**. Grep for `parseServerDate|due_at.*Z|\+ "Z"` under `client-tauri/` returns no matches. All display code falls into one of two bad patterns:

```ts
// client-tauri/web-src/src/components/TaskCard.tsx:11-15
const due = req.due_at ? new Date(req.due_at) : null;
const overdue = !!(due && due.getTime() < Date.now());  // ← off by tz offset

// client-tauri/web-src/src/routes/TaskDetail.tsx:152
{req.due_at && <span>截止 {new Date(req.due_at).toLocaleString("zh-CN", { hour12: false })}</span>}

// client-tauri/web-src/src/routes/MyWorkload.tsx:116
{r.due_at && <div>...截止 {new Date(r.due_at).toLocaleString("zh-CN", { hour12: false }).slice(5, 16)}</div>}

// client-tauri/web-src/src/routes/Inbox.tsx:129
{new Date(n.created_at).toLocaleString("zh-CN", ...)}

// client-tauri/web-src/src/routes/TaskDetail.tsx:492
{u.actor_nickname} · {new Date(u.created_at).toLocaleString("zh-CN", ...)}

// client-tauri/web-src/src/routes/Calendar.tsx:67, 77, 89, 127
const ed = new Date(e.end_at);  // ← used for filtering BY day, so the bug
                                //   can put events on wrong days entirely
```

**Why this matters**: For users in `Asia/Shanghai` (+08:00):
- `due_at = "2026-05-29T10:00:00"` (server-side: 10am UTC = 18:00 China time)
- `new Date("2026-05-29T10:00:00")` is parsed by JS as LOCAL time → "10:00 China time" → 02:00 UTC internally
- `toLocaleString("zh-CN")` then prints **"2026-05-29 10:00"** instead of **"2026-05-29 18:00"** — an 8-hour error.
- `due.getTime() < Date.now()` therefore reports overdue incorrectly (a thing actually due tonight at 22:00 China time will show as due at 14:00 and look overdue all afternoon).
- In `Calendar.tsx` the bug is worse: `ed.toDateString() === d.toDateString()` filter puts events on the wrong day for anything near midnight UTC (08:00 China time).

**Why this is P1 not P0**: the app still works, no data corruption. But every user sees wrong times immediately, including critical "due in X hours" judgments. This is a one-day-to-prod-then-everyone-complains bug.

**Fix**: hoist `parseServerDate` from `web/src/pages/RequirementDetail.tsx` into `shared/src/api/types.ts` (or a new `shared/src/util/dates.ts`), then replace every `new Date(req.due_at)` / `new Date(...created_at)` / `new Date(...end_at)` callsite in `client-tauri/web-src/` with the helper. Web side already uses similar patterns inconsistently (some places use `+ "Z"`, others `parseServerDate`) — extracting a shared helper kills both birds.

Files to touch (callsites I verified):
- `client-tauri/web-src/src/components/TaskCard.tsx:11`
- `client-tauri/web-src/src/routes/TaskDetail.tsx:152, 492`
- `client-tauri/web-src/src/routes/MyWorkload.tsx:116`
- `client-tauri/web-src/src/routes/Inbox.tsx:129`
- `client-tauri/web-src/src/routes/Calendar.tsx:67, 77, 89, 127`

## P2 findings

### P2-5 `client-tauri/web-src/src/components/FileAttachRail.tsx:75-86` — listener handler missing alive guard

ProjectDrive's R7.1 fix added two `if (!alive)` checks (one inside the handler, one inside the deferred setTimeout). FileAttachRail's listener has the same `alive` flag mechanic at the registration site (line 73-84), but the handler body itself does NOT check `alive` before calling setState:

```ts
let alive = true;
let off: (() => void) | undefined;
listen<UploadProgress>("upload-progress", (p) => {
  if (p.req_id !== reqId) return;
  setProgress(p);                     // ← no alive guard
  if (p.phase === "done") {
    setProgress(null);                // ← no alive guard
    refresh();                        // ← no alive guard, fires API call after unmount
  }
}).then((d) => {
  if (!alive) d(); else off = d;
});
return () => { alive = false; if (off) off(); };
```

Race: cleanup runs → `alive = false` → an in-flight Tauri event delivered between cleanup and `d()` invocation calls `setProgress` / `refresh` on the unmounted component. React 18 will swallow the setState warning but `refresh()` actually issues a backend call (`invoke("list_attachments", ...)`) for a component that no longer exists — wasted IPC + the result is just thrown away.

Same shape as P1-2 from Round 1 (since fixed in ProjectDrive). Worth bringing this site up to the gold-standard pattern for consistency:

```ts
listen<UploadProgress>("upload-progress", (p) => {
  if (!alive) return;                      // ← add
  if (p.req_id !== reqId) return;
  setProgress(p);
  if (p.phase === "done") {
    setProgress(null);
    refresh();
  }
}).then(...)
```

Lower severity than P1-2 was because:
- The race window is narrower (Tauri events only arrive while an upload is in progress; cleanup typically fires on route change, not mid-upload).
- StrictMode dev double-mount doesn't trigger here as reliably because the listener requires an active upload event.

But it's still a hole, and we explicitly cited FileAttachRail as the gold standard in Round 1 — that's no longer true after R7.1, so this is a "promote ProjectDrive's pattern back to FileAttachRail" cleanup.

### P2-6 `client-tauri/web-src/src/routes/Hub.tsx:20-46` — tab-switch race overwrites stale data

```ts
const refresh = async () => {
  setErr(null);
  try {
    let list: Requirement[];
    if (tab === "public") { list = await invoke<Requirement[]>("list_public_pool"); ... }
    else if (tab === "mine") { list = await invoke<Requirement[]>("list_my", ...); ... }
    ...
    setItems(list);                  // ← uses outer `tab` at the time of call
  } catch (e: any) { ... }
};
useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [tab]);
```

Fast tab-mashing `public → mine → active → public` fires four `refresh()`s. Each invokes the backend with the `tab` value at call-time, but they all converge on the same `setItems` setter. If `public`'s response arrives AFTER `active`'s, `items` ends up showing public-pool requirements under the `active` tab header.

This is the same pattern as P2-4 (web RequirementDetail's `refresh` lacking cancel-aware guard). Fix is the same: `let myToken = ++tokenRef.current; ... if (myToken !== tokenRef.current) return;` before `setItems`, or wrap each effect in `let alive = true; ... if (!alive) return;`.

Lower severity because users normally don't mash tabs, and the next `useEffect` cleanup→remount on tab change isn't a race (it's a re-fire). The Hub-tab specifically is the most-used view though, so worth fixing for the same reason P1-2 was: StrictMode dev double-mount and any latency spike makes the race observable.

Same race shape exists in:
- `client-tauri/web-src/src/routes/HubDispatch.tsx:37-48` — though less acute since `dtab` filtering is client-side after one `list_my` fetch
- `client-tauri/web-src/src/routes/Knowledge.tsx:30-42` (`doSearch` — though the Knowledge file already protects `doAsk` via `askTokenRef`, ironically `doSearch` doesn't)
- `client-tauri/web-src/src/routes/Inbox.tsx:24-33` — `view` toggle between "unread"/"all" has the same shape

## Coverage

Read every TS/TSX file in scope, focusing on the surfaces called out in the prompt. Total file count: **104**.

### Specifically verified this round
- **R7.1 fixes** (Onboarding.tsx port guard, ProjectDrive.tsx alive flag): both correct, no regressions.
- **All callsites of `clientFetch` / `clientJson`** (16 files): Onboarding, Settings, App, Inbox, Calendar, Knowledge, MyWorkload, ProjectPulse, Clarify in client-tauri; useChatStream uses it via prop; everywhere uses `clientJson` for status-checked decoding or guards `r.ok` manually. No leaked credentials, no unhandled 4xx/5xx bodies sprayed into setState. The notification SSE handler in App.tsx correctly debounces the badge fetch.
- **SSE / streaming**: `useChatStream` and `useReqStream` both correctly CR-strip, multi-line accumulate, abort on unmount via `reader.cancel()` + `AbortController.abort()`. `useReqStream` has an `alive` flag inside the reader loop. `Dashboard` (web) has exponential reconnect backoff with `document.hidden` pause.
- **Modal / Drawer / Toast / Combobox / WelcomeTour edge cases**: Modal has ESC + focus trap + focus restoration + body lock; Drawer has ESC + body lock (no trap — acceptable for a side panel); ToastHost stack ref-counts pushFn and clears timers on unmount; Combobox has full keyboard nav + scroll-into-view + close on Tab; WelcomeTour resets idx on re-open and supports arrow keys. **ProjectDrive's preview modal (line 685) is a hand-rolled dialog with NO ESC handler, NO body lock, NO focus trap** — flagged as a known regression vs. shared/Modal, but documented as a deliberate non-portal choice in the file's comments. Not raising as a finding (already known).
- **Form validation**: Onboarding now matches Settings on port. NewRequirement's `Number(estimateHours)` produces NaN on garbage input but the `type="number"` input blocks non-numeric paste in modern browsers; server-side validation catches it as well. Clarify's `SummaryCard.deliver` will throw a generic `RangeError` if `dueAt` is somehow an invalid datetime-local; the catch handles it but the error message is uninformative. Both are minor.
- **`any` usage audit**: 11 sites of `as any` for `catch (e: any)`, 1 for `__TAURI_INTERNALS__` detection (`shared/src/api/client.ts:10`), 1 for `(document as any).startViewTransition` polyfill, 1 for `(window as any).__YQGL_MOCK_INVOKE__` test hook in `lib/tauri.ts:14`, 1 for `useState<any>(null)` for the Tauri window API in `TitleBar.tsx:7` (this one is the only weak spot — could be `WebviewWindow | null` once `@tauri-apps/api/window` types are imported). Zero `// @ts-ignore`. Zero `// @ts-expect-error`.
- **Race / leak patterns**: Verified `alive` flags or token refs in `ProjectDrive` (web), `Knowledge.doAsk`, `RequirementDetail` (web — module-scope `latestStatus` race callout in P2-4), `AssigneeSelector`, `useChatStream`, `useReqStream`, `useEvent`, `Sidebar.tsx` pubsub. Found Hub.tsx still races (P2-6) and `FileAttachRail` handler missing the inside-handler alive guard (P2-5).

### What's clean
- Auth — every `fetch` goes through `withCommon` (web) or `clientFetch` (Tauri), both correctly gate `X-YQGL-Client-Token` on origin match. Public-only endpoints (`/api/downloads/manifest`, `/api/voice/*`) explicitly bypass.
- Modal close → focus restoration verified working with `prevFocus` snapshot.
- `bodyScrollLock.ts` ref-counts correctly so nested Modal+Drawer don't leak `overflow: hidden`.
- `useEvent` handlerRef pattern correctly captures latest closure without re-subscribing on every render (prevents the listener pile-up that R5 fixed).
- `ToastHost` push stack pattern handles multiple hosts mounting / unmounting without disabling each other.
- `WorkspaceCard`'s dirty-flag protection (web/RequirementDetail.tsx:712) correctly prevents SSE refresh from wiping in-flight typing.
- `_cfgCache` invalidation via `resetClientTokenCache()` is called in all four required spots: Onboarding (`testServer` after `set_config`), Onboarding (`identifyAndRegister` after `register_device`), Settings (`save` when server config changes), and App (after auto re-auth on launch).
- SSE `\r$` strip + multi-line `data:` accumulation + `^ ` strip per RFC are all correct in both `useChatStream` and `useReqStream`.

### Files read this round
All 104 from Round 1 plus the R7.1-modified `Onboarding.tsx` and `ProjectDrive.tsx`. The TS surface didn't change in shape since Round 1 — same files, same module structure.
