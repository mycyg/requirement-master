# R7 Round 13 — SSE handler audit

HEAD `44e1f9a` (R7.12). Scope: confirm R7.12's N1 fix is complete, and prove that
R7.11's `delivery.doc_ready`→`all` dual-publish did not accidentally light up any
*other* previously-dead SSE handler on either surface.

## Verdict: CLEAN

N1 is fully and correctly removed. The `delivery.doc_ready`→`all` publish lights up
exactly one intended consumer (the scoped DeliveryWizard) and is silently ignored
everywhere else. No handler on either surface fires an OS notification, toast, or
navigation for an event it shouldn't. Both TS projects (Tauri web-src + web)
typecheck clean. No fixes required.

## N1 removal confirmation

`client-tauri/web-src/src/App.tsx`:
- The unconditional global `delivery.doc_ready` branch is **GONE**. In its place
  (lines 202-207) is an explanatory comment documenting why there is deliberately
  no global handler. The first `push-event` handler (lines 187-208) now matches
  **only** `requirement.ready`.
- `requirement.ready` branch (lines 188-201) **remains** — toast + `osNotify`,
  org-wide by design (every desktop user is a worker who wants new-claimable-work
  pings). Comment at 189-190 states the intent explicitly. Correct.
- `notification.created` handler (second `push-event`, lines 212-225) is
  **unaffected** — still toast + `osNotify` + `refreshUnreadBadge`, gated on
  `p?.event !== "notification.created"` early-return and `if (!title) return`.
  `notification.created` is published only to `user:{id}` (never `all`), reaching
  the client via the `/stream/me` connection. No org-wide leak.
- No syntax/logic breakage from the removal: the file is well-formed (the removed
  `else if` was the only other branch in handler #1, so collapsing it to a single
  `if` is clean) and `npx tsc -p tsconfig.json --noEmit` exits 0 (see below).

The double-toast the worker previously saw (App.tsx generic "AI 助理写完交付文档了"
+ DeliveryWizard "交付文档已生成") is also eliminated, since the generic branch is gone.

## all-topic event → consumer matrix (every event, every handler, intended?)

Distinct event names published to `bus.publish("all", ...)` in `app/` (verified by
enumerating all 28 call sites across auto.py, decompositions.py, deliveries.py,
delivery_upload.py, meetings.py, project_drive.py, requirements.py, sync.py):

| `all` event | # sites | web `all` consumer (Dashboard `/stream`) | Tauri `all` consumer (`push-event`) | intended? |
|---|---|---|---|---|
| `requirement.updated` | 17 | Dashboard `refresh()` (non-heartbeat) ✓ | Hub `refresh()` ✓; TaskDetail `refresh()` **iff `data.requirement_id===id`** ✓ | YES — read-only list/detail refresh, no toast/OS/nav |
| `requirement.ready` | 3 | Dashboard `refresh()` ✓ | App.tsx toast+`osNotify` (intended org-wide worker ping) ✓; Hub `refresh()` ✓ | YES — the one intended global OS popup |
| `delivery.doc_ready` | 2 | no string handler (Dashboard incidental `refresh()`) ✓ | **DeliveryWizard only**, gated `step===2 && data.requirement_id===reqId` → close+toast ✓ | YES — scoped to the wizard's own req; ignored elsewhere |
| `revision.requested` | 1 | Dashboard `refresh()` ✓ | **no handler → ignored** ✓ | YES — falls through; assignee gets a user-scoped `notification.created` instead |
| `meeting.ready` | 1 | Dashboard `refresh()` ✓ | **no handler → ignored** ✓ | YES |
| `meeting.insight_confirmed` | 1 | Dashboard `refresh()` ✓ | **no handler → ignored** ✓ | YES |
| `drive.changed` | 1 | Dashboard `refresh()` (incidental) | **no handler → ignored** ✓ | YES (accepted-P3 F4: latent, no UI reaction) |
| `drive.comment` | 1 | Dashboard `refresh()` (incidental) | **no handler → ignored** ✓ | YES (accepted-P3 F4) |

**The key audit result.** Every event-name comparison in the *entire* Tauri client
was enumerated (`git grep '\.event ===|\.event !=='` across all .ts/.tsx):

- `DeliveryWizard.tsx:46` → `delivery.doc_ready` (req-scoped, step-gated)
- `Hub.tsx:64` → `requirement.ready` | `requirement.updated` (read-only refresh)
- `Inbox.tsx:47` → `notification.created` (`user:` topic, not `all`; read-only refresh)
- `TaskDetail.tsx:65` → `requirement.updated` | `workspace.updated` (req-id-gated)
- App.tsx handler #1 → `requirement.ready` only; handler #2 → `notification.created` only

No Tauri handler matches `revision.requested`, `meeting.ready`,
`meeting.insight_confirmed`, `drive.changed`, or `drive.comment`. Those five reach
the `push-event` bridge and fall through every `if` → **no-op**. So R7.11's
dual-publish lit up exactly **one** consumer — the DeliveryWizard, which is the
intended target and is double-guarded (`requirement_id===reqId` AND `step===2`).
**No accidentally-lit dead handler. No org-wide toast/OS/navigation noise.**
N1 was the only handler the dual-publish could have lit, and it is now removed.

Other surfaces named in the prompt: `FileAttachRail.tsx` and `ProjectDrive.tsx`
have **no** `useEvent("push-event")` handler at all (verified by `git grep`); the
earlier file-list hit was a substring false-positive (`addEventListener` DOM
listeners), not an SSE consumer. So neither consumes any `all` event.

Cross-surface scoping note (unchanged, confirmed): Tauri's `sse.rs` subscribes to
exactly two streams — `/api/push/stream` (`all`, line 38) and `/api/push/stream/me`
(`user:{id}`, line 43) — both forwarded to the same `push-event`. It never
subscribes to `req:{id}` or `job:{id}`. So a `req:`-only `delivery.doc_ready`
(pre-R7.11) genuinely never reached the client — confirming the N1 handler was
dead before R7.11, exactly as Round 12 diagnosed.

## DeliveryWizard completion + Dashboard refresh-rate check

**DeliveryWizard completion — correct.** `DeliveryWizard.tsx:45-50`:
`if (step === 2 && p.event === "delivery.doc_ready" && p.data?.requirement_id === reqId)`
→ success toast + `onClose()`. The backend payload now carries `requirement_id`
(`delivery_upload.py:386/436`), so the guard matches. The wizard reaches `step 2`
via the `delivery-progress` event with `phase === "doc_pending"` (line 42). With the
`all` dual-publish in place, the `delivery.doc_ready` event reliably arrives at this
client's `push-event` bridge (it's no longer a `req:`-only event the Tauri client
never subscribed to), so the wizard completes instead of hanging — the Round-11 F1
hang is closed and stays closed. The `step===2` + `requirement_id` double-guard means
a *different* requirement's `delivery.doc_ready` flowing on `all` cannot prematurely
close someone else's open wizard. Correct and isolated.

**Dashboard refresh rate — not over-refreshing.** `web/src/pages/Dashboard.tsx`
connects to `/api/push/stream` (`all`) and, on every non-`heartbeat` frame, calls
`refresh()` (line 115). Heartbeats are framed as raw `: ping\n\n` comments
(`push.py:46`) with **no `event:` line**, so the parser's `event` stays `""` and the
`else if (line === "" && event)` block never fires on a ping — heartbeats correctly
do **not** refresh. (The one-time `connected` ack on connect *does* trigger one
refresh; harmless.)

Realistic `all` event rate: this is a small LAN deployment (single backend worker per
the R7.x notes). `all` traffic is requirement lifecycle transitions
(`requirement.updated`/`.ready`/`revision.requested`), per-completion
`delivery.doc_ready`, occasional `meeting.*`, and `drive.*` on drive edits. These are
human-paced — a handful per minute at busy times, not a flood. `refresh()` is a
read-only `Promise.all` over 7 status queries; the component already polls every
`TICK_MS = 6000` ms regardless, so SSE-driven refreshes are strictly *additive* to a
baseline the page already sustains, and a burst of N `all` events at worst collapses
into N cheap reads. The R7.11 concern (extra Dashboard refresh on the new
`all` `delivery.doc_ready`) is the negligible, already-accepted case: it fires once
per delivery, immediately before the `requirement.updated`(`delivered`) it would
refresh on anyway. No over-refresh risk.

## Findings

**None (CLEAN).**

Carryover items, unchanged and still correctly inert (restated for the ledger, not
new findings):
- **F4 (accepted P3):** `drive.changed` / `drive.comment` published to `all`,
  consumed by no handler on either surface. Latent fan-out overhead only; drive
  isn't realtime-critical. No UI reaction, so no noise.
- `revision.requested` / `meeting.*` on `all`: consumed by the web Dashboard's
  generic refresh, ignored by Tauri. Intended; the relevant user is notified via
  the user-scoped `notification.created` path.
- **F5 (accepted P3):** dead `job:{id}` publish (no stream endpoint); unrelated to
  the `all` topic.

## TS check

- Tauri client: `client-tauri/web-src`, `tsc -p tsconfig.json --noEmit` → **exit 0**
  (project includes `../../shared/src`; `strict`, `noUnusedLocals`,
  `noUnusedParameters`, `noFallthroughCasesInSwitch` all on).
- Web: `web`, `tsc -b` → **exit 0**.

Both clean. No type errors introduced by the N1 removal.
