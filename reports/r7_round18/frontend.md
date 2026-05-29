# R7 Round 18 — Frontend frozen confirmation

## Verdict: CLEAN (no P1/P2)

HEAD `3dcf440` (R7.17). Working tree confirmed clean — no edits made during this review.
R7.17 verified correct. Full frontend sweep (web + client-tauri + shared) found NO P1/P2.
The frozen tree is confirmed; nothing changes it.

## R7.17 SpeakButton aliveRef verification

File: `web/src/components/SpeakButton.tsx`. R7.17 diff is a single added line inside the
existing R7.16 unmount cleanup:

```js
useEffect(() => () => {
  aliveRef.current = false;                                              // R7.17 added
  if (myAudioRef.current && currentAudio === myAudioRef.current) stopCurrent();  // pre-existing
}, []);
```

Every correctness property holds:

- **aliveRef starts true** (line 46 `useRef(true)`). The `speak()` bail at line 66
  `if (myGen !== playGeneration || !aliveRef.current) return;` is therefore false during
  normal life — normal play path and autoplay path are unaffected. No regression.
- **Bail is now functional.** Before R7.17 `aliveRef` was never flipped, so the bail was a
  dead no-op (R7.17's stated motivation). Now an in-flight `speak()` whose `fetch`/`blob()`
  resolves after unmount hits line 66 (`!aliveRef.current` → true) and returns before
  creating the Audio element — no orphaned clip on a dead component. Intended R7.16 fix
  completed.
- **No stale closure.** `aliveRef`/`myAudioRef` are stable `useRef` objects; the cleanup
  reads `.current` at unmount time. `currentAudio` is a module-level `let` read live. Correct.
- **No regression to supersede.** The unmount stop is identity-guarded
  (`currentAudio === myAudioRef.current`): a component only stops the clip if it *owns* the
  currently-playing audio. Component A unmounting after B superseded it will NOT stop B
  (A's `myAudioRef` ≠ `currentAudio` which now points at B). Verified across the supersede
  path (lines 52/53/68 claim+stop+reassign) and the `onended` identity-guarded resets
  (lines 76-78).
- **Clarify hidden-autoplay edge confirmed benign.** The hidden autoplay `SpeakButton`
  (Clarify.tsx:322-329) unmounts when `stream.running` flips; its cleanup stops only its own
  autoplayed clip (identity guard), never a manually-played visible button's audio. New
  parsed while `!stream.running` re-renders the same instance (no `key`, same position) →
  no spurious unmount-stop; `lastTriggerRef` dedupes. Correct.
- The `finally { setBusy(false) }` running on an unmounted component is a harmless React-18
  no-op and is not introduced by R7.17 (setErr/setBusy in catch/finally always ran).

R7.17 is a minimal, surgical, regression-free completion of the R7.16 intent.

## tsc + full sweep

tsc — **0 errors on all 3 packages**:
- `shared`  — `tsc -p tsconfig.json --noEmit` → exit 0
- `web`     — `tsc -b` → exit 0
- `client-tauri` — `tsc -p web-src/tsconfig.json --noEmit` → exit 0

Race / async / SSE guards — all intact:
- **useChatStream** (`shared/src/hooks/useChatStream.ts`): AbortController per run, aborts
  prior run + on unmount, `resp.ok` checked, `reader.cancel()` in `finally`, `\r` strip,
  SSE single-leading-space data strip, aborted-error swallowed. Clean.
- **useReqStream** (`shared`): `alive` setState guard, reader.cancel + ctrl.abort cleanup,
  `.ok` check, `\r` strip, events capped `slice(-200)`, re-keyed on `reqId`. Clean.
- **Dashboard SSE** (`web/src/pages/Dashboard.tsx`): reconnect loop w/ capped exponential
  backoff (≤30s), `.ok`/`.body` checks, abort + reader.cancel cleanup, heartbeat handling.
  URL is `/api/push/stream` (forward slashes — backslashes seen in grep output were a
  pipe-rendering artifact; confirmed via Read). Clean.
- **useNotificationToasts** (`web`): same robust SSE pattern, `.ok` check, capped backoff,
  abort+cancel, multi-line data join, malformed-JSON swallow. Clean.
- **VoiceButton** (`web`): R7.15 `wantRecordingRef` press-intent guard closes mic if
  released/unmounted mid-getUserMedia; unmount cleanup stops recorder + releases tracks.
  No hot-mic, no leak. Clean.
- **AdminPanel** (`client-tauri`): R7.15 monotonic `reqTokenRef`; both `.then`/`.catch`
  gated on `token === reqTokenRef.current`. Stale type-ahead discarded. Clean.
- **AssigneeSelector** (`web`): `alive` staleness guard on listUsers; `EMPTY_SELECTED_USERS`
  stable const avoids effect re-fire; keys use `u.id`. Clean.

Other classes:
- **Missing `.ok`**: none. All raw `fetch`/`clientFetch` sites check `.ok` inline; the rest
  funnel through `apiFetch`/`json()`/`withCommon` (central check at `client.ts:34`).
- **Timezone**: canonical `parseServerDate` (`shared/src/api/time.ts`) appends `Z` to naive
  UTC, idempotent on offset/Z values, NaN-guarded. All server-field `new Date(...)` reads
  use `parseServerDate` or an explicit `+ "Z"` guard; user `datetime-local` inputs round-trip
  via `.toISOString()`. `AILiveView` `new Date(ev.at)` uses a client epoch (`Date.now()`),
  not a server string. No timezone bug.
- **List keys**: no index-based keys in the SpeakButton render paths (Clarify); checked
  clean.
- **Leaks / stale closures**: none found beyond the (correctly guarded) cases above.

## P3 notes (non-blocking)

None new. The audio + SSE race-guard families are fully and consistently hardened across all
three packages; the R7.17 change closes the last loose end (the dead `aliveRef`). No P3 worth
the tree.

**CLEAN (no P1/P2).**
