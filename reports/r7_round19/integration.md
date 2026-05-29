# R7 Round 19 — Integration final confirmation

HEAD `3dcf440` (R7.17), FROZEN tree. Re-ran the whole-system integration angle on
the FINAL tree: mapped every `bus.publish` to its consumer(s) on both surfaces,
traced the full create→accept lifecycle across backend + web + Tauri, diffed the
notification / delivery.doc_ready payloads against TS types, and re-checked the
single-worker docs. Confirmed every Round-11 gap (5) stays closed and the R7.12
N1 OS-popup regression is fixed. Re-verified nothing in R7.12–R7.17
(notification live-publish, audio, race guards, orphan guards) re-broke parity.

## Verdict: COHERENT (no P1/P2) — 0 blockers

The SSE event contract is coherent on both surfaces. Every event a UI *needs*
live is consumed where it's relevant; no consumer waits on an event it can never
receive that matters; no PII leaks org-wide. The workflow chain is intact (no
dead button, no impossible state, no removed endpoint). No TS↔Pydantic drift.
Single-worker is documented in BOTH the systemd unit and DEPLOY.md. The only
remaining unconsumed events are the long-accepted F4/F5-class P3 items (drive.*
on Tauri, dead `job:{id}` publish, unread `cursor`, `workspace.updated` Tauri),
all latent overhead — no behavior regression.

---

## SSE contract (emitted ↔ consumed, both surfaces)

Topics published: `all`, `req:{id}`, `user:{id}`, `job:{id}`. Stream endpoints
(`push.py`): `/stream`(`all`), `/stream/req/{id}`, `/stream/me`(`user:`). No
`job:` endpoint (by design — jobs polled via `GET /jobs/{id}`).

Subscriptions on the final tree:
- **Web**: `/stream`(`all`) Dashboard.tsx:105 · `/stream/req/{id}`
  RequirementDetail via useReqStream · **`/stream/me`** useNotificationToasts
  (App.tsx:129, mounted once in `Shell`, post-identify so cookie is valid).
- **Tauri**: `/stream`(`all`) + `/stream/me`(`user:`) (sse.rs:38/43) — still
  never `/stream/req/{id}` (intentional).

| event | topic(s) | web | Tauri | status |
|---|---|---|---|---|
| requirement.updated | all + req:{id} | Dashboard(all) refresh✓; RequirementDetail(req)→latestStatus✓ | Hub refresh✓; TaskDetail refresh✓ (filters on data.requirement_id — present on all `all` copies) | OK both |
| requirement.ready | all (payload: requirement_id/code/title/project_id) | Dashboard refresh✓ | App toast+OS✓ (reads code/title/requirement_id); Hub refresh✓ | OK both |
| notification.created | user:{id} ONLY (no `all` fanout — publish_notification 105 / threadsafe 124 both user-scoped) | useNotificationToasts toast✓ | App toast+OS+badge✓; **Inbox refresh✓** | OK both |
| delivery.doc_ready | req:{id} + all (payload carries requirement_id, 386/436) | no string handler (refreshes via requirement.updated)✓ | DeliveryWizard scoped close✓ (`data.requirement_id===reqId`); **no global App handler (N1 fixed)** | OK both |
| workspace.updated | req:{id} ONLY | RequirementDetail no refresh on it (status-only) | TaskDetail handler exists but event never arrives (Tauri not on `req:`) | P3 carryover (intended) |
| comment.added | req:{id} | RequirementDetail/CommentsPanel✓ | n/a | OK |
| ai.* (started/thinking/text/tool_call/done/failed) | req:{id} | AILiveView✓ | n/a (chat POST-stream) | OK |
| revision.requested | all | Dashboard blanket refresh✓ | no string handler; assignee covered by `revision` notification.created (user:) | OK (P3-class) |
| meeting.ready / meeting.insight_confirmed | all | Dashboard blanket refresh✓ | no handler | OK (P3-class) |
| drive.changed / drive.comment | all | Dashboard blanket refresh (incidental) | no handler | F4 (accepted P3) |
| job.updated | job:{id} + user:{id} | — | user: copy → push-event with no matching `if` → ignored; polled via GET | F5 (accepted P3) |

**Round-11 5-gap closure re-confirmed on final tree:**
- F1 (Tauri DeliveryWizard hang): `delivery.doc_ready` dual-published to `all`
  with `requirement_id` → scoped listener (DeliveryWizard.tsx:46) matches. ✓
- F1b (workspace.updated Tauri): still `req:`-scoped by design; TaskDetail status
  updates ride the dual-published `requirement.updated`. ✓ (intended trade)
- F2 (Tauri Hub stale): Hub.tsx:63 refreshes on requirement.ready/.updated. ✓
- F3 (web no live notifications): useNotificationToasts on `/stream/me`. ✓
- **N1 (R7.12, the F1 side effect — global delivery-doc OS popup)**: the
  unconditional App.tsx `delivery.doc_ready` branch is REMOVED, replaced by an
  explanatory comment (App.tsx:202–207). The submitter is covered by the
  user-scoped `delivered` notification.created; the worker by the wizard toast.
  No org-wide OS popup, no double-toast. **Fixed.** ✓

**Emitted-but-unconsumed audit (final):** only the accepted P3 set — `drive.*`
(Tauri), `job:{id}` copy, `meeting.*`/`revision.requested` on Tauri (covered by
notification.created where it matters). **Consumed-but-never-emitted: none** —
every Tauri `push-event` `if`-branch (App.tsx requirement.ready /
notification.created, Hub requirement.ready/.updated, Inbox notification.created,
DeliveryWizard delivery.doc_ready, TaskDetail requirement.updated) maps to a real
emit on a topic that surface subscribes to. (TaskDetail's `workspace.updated`
branch is the one harmless dead branch — emit exists but on `req:`, which Tauri
doesn't open; P3 carryover.) **No accidental org-wide PII noise** —
notification.created is user-scoped only; the `all` payloads (requirement.*,
delivery.doc_ready, drive.*) are ids/code/title only, no actor PII.

---

## Workflow chain + parity + contract drift

**Lifecycle chain (create→clarify→summary_ready→submit→ready→claim→doing→
delivery_doc_pending→delivered→accept):** intact end-to-end. All transition
endpoints present and unchanged: submit (sync.py:39), claim (sync.py:111),
auto-process (auto.py:54), PATCH status (requirements.py:249), delivery
init/chunk/finalize (delivery_upload.py:96/128/171), accept (deliveries.py:158),
revisions (deliveries.py:199), finalize-summary (requirements.py:561). No UI
button calls a removed endpoint. Worker-only transitions still 403 the browser
and are still hidden in web UI (no dead button); submitter actions still work
cookie-only. No impossible UI state — every rendered status badge is produced by
a real backend path. The R7.10 finalize zombie-window guard and R7.12+ orphan
guards (`_recover_stranded_delivery`, threadsafe-publish loop fallback) sit on
the lifecycle without changing its transition graph.

**Web/client parity:** notifications now live on BOTH (web useNotificationToasts
`/stream/me`; Tauri App.tsx + Inbox on the same topic). Hub refreshes live on
both. DeliveryWizard completes on both (web via requirement.updated, Tauri via
the scoped delivery.doc_ready). The NEW R7.12 path — direct-assign requirement
creation pushes the "你被指派到 …" notification live via
`publish_notification_threadsafe` (requirements.py:184, AFTER commit, payload
captured before the thread boundary so no off-thread Session access) — reaches
the assignee's `/stream/me` on both surfaces. Verified correct.

**Contract drift (TS ↔ Pydantic):** none.
- `NotificationOut` (schemas.py:482, 12 fields) ↔ TS `Notification`
  (types.ts:436) — exact 1:1, datetime↔string, Optional↔`| null`. The
  notification.created payload is `notification_out(row).model_dump(mode="json")`,
  so it carries `requirement_id` → App.tsx `nav(/r/{requirement_id})` action
  works; severity `normal`/`high` maps correctly on both (web `high|urgent`→warn,
  Tauri `high`→accent).
- `delivery.doc_ready` payload `{delivery_id, round, requirement_id}` (additive
  `requirement_id`, untyped on the consumer side as `p.data?.requirement_id` /
  `data?.requirement_id` off `any`) — no shared type change needed, none drifted.
- web `lib/types.ts` is still a pure re-export of `@yqgl/shared` — one type
  source for web + client, no second copy to drift.

**Single-worker assumption — documented in BOTH places (R7.11 P2-doc closed):**
- systemd `yqgl-web.service:9-15`: `--workers 1` with a 5-line comment ("MANDATORY,
  not a capacity choice … SSE push bus, presence map, in-flight-chat slot guard,
  background-task dedup are in-process singletons … scale with Redis pub/sub
  BEFORE raising this").
- DEPLOY.md:89: the same warning in Chinese, naming the split-brain failure mode
  (worker A's SSE events never reach a client on worker B, silently).

---

## P3 notes (non-blocking)

- **F4 (carryover)** `drive.changed` / `drive.comment` published to `all`,
  consumed by no dedicated handler on either surface (web Dashboard incidentally
  re-fetches via its blanket `all` refresh; Tauri ProjectDrive ignores them).
  Drive isn't realtime-critical; pure latent overhead.
- **F5 (carryover)** dead `job:{id}` publish (jobs.py:79 — no `/stream/job`
  endpoint; the `user:` copy + `GET /jobs/{id}` poll cover the need); and
  `DriveManifestOut.cursor` still shipped but unread by Tauri `sync.rs` (full
  manifest re-pull each sync).
- **workspace.updated Tauri (carryover, intended)** TaskDetail.tsx:72 has a
  `workspace.updated` branch, but the event is `req:`-only and Tauri never opens
  `/stream/req/{id}` → branch is dead-on-Tauri. Status still live-updates via the
  dual-published `requirement.updated`; collaborator checklist edits don't
  live-refresh the desktop TaskDetail (re-open to see them). R7.11 deliberately
  chose not to dual-publish workspace.updated to `all` to avoid over-refreshing
  the web Dashboard on every checklist edit. Accepted trade, not a regression.
- **Web Dashboard blanket `all` refresh** (Dashboard.tsx:123) re-fetches on every
  non-heartbeat `all` event — slightly coarse (one extra idempotent fetch on the
  `all` `delivery.doc_ready` just before the `requirement.updated` it'd refresh on
  anyway), but the dashboard is 6s-polled regardless. Negligible, as the R7.11
  commit note states. Not worth changing.
