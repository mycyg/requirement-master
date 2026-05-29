# R7 Round 12 — Integration re-verify

HEAD `bca6001` (R7.11). Re-verified the 3 SSE-wiring fixes R7.11 landed for
Round 11's F1/F2/F3, then re-ran the full emitted↔consumed SSE sweep across
backend + web + Tauri client to confirm the contract is coherent and that the
new wiring introduced no regression.

## Verdict: ISSUES (1) — 0 P1, 0 P2, 1 P3 (new), F4/F5 still accepted-P3

F1/F2/F3 are **functionally fixed and correct** — every gap Round 11 flagged is
closed and the payloads/parsers/lifecycles all line up. The core SSE contract is
now coherent on both surfaces. BUT the F1 wiring (publishing `delivery.doc_ready`
to `all`) lit up a **previously-dead, unfiltered** handler in the Tauri
`App.tsx`, which now broadcasts a toast + OS desktop notification to **every**
desktop user org-wide on **every** delivery-doc completion of any requirement
(N1, P3). It's noise, not corruption — but it's a real, new, user-visible side
effect of R7.11 that the fix's own design note didn't account for.

---

## R7.11 fix verification (F1/F2/F3, rigorous)

### F1 — `delivery.doc_ready` dual-published + `requirement_id` added — CORRECT
- `delivery_upload.py` now publishes `delivery.doc_ready` to BOTH `req:{id}` and
  `all`, in `_finalize_doc` (387/388) AND `_recover_stranded_delivery` (437/438),
  payload `{"delivery_id", "round", "requirement_id"}` (386/436).
- **Consumer satisfied:** the Rust client (`sse.rs`) parses each SSE record into
  `PushEvent { event, data }` where `data` is the parsed JSON, and re-emits as the
  Tauri `push-event`. So `DeliveryWizard.tsx:46`'s guard
  `p.event === "delivery.doc_ready" && p.data?.requirement_id === reqId` now
  matches (it could NOT match before — the old payload lacked `requirement_id`,
  the second half of the original double-bug). Confirmed.
- **Web not double-handled:** the web has NO `delivery.doc_ready` *string*
  handler anywhere (only a `delivery_doc_ready_at` field). `useReqStream`
  (`shared/src/hooks/useReqStream.ts`) updates `latestStatus` ONLY on
  `requirement.updated` with a `data.status`; the new `req:` `delivery.doc_ready`
  is appended to `events` but triggers no refresh. RequirementDetail still
  refreshes off the `requirement.updated` status=delivered that immediately
  follows (RequirementDetail.tsx:133). No double-fetch, no behavior change. ✓
- **`all` is PII-free for this payload:** ids + integer round only. Safe on the
  global topic. ✓
- **Recovery-path edge (low):** in `_recover_stranded_delivery`, the publish block
  is gated by `if r:` rather than by whether the `delivery_doc_pending→delivered`
  flip actually happened this call. If `_finalize_doc` committed the flip and
  published, then raised *after* the publishes (only a `bus.publish` raising could
  do this — and `publish` swallows `QueueFull`, so it's effectively non-throwing),
  recovery would re-publish a duplicate `delivery.doc_ready`. In every realistic
  failure (commit at 375 / flush at 378 raising — both *before* the publishes)
  recovery is the *sole* publisher, so no real double-publish. Consumers are
  idempotent-ish anyway (re-close an already-closed modal; one redundant toast).
  Noted, not a finding.

### F2 — Tauri `Hub.tsx` live-refresh on requirement.ready/.updated — CORRECT
- `Hub.tsx:63-67` adds `useEvent("push-event")` calling `refresh()` on
  `requirement.ready` / `requirement.updated`.
- **Events arrive:** both are published to `all` (sync.py:81/83 submit;
  the 11 `requirement.updated`→`all` sites), and the Rust client opens `/stream`
  (`all`) — so they reach `push-event`. ✓
- **Latest-closure / handlerRef:** `useEvent` (`tauri.ts:43-44`) stores the
  handler in a ref refreshed every render and the listener invokes
  `handlerRef.current` — so it always calls the newest `refresh` closure (which
  reads the current `tab` via `params.get`). No stale-tab refresh. ✓
- **Token guard / races:** `refresh` bumps `reqTokenRef` and only the latest token
  may `setItems` (Hub.tsx:26/46/50) — overlapping IPCs can't land out of order. ✓
- **No infinite loop:** `refresh` issues only read IPCs (`list_public_pool`,
  `list_my`); it publishes no SSE event, so a refresh can't re-trigger
  `push-event`. ✓
- Nit (not a bug): the comment says "debounced implicitly by refresh's own token
  guard" — the guard *de-dupes the write*, it does not debounce the *call*. A
  burst of N `all` events fires N read IPCs, only the last writes. Cheap, correct,
  just imprecise wording.

### F3 — web `useNotificationToasts` on `/stream/me` — CORRECT
- New `web/src/hooks/useNotificationToasts.ts`, mounted once in `web/src/App.tsx`
  `Shell` (line 129). `Shell` renders only after identify and is not remounted, so
  exactly one `/stream/me` connection for its lifetime.
- **SSE framing matches backend `_sse` (push.py:26-34):** backend emits
  `event: <name>\n` then one `data: <line>` per `splitlines()` line, blank-line
  terminated. The hook: `line.slice(6).trim()` for `event:` (6 chars), and
  `line.slice(5).replace(/^ /,"")` for `data:` (5 chars, strips the single
  framing space), joining multi-line `data:` with `\n` before `JSON.parse`. Exact
  round-trip with the backend's per-line framing — multi-line notification bodies
  survive. Heartbeat (`: ping`) and the initial `connected` event fall through
  harmlessly (guarded by `event === "notification.created"`). ✓
- **Payload contract:** backend ships `notification_out(row).model_dump()`
  (notifications.py:103-104) → `{id,type,severity,title,body,target_url,...}`. The
  hook reads `title/body/severity` only; severity is `"normal"|"high"` in practice
  (lifecycle.py / requirements.py), so `high`→`warn` tone, else `info`. `tone:
  "warn"|"info"` are valid `ToastTone`s (shared/src/ui/Toast.tsx:5). Type-safe. ✓
- **Reconnect backoff:** capped exponential 1s→30s, reset to 1s on a successful
  connect (mirrors Dashboard/sse.rs). ✓
- **Cleanup / no leak:** `return () => { ctrl.abort(); reader?.cancel() }`. Abort
  rejects the in-flight `read()`, the catch returns on `signal.aborted`; the
  reader cancel releases the body lock immediately. Matches the existing
  Dashboard + useReqStream pattern. ✓
- **No double-fire:** web's three SSE consumers are now disjoint — Dashboard
  `/stream` (`all`), RequirementDetail `/stream/req/{id}`, this hook
  `/stream/me` (`user:`). `notification.created` is published only to
  `user:{id}`, consumed only here. Once per notification. ✓
  (StrictMode double-invokes the effect in *dev* → 2 transient connections, the
  first aborted by its own cleanup; prod build strips it. Pre-existing pattern,
  same as Dashboard. Not a regression.)

---

## SSE contract re-sweep (emitted ↔ consumed, both surfaces)

Topics published: `all`, `req:{id}`, `user:{id}`, `job:{id}`. Stream endpoints:
`/stream`(all), `/stream/req/{id}`, `/stream/me`(user:). No `job:` endpoint.

Tauri opens `all` + `user:` (sse.rs:38/43) — still never `req:{id}`.
Web opens `all` (Dashboard) + `req:{id}` (RequirementDetail) + **now** `user:`
(useNotificationToasts).

| event | topic(s) | web | Tauri | status |
|---|---|---|---|---|
| requirement.updated | all + req:{id} | Dashboard(all)✓ RequirementDetail(req)✓ | App toast n/a; Hub refresh✓ (F2); TaskDetail refresh✓ | OK both |
| requirement.ready | all | Dashboard refresh✓ | App toast+OS✓; **Hub refresh✓ (F2 new)** | OK both |
| notification.created | user:{id} | **useNotificationToasts✓ (F3 new)** | App toast+OS+badge✓; Inbox refresh✓ | OK both |
| delivery.doc_ready | **req:{id} + all (F1 new)** | no string handler (refreshes via requirement.updated)✓ | **DeliveryWizard close✓ (F1 fixed)**; App.tsx unfiltered toast (N1) | F1 fixed; N1 |
| workspace.updated | req:{id} only | RequirementDetail no refresh on it (status-only) | TaskDetail refresh✓ when viewing that req | unchanged (intended; doc'd in R7.11) |
| comment.added | req:{id} only | RequirementDetail/CommentsPanel✓ | n/a | OK |
| ai.* (started/thinking/text/tool_call/done/failed) | req:{id} only | AILiveView✓ | n/a (chat POST-stream) | OK |
| revision.requested | all | Dashboard refresh✓ | no string handler; submitter's `revision` notification.created covers the assignee | minor (P3, pre-existing F4 class) |
| drive.changed / drive.comment | all | no handler (Dashboard incidental re-fetch) | no handler | F4 (accepted P3) |
| meeting.ready / meeting.insight_confirmed | all | Dashboard refresh✓ | no handler | minor (pre-existing) |
| job.updated | job:{id} + user:{id} | — | user: copy reaches App as a `push-event` with no matching `if` → ignored; polled via GET /jobs/{id} | F5 (accepted P3) |

**Coherence:** every event a UI *needs* live is now consumed on both surfaces
where it's relevant. The two Round-11 hard gaps (Tauri DeliveryWizard hang; web
no live notifications) are closed, and the Tauri Hub now live-updates. The
remaining unconsumed events (drive.*, job.* `job:` copy, meeting.* on Tauri) are
the previously-accepted F4/F5 P3 items — no behavior regression, just latent
overhead. `workspace.updated` is deliberately still `req:`-scoped (R7.11 chose
not to dual-publish it to `all` to avoid over-refreshing the web Dashboard on
every checklist edit); Tauri TaskDetail still updates status via the dual-
published `requirement.updated`, so this is an intended trade, not a gap.

---

## Regression check

- **delivery_upload.py:** AST-parses clean. The added publishes are pure
  fan-out additions after the existing commit+flush; no reordering of the
  status flip / notification flush / commit. The submitter's `delivered`
  notification path (queue→commit→flush) is untouched. No new exception surface
  (`bus.publish` is non-throwing). ✓
- **Hub.tsx (F2):** read-only IPC refresh; cannot loop; token-guarded. ✓
- **useNotificationToasts.ts (F3):** isolated new hook; disjoint stream from the
  other two web consumers; clean teardown. ✓
- **No contract drift introduced:** the `delivery.doc_ready` payload gained
  `requirement_id` (additive); no TS type consumes it as a typed field (the Tauri
  handlers read `p.data?.requirement_id` off `any`), so no shared-type change was
  needed and none drifted. ✓
- **Web RequirementDetail / DeliverablesTab:** still driven by the
  `requirement.updated`→`latestStatus`→`refresh` path; the extra `req:`
  `delivery.doc_ready` is inert there. The web Dashboard fires one *extra*
  (idempotent, 6s-polled anyway) refresh on the `all` `delivery.doc_ready` just
  before the `requirement.updated` it would refresh on regardless — negligible,
  as the commit note states. ✓
- **NEW side effect → N1 below.**

---

## Findings

### N1 (P3, NEW — introduced by the F1 wiring) — Tauri `App.tsx` now broadcasts a delivery-doc toast + OS notification to every desktop user, org-wide
`client-tauri/web-src/src/App.tsx:199-202` has an unconditional
`else if (p?.event === "delivery.doc_ready")` → `toast("AI 助理写完交付文档了")`
+ `osNotify(...)`, with **no requirement_id / ownership / recipient filter**.

This handler shipped in `f517517` but was **dead code** until now: pre-R7.11,
`delivery.doc_ready` was published only to `req:{id}`, which the Tauri client
never subscribes to (sse.rs opens only `all` + `me`), so it never fired. F1's new
`bus.publish("all", "delivery.doc_ready", …)` makes it live for the first time —
and because `all` is the org-wide topic, **every** desktop client now pops an
in-app toast **and a Windows desktop notification** every time **anyone**
finishes **any** delivery doc, regardless of whether that user submitted, claimed,
or has any relationship to the requirement.

Secondary, smaller: the **delivering** worker who has the DeliveryWizard open gets
a **double toast** — App.tsx's generic "AI 助理写完交付文档了" *and*
DeliveryWizard's specific "交付文档已生成" — on the same event.

- Severity P3: pure noise, no data effect, but it's an OS-level desktop popup to
  uninvolved users, which is more intrusive than an in-app toast and easy to
  notice in a multi-user LAN deployment. It's a genuine *new* behavior R7.11
  introduced and the fix's design note ("fires once per delivery, so the extra
  web-Dashboard refresh is negligible") only reasoned about the web Dashboard, not
  this Tauri handler.
- Fix options (all small, no backend change): (a) gate App.tsx:199 by the same
  ownership signal the submitter already gets — i.e. **drop** the App.tsx
  `delivery.doc_ready` branch entirely and rely on the `delivered`
  `notification.created` (user-scoped) the submitter already receives + the
  DeliveryWizard toast for the worker; or (b) filter it to requirements the user
  is involved in; (a) is cleanest and also removes the double-toast. The relevant
  fact: the submitter is *already* notified via `notification.created`
  (delivery_upload.py flush at 378/435 → `user:` topic), so the broadcast branch
  is redundant for the one user who actually cares.

### Carryover (unchanged, accepted P3 in R7.11 — restated for the ledger)
- **F4** `drive.changed` / `drive.comment` published to `all`, consumed by no
  one on either surface. Latent overhead, drive isn't realtime-critical.
- **F5** dead `job:{id}` publish (no stream endpoint; `user:` copy + GET poll
  cover it); `DriveManifestOut.cursor` shipped but unread by Tauri `sync.rs`.
- `workspace.updated` intentionally kept `req:`-scoped (R7.11 design choice).

### What is solid (re-confirmed; reviewers can stop re-checking)
- F1 payload now carries `requirement_id` → DeliveryWizard guard matches; web is
  not double-handled (no `delivery.doc_ready` string handler, refreshes off
  `requirement.updated`); `all` copy is PII-free.
- F2 Hub uses the handlerRef latest-closure, token-guarded refresh, no loop.
- F3 hook's SSE parsing exactly mirrors the backend `_sse` per-line framing,
  capped-backoff reconnect, clean abort+cancel teardown, single mount, disjoint
  from the other two web streams → notification.created consumed exactly once.
- Auth/topic scoping unchanged: `/stream/me` resolves the topic from the cookie
  user id (not a path param) — no cross-user notification leak.
