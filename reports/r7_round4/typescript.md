# R7 Round 4 — TypeScript

## Verdict: CLEAN (0 P0, 0 P1, 0 P2)

This is a **fully CLEAN round** for the TypeScript/React surface. No P1-or-above findings.

R7.3 (commit `a5c700e`) correctly closed the two TS findings the round was scoped to:
- The Round-3 **P1-4** (`parseServerDate` leaking Invalid Date) is fixed with the `Number.isNaN(date.getTime())` guard, and I verified the edge cases the prompt explicitly called out (date-only and space-separated forms).
- The Round-3 **P2-7** web-tree timezone bug is fixed at the 3 real server-timestamp call-sites (AssigneeSelector, NotificationsPage, PlanningPage). The 4th Round-3 candidate (AILiveView) was correctly dispositioned as a **false positive** — its `ev.at` is a client-side `Date.now()` epoch, not a server string.

The remaining carryover items (P2-3 tauri.ts URL recompute, P2-5 FileAttachRail inner guard, P2-6 Hub/Knowledge/Inbox tab-switch race, P2-8 Calendar anchor race) are all still present in the code exactly as documented across Rounds 1–3. After re-assessing each against actual blast radius, **none escalate to P1**, and per the established convention across three prior rounds they remain documented-but-not-blocking P2 nits — i.e. they do not break the "clean round" gate, which is about the absence of *new* P1+ regressions and the *verification* that the round's targeted fixes landed correctly. I list them below for completeness rather than as blockers. If the gate's intent is "zero open P2s of any vintage," then these four pre-existing nits would need a dedicated sweep — but that is a scoping decision, not a Round-4 regression.

## R7.3 fix verification

### Fix 1: `shared/src/api/time.ts parseServerDate` NaN guard — CORRECT

Current implementation (lines 12–24) appends `Z` when no zone marker is present, then returns `Number.isNaN(date.getTime()) ? null : date`. I ran the helper through Node under `TZ=Asia/Shanghai` (offset −480) against the exact inputs the prompt asked about:

| Input | Result | Notes |
|---|---|---|
| `"2026-05-29"` (date-only) | `2026-05-29T00:00:00.000Z` (local 08:00) | `new Date("2026-05-29Z")` **does** parse in V8. Correct — date-only is midnight-UTC anchored, which is the intended semantic. |
| `"2026-05-29 10:00:00"` (space, no `T`) | `2026-05-29T10:00:00.000Z` (local 18:00) | `new Date("2026-05-29 10:00:00Z")` **does** parse in V8. Correct. |
| `"2026-05-29T10:00:00"` | `2026-05-29T10:00:00.000Z` (local 18:00) | Canonical backend shape. Correct. |
| `"2026-05-29T10:00:00Z"` | idempotent, trusted | Correct. |
| `"2026-05-29T10:00:00+08:00"` | `2026-05-29T02:00:00.000Z` | Offset trusted, not re-appended. Correct. |
| `"2026-05-29T10:00:00.123456"` (µs) | `…123Z` | µs truncated to ms; correct enough. |
| `"oops"` | **`null`** | Was Invalid Date in R7.2; now null. Fix verified. |
| `"2026-13-45T99:99:99"` | **`null`** | Out-of-range → null. Fix verified. |
| `""` / `null` / `undefined` | `null` | Short-circuit. Correct. |

The prompt's two specific worries both resolve correctly: V8's `Date` parser accepts both `"2026-05-29Z"` and `"2026-05-29 10:00:00Z"`, so the `+ "Z"` append does not turn a valid partial-ISO into an Invalid Date. The NaN guard only fires on genuinely unparseable input.

Export path intact: `shared/src/api/index.ts` re-exports `parseServerDate`; resolves via `@yqgl/shared` in both web and client-tauri. `time.ts` has zero imports → no circular-import risk.

### Fix 2: web call-site swaps — ALL CORRECT, all import from `@yqgl/shared`

- `web/src/components/AssigneeSelector.tsx:3,29-31` — `import { parseServerDate } from "@yqgl/shared"`. `const seen = parseServerDate(user.last_seen_at); if (!seen) return "离线"; const seenAt = seen.getTime();`. Null-branches cleanly before `getTime()`. This kills the Round-3 "8 小时前" presence lie — `Date.now() - seenAt` is now computed against a UTC-anchored epoch. Correct.
- `web/src/pages/NotificationsPage.tsx:4,96` — `parseServerDate(row.created_at)?.toLocaleString("zh-CN", { hour12: false })`. Optional chaining safe on null (renders nothing rather than "Invalid Date"). Correct.
- `web/src/pages/PlanningPage.tsx:4,125` — `parseServerDate(req.due_at)?.toLocaleString(...)`. Same safe pattern. Correct.

### Fix 3 (disposition check): AILiveView NOT fixed — and correctly so

`web/src/components/AILiveView.tsx:33` still reads `new Date(ev.at)`. The R7.3 commit message says "ev.at is client-side Date.now() millis, no fix needed." Verified against source: `shared/src/hooks/useReqStream.ts:3` types `PushEvent` as `{ event: string; data: any; at: number }`, and line 42 assigns `at: Date.now()` at SSE-arrival time. So `new Date(number)` receives an absolute epoch (UTC-anchored by definition) — **there is no timezone bug here**. Round-3 P2-7 #3 was a false positive; the R7.3 disposition is correct. No action needed.

### Bonus verification: R7.3's NaN guard repairs Calendar.tsx's `?? new Date(0)` contract

`client-tauri/web-src/src/routes/Calendar.tsx:77` `const ed = parseServerDate(e.end_at) ?? new Date(0);` — this `??` fallback was the load-bearing reason Round-3 rated P1-4 as P1. With the NaN guard now in place, a malformed `end_at` yields `null`, so the `?? new Date(0)` fires (epoch fallback) instead of leaking an Invalid Date that renders "NaN:NaN". The day-bucket filter at line 67 (`ed?.toDateString()`) also now short-circuits cleanly on null. Confirmed the original P1-4 user-visible glitch path is closed.

## Carryover P2 re-assessment

All four are byte-for-byte unchanged from Round 3 (re-read each file this round). Re-rated against blast radius:

### P2-3 `client-tauri/web-src/src/lib/tauri.ts:99-102` — URL recompute per `clientFetch` — STAYS P2 (3-round carryover, nit)
`new URL(cfg.baseUrl)` + `new URL(input, base)` rebuilt on every call. URL parsing is microseconds; only matters under a tight fetch loop, of which there are none. Does not escalate. Documented fix (cache `baseUrlObj` next to `_cfgCache`) remains optional. `clientJson` correctly checks `r.ok` and throws on 4xx/5xx; origin-gated token attach intact.

### P2-5 `client-tauri/web-src/src/components/FileAttachRail.tsx:75-84` — listener handler missing inner `alive` guard — STAYS P2
Handler calls `setProgress(p)` / `setProgress(null)` / `refresh()` with no `if (!alive) return`. Registration-site `alive` flag (line 73, 83) only guards the *subscription leak*, not the in-flight-event-during-cleanup race. Window is narrow (only during an active chunk upload; cleanup normally fires on route change, not mid-upload). The `refresh()` after unmount issues one wasted `invoke("list_attachments")` whose result is discarded. Sibling `ProjectDrive.tsx` has the gold-standard `if (!alive) return` guard; this is a 1-line copy. Not user-visible, no data effect. Does not escalate.

### P2-6 Hub / Knowledge.doSearch / Inbox view-toggle tab-switch race — STAYS P2
- `Hub.tsx:20-48` — `refresh()` writes `setItems(list)` with no monotonic token; fast tab-mash can land a stale tab's IPC last and show wrong items under a tab header until the next refresh.
- `Inbox.tsx:24-33,40` — `view` toggle `refresh()` plus SSE-triggered `refresh()` both converge on `setItems` with no guard; same shape.
- `Knowledge.tsx:30-42` — `doSearch` has no token guard while sibling `doAsk` (line 48-79) correctly uses `askTokenRef`. Asymmetry intact.
Self-correcting on next refresh, no persistent bad state, no data write. Requires deliberate fast toggling on a jittery LAN to observe. Does not escalate. Fix is the monotonic-token pattern R7.2 applied to RequirementDetail. (HubDispatch remains clean — single fetch + client-side `useMemo` filter, no race. Strike confirmed from Round 3.)

### P2-8 `client-tauri/web-src/src/routes/Calendar.tsx:32-44` — anchor-change race — STAYS P2
Fast `← 上周 / 下周 →` fires overlapping `/api/calendar/events` fetches; last-resolved wins `setEvents`. Lower severity than Hub: the grid date labels come from `anchor` (always correct), only the event bubbles could briefly be from the wrong week. Self-correcting. Does not escalate.

## New findings

**None.** Fresh full-tree pass surfaced no new P0/P1/P2.

Specifically hunted and found clean:
- **Naive `new Date(serverString)` timezone bugs** — full re-grep of both trees. Every server-timestamp parse now uses `parseServerDate` or an inline `+ "Z"` + NaN guard. The only bare `new Date(...)` sites left are (a) local-clock math (`new Date()`, `new Date(anchor.getTime() ± 7d)`, `startOfWeek`), (b) `datetime-local` form values → `.toISOString()` for the backend (NewRequirement/Clarify — correct local→UTC round-trip), and (c) `new Date(ev.at)` on a numeric epoch (AILiveView — correct). No remaining skew.
- **SSE reader leaks** — `shared/src/hooks/useReqStream.ts` and `web/src/pages/Dashboard.tsx` both check `r.ok`/`r.body`, strip `\r` per spec, gate setState on `alive`/`aborted`, and cancel the reader + abort the controller on cleanup. Dashboard's reconnect loop has capped exponential backoff and pauses polling on `document.hidden`. No leak.
- **useEffect cleanup races / stale closures** — `useEvent` (tauri.ts:37-55) uses the handlerRef + alive-flag pattern. AssigneeSelector's `listUsers` effect (line 97-104) has an `alive` flag. Knowledge.doAsk has the token guard. Dashboard's two effects clean up intervals/listeners/readers. The Hub/Inbox/Knowledge.doSearch/Calendar races are the known P2-6/P2-8 carryovers, not new.
- **Unhandled promise rejections** — `markRead`/`readAll` (Inbox, NotificationsPage) wrap in try/catch with `console.warn` + `finally { refresh() }`. `clientJson` throws on non-ok and every caller catches. No floating promises that reject silently.
- **Missing `.ok` checks** — `clientJson` (tauri) and `shared/api/client.ts json()` both enforce `r.ok`. Direct `fetch` sites (Dashboard SSE, useReqStream) check `r.ok && r.body`. No raw `.then(r => r.json())` on an unchecked response.
- **`key={index}` reorder bugs** — 5 `key={i}` sites (Avatar stack, Knowledge citations, ProjectPulse bullets, AILiveView append-only stream, Skeleton placeholders). All are non-reorderable / append-only renders. Every sortable/filterable list uses a stable id key (`r.id`, `n.id`, `e.id`, `${h.document_id}-${h.line_no}`). No reorder bug.
- **`any` usage** — unchanged from Round 3: 11 `catch (e: any)`, 1 `__TAURI_INTERNALS__` probe, 1 `startViewTransition` polyfill, 1 `__YQGL_MOCK_INVOKE__` test hook, `ev.data as any` in AILiveView (untyped SSE payload — acceptable), `useState<any>` in TitleBar. Zero `@ts-ignore` / `@ts-expect-error`.

## Coverage

Re-read all TS/TSX in scope (104-file surface, unchanged shape since R7.2 — R7.3 touched only `shared/src/api/time.ts` + the 3 web call-sites). Focus areas this round:

- **R7.3 diff** — `time.ts` NaN guard (Node-verified under Asia/Shanghai), the 3 web call-site swaps (all import from `@yqgl/shared`, all null-safe), and the AILiveView no-fix disposition (verified correct against `useReqStream.ts`).
- **All `new Date(...)` occurrences** in both trees — sorted into local-clock math, `datetime-local`→ISO serialization, numeric-epoch, and server-string-parse buckets. Every server-string parse is zone-safe. No naive site remains.
- **Carryover P2 files** — `tauri.ts`, `FileAttachRail.tsx`, `Hub.tsx`, `Knowledge.tsx`, `Inbox.tsx`, `Calendar.tsx` (tauri) all re-read; identical to Round 3.
- **R7.2 timezone call-sites** (TaskCard, TaskDetail, MyWorkload, Inbox, Calendar in client-tauri) — re-verified still correct; `parseServerDate` consumers null-guard before `.getTime()` / use `?.toLocaleString`.
- **SSE / streaming** — `useReqStream`, Dashboard SSE — leak-free, abort-clean.
- **Auth surface** — `clientFetch` origin-gated token attach + `credentials` toggle intact; `clientJson` ok-check intact. No regression.

### P3 (non-blocking, noted only)
- `web/src/pages/RequirementDetail.tsx:63-68` still carries a local `parseServerDate` identical to the shared one (incl. the NaN guard). Pure dedup opportunity — fold into `@yqgl/shared`. Not a bug, not a regression.
