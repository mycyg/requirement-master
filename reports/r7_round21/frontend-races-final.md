# R7 Round 21 — Final adversarial frontend races

HEAD `3dcf440` (R7.17). 4th/final round of the 4-consecutive-clean gate.
Tree frozen; **no code written**. tsc run on shared + web + client-tauri.

## Verdict: NEEDS FIXES (1)

One real **P2 residual hot-mic / mic-track leak in `VoiceButton`** survives R7.15.
It's narrow but it is exactly the bug-class this gate exists to kill, and the
prompt named the triggering gesture ("rapid press-release-press"). The gate does
**not** pass clean. Everything else — SpeakButton, the token-guard family, the
SSE/toast/event layer, the Tauri event bridge — held under genuinely hostile
tracing. Details below; the P2 is the only blocker.

---

## VoiceButton / SpeakButton final edges

### P2 — VoiceButton: concurrent `start()` orphans the first mic stream (`web/src/components/VoiceButton.tsx`)

R7.15 added a **single boolean** intent flag `wantRecordingRef`. That flag solves
press-then-release-before-getUserMedia-resolves (release sets `want=false`, the
resolved stream is closed at line 33). It does **not** survive two *concurrent*
`start()` calls, because a boolean cannot encode "the FIRST start must abort
because a SECOND superseded it." This is the textbook boolean-vs-state-machine
gap (your own SpeakButton fixed the analogous TTS case with a monotonic
`playGeneration`; VoiceButton never got the same medicine).

Unfolding of events (mic already permission-granted once, so getUserMedia
resolves in ~1–50ms — the overlap window):

1. press1 → `start()`: `want=true`, `await getUserMedia()` (#1 in flight).
2. release1 → `stop()`: `want=false`. `mediaRef`/`streamRef` still null (recorder
   not built yet) → nothing stopped. `setRecording(false)`.
3. press2 → `start()`: `want=true` AGAIN, `await getUserMedia()` (#2 in flight).
4. getUserMedia **#1 resolves**: line 33 sees `want===true` (press2 set it!) → it
   sails past the guard, sets `streamRef.current = stream1`, builds `mr1`,
   `mediaRef.current = mr1`, `setRecording(true)`.
5. getUserMedia **#2 resolves**: `want` still true → **overwrites**
   `streamRef.current = stream2`, `mediaRef.current = mr2`.
   `stream1` and `mr1` are now unreferenced — **never stopped**.
6. release2 → `stop()` stops only `mr2`/`stream2`. **stream1's mic track stays
   live until GC.** The recording-light/OS-mic-indicator stays on with nobody
   holding the button — the precise "hot mic" symptom R7.15 was chartered to end.

The unmount cleanup does NOT mask this: both streams are created while the
component is alive; the leak is a same-mount orphan, not an unmount escape.

Why it's P2 not P1: requires two getUserMedia calls overlapping, which needs
press-release-press inside the post-grant resolve window (tens of ms). A user
fat-fingering the "按住说话" button, or a trackpad/touch double-trigger, hits it.
Low frequency, high creep-factor: a silently live microphone is the kind of thing
that ends up in a "why is the mic light on" bug report and erodes trust harder
than any visual jank. It blocks the clean-gate because it's an unbounded
peripheral leak, not a cosmetic flicker.

Shape of the fix (for the implementer, NOT applied here): give `start()` a
monotonic generation claimed synchronously before the await (mirror SpeakButton),
bail after each `getUserMedia` resolve if a newer `start()` superseded this one
(closing that resolve's own tracks), and on overwrite stop the prior
recorder/stream. ~6 lines. Do not reach for a library.

### SpeakButton — CLEAN under the named adversarial combos

- 3+ buttons on web `Clarify` (each `Bubble`, `QuestionCard`, `SummaryCard` +
  hidden autoplay driver) all share module-level `currentAudio`/`playGeneration`.
  Traced: autoplay-fires-while-user-clicks-another (both orderings), click-A-then
  -click-B, unmount-during-play, unmount-during-fetch. The synchronous
  `++playGeneration` claim + post-fetch `myGen !== playGeneration` supersede +
  `aliveRef` unmount bail + `onpause`→`setPlaying(false)` cross-button flip all
  compose correctly. Exactly one voice in every ordering; no orphaned `<audio>`,
  every `URL.createObjectURL` has a matching revoke on the `onended`/`stopCurrent`
  paths. R7.17's `aliveRef` is genuinely load-bearing now (used at line 66 + 96).
- Tauri `Clarify` has no SpeakButton (TTS deferred), so the multi-button overlap
  surface is web-only — and it holds.

### NOTE (dev-only, NOT a blocker) — `aliveRef` is permanently false after StrictMode double-invoke

`aliveRef = useRef(true)` is set `false` by the unmount cleanup, and nothing
re-sets it to `true` on re-setup. Under React 18 **dev** StrictMode (enabled in
both `main.tsx`), the simulated mount→unmount→remount leaves `aliveRef.current ===
false` for the component's whole life → autoplay/`speak()` would no-op in dev.
**Production builds do not double-invoke**, so the guard works in prod (traced:
single setup, ref stays true). Worth a `useEffect(() => { aliveRef.current =
true; return () => { aliveRef.current = false }; }, [])` someday for dev fidelity,
but it does not affect shipped behavior. Flagging only because the prompt asked
"can a remount reset a ref such that a guard is defeated" — here a remount makes
the guard *over*-fire (fail-safe: silence), not leak.

---

## Token-guard / SSE / Tauri-event final edges

**Token-guard family — CLEAN.** Audited every monotonic-token refresher:
web `Dashboard`, `RequirementDetail`, `Clarify`; tauri `TaskDetail`, `Hub`,
`Inbox`, `AdminPanel`; both `Knowledge` ask-poll loops. Every one bumps the token
synchronously, then guards **both** the success and the error setState behind the
`token !== ref.current` / `askTokenRef !== myToken` check. I specifically hunted
the prompt's "guard present but a SECOND un-guarded setState still leaks" pattern
— **none found**. The Knowledge poll loops re-check the token after *every* await
(before and after each fetch), the strongest variant.

**Remount-defeats-a-guard? — No.** Token refs start at 0 via `useRef(0)`; a real
unmount→remount creates a NEW fiber/ref, and the old fiber's in-flight promise
closes over the OLD ref object — so a stale resolve compares against its own
generation and a cross-component overwrite is structurally impossible. The token
guards prevent stale *ordering* within a living component; they intentionally do
not (and need not) prevent setState-after-unmount, which React 18 silently no-ops.

**Dashboard SSE `setConnected(false)` (line 131) — theoretical post-unmount
no-op, not a bug.** The only way to reach it without returning at the abort check
(line 132) is the coincidence of a server-close `read()` resolving `{done:true}`
in the same tick the unmount-abort fires. Result: one `setConnected(false)` on an
unmounted component = silent React-18 no-op. No DOM, no warning, no leak.
`useNotificationToasts` has no setState after its loop at all → fully clean.

**useNotificationToasts + Dashboard `/api/push/stream` + useReqStream under
repeated network flaps — CLEAN.** Each has its own `AbortController` +
`reader.cancel()` in cleanup, capped exponential backoff (1s→30s), and aborts the
backoff sleep on signal. No shared reader, no backoff-storm convergence (each
reconnects independently with its own capped timer), no toast flood (toasts only
on a successfully-parsed `notification.created` frame, and a flapping connection
yields reconnect attempts, not duplicate frames). `useReqStream`'s `flush()`
checks `alive` before every setState.

**Tauri `useEvent` burst during route transition — CLEAN.** `lib/tauri.ts`
`useEvent` holds the handler in a ref (re-pointed every render) so a burst of
`push-event`s always hits the current closure, and the `alive`-flag +
dispose-if-resolved-after-unmount pattern (lines 49-58) prevents the
fast-mount/unmount listener leak. The App-level `push-event`/`navigate`/
`tray-action`/`sse-status` handlers only `nav()`/`toast()`/`osNotify()` (all
safe post-transition) — none touch component state of an unmounting route.
`osNotify`'s async permission prompt is fire-and-forget and guarded by try/catch.
`refreshUnreadBadge`'s 250ms debounce coalesces a 10-notification burst into one
fetch and never resets the badge to 0 on transient error.

---

## setState-after-unmount final scan

No reachable setState-after-unmount that causes a **race, crash, or stale DOM**.
Catalogued the dev-only silent-no-op cases (React 18 swallows all of them):

- `Dashboard` SSE `setConnected(false)` — the line-131 coincidence above.
- web `NotificationsPage.load()` — no token/alive guard; rapid 未读/全部 toggle can
  land the slower fetch last (ordering flicker) and setState after unmount. Its
  Tauri twin `Inbox` HAS a token guard; this web twin is the weaker sibling.
  Pre-existing, low-frequency (tab toggles), idempotent re-fetch → **P3, not a
  blocker**, not introduced by R7.
- `ProjectPulse` (tauri) and `ClientDownloadBanner` (web) — single-shot / tab-
  return mount fetches with no `alive` guard. App-shell-lifetime components that
  rarely unmount; prior rounds already accepted these. P3 at most.
- `RequirementDetail` `DecompositionPanel.trigger` line 536 —
  `window.setTimeout(() => onChange(), 1400)` is uncancelable; navigating away
  inside 1.4s fires a token-guarded `refresh()` on an unmounted fiber → silent
  no-op + one wasted fetch. Cleanliness wart (P3), not a race.

Timers/listeners swept: `Dashboard` interval (vis-gated, cleared on cleanup),
`ProjectMeetings` 1500ms poll (`alive` + `clearInterval`), `ProjectDrive` 600ms
`setProgress(null)` (`if (alive)` token check inside), `AdminPanel` 200ms debounce
(cleared + token-guarded refresh), both Knowledge 900/1000ms poll loops
(token-checked each iteration). All `addEventListener` sites (15) add-in-effect /
remove-in-cleanup. No uncleaned interval; no requestAnimationFrame in the tree.

---

## tsc + Findings

```
shared        : npx tsc -p tsconfig.json --noEmit   → EXIT 0  (clean)
web           : npx tsc -b                           → EXIT 0  (clean)
client-tauri  : npx tsc -p web-src/tsconfig.json --noEmit → EXIT 0 (clean)
```

**Findings**

| # | Sev | Component | Issue |
|---|-----|-----------|-------|
| 1 | **P2** | `web/src/components/VoiceButton.tsx` | Concurrent `start()` (rapid press-release-press inside the getUserMedia resolve window) orphans the first MediaStream/MediaRecorder → live mic-track leak. Boolean `wantRecordingRef` can't supersede; needs a monotonic generation like SpeakButton. **Blocks the clean gate.** |
| 2 | P3 | `web/src/pages/NotificationsPage.tsx` | `load()` has no token/alive guard (tauri `Inbox` twin does); rapid tab toggle → ordering flicker + post-unmount no-op. Pre-existing. |
| 3 | P3 | `web/.../RequirementDetail.tsx:536` | Uncancelable `setTimeout(onChange, 1400)` can fire a wasted token-guarded refresh after unmount (silent no-op). |
| 4 | P3 (dev only) | `web/src/components/SpeakButton.tsx` | `aliveRef` stays `false` after StrictMode dev double-invoke → autoplay no-ops in dev. Prod unaffected. |

**Gate result:** does NOT pass clean — finding #1 (P2) must be fixed and then
re-verified before ship. The streak resets. The rest of the surface
(SpeakButton, token-guards, SSE/toast/event layer, Tauri bridge, timers,
listeners) is genuinely clean after hostile tracing.
