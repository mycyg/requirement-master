# R7 Round 13 — Backend (verify R7.12 anyio bridge + sweep)

HEAD `44e1f9a` (R7.12). Backend surface in this commit: `app/services/notifications.py`
(+ `publish_notification_threadsafe`) and `app/routers/requirements.py` (3 publish sites).
`client-tauri/.../App.tsx` is frontend (out of scope). Verified against installed
anyio 4.10.0 / starlette 1.0.0 / fastapi 0.135.2 / uvicorn 0.30.6.

## Verdict: CLEAN

R7.12's anyio threading bridge is **correct**. Every claim in the prompt's verification
checklist holds up under source-level inspection of the actual installed anyio/starlette/
fastapi. No P0/P1/P2 found. One P3-observability nit and one informational note below — neither
is a defect in the shipped behaviour, and I am not asking for a fix to ship R7.

## publish_notification_threadsafe correctness (the anyio question, rigorous)

`notifications.py:107-135`. Each sub-claim verified against installed source, not memory:

**1. Is `anyio.from_thread.run` valid from a Starlette sync-endpoint threadpool worker? — YES, confirmed.**
Traced the full call chain in the installed packages:
- `fastapi.routing.run_endpoint_function` → for a non-coroutine endpoint calls
  `await run_in_threadpool(dependant.call, **values)`.
- `starlette.concurrency.run_in_threadpool` → `await anyio.to_thread.run_sync(func)`.
- `anyio.to_thread.run_sync` dispatches onto an anyio `WorkerThread`. Inspected
  `anyio._backends._asyncio.WorkerThread.run`: its entire loop body executes inside
  `with claim_worker_thread(AsyncIOBackend, self.loop):`.
- Inspected `anyio._core._eventloop.claim_worker_thread`: it sets
  `threadlocals.current_async_backend = backend_class` and
  `threadlocals.current_token = token` (the loop) for the worker's lifetime.
- Inspected `anyio.from_thread.run`: it reads exactly those two threadlocals
  (`current_async_backend`, `current_token`), raising `RuntimeError("This function can
  only be run from an AnyIO worker thread")` if absent.
Because `create_requirement` runs *inside* that `WorkerThread`, both threadlocals are
present, so `from_thread.run` resolves the backend + loop token and succeeds. The
reasoning in the prompt is correct. There is also an in-repo precedent for this exact
pattern: `project_drive.py:269-279 _publish_drive_changed` already ships
`from_thread.run(bus.publish, ...)` with the same `get_running_loop` fallback — R7.12 is
consistent with an already-deployed idiom, not a novel risk.

**2. Is the payload captured BEFORE crossing the thread boundary? — YES, confirmed.**
`notifications.py:119-123`: `payload = notification_out(row).model_dump(mode="json")` and
`topic = f"user:{row.user_id}"` run synchronously on the worker thread. The `_go()` closure
closes over `payload` (a plain dict) and `topic` (a str) only — it never references `row`.
So no Session-bound ORM object is touched on the event loop.
- `NotificationOut` (verified in `notification_out`, lines 12-26) reads only scalar columns
  (id/type/severity/title/body/target_url/project_id/requirement_id/read_at/archived_at/
  created_at/updated_at) — NO relationship attributes. No lazy-load is possible even
  on-thread.
- Session is `expire_on_commit=False` (`db.py:42`), and SQLAlchemy 2.0 (`future=True`)
  eagerly post-fetches `server_default` columns after INSERT. I verified empirically:
  after `flush()` + `commit()`, `created_at`/`updated_at`/`id` are all present in the
  instance `__dict__` with real values. So `model_dump` reads cached in-memory scalars —
  zero DB I/O, definitely nothing off-thread. The payload snapshot is fully detached.

**3. The `loop.create_task` fallback — when would it fire, and is it a no-op in a worker thread? — confirmed no-op there, and that's fine.**
`notifications.py:131-135`. In the threadpool worker, `from_thread.run` is the primary path
and succeeds (returns at line 128), so the fallback is never reached. *If* the primary
raised, the fallback does `asyncio.get_running_loop()` — which I verified empirically raises
`RuntimeError("no running event loop")` in any thread not running a loop (a WorkerThread
qualifies). The `except RuntimeError: pass` swallows it. So in the threadpool context the
fallback is effectively dead. That is acceptable and intentional: it exists only as defence
for the theoretical case where this helper is ever called from a thread that *is* running a
loop (it currently never is — sole caller is `create_requirement`, sync). The primary
`from_thread.run` is the real delivery path.

**4. Does `from_thread.run` BLOCK the worker thread? Any deadlock risk? — blocks the WORKER (not the loop); no deadlock.**
Inspected `AsyncIOBackend.run_async_from_thread`: it does
`f = asyncio.run_coroutine_threadsafe(wrapper, loop)` then `return f.result()`. So it
schedules the coroutine on the main event loop and blocks the *worker thread* on
`f.result()` until completion. This is the correct thing to block — it is a threadpool
worker, not the loop. No deadlock: the loop is free (the sync endpoint yielded it the moment
it entered the threadpool), so it can run `_go()` → `bus.publish`. `bus.publish`
(`push_bus.py:37-44`) acquires `self._lock` (an `asyncio.Lock`) on the loop and `put_nowait`s
into subscriber queues, swallowing `QueueFull`; it touches no thread primitive that the
worker holds. The only coupling is worker→loop one-way, so the classic lock-ordering deadlock
cannot form. Cost is a brief worker-thread block per publish — bounded by the in-memory bus
fan-out (no network, no await on external I/O), so negligible.

**5. If publish fails, is the row already committed (no data loss)? — YES, confirmed.**
In `create_requirement`, `publish_notification_threadsafe` is invoked at line 183-184,
strictly AFTER `db.commit()` (176) and `db.refresh(r)` (177), and only on the success path
before `return` — it is never reached after `db.rollback()`. The rows are durably persisted
before any publish is attempted. A publish miss degrades to poll-delivery via
`GET /notifications` (which the recipient polls; rows are returned regardless of SSE). No data
loss. This matches the contract documented in the docstring and the established
`flush_status_notifications` poll-fallback philosophy (`lifecycle.py:164-173`).

## requirements.py 3-site verification

**Site A — `create_requirement` (SYNC, lines 111-189): correct.**
- `notes_to_publish: list = []` is initialised *inside* the `for _ in range(5)` retry loop
  (line 146), so it is reset per attempt. On `IntegrityError` → `db.rollback()` (187) → next
  iteration re-creates an empty list — no stale notification object from a discarded attempt
  is ever carried forward or published. Correct scoping.
- Notes appended only on the success path (160-172); published only after `db.commit()` +
  `db.refresh(r)` (183-184), then `return`. Publish never runs post-rollback.
- Uses `publish_notification_threadsafe` (not `await`) — correct, this is a sync endpoint.

**Site B — `update_assignees` (ASYNC, lines 432-494): correct.**
- `notes_to_publish` built from `assignments` (the return of `replace_assignments`), skipping
  rows with no `.user`. `await publish_notification(note)` after `db.commit()` (486-491).
  Correct for an async endpoint.
- Content-change guard interplay verified: `replace_assignments` deletes+recreates assignment
  rows, but the notification `dedupe_key` is `assigned:{r.id}:{user_id}` (stable per
  req+user). So a re-assign of the same user hits the existing notification row in
  `create_notification` (lines 42-76). The first re-assign after creation changes the body
  (creation body = raw_description; re-assign body = "{nick} 调整了接单人。"), so the row
  legitimately resurfaces (genuinely new event). A *second identical* re-assign produces no
  content change → guard returns the existing (possibly already-read) row unmodified →
  `publish_notification` pushes a harmless unchanged snapshot. No spurious unread-badge reset,
  no double-toast of new content. Matches the inline comment. Behaviour is benign.

**Site C — `update_requirement_schedule` (ASYNC, lines 497-548): correct.**
- Iterates `r.assignments`, builds `notes_to_publish`, `await publish_notification(note)`
  after `db.commit()` + `db.refresh(r)` (542-545). Correct for async.
- `dedupe_key` includes the new due date
  (`due_changed:{r.id}:{user_id}:{due_at-or-'none'}`), so each distinct DDL value is its own
  notification — a back-and-forth DDL edit doesn't silently overwrite. Sensible.

All three publish loops run AFTER commit, so the SSE event can never advertise a notification
that a subsequent rollback would erase. Consistent with `flush_status_notifications` ordering.

## Fresh-pass findings

- **No other sync endpoint creates-then-needs-to-publish notifications.** Swept all
  `create_notification` / `publish_notification` callers: `decompositions.py:300-314` and
  `knowledge.py:131-144` are `async` background workers on their own `SessionLocal` loop —
  `await publish_notification` is correct there, no bridge needed. `lifecycle.py` uses the
  queue+flush pattern from async `update_status`. `notifications.py:_ensure_due_notifications`
  deliberately does NOT publish (it runs inside the `GET /notifications` poll itself, so the
  rows are returned in the same response — live-push would be redundant). `create_requirement`
  was the sole sync gap, and it is now correctly bridged. Coverage is complete.

- **Topic naming matches end-to-end.** Publisher emits to `user:{row.user_id}`
  (`notifications.py:104,120`); subscriber `GET /api/push/stream/me` listens on
  `user:{user.id}` (`push.py:101`) where `user.id` is the cookie-resolved auth id (no path
  param, so no cross-user subscription). Event type `notification.created` matches what the
  web toast hook / Tauri client consume. Correct wiring.

- **[P3 / observability, not a defect] Silent publish failure in the threadsafe bridge.**
  `publish_notification_threadsafe` uses `except Exception: pass` on the primary path
  (`notifications.py:129-130`) and `except RuntimeError: pass` on the fallback. If `_go()` /
  `bus.publish` ever raised a real exception on the loop, it is swallowed with no log line —
  unlike the async sibling `flush_status_notifications` which does
  `logger.exception(... will be picked up via polling)`. Behaviour is still correct (row is
  committed, poll-delivery covers it — no data loss), but a persistent SSE regression here
  would be invisible in logs. In practice `bus.publish` cannot raise under normal operation
  (it internally swallows `QueueFull`), so the risk is minimal. Optional future polish: log
  the swallowed exception. NOT a ship blocker.

- **[Informational] Per-publish worker-thread block in `create_requirement`.** Each assigned
  user triggers one `from_thread.run` round-trip that blocks the threadpool worker until the
  loop drains the publish. For the realistic assignee count (1 lead + a few collaborators)
  this is microseconds of in-memory fan-out and irrelevant. Worth noting only so a future
  change that fans out to dozens of recipients in a sync endpoint reconsiders batching into a
  single `from_thread.run` call. No action for R7.

- **No regressions in the surrounding code.** `notes_to_publish` lists don't leak across the
  retry boundary; the CAS/transaction logic in `update_status`, the FK-null-out delete path,
  and `replace_assignments` are unchanged by R7.12 and remain consistent with prior rounds.
  `import asyncio as _asyncio` inside the function (notifications.py:118) is a harmless local
  import (lazy, avoids a module-level dep); not a concern.

**Bottom line: the R7.12 anyio bridge is correct on every point raised, follows an
already-shipped in-repo pattern, and the 3 publish sites are properly scoped and ordered
after commit. Backend is CLEAN for R7 ship.**
