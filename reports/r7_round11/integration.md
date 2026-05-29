# R7 Round 11 — Holistic integration

HEAD `6693426` (R7.10). Whole-system pass: traced the lifecycle across backend +
web + Tauri client, diffed Pydantic↔TS contracts, mapped every emitted SSE event
to its consumers, and checked the single-worker runtime assumptions against the
prod systemd unit.

## Verdict: ISSUES (5) — 0 P1, 4 P2, 1 P3

The state machine is internally coherent (no dead UI buttons, no impossible
states, no contract drift in the JSON bodies). All 5 findings are
**realtime/parity** gaps: the Tauri client subscribes to a strictly smaller set
of SSE topics than the web, and several listeners wait on events that
structurally cannot reach that surface. None corrupt data — they degrade to
"manual refresh / stuck spinner". Worth fixing because they make the desktop
client feel broken in exactly the moments it should feel live (delivery wrap-up,
new claimable work, collaborator progress).

---

## Workflow chain trace (UI states ↔ backend states)

Full chain, with the endpoint that owns each transition. CAS = atomic
compare-and-swap on `status` (all hot transitions have one — verified).

| from → to | endpoint | gate | notify |
|---|---|---|---|
| draft → clarifying | AI chat / PATCH | submitter | — |
| clarifying → summary_ready | AI chat auto / `finalize-summary`(admin) | submitter/admin | — |
| summary_ready → ready | `POST /submit` | submitter, needs summary+DDL | `requirement.ready` |
| summary_ready/ready → ai_processing | `POST /auto-process` | submitter | — |
| ready → claimed | `POST /claim` | assignee, **local client** | `claimed`→submitter |
| claimed → doing | `PATCH /status` | assignee, **local client** | — |
| doing → delivery_doc_pending | `delivery/finalize` | assignee | `delivery_doc_pending`→submitter |
| delivery_doc_pending → delivered | bg `_finalize_doc` | (system) | `delivered`→submitter |
| ai_processing → delivered\|ready | bg `_run_and_finalize` | (system) | `delivered`→submitter |
| delivered → accepted | `POST /accept` | submitter | `accepted`→assignees |
| delivered → revision_requested | `POST /revisions` | submitter | `revision`→assignees |
| revision_requested → doing | `PATCH /status` | assignee, **local client** | — |
| * → cancelled | `PATCH /status` | submitter or assignee | `cancelled`→other side |

Coherence checks — all PASS:
- Every status in the Pydantic `StatusUpdateIn` regex, the `STATUS_VOCAB`/
  `STATUS_PROGRESS` maps (shared), and the `Requirement.status` TS union is the
  exact same 12-element set. No orphan status on either side.
- `ai_processing`, `delivered`, `accepted`, `revision_requested`,
  `delivery_doc_pending` are deliberately NOT destinations in PATCH `/status`'s
  `allowed` map — they're owned by dedicated endpoints with their own CAS. So
  PATCH can't be used to forge e.g. `doing → delivered`. Good separation; no
  double-owner races.
- No **dead button**: web hides worker actions (`claim`/`开始做`/deliver) unless
  `isDesktopRuntime()` (RequirementDetail.tsx:320, Hub gating), matching the
  backend's `worker_transition → local client required` 403 gate
  (requirements.py:285-291). Submitter-only actions (submit/accept/revision/
  cancel) use plain `current_user` (cookie OK), so they work from the browser.
- No **unreachable UI state**: every status the UI renders a badge for is
  produced by some backend path.

---

## Contract drift (TS types ↔ Pydantic)

Diffed `RequirementOut`, `NotificationOut`, `DeliveryOut`, `DriveItemOut`,
`DriveManifestOut`, `DriveCommentOut`, `RequirementWorkspaceOut`,
`ProgressUpdateOut`, `BackgroundJobOut`, `ProjectHealthOut`, `MeetingOut`,
`ReminderOut` against `shared/src/api/types.ts`. **No drift found.**

- `web/src/lib/types.ts` is a pure re-export of `@yqgl/shared` — web and client
  share one type source, so there's no second copy to drift.
- `DriveComment.status` TS enum `pending_llm|posted|draft_created|review_failed`
  exactly matches the four values project_drive.py assigns (1323/1344/1359/1394).
- `DriveManifestOut.cursor: datetime` → TS `cursor: string` is correct (datetime
  JSON-serializes to ISO string).
- Optional/nullable alignment is consistent (every `Optional[...]` has a `| null`
  or `?` partner).
- Field the frontend reads that the backend never sends: none observed.
- Field the backend sends that the frontend ignores: `DriveManifest.cursor` is
  sent on every manifest but the Tauri `sync.rs` has **zero** `cursor`
  references — see Finding 5 (known, P3).

---

## Web/client parity

The same React routes run in the browser (cookie) and the Tauri webview
(`clientFetch` + `X-YQGL-Client-Token`). Auth is unified: `current_user` accepts
EITHER cookie or worker-token (auth.py:104-125), and `require_stream_user` does
the same for SSE. So no endpoint 401s in one surface but not the other for the
same logical user. **The auth/CORS layer is coherent.** Parity breaks are purely
in *which SSE topics each surface listens to*:

| surface | subscribes to | gets per-req events? |
|---|---|---|
| web Dashboard | `/stream` (`all`) → refresh on ANY event | no (but RequirementDetail opens `/stream/req/{id}`) |
| web RequirementDetail | `/stream/req/{id}` via `useReqStream` | yes |
| web (notifications) | **nothing user-scoped** | no live `notification.created` |
| Tauri (Rust sse.rs) | `/stream` (`all`) + `/stream/me` (`user:`) | **no — never opens `/stream/req/{id}`** |

Consequences are Findings 1–4 below. The agent-native-parity question
("can everything a user does in the UI be driven by the documented API?"):
**yes** — every state transition is a plain REST endpoint (`/submit`, `/claim`,
`/accept`, `/revisions`, `/auto-process`, `PATCH /status`, `delivery/*`), no
action is hidden behind a Tauri-only IPC that lacks an HTTP equivalent (the
Tauri `invoke("claim")` etc. just call those same endpoints with the worker
token). An agent with a worker token can drive the full lifecycle.

---

## SSE event contract (emitted ↔ consumed)

Topics the backend publishes to: `all`, `req:{id}`, `user:{id}`, **`job:{id}`**.
push.py exposes stream endpoints for only the first three.

Emitted events and their topic (from grep of all `bus.publish`):

| event | topic(s) | consumed by |
|---|---|---|
| requirement.updated | `all` + `req:{id}` | web (both), Tauri (`all`) ✓ |
| requirement.ready | `all` | web Dashboard refresh ✓, Tauri toast (no list refresh — F2) |
| notification.created | `user:{id}` | Tauri ✓ ; **web: never (F3)** |
| delivery.doc_ready | `req:{id}` only | web RequirementDetail ✓ ; **Tauri waits but never receives (F1)** |
| workspace.updated | `req:{id}` only | web (no refresh trigger) ; **Tauri waits but never receives (F1)** |
| comment.added | `req:{id}` only | web RequirementDetail ✓ ; Tauri n/a |
| ai.started/thinking/text/tool_call/done | `req:{id}` only | web AILiveView ✓ ; Tauri n/a (uses chat POST-stream) |
| ai.failed | `req:{id}` only | web ✓ ; Tauri n/a |
| revision.requested | `all` | web Dashboard refresh ✓ ; **Tauri: no handler (F4)** |
| drive.changed | `all` | **no consumer on either surface (F4)** |
| drive.comment | `all` | no string-handler either surface (F4) |
| meeting.ready | `all` | web Dashboard refresh ✓ ; Tauri: no handler |
| meeting.insight_confirmed | `all` | web refresh ✓ ; Tauri: no handler |
| **job.updated** | `job:{id}` + `user:{id}` | **`job:{id}` copy has NO stream endpoint** (F5 note) |

The `job:{job.id}` publish (jobs.py:79) is dead — there is no
`/api/push/stream/job/{id}` route (push.py only has `stream`, `stream/req`,
`stream/me`). The `user:{...}` copy (jobs.py:81) IS reachable, and jobs are
otherwise polled via `GET /jobs/{id}`, so this is harmless waste, not a bug.

No event is *consumed-but-never-emitted* in a way that would crash; the gaps are
all *emitted-but-not-received-on-this-surface*.

---

## Single-worker concurrency assumptions

systemd `yqgl-web.service` runs `uvicorn main:app --workers 1`. This is
**load-bearing** — the code has three in-process singletons that a 2nd worker
would silently fork:

1. **SSE bus** (`push_bus.py`): `PushBus._subs` is an in-memory dict of asyncio
   queues. An event published on worker A reaches only subscribers connected to
   worker A. With 2 workers, ~half of all SSE clients miss ~half of all events,
   nondeterministically. This is the single biggest reason workers must stay 1.
2. **Presence** (`presence.py`): module-level `_last_seen` / `_open_streams`
   dicts. 2 workers → split-brain online/last-seen; a user streaming on worker B
   shows offline to a presence query served by worker A.
3. **Background tasks**: `auto-process` and `_finalize_doc` run via
   `asyncio.create_task` in-process. The CAS on `status` prevents *duplicate*
   work (2nd worker's CAS fails), so this is safe — but the startup sweep
   `main._resume_stuck_jobs()` runs unconditionally on every worker boot; with 2
   workers both sweep simultaneously (idempotent flips, so benign, but racy).

As deployed (1 worker) everything is consistent. **Gap: DEPLOY.md does not
document the `--workers 1` requirement** (grep for "worker"/"concurren" → no
hits). An operator scaling to `--workers 2` for throughput would break SSE +
presence with no error message — silent realtime degradation. Recommend a one-
line note in DEPLOY.md (and/or a startup `WARNING` log if `WEB_CONCURRENCY>1` or
`--workers>1` is detected). P2-doc.

---

## Findings

### F1 (P2) — Tauri DeliveryWizard hangs on `delivery.doc_ready` it can't receive
`client-tauri/web-src/src/components/DeliveryWizard.tsx:45-50` (and App.tsx:199)
listen for `delivery.doc_ready`, but that event is published **only** to
`req:{id}` (delivery_upload.py:379) and the Tauri client subscribes to only
`all` + `me` (sse.rs:38/43, never `/stream/req/{id}`). After upload the wizard
advances to step 2 ("等 AI 写交付文档") via the local `delivery-progress` event,
then waits forever for `delivery.doc_ready` — it never arrives, so the success
toast + auto-close never fire. The worker must close the modal manually.
- The *submitter* is unaffected (they get the `delivered` `notification.created`
  on `user:`, which the Tauri client does receive).
- The web is fine — RequirementDetail's `useReqStream` opens `/stream/req/{id}`.
- Fix options: (a) close the wizard on `requirement.updated`+status=`delivered`
  (already on `all`, already filters by `requirement_id`), or (b) have sse.rs /
  the webview also subscribe to the active requirement's `req:` topic, or
  (c) emit `delivery.doc_ready` to `all` too. (a) is smallest.

### F1b (P2, same root) — `workspace.updated` never reaches the Tauri client
TaskDetail.tsx:65 refreshes on `workspace.updated`, but that event is published
only to `req:{id}` (workspaces router, 5 sites). Same missing-subscription root
as F1. Effect: when a collaborator updates progress/phase, the desktop
TaskDetail does not live-refresh — the lead sees stale progress until they
re-open the task. (Web has the inverse minor gap: RequirementDetail only
refreshes on status change, line 133, so it ignores `workspace.updated` too —
but at least receives it.) Folding into F1 since the fix is the same
subscription change.

### F2 (P2) — Tauri Hub lists don't refresh on `requirement.ready`/`.updated`
`routes/Hub.tsx` refreshes only on tab change and local claim/start actions
(lines 56/70/80); it has no `push-event` listener. App.tsx shows a toast on
`requirement.ready` but doesn't refresh any list. So a worker sitting on the
"在抓/public" tab does NOT see newly-dispatched claimable work appear until they
hit 刷新 or change tabs. The web Dashboard refreshes on every `all` event
(Dashboard.tsx:115), so this is a desktop-only staleness. Fix: add a
`useEvent("push-event", …)` in Hub that calls `refresh()` on
`requirement.ready`/`requirement.updated`.

### F3 (P2) — Web never receives live notifications (no `/stream/me` subscriber)
The web subscribes only to `/api/push/stream` (the non-PII `all` topic,
Dashboard.tsx:97). It never opens `/api/push/stream/me`, so `notification.created`
(published to `user:{id}`) is never delivered live in the browser.
NotificationsPage.tsx loads only on mount/tab-change (no interval), so a web user
viewing the inbox sees new notifications only after manual reload, and gets no
toast/badge bump anywhere. The Tauri client does both (App.tsx:207 toast + OS
notify + badge). This is a genuine web/client parity gap, not a security issue
(the endpoint exists and is cookie-scoped — the web simply doesn't use it). Fix:
add a `/stream/me` reader in the web App shell mirroring sse.rs's intent.

### F4 (P3) — `drive.changed` / `drive.comment` consumed by no one
`drive.changed` (project_drive.py `_publish_drive_changed`, ~12 sites) and
`drive.comment` are published to `all` but neither web ProjectDrive/DriveHome nor
the Tauri ProjectDrive route has a handler — the Tauri drive page listens only to
the local `drive-upload-progress` Tauri event. Effect: a second user's drive
edits don't live-refresh anyone's open drive view (re-navigate to see them). The
web Dashboard's blanket "refresh on any `all` event" incidentally re-fetches
dashboard data but not the drive listing. Low severity (drive is not a realtime-
critical surface), hence P3 — but the events are pure overhead today.

### F5 (P3) — dead `job:{id}` publish + unused drive sync `cursor`
- jobs.py:79 publishes `job.updated` to `job:{job.id}`, but push.py has no
  `/stream/job/{id}` endpoint. The `user:{...}` copy (line 81) and the
  `GET /jobs/{id}` poll cover the need, so this publish is wasted, not broken.
- `DriveManifestOut.cursor` is set to `utcnow()` and shipped on every manifest,
  but the Tauri `sync.rs` never reads it — drive sync re-pulls the full manifest
  each time (confirmed: zero `cursor` refs client-side). Known limitation from a
  prior round; restated here for the integration ledger. Either wire incremental
  sync or drop the field to stop implying a capability that doesn't exist.

---

### What is solid (so per-round reviewers can stop re-checking)
- Lifecycle CAS coverage: submit/claim/auto-process/finalize/accept/revision/
  PATCH-status all guard with `WHERE status = <old>` and 409 on rowcount 0.
- Notification dedup is DB-side (`user_id`+`dedupe_key`) with a content-change
  guard (notifications.py:42-76) — no double-toast, no stuck-unread.
- `notification.created` is per-user only (no cross-user PII leak over `all`).
- Type contracts: web/client share one source; no Pydantic↔TS field drift.
- Auth: cookie OR worker-token everywhere a surface needs it; worker-only
  transitions correctly 403 the browser AND are correctly hidden in web UI.
