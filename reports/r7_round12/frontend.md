# R7 Round 12 — Frontend regression + final

HEAD `bca6001` (R7.11), tree clean. R7.11 TS/TSX surface = exactly 3 files
(`git show bca6001 --stat`): `web/src/hooks/useNotificationToasts.ts` (NEW, +88),
`web/src/App.tsx` (+3), `client-tauri/web-src/src/routes/Hub.tsx` (+13). The
DeliveryWizard "expectation" in the commit was a **backend** payload change
(publish `delivery.doc_ready` to `all` + add `requirement_id`); `DeliveryWizard.tsx`
itself was NOT edited — its existing `p.data?.requirement_id === reqId` guard now
matches because the backend finally sends that field. No frontend regression there.

## Verdict: CLEAN

All three R7.11 frontend changes are correct and regression-free. Fresh full-tree
`tsc` pass is clean across all three surfaces (shared / web / client-tauri web-src).

## R7.11 frontend-change verification (3 items)

### 1. `web/src/hooks/useNotificationToasts.ts` (NEW) — CLEAN

Full review of the fetch + ReadableStream SSE reader. No leak, no loop, no stuck
state, no double-toast, no parse crash. Specifics:

- **No leak.** Cleanup calls `ctrl.abort()` then `reader.cancel()` (try/wrapped).
  `abort()` rejects the in-flight `fetch`/`reader.read()` with an AbortError, which
  the inner `catch` swallows; the immediately-following `if (ctrl.signal.aborted)
  return` (line 74) exits the async IIFE so the `while (!ctrl.signal.aborted)` loop
  terminates. Both the request and the stream reader are released.
- **No infinite hot-loop.** Reconnect path always `await`s `setTimeout(backoff)`
  (line 77) before retrying, and re-checks `aborted` both before the sleep (76) and
  via the loop condition (30). Backoff starts at 1000ms, doubles, caps at 30s (78),
  and resets to 1000 only after a *successful* `r.ok && r.body` connect (34) — so a
  flapping endpoint can't busy-spin.
- **`data:` accumulation is correct.** Lines are split on `\n` with a trailing `\r`
  stripped (`.replace(/\r$/, "")`, line 46) — the missing-`\r`-strip risk is handled.
  Each `data:` line strips exactly one leading space (`.replace(/^ /, "")`, SSE spec)
  and pushes to `dataLines`; on the blank-line dispatch they're rejoined with `\n`
  (57). This exactly mirrors the backend `_sse()` framing in `app/routers/push.py`
  (`splitlines()` → per-line `data:`) and the Rust `sse.rs` decoder. Multi-line
  notification bodies round-trip losslessly.
- **Event-reset is correct.** On the blank-line boundary, after the optional dispatch,
  both `event = ""` and `dataLines = []` reset unconditionally (68–69) — so a
  subsequent event with no `event:` line can't inherit the prior event name, and
  stale data lines never bleed into the next record.
- **No double-toast.** Toast fires only inside the `line === ""` branch, gated on
  `event === "notification.created" && dataLines.length`. One toast per complete SSE
  record. The web has NO other `notification.created`/`stream/me` consumer
  (grep confirms `useNotificationToasts` is the sole web SSE listener; `useReqStream`
  is a per-`req:` detail stream, different topic, no toast).
- **No JSON.parse crash.** `JSON.parse(dataLines.join("\n"))` is wrapped; a malformed
  payload is swallowed and the stream continues (64–66) rather than killing the loop.
- **Payload type matches the wire.** Backend `notification.created` data is
  `NotificationOut.model_dump(mode="json")` (`services/notifications.py`) →
  `{id, type, severity, title, body, target_url, ...}`. The hook's `NotifPayload`
  (`id/title/body/severity/target_url`, all optional) is a safe structural subset.
  `severity` default is `"normal"`, so the `high|urgent` check correctly falls
  through to `tone: "info"` — `toast({title, description, tone})` matches `ToastItem`.
- **Topic is cookie-scoped.** `/api/push/stream/me` resolves to `user:{id}` server-side
  (push.py line 95–104) — no cross-user disclosure, consistent with the Tauri client.

Minor (non-blocking, not a defect): `description: n.body || undefined` coerces an
empty-string body to undefined — intentional and correct (empty description renders
nothing). No action needed.

### 2. `web/src/App.tsx` — CLEAN

- `useNotificationToasts()` is called at the top of `Shell` (line 129), and `Shell`
  is rendered only inside the `return` that is reached **after** the `if (!me) return
  <NicknameDialog/>` early-out (line 78). So the stream opens only once the user is
  identified (cookie present) — correct gating; an unauthenticated `/stream/me` would
  401 and just backoff-retry harmlessly, but it won't even get there.
- **Mounted once.** `Shell` is rendered exactly once under `<BrowserRouter>` (94).
  The hook has `[]` deps, so one stream per Shell lifetime. No remount churn (Shell is
  not keyed/conditionally swapped).
- **Hook-order is sound.** `useNotificationToasts` (an effect-only hook) sits beside
  `useNavigate` / `useCommandMenu` at the top of `Shell`, unconditionally, before any
  early return in `Shell` (there are none). The `if (loading)` / `if (!me)` early
  returns live in the **parent** `App`, before `Shell` is ever rendered — they don't
  straddle this hook, so no conditional-hook violation. React 18 StrictMode double-mount
  in dev would abort+reopen the stream once; harmless and self-correcting.
- The hook runs inside `<BrowserRouter>` but doesn't use router context, so ordering
  relative to BrowserRouter is irrelevant.

### 3. `client-tauri/web-src/src/routes/Hub.tsx` — CLEAN

- **No stale closure.** `useEvent` (`lib/tauri.ts`) stores the handler in a
  `handlerRef` updated every render and dispatches through it, while the underlying
  Tauri `listen` is registered once on `[event]`. So the `push-event` handler always
  sees the current `refresh` closure, which closes over the current `tab` — a tab
  switch is reflected without re-subscribing. Pattern is identical to the already-
  verified `Inbox.tsx` (`notification.created` → refresh) and `TaskDetail.tsx`.
- **No infinite loop.** `refresh()` only issues read-only IPC (`list_public_pool` /
  `list_my`) — it mutates nothing server-side and emits no SSE event, so a refresh
  cannot trigger another `requirement.ready`/`requirement.updated`. The user-initiated
  `claim`/`startDoing` mutations do emit `requirement.updated`, but they already call
  `refresh()` directly; the echoed event causing one extra `refresh()` is a single
  redundant read, fully absorbed by the token guard — not a loop.
- **Token guard interaction is correct.** Each `refresh` bumps `reqTokenRef` and the
  two `token !== reqTokenRef.current` checks (46, 50) ensure only the newest in-flight
  refresh writes `setItems`/`setErr`. An event-driven refresh and a `[tab]`-effect
  refresh racing simply means the later one wins — no torn state, no stale list under
  the wrong tab header. The "debounced implicitly" comment is accurate.
- **`[tab]` effect coexists.** The mount/tab-change `useEffect` (56) and the event
  listener are independent; both funnel through the same token-guarded `refresh`.
- Payload type `{ event: string }` matches the Rust `PushEvent { event, data }` shape
  forwarded from `sse.rs`; `requirement.ready`/`requirement.updated` both arrive on
  the `all` topic the client already opens (confirmed in sse.rs + push.py docstring).

## Fresh full-tree pass

`tsc` run per surface (each with its own tsconfig + strict, noUnusedLocals,
noUnusedParameters):

- `shared/tsconfig.json --noEmit` → **exit 0**, no diagnostics.
- `web/tsconfig.json` via `tsc -b` (project refs → pulls shared) → **exit 0**.
- `client-tauri/web-src/tsconfig.json --noEmit` (includes ../../shared/src) → **exit 0**.

No `any`-creep introduced by R7.11: the new hook uses a typed `NotifPayload`, no
`any`. (The `catch (e: any)` and `useEvent<any>` usages in Hub/App are pre-existing,
out of R7.11 scope.) No unused imports/vars, no implicit-any, no type errors anywhere
in the three TS surfaces. TS surface remains CLEAN as it has been since R7.5.

Note: `web/dist/assets/index-ZLNoGMVN.js` shows a `stream/me` reference — that is a
stale compiled bundle artifact, not source, and is not type-checked. Ignorable.

## Findings

None. CLEAN.

The three R7.11 frontend changes are each correct: the new web SSE hook is leak-free,
loop-free, double-toast-free, and parse-safe with correct multi-line `data:` framing
and CRLF handling; it is mounted exactly once under the authed Shell branch with no
hook-order issue; and the Hub `push-event` refresh has no stale closure and cannot
loop (read-only refresh, token-guarded). The full-tree `tsc` pass is clean across
shared, web, and client-tauri web-src. No regression from R7.6–R7.11 detected, and
no defect the prior rounds missed.
