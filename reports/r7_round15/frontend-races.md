# R7 Round 15 — Frontend races (adversarial)

HEAD `580754c`. Hunted both React surfaces (`web/src`, `client-tauri/web-src/src`) plus
`shared/src` hooks, with malice. The streak is real but it has been earned on the
*data-fetch* paths; the cracks left are in the two **audio** components, where nobody seems
to have pointed the same paranoia at `MediaRecorder` / `<audio>` that was lavished on the
SSE readers.

## Verdict: NEEDS FIXES (2× P2, 4× P3)

The SSE/fetch story is genuinely tight (token guards, `alive` flags, reader-cancel,
unmount-before-`listen()` guard all present where they matter). The new bugs are in
`VoiceButton` and `SpeakButton` — press-and-hold timing and a module-singleton that
guards sequential plays but not two in-flight fetches.

---

## Unguarded async-race scan (every fetch-on-mount + event + action component)

| Component | Triggers | Guard | Verdict |
|---|---|---|---|
| `web/Dashboard` | mount + 6s interval + SSE event + tab-return | SSE loop: abort+backoff ✅. **`refresh()` ordering: NO token guard** | P3 stale-overwrite |
| `web/RequirementDetail` | mount + `useReqStream` status + actions | `refreshTokenRef` ✅, `WorkspaceCard` dirty-flag ✅ | CLEAN (gold standard) |
| `tauri/TaskDetail` | mount + `push-event` + claim/start/wizard/`onChange` | **NO token guard** (web twin has one); `MyWorkspace` uses "never re-sync from props" | P3 stale-overwrite |
| `tauri/Hub` | mount + tab + `push-event` + claim | `reqTokenRef` ✅ | CLEAN |
| `tauri/HubDispatch` | mount + button only (tabs client-side) | none, but no concurrent trigger | CLEAN (no SSE refresh = UX gap, not a race) |
| `tauri/Inbox` | mount + view + `push-event` + markRead | `reqTokenRef` ✅ | CLEAN |
| `tauri/Knowledge` | search + ask(poll loop) | `searchTokenRef`+`askTokenRef`, unmount bumps token ✅ | CLEAN |
| `web/KnowledgePage` | search + ask(8× poll loop) | **NO token/unmount guard** (Tauri twin has one); `busy` blocks same-mount re-entry | P3 (post-unmount polling for ~7s) |
| `web/PlanningPage` | mount + project-filter re-fetch | **NO token guard** | P3 stale-overwrite on fast filter switch |
| `web/HealthPage` | mount only (filter client-side) | n/a | CLEAN |
| `web/ProjectView` | mount/id-change + actions | **NO token guard** | P3 (fast `/p/A→/p/B`; low reachability) |
| `web/ProjectMeetings` | mount + 1.5s job poll + actions | poll `alive`+clearInterval ✅; **`load()` no token guard** | P3 stale-overwrite |
| `web/CalendarPage` | mount + actions (view client-side) | `busy`-gated | CLEAN |
| `web/Clarify` | mount/id + autostart + done | `autoStartedRef`+`loadedReqId` ✅; **`refresh()` no token guard** | P3 (fast req-nav) |
| `tauri/Calendar` | mount + week-nav | effect `alive` flag ✅ | CLEAN |
| `tauri/ProjectDrive` | mount + projectId + upload + drive-progress | `[projectId]` `alive` ✅, listener guard ✅; **`pickAndUpload`/refresh-button `setItems` unguarded** | P3 (navigate-away-mid-upload) |
| `tauri/MyWorkload` / `ProjectPulse` | mount only | n/a | CLEAN |
| `web/AssigneeSelector` | type-ahead | effect `alive` flag ✅ | CLEAN |
| `tauri/AssigneeSelector` | debounced type-ahead | debounce + `alive` ✅ | CLEAN |
| `tauri/AdminPanel UsersSection` | debounced type-ahead | debounce only, **NO `alive` guard** | **P2** type-ahead stale-overwrite |
| `tauri/Settings` / `Onboarding` | actions, `busy`-gated | sequential | CLEAN |
| `web/VoiceButton` | press-and-hold record | **none** | **P2** orphaned recording + mic leak |
| `web/SpeakButton` | click / autoplay | module singleton (sequential only) | **P2** dual-fetch overlap, no unmount stop |

## Effect-cleanup / SSE-reconnect / rapid-interaction / Tauri-event findings

- **SSE reconnect storms** — `useNotificationToasts`, `Dashboard` stream, `useReqStream`,
  `useChatStream` all use a single `AbortController`, check `ctrl.signal.aborted` at every
  loop boundary, `reader.cancel()` + `abort()` on cleanup, and re-check after the backoff
  sleep. Fast mount/unmount/remount cannot spawn overlapping readers — the abort wins
  before the loop reopens. **Solid.**
- **`useEvent` (tauri.ts)** — latest-handler `handlerRef` (no stale `id`/`refresh`
  closures) + the unmount-before-`listen()`-resolves guard (`if (!alive) d()`). Used
  correctly everywhere (TaskDetail, Inbox, Hub, DeliveryWizard, App). **Solid.**
- **`useChatStream`** — overlapping `run()` is gated by `running`/disabled-button in both
  Clarify surfaces, so the `finally`-flips-`running:false` would only misfire if two runs
  genuinely overlapped (they can't). setState-in-`finally` after unmount is benign (R18).
- **Tauri App.tsx events** — `navigate`/`tray-action` call `nav()` (stable, idempotent)
  even mid-transition; three `push-event` listeners are independent/idempotent; the root
  effect's identify→register→`resetClientTokenCache`→get_config chain is sequential and the
  cache reset is correctly placed. `_badgeTimer` debounce is module-global at the root. **Fine.**
- **SpaceSwitcher / Ctrl+1·2** — pure store dispatch, doc-listeners keyed on `open`, no async.

---

## Findings

### P2 — `VoiceButton`: fast tap orphans an unstoppable recording + leaks the mic
`web/src/components/VoiceButton.tsx:19-62`

`start()` is async (`getUserMedia` awaits a **permission prompt** on first use — can be
several seconds). `onPointerUp → stop()` does `mediaRef.current?.stop()`, but
`mediaRef.current` is only assigned **after** the await (line 51). Sequence under a quick
tap (or first-use permission dialog):

1. `onPointerDown` → `start()` begins awaiting `getUserMedia`.
2. User releases / the permission dialog steals focus → `onPointerUp` → `stop()` →
   `mediaRef.current` is still `null` → **no-op**. `recording` is still `false`.
3. `getUserMedia` resolves → `mr.start()`, `mediaRef.current = mr`, `setRecording(true)`.

Now a `MediaRecorder` is running with the pointer already up and nobody holding the button.
The browser's recording indicator stays lit; the mic records until the next full
down/up cycle. On a touchpad with a permission prompt this is the *common* first-run path,
not a corner case. The microphone staying hot after the user thinks they let go is exactly
the kind of "cheap-feeling, slightly creepy" behaviour that erodes trust.

Compounding it: there is **no unmount cleanup**. `useEffect(() => () => stop tracks, [])`
is absent, so if the host card unmounts mid-hold (Clarify swaps the `QuestionCard` after an
answer lands), the `getUserMedia` stream tracks are never `.stop()`-ed and `onstop` later
`setBusy`/`setErr` on a dead component.

Fix shape: capture the stream/recorder in refs, add a cancellation token checked after the
`getUserMedia` await (if released-before-resolve, immediately stop tracks and bail), and an
unmount cleanup that stops tracks + recorder.

### P2 — `SpeakButton`: two concurrent `speak()` calls play two voices, one unstoppable
`web/src/components/SpeakButton.tsx:5-71`

The module-level `currentAudio` singleton + `stopCurrent()` enforces "one at a time" only
for **sequential** plays. Two SpeakButtons whose TTS `fetch`es are in flight at once race
on the `currentAudio = a` assignment (lines 55-56), which happens *after* each fetch
resolves:

1. Click A → `stopCurrent()` (nothing playing) → fetch A in flight.
2. Click B (B not `busy`, only A is) → `stopCurrent()` (A's audio not created yet) →
   fetch B in flight.
3. B resolves first: `currentAudio = aB; aB.play()` — B audible.
4. A resolves: `currentAudio = aA; aA.play()` — **A also audible**, and `currentAudio` now
   points only to A. B's reference is lost → `stopCurrent()` can never pause B.

Result: two overlapping TTS voices, one of which no button can stop until the page
reloads. Reachable in Clarify, which renders multiple `SpeakButton`s (the question card's,
each history bubble's, and the hidden autoplay driver) on one screen.

Also: **no unmount cleanup of in-flight/playing audio** — a SpeakButton that unmounts while
playing (the autoplay driver remounts/keys per `stream.parsed`) keeps the `<audio>` playing
and the blob URL un-revoked until `onended`; `setBusy`/`setPlaying`/`setErr` fire after
unmount.

Fix shape: assign `currentAudio` synchronously to a per-call token *before* the fetch (or
abort the prior fetch), and on resolve only `play()` if this call still owns the singleton;
add unmount cleanup that calls `stopCurrent()` when this instance owns the current audio.

### P2 — `AdminPanel` UsersSection: type-ahead stale-overwrite (the only unguarded search)
`client-tauri/web-src/src/components/AdminPanel.tsx:178-187`

Debounced 200ms `list_users(search)`, but unlike **both** AssigneeSelectors (which add an
`alive` flag in the same effect), the cleanup here only `clearTimeout`s the pending debounce
— it does **not** guard the in-flight `invoke` once the timer has fired. Type `"ab"` →
timer fires → `list_users("ab")` in flight → type `"abc"` → `list_users("abc")` fires; if
the `"ab"` query resolves last, `setUsers(ab-results)` lands under the `"abc"` box. Classic
autocomplete inversion. Admin-only + fast local IPC keeps the window small and self-healing,
but it's the textbook race and the fix is one `let alive = true; … if (alive)` — the exact
pattern its two sibling components already use.

### P3 — Missing-token-guard `refresh()` cluster (stale-overwrite, self-correcting)
`tauri/TaskDetail.tsx:45-68`, `web/Dashboard.tsx:47-58`, `web/PlanningPage.tsx:24-40`,
`web/ProjectMeetings.tsx:32-41`, `web/ProjectView.tsx:21-38`, `web/Clarify.tsx:70-89`,
`tauri/ProjectDrive.tsx:108-109,189-191`

Same shape in all: `refresh()`/`load()` is invoked from several sources (mount, SSE/event,
interval, user action) with no monotonic token, so an *older* invocation can resolve after a
newer one and `setX(stale)`. **TaskDetail is the notable one** — its web twin
(`RequirementDetail`) was explicitly given `refreshTokenRef` in an earlier round; the Tauri
twin was not, despite the heavier action surface (claim/start/deliver/workspace-edit all
fan into one unguarded `refresh()`). Worst observed effect: brief wrong status / a re-shown
"接这单" button until the next SSE event corrects it (sub-second on LAN). All are bounded and
self-healing — hence P3 — but TaskDetail deserves the same `refreshTokenRef` treatment for
parity, and Dashboard's 3-way concurrent `refresh()` (interval + SSE + tab-return) is the
most likely to actually invert in the wild.

### P3 — `web/KnowledgePage` ask-poll: no unmount cancellation
`web/src/pages/KnowledgePage.tsx:48-65`

The 8×900ms poll loop has no `alive`/token guard (its Tauri twin `Knowledge.tsx` does). The
`busy` gate prevents an overlapping second loop within a mount (so no answer-flicker race),
but navigating away mid-ask keeps firing `getKnowledgeRun` for up to ~7s and `setRun`s on a
dead component. Wasteful, not corrupting.

---

## Net
The data layer holds. The unguarded edges are the audio peripherals (`VoiceButton`,
`SpeakButton`) — where the press-and-hold/await-permission timing and a fetch-racing
singleton produce a hot mic and double-voiced TTS — plus the one search box
(`AdminPanel`) that skipped the `alive` flag its siblings all have, and a cluster of
self-healing `refresh()` stale-overwrites (TaskDetail being the parity gap worth closing).
No P1: nothing here tears the React tree, leaks a stream reader, or corrupts persisted state.
