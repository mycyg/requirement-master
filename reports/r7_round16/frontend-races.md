# R7 Round 16 — Frontend races verify + re-sweep

HEAD `edfb4fd` (R7.15). Verified the three P2 audio/search fixes line by line and
adversarially re-traced every guarded path, then re-swept both React surfaces for any
remaining mount+event+action component without a guard. The audio rewrites are genuinely
correct — the press-intent ref and the monotonic `playGeneration` both close the windows
the Round 15 pass described, and none of the seven token guards broke an existing effect.

## Verdict: CLEAN

No P1/P2. No regression in the R7.15 fixes. One pre-existing residual P3 narrowed (not a
new bug; documented below for honesty). tsc clean on all three packages. The streak holds.

---

## R7.15 audio-fix verification (VoiceButton, SpeakButton)

### VoiceButton (`web/src/components/VoiceButton.tsx`) — CORRECT
The `wantRecordingRef` press-intent flag closes the hot-mic window cleanly. Traced all paths:

- **Normal hold→release**: `start()` sets intent, getUserMedia resolves with intent still
  true → `streamRef`/`mr` assigned, `mr.start()`, `setRecording(true)`. `stop()` sets intent
  false, `mediaRef` exists → `mr.stop()` (its `onstop` stops the tracks + nulls `streamRef`),
  `mediaRef=null`. No leak. ✅
- **Release BEFORE getUserMedia resolves** (the bug): `stop()` runs while both refs are null
  → no-op on the stream (correct: it doesn't exist yet), `setRecording(false)`. getUserMedia
  then resolves, sees `!wantRecordingRef.current` → `stream.getTracks().forEach(t.stop())` +
  `return`. **Mic closed, no recorder ever started, nobody holding.** Fix works. ✅
- **The two `stop()` branches are exhaustive & correct**: recorder-exists branch defers track
  release to `onstop`; stream-only branch (released after stream assigned but before recorder
  — a narrow window between lines 38 and 65) stops tracks directly and nulls `streamRef`.
  There is no state where a track is opened with neither branch reachable. ✅
- **Unmount cleanup** (lines 89-94): sets intent false, `mediaRef?.stop()` (safe if null),
  `streamRef?.getTracks().forEach(stop)`, nulls `streamRef`. Combined with the post-await
  intent check, unmount-mid-prompt also stops the resolving stream. No track leak on any
  unmount timing. ✅
- **Double-stop**: `stop()` nulls `mediaRef` after stopping, so a second `stop()`
  (PointerUp + PointerCancel + PointerLeave can all fire) hits neither branch — idempotent.
  `MediaRecorder.stop()` is never called twice on the same recorder. ✅
- `disabled={busy}` only blocks pointer events during the post-record transcribe phase, when
  no recorder/stream is open — no interaction with the press window. ✅

### SpeakButton (`web/src/components/SpeakButton.tsx`) — CORRECT
The monotonic `playGeneration` (claimed synchronously at line 51, before any await) is the
right shape. Traced two concurrent `speak()` (the Clarify multi-button case, confirmed real:
5 SpeakButtons + the hidden autoplay driver render on one screen — lines 324/373/424/471/554):

- A claims gen 1, B claims gen 2 (both before their fetches). **Older A resolves first**:
  `myGen(1) !== playGeneration(2)` → `return` *before* `URL.createObjectURL` (line 63) →
  **no blob URL leaked**, A never plays. B resolves: gen matches → `stopCurrent()` →
  assign → play. **Exactly one voice.** ✅
- **Reverse (B resolves first)**: B plays; A then bails on the gen check, no url created. ✅
- **stop-before-assign** (line 64): `stopCurrent()` runs *after* the gen check and *before*
  `currentAudio = a`, so anything that started playing between this call's claim and its
  resolve is paused + its blob revoked. No orphaned `<audio>`. ✅
- **Unmount stop-if-mine** (lines 88-90): `currentAudio === myAudioRef.current` → `stopCurrent()`.
  Correct ownership check — only stops the singleton if *this* instance owns it; a SpeakButton
  that lost the singleton to a newer play unmounts without disturbing the winner. ✅
- **Autoplay useEffect** (lines 93-100): still works. `lastTriggerRef` dedups by key; calls
  `speak()` which now claims a generation. The Clarify autoplay-driver remount (new `parsed`
  → unmount old driver, mount new) is safe: the new driver's `speak()` bumps the generation
  and `stopCurrent()`s, superseding any in-flight old fetch. No double-play across remounts. ✅
- **onended handler** (lines 69-75) revokes the url and nulls all three module/instance refs
  only if they still point at this clip — no cross-clip clobber. ✅
- `onClick={playing ? stopCurrent : speak}` binding is fine — `stopCurrent` is a stable module
  fn, `speak` a fresh closure each render but only invoked on click. ✅

---

## R7.15 token-guard verification (AdminPanel + 7 components)

All eight use the identical, correct shape: `const token = ++ref.current` at the top of the
async fn, then `if (token !== ref.current) return;` guarding **every** setState in both the
success and the catch branches (and the `finally` setLoading/setBusy where present). No
off-by-one (pre-increment means the first call is token 1 vs ref 1 → passes), no setState
that escapes the guard.

| Component | Sources fanning into the guarded fn | Verdict |
|---|---|---|
| `tauri/AdminPanel` UsersSection | `reqTokenRef` covers **both** the 200ms-debounced effect search AND `toggle`/`removeUser`→`refresh()` — all three call the single `refresh` callback, and the toggle/delete paths call `refresh()` (no-arg → uses `search` from closure). Guard checked in `.then` and `.catch`. No stale write. ✅ |
| `tauri/TaskDetail` | mount `[id]` + `useEvent("push-event")` + claim/start/deliver/wizard. `refreshTokenRef` checked before `setReq/setWorkspaces/setMe` and in catch. The `useEvent` handler is `id`-scoped (ignores other reqs) and uses the latest-handler ref (R15-verified). Cross-id nav: old in-flight refresh sees token mismatch → bails. ✅ Parity with web twin achieved. |
| `web/Dashboard` | mount + 6s interval + SSE event (line 123) + tab-return (`onVis`). All four call the same `refresh`; `refreshTokenRef` dedups. Interval/visibility cleanup intact. The 7-status fan-out resolves atomically under one token. ✅ |
| `web/Clarify` | `[reqId]` effect + `stream.done` effect (line 106). `refreshTokenRef` checked before `setReq/setAttachments/setHistory/setLoadedReqId` and in catch. The unconditional `setLoadedReqId(null)` at call-time can't clobber a newer resolved value (it runs before any await; the winner always resolves last or the loser bails on the null render-gate uses `req`, not `loadedReqId`). Auto-start (`autoStartedRef`+`loadedReqId`) untouched. ✅ |
| `web/PlanningPage` | `[projectId]` effect only, but rapid filter switch overlaps. `loadTokenRef` guards setState + the `finally setLoading(false)` (only the latest clears loading → no stuck spinner, no premature clear). ✅ |
| `web/ProjectView` | `[id]` effect + `runProjectAction`→`refresh()`. Guard before `setProject/setReqs/setLoadErr` and in catch. `[id]` dep preserved; delete path navs away instead of refreshing. ✅ |
| `web/ProjectMeetings` | `[load]` effect + 1.5s job-poll→`load()` (on job done) + upload/confirm→`load()`. `loadTokenRef` checked before `setProject/setMeetings/setActive`. The `setActive` functional updater runs *after* the guard, so a stale load can't reset the active meeting. Poll's own `alive`+clearInterval intact. ✅ |
| `web/KnowledgePage` | `ask()` re-entry + unmount. `askTokenRef` bumped on each `ask()` and on unmount; checked after each `getKnowledgeRun` and each 900ms sleep in the 8× poll, and gating the `setErr`/`setBusy` in catch/finally. Post-unmount polling now stops within one tick. `busy` correctly owned by the latest ask. Parity with Tauri Knowledge twin. ✅ |

No effect-dependency was broken: the `[reqId]`/`[projectId]`/`[id]` deps are all preserved
(the added `/* eslint-disable-next-line */` is only to silence the exhaustive-deps lint about
calling the non-memoized `refresh`/`load` — the intentional mount-on-id-change behavior is
unchanged). The `stream.done` refresh in Clarify still fires; it's just deduped now.

---

## Fresh adversarial re-sweep + tsc

**Scope check**: R7.15 touched exactly 10 frontend TS files (git diff stat) — the 2 audio
components, AdminPanel, and the 7 token-guard pages/routes. The gold-standard files
(`web/RequirementDetail`, `tauri/Hub`, `tauri/Inbox`, `useNotificationToasts`,
`useReqStream`/`useChatStream`, `lib/tauri.ts`, `App.tsx`) were **not** in the diff, so no
regression to the SSE/event layer is possible from this commit.

**Remaining mount+event+action+interval components** (full enum of both surfaces):
- web: `Dashboard` ✅guarded, `ProjectMeetings` ✅guarded, `useNotificationToasts` ✅(abort+
  signal-check, R15-solid), `ClientDownloadBanner` (mount-only check, no concurrent trigger).
- tauri: `TaskDetail` ✅guarded, `Hub` ✅(`reqTokenRef`), `Inbox` ✅(`reqTokenRef`),
  `App.tsx`/`SpaceSwitcher`/`DeliveryWizard`/`lib/tauri.ts` — all R15-CLEAN, untouched.

No unguarded fetch-on-mount+event+action component remains on either surface. Every such
component is now last-write-wins.

**New races introduced by R7.15?** None found. The token-guard pattern only *adds* early
returns — it cannot create a write that wasn't there. The audio rewrites add refs + cleanup;
I checked that the new `wantRecordingRef`/`playGeneration` reads/writes are all synchronous
or correctly ordered around their single awaits. The `finally` setLoading/setBusy guards were
the one place a "stuck loading" regression could hide — verified they only *skip* the clear
on a superseded call, and the winning call always clears it.

**tsc — all three packages clean:**
- `shared` (`tsc --noEmit -p tsconfig.json`) → **exit 0**
- `web` (`tsc --noEmit -p web/tsconfig.json`, includes `src` + `../shared/src`) → **exit 0**
- `client-tauri/web-src` (root tsc `-p web-src/tsconfig.json`) → **exit 0**

---

## Findings

None at P1/P2. No regression.

### P3 (residual, narrowed — NOT new) — SpeakButton unmount during in-flight fetch
`web/src/components/SpeakButton.tsx:88-90`

The unmount cleanup checks `myAudioRef.current`, which is only assigned *after* the fetch
resolves (line 68). A SpeakButton that unmounts **while its TTS fetch is still in flight**,
with no newer `speak()` to supersede it, leaves `myAudioRef.current` null at cleanup → the
in-flight `speak()` still resolves, creates the `<audio>`, and `play()`s it on a component
that no longer exists (plus benign setState-after-unmount on `setPlaying`/`setBusy`).

Why this is P3, not a re-opened P2:
- The R7.15 fix targeted *concurrent* `speak()` overlap (two voices, one unstoppable) — that
  is fully closed. This is the orthogonal "lone unmount mid-fetch" case.
- In the primary real-world scenario — the Clarify autoplay driver remounting on new
  `parsed` — the replacement driver's `speak()` bumps `playGeneration` and `stopCurrent()`s,
  so the old in-flight fetch is superseded and bails before creating audio. Covered.
- It only bites a *manually-clicked* SpeakButton whose host unmounts inside the sub-second
  TTS fetch window with nothing else speaking. Single disembodied clip, stoppable by the next
  click anywhere (it owns the singleton), self-clears on `onended`. No leak persists, no tree
  torn, no state corrupted.

If you want it airtight (one line): bump a per-instance "alive" ref in the unmount cleanup and
check it alongside the generation after the fetch resolves — `if (!alive.current) return;`
before `createObjectURL`. Not required to hold the streak; flagging for completeness so the
next adversarial pass doesn't "discover" it as new.

---

## Net
The audio paranoia finally matches the SSE paranoia. VoiceButton's hot-mic window is shut
from both ends (release-mid-prompt and unmount-mid-prompt), SpeakButton's dual-voice race is
closed by a synchronous generation claim with a stop-before-assign, and the seven token
guards are textbook last-write-wins with no broken effect deps and no stuck-loading
regression. tsc green ×3. CLEAN.
