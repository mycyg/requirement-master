# R7 Round 5 — TypeScript

## Verdict: CLEAN

0 P0, 0 P1, 0 open P2. This is a fully clean round — Round 1 of the fresh "4 consecutive CLEAN rounds" streak passes for the TypeScript/React surface.

All 7 R7.4 TS changes verified correct (no regressions introduced). All 4 long-standing carryover P2s (P2-3 tauri URL recompute, P2-5 FileAttachRail inner guard, P2-6 Hub/Knowledge.doSearch/Inbox tab-switch race, P2-8 Calendar anchor race) are now genuinely closed in code. Fresh full-tree pass surfaced no new P1+ and no new P2.

Scope confirmation: `git diff a5c700e..HEAD` over `*.ts`/`*.tsx` touches exactly the 7 files the prompt scoped (plus the new `reports/r7_round5/` dir). HEAD = `8d30bc7`, working tree clean.

---

## R7.4 regression check (7 items)

### 1. FileAttachRail.tsx — inner `alive` guard — CORRECT
`client-tauri/web-src/src/components/FileAttachRail.tsx:75-90`. The listener callback now opens with `if (!alive || p.req_id !== reqId) return;`. The `alive` flag is correctly closed over: it's declared `let alive = true` at line 73 inside the effect body, the callback captures it by reference, and the cleanup `return () => { alive = false; if (off) off(); }` (line 89) flips it. The early return does **not** skip needed cleanup — cleanup is the effect's returned function, entirely separate from the callback; the callback only does `setProgress`/`refresh`, both of which are precisely what we want suppressed post-unmount. The outer registration guard (`.then((d) => { if (!alive) d(); else off = d; })`, line 87) still handles the subscription-leak case. Both windows now covered. No double-off, no missed dispose.

### 2. Hub.tsx — monotonic `reqTokenRef` — CORRECT
`client-tauri/web-src/src/routes/Hub.tsx:23,26,46,50`. `const token = ++reqTokenRef.current` is captured at the top of each `refresh()`; the success path checks `if (token !== reqTokenRef.current) return` (line 46) before `list.sort`/`setItems`, and the catch path checks before `setErr`/`setItems` (line 50). No off-by-one: `++ref` pre-increments, so the first call gets token 1 and `ref===1`; a superseding call bumps to 2, so the older closure's `1 !== 2` correctly bails. `claim`/`startDoing` call `refresh()` after their mutation — each gets a fresh token bump, so the post-action refresh always wins (it's the latest). No regression to those flows. (No unmount-bump cleanup, but that's harmless for a route component — a stale setItems-after-unmount is a no-op warning at worst, and the token still guarantees ordering among in-flight calls.)

### 3. Inbox.tsx — `reqTokenRef` — CORRECT
`client-tauri/web-src/src/routes/Inbox.tsx:26,29,32,35`. Same pre-increment pattern, guard before `setItems` on both success and catch. The view-toggle path (`useEffect([view])` → `refresh`) and the SSE path (`useEvent("push-event")` → `refresh` when `event === "notification.created"`) both route through the single guarded `refresh()`, so a slow `status=unread` fetch can no longer overwrite a fast `status=all` fetch. The `markRead`/`readAll` `finally { refresh() }` calls also get fresh tokens and win correctly. SSE handler uses `useEvent` (stable handler-ref), so it always sees the current `view`/closure. Verified.

### 4. Knowledge.tsx — `searchTokenRef` for doSearch — CORRECT
`client-tauri/web-src/src/routes/Knowledge.tsx:32-33,37,44,47,50`. Mirrors the existing `askTokenRef` exactly. Unmount cleanup present and correct: `useEffect(() => () => { searchTokenRef.current++; }, [])` (line 33) bumps the token on unmount so a late-resolving search can't setState on an unmounted component. Guards on success (line 44) and catch (line 47); the `finally` correctly gates `setBusy(false)` behind `token === searchTokenRef.current` (line 50) so a superseded search doesn't prematurely clear the spinner of the newer one. Symmetry with `doAsk` now restored.

### 5. Calendar.tsx — `alive` flag on anchor fetch — CORRECT
`client-tauri/web-src/src/routes/Calendar.tsx:36,46-48`. `let alive = true` at effect top; both `.then` and `.catch` gate `setEvents` behind `if (alive)`; cleanup `return () => { alive = false; }` (line 48). Fast ←上周/下周→ now drops late responses from the prior week. Grid day labels derive from `anchor` directly (lines 51-56, outside the effect), so they're always correct regardless of fetch ordering — only the event bubbles were ever at risk, and now they're guarded too. `parseServerDate(e.end_at) ?? new Date(0)` fallback (line 82) and the `?.toDateString()` day-bucket (line 73) remain NaN-safe.

### 6. tauri.ts — cached `baseObj: URL|null` — CORRECT (all 4 sub-checks pass)
`client-tauri/web-src/src/lib/tauri.ts:66-121`.
- **(a) makeCache parses correctly** (lines 72-78): parses `baseUrl` once into `baseObj`, wrapped in try/catch → `null` on parse failure. Only attempts parse when `baseUrl` is truthy.
- **(b) resetClientTokenCache still nulls the whole cache** (lines 124-126): `_cfgCache = null` — unchanged, drops `token`+`baseUrl`+`baseObj` together. Since `baseObj` only ever lives inside `_cfgCache` and the cache is invalidated wholesale on settings change, `baseObj` can never go stale relative to `baseUrl`.
- **(c) canAttachClientToken logic unchanged in behavior**: initial `!cfg.baseUrl && input.startsWith("/")` uses `baseUrl` (unchanged); the recompute branch now gates on `if (cfg.baseObj)` instead of `if (cfg.baseUrl)` and reuses the cached object instead of `new URL(cfg.baseUrl)`. For every real production state (`baseUrl` either empty or a valid URL) the two predicates are equivalent and the origin-comparison + `url` rewrite are byte-identical. The one behavioral delta is strictly graceful: a non-empty-but-**unparseable** `baseUrl` used to make `clientFetch` **throw** (`new URL` rejected the promise); it now degrades to a no-token relative fetch (`baseObj=null` → skip branch). That's not a real production state (`server_url` is written from a validated device-register URL), so no behavior change in practice, and the new behavior is safer.
- **(d) dev (no baseUrl) path still works**: `makeCache("", "")` → `baseObj=null` → `clientFetch` skips the rewrite block, keeps `input` verbatim, `canAttachClientToken = true && input.startsWith("/")`. The vite dev `/api` proxy (`client-tauri/web-src/vite.config.ts:22`) serves it. Identical to pre-R7.4.

### 7. RequirementDetail.tsx — import shared parseServerDate — CORRECT
`web/src/pages/RequirementDetail.tsx:26`. Local duplicate removed; now `import { parseServerDate } from "@yqgl/shared"`. The shared version (`shared/src/api/time.ts:12-24`) is semantically identical, including the `Number.isNaN(date.getTime())` NaN guard. `formatServerDate` (lines 64-67) still resolves to it; the other in-file use at line 176 (`const due = parseServerDate(req.due_at)`) now also resolves to the shared one and remains null-guarded before `.getTime()`/`.toDateString()` (lines 185-188). Export chain verified: `shared/src/api/index.ts:3` re-exports it. No other local usage broke (grep confirms the only `parseServerDate`/`formatServerDate` references resolve correctly).

---

## New findings

**None.** Fresh full-tree pass (104-file TS/TSX surface) surfaced no new P0/P1/P2.

Specifically hunted and found clean:
- **useEffect races / stale closures** — fetch-on-deps effects all carry a guard: ProjectDrive (tauri) project-switch + upload-progress both use `alive` (incl. the deferred `setTimeout` re-checking `alive` at line 85 — gold standard); AssigneeSelector (web) listUsers uses `alive` (lines 99-103); `useEvent` (tauri.ts:37-55) uses handler-ref + alive; Knowledge doAsk/doSearch and Hub/Inbox use monotonic tokens. MyWorkload/ProjectPulse are mount-only single fetches (no re-fetch trigger → no race). TaskDetail's `refresh` has no token but is `Promise.all` keyed on `[id]` and self-corrects via the SSE `requirement_id !== id` guard — pre-existing, not flagged in any prior round, does not escalate.
- **SSE reader leaks** — `useReqStream` (shared + web), `useChatStream` (shared), and Dashboard SSE all: check `.ok && .body`, strip trailing `\r` per spec, gate setState on `alive`/`aborted`, cancel the reader + abort the controller on cleanup. Dashboard's reconnect loop has capped exponential backoff (1s→30s) and pauses the 7-endpoint polling fan-out on `document.hidden`. No leak.
- **Missing `.ok` checks** — `clientJson` (tauri) and `shared/api/client.ts json()` both enforce `r.ok` and throw on 4xx/5xx with a sliced body. Direct `fetch` SSE sites check `r.ok && r.body`. The only raw `.then(r => r.json())` sites are `ClientDownloadBanner.tsx:63,159` — but the consumed `Manifest` shape is render-guarded on `manifest.available` and `platformDownloads()` returns `[]` when absent, so a non-ok JSON error body degrades to "no banner" (same as the `.catch` fallback) — no `.map` on a non-array, no tree crash. Public near-always-200 endpoint. P3-level, unchanged from prior rounds.
- **Timezone bugs** — every server-timestamp parse is zone-safe: either `parseServerDate` (NaN-guarded), an inline `+ "Z"`/`endsWith("Z") ? "" : "Z"` on always-present fields (Dashboard, CommentsPanel, ActivityTimeline, DeliverablesTab, ProjectView, ProjectMeetings, ProjectDrive web, CalendarPage `eventDate`), with explicit NaN guards where the value is nullable (Clarify `toLocalInput`). Remaining bare `new Date(...)` sites are local-clock math (`startOfWeek`, anchor ±7d, `new Date()`), `datetime-local`→`.toISOString()` form serialization (NewRequirement, Clarify `deliver`, CalendarPage `isoLocal`), or numeric epoch (AILiveView `new Date(ev.at)`). No skew.
- **`key={index}` reorder bugs** — 5 `key={i}` sites (Knowledge citations, ProjectPulse risk bullets, AILiveView append-only stream, AvatarGroup stack, Skeleton placeholders) are all non-reorderable / append-only. Every sortable/filterable list uses a stable id key (`r.id`, `n.id`, `e.id`, `d.toISOString()`, `${h.document_id}-${h.line_no}`). No reorder bug.
- **`any` / type-safety** — 125 `: any`/`as any` occurrences across 49 files, dominated by `catch (e: any)`, e2e test mock fixtures (`*.spec.ts`), and the documented `__TAURI_INTERNALS__` / `__YQGL_MOCK_INVOKE__` / untyped-SSE-payload probes. **Zero** `@ts-ignore` / `@ts-expect-error` / `@ts-nocheck` (separately confirmed). Unchanged from Round 4.

---

## Open P2 status (are the 4 carryovers truly closed now?)

All four are now **CLOSED in code** (verified by reading the current files, not just the diff):

| ID | Item | Status |
|---|---|---|
| **P2-3** | tauri.ts URL recompute per `clientFetch` call | **CLOSED** — `baseObj` cached in `_cfgCache`, parsed once in `makeCache`, reused per call (item 6 above). |
| **P2-5** | FileAttachRail listener missing inner `alive` guard | **CLOSED** — `if (!alive || p.req_id !== reqId) return` (item 1). |
| **P2-6** | Hub / Knowledge.doSearch / Inbox tab-switch race | **CLOSED** — all three now carry monotonic tokens (items 2, 3, 4). HubDispatch was already clean (single fetch + `useMemo` filter). |
| **P2-8** | Calendar (tauri) anchor-change race | **CLOSED** — `alive` flag + cleanup on the anchor effect (item 5). |

The Round-4 P3 dedup nit (RequirementDetail local `parseServerDate`) is also now resolved (item 7). No open P2 or P3 of any vintage remains on the TS surface.

---

## Coverage

Re-read in full this round:
- **All 7 R7.4-touched files** — FileAttachRail, Hub, Inbox, Knowledge, Calendar, tauri.ts (client-tauri), RequirementDetail (web) — verified in context against the diff.
- **Streaming surface** — `shared/src/hooks/useReqStream.ts`, `shared/src/hooks/useChatStream.ts`, `web/src/pages/Dashboard.tsx` SSE loop — leak/abort/`.ok`/`\r` all clean.
- **Other client-tauri routes with effects/listeners** — ProjectDrive, MyWorkload, ProjectPulse, TaskDetail, Clarify (date helper) — race/leak/`.ok` clean.
- **shared/api** — `client.ts` (`json()` ok-check), `time.ts` (NaN guard), `index.ts` (export chain).
- **Full-tree greps** — all `new Date(` (~40 source sites bucketed), all raw `.then(r=>r.json())`, all `key={i|idx|index|n}`, all `: any`/`as any`/`@ts-*`, AssigneeSelector listUsers guards, vite dev proxy.
- **Build config** — `client-tauri/web-src/vite.config.ts` `/api` proxy confirmed (validates tauri.ts dev path).

git scope cross-check: only the 7 in-scope files changed since R7.3 (`a5c700e`); working tree otherwise clean.
