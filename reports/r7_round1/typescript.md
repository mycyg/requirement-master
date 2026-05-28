# R7 Round 1 — TypeScript review

## Verdict

**NEEDS FIXES — 4 findings (0 P0, 2 P1, 2 P2).**

R7 (commit `306edbd`) is purely a Python/Rust revert + admin override restoration. It does not touch TS. The TS surface that survived R6 + R5 hardening is in good shape: SSE handling has CR-strip + reader.cancel + reconnect-with-backoff, modals have body-scroll-lock ref-counting + focus restoration + focus trap, fetch+setState pairs use cancel-aware `alive` flags or monotonic token refs, `useChatStream`/`useReqStream` abort on unmount, and `clientFetch` correctly gates `X-YQGL-Client-Token` on origin match. The only outstanding issues are 4 narrowly-scoped items, none of which block release.

The 4 items below include 2 carry-overs from `reports/codex_review/typescript.md` (P1-#4 NaN port guard and P2-#8 cached URL parse) that R7 didn't fix because R7's scope was Python+Rust only.

## P0 findings (ship blockers)

**None.**

## P1 findings

### P1-1 `client-tauri/web-src/src/routes/Onboarding.tsx:49` — NaN/out-of-range port guard missing (carryover from Codex review P1-#4)

```ts
await invoke("set_config", { patch: { server_ip: ip, server_port: Number(port) } });
```

`Number("abc")` is `NaN`, `Number("")` is `0`. Either writes a garbage value into `config.json` (serde will likely serialize `NaN` as `null`, then Rust defaults kick in; `0` is a silently broken port). `Settings.tsx:159` already has the right guard:

```ts
const n = Number(e.target.value);
if (!Number.isFinite(n) || n < 1 || n > 65535) {
  toast({ title: "端口必须是 1-65535 的整数", tone: "error" });
  e.target.value = String(cfg.server_port);
  return;
}
```

The asymmetry between Onboarding and Settings is the actual bug — a fresh-install user can type `abc` and get past the wizard with broken config, then every direct-API call fails until they go re-edit Settings (which they can't reach if the test_server call later in onboarding refuses because of the bad port). Same fix as Settings; or hoist to a shared `parsePort()` helper in `lib/tauri.ts`.

**Why P1 not P0:** the wizard's `testServer` call (line 54) will surface the bad port immediately ("连不上") so the user can self-correct. Not silent. But still bad UX vs. catching at input time.

### P1-2 `client-tauri/web-src/src/routes/ProjectDrive.tsx:75-82` — listener subscription leak across fast unmount

```ts
useEffect(() => {
  let off: (() => void) | undefined;
  listen<UploadProgress>("drive-upload-progress", (p) => {
    setProgress(p);
    if (p.phase === "done") setTimeout(() => setProgress(null), 600);
  }).then((d) => { off = d; });
  return () => { if (off) off(); };
}, []);
```

Mirror bug of the one Codex already fixed in `FileAttachRail.tsx` (where the fix was the `alive` flag pattern):

```ts
// FileAttachRail.tsx:72-86 — the CORRECT pattern
let alive = true;
let off: (() => void) | undefined;
listen<UploadProgress>("upload-progress", (p) => { ... }).then((d) => {
  if (!alive) d(); else off = d;
});
return () => { alive = false; if (off) off(); };
```

ProjectDrive can race: user clicks `/p/:projectId` then immediately navigates away within ~20ms (the time it takes `listen` to register on the Rust side). Component unmounts → cleanup runs with `off` still undefined. Then `listen` resolves → registers a handler that will call `setProgress()` on an unmounted component. React's StrictMode dev double-mount makes this hit reliably — first mount listens, cleanup runs without disposing because `off` is undefined, second mount listens AGAIN, and now you have 2 active listeners both calling setState on real and ghost components.

Also: setTimeout at line 79 has no cleanup if component unmounts during the 600ms window — another setState-on-unmounted leak. Wrap in a ref or use the same `alive` flag.

**Fix:** copy the `alive`-flag pattern from FileAttachRail. Drop or guard the 600ms setTimeout the same way.

## P2 findings (nits)

### P2-3 `client-tauri/web-src/src/lib/tauri.ts:96-103` — `new URL()` called on every clientFetch (carryover from Codex review P2-#8)

```ts
export async function clientFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const cfg = await ensureCfg();
  ...
  if (cfg.baseUrl) {
    const base = new URL(cfg.baseUrl);              // <-- recomputed every call
    const target = new URL(input, base);
    canAttachClientToken = target.origin === base.origin;
    url = /^https?:\/\//i.test(input) ? input : target.toString();
  }
  ...
}
```

The `_cfgCache` already caches the parsed token+baseUrl string, but the `URL(cfg.baseUrl)` parse runs on every `clientFetch` call (the Inbox view alone fires 1 fetch per route + 1 per SSE notification.created). Cheap individually, but trivially cacheable alongside `_cfgCache`:

```ts
let _cfgCache: { token: string; baseUrl: string; baseUrlObj: URL | null } | null = null;
// ...
_cfgCache = {
  token: cfg?.client_token ?? "",
  baseUrl: (cfg?.server_url ?? "").replace(/\/+$/, ""),
  baseUrlObj: cfg?.server_url ? new URL(cfg.server_url.replace(/\/+$/, "")) : null,
};
```

Not load-bearing for correctness. Only landed cache, leave the URL parse uncached: same hit either way after the first call.

### P2-4 `web/src/pages/RequirementDetail.tsx:96-117` — `refresh()` lacks cancel-aware guard across id changes

```ts
const refresh = async () => {
  if (!id) return;
  try {
    const r = await api.getRequirement(id);
    setReq(r);
    setLoadErr(null);
    const [nextAttachments, nextWorkspaces, nextPlans, nextAcceptance] = await Promise.all([
      api.listAttachments(id),
      api.listRequirementWorkspaces(id).catch(() => []),
      api.listTaskPlans(id).catch(() => []),
      api.listAcceptanceItems(id).catch(() => []),
    ]);
    setAttachments(nextAttachments);
    setWorkspaces(nextWorkspaces);
    setTaskPlans(nextPlans);
    setAcceptanceItems(nextAcceptance);
  } catch (e: any) { setLoadErr(String(e)); }
};
useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [id]);
```

If the user navigates `/r/A → /r/B` and A's `Promise.all` is still pending when B's `getRequirement` resolves first, A's late completion will `setAttachments`/`setWorkspaces`/`setTaskPlans`/`setAcceptanceItems` with A's data while `req` is already B. The header/title/status show B but the four collateral lists are A's. Visible glitch lasts until the next SSE refresh.

Pattern fix is the same one `web/src/pages/ProjectDrive.tsx:98-117` already uses (the `reloadTokenRef` monotonic counter pattern). For RequirementDetail, the simpler fix is a cleanup-scoped `alive` flag inside the `useEffect`:

```ts
useEffect(() => {
  let alive = true;
  (async () => {
    if (!id) return;
    try {
      const r = await api.getRequirement(id);
      if (!alive) return;
      setReq(r); setLoadErr(null);
      const [attachments, workspaces, plans, acceptance] = await Promise.all([...]);
      if (!alive) return;
      setAttachments(attachments); ...
    } catch (e) { if (alive) setLoadErr(String(e)); }
  })();
  return () => { alive = false; };
}, [id]);
```

Same risk also exists in `RequirementDetail`'s `latestStatus`-triggered `refresh()` (line 128) but it's lower-impact since the user isn't navigating in that case — just SSE-triggered.

**Why P2 not P1:** the race window is < 200ms on LAN and the next SSE event resolves it within a couple seconds. Users won't notice unless they're navigation-mashing.

## Coverage

Read every TS/TSX file in scope. Total file count: **104** across `web/src/`, `client-tauri/web-src/src/`, and `shared/src/`.

### shared/src/
- `api/client.ts`, `api/index.ts`, `api/types.ts`
- `design/status-vocab.ts`, `design/tailwind-preset.ts`
- `hooks/{useChatStream,useReqStream,useIdentity,useFirstRun,useSettings,useSpace,useTheme,useViewerRole,index}.ts`
- `ui/{Avatar,Badge,Button,Card,Combobox,CommandMenu,Drawer,DropdownMenu,EmptyState,Input,Modal,Panel,Progress,RouteTransition,Select,Skeleton,StatusBadge,Stepper,Tabs,Textarea,Toast,Toggle,Tooltip,WelcomeTour,bodyScrollLock,cn,index}.tsx`

### client-tauri/web-src/src/
- `main.tsx`, `App.tsx`
- `lib/tauri.ts`
- `routes/{Calendar,Clarify,Hub,HubDispatch,Inbox,Knowledge,MyWorkload,NewRequirement,Onboarding,ProjectDrive,ProjectPulse,Settings,TaskDetail}.tsx`
- `components/{ActionRailDispatch,AdminPanel,AssigneeSelector,DeliveryWizard,FileAttachRail,Sidebar,SidebarDispatch,SidebarWork,SpaceSwitcher,TaskCard,TitleBar}.tsx`

### web/src/
- `main.tsx`, `App.tsx`
- `lib/{api,types}.ts`
- `hooks/{useChatStream,useIdentity,useReqStream,useSettings}.ts` (all re-export shims)
- `pages/{CalendarPage,Clarify,Dashboard,DriveHome,HealthPage,Home,KnowledgePage,NewRequirement,NotificationsPage,PlanningPage,ProjectDrive,ProjectMeetings,ProjectView,RequirementDetail}.tsx`
- `components/{AILiveView,ActivityTimeline,AssigneeSelector,ClientDownloadBanner,CommentsPanel,DeliverablesTab,FileUpload,NicknameDialog,ProjectStateConfirm,SettingsDialog,SpeakButton,StatusBadge,VoiceButton}.tsx`

### What I specifically checked and found clean
- **Race conditions** — every fetch+setState pair I found is gated by `alive`/`AbortController`/monotonic-token (except P1-2 + P2-4). `Knowledge.tsx`'s polling loop checks `askTokenRef` before AND after every `setRun`. `ProjectDrive.tsx` (web) uses `reloadTokenRef`. `WorkspaceCard` has the dirty-flag protection so SSE-refresh doesn't wipe in-flight typing. `useChatStream`/`useReqStream` both call `reader.cancel()` on cleanup.
- **SSE protocol** — `\r$/` strip is present in `useChatStream:90`, `useReqStream:56`, and `Dashboard:111`. Multi-line `data:` is correctly accumulated with `\n`-join in both `useReqStream:31,42-44` and `useChatStream:99-100`. Heartbeat handling exists in `Dashboard:115`. Reconnect with exponential backoff (1s → 30s cap) is in `Dashboard:94-127`.
- **Error handling** — `RequirementDetail`, `ProjectView`, `Clarify` (web) all gained `loadErr` state + retry buttons in R5 to escape the "loading forever on 401/404" trap. `clientJson` (tauri.ts:126) throws on non-2xx so direct-API pages can't accidentally render error bodies as data. `ProjectPulse` (client-tauri) explicitly guards against `setList({detail: "..."})` (the bug that crashed the route in v0.2.1).
- **Type safety** — 12 `as any` casts in TS/TSX. All justified: 1 for `__TAURI_INTERNALS__` detection (intentional; matches `isTauri()` pattern; previously flagged Codex P1-#3 — minor nit, not load-bearing), 1 each for `(document as any).startViewTransition` polyfill, 11 for `catch (e: any)` (standard pattern; TS still requires explicit annotation since 4.0). Zero `// @ts-ignore`. Zero `// @ts-expect-error`.
- **Auth** — every `fetch` direct call in scope either (a) goes through `withCommon`/`clientFetch` (which attach the token + credentials) or (b) is to an explicitly-public endpoint (`/api/downloads/manifest`, `/api/voice/voices`, `/api/voice/tts`, `/api/voice/transcribe`). The `clientFetch` origin guard (Codex's good fix) prevents the worker token from leaking to off-origin URLs.
- **UI polish** — `Modal.tsx` has ESC, focus trap (Tab/Shift+Tab cycle), focus restoration to previously-focused element, body scroll lock, backdrop dismiss. `Drawer.tsx` has ESC + body lock. `Combobox.tsx` has arrow-key nav, type-ahead, scroll active into view, Tab closes. `CommandMenu.tsx` has arrow-key + Enter nav, autofocus on open. `WelcomeTour.tsx` has Arrow-Left/Right, progress dots, focus reset on re-open. `bodyScrollLock.ts` ref-counts correctly across nested Modal+Drawer.
- **Performance** — `useChatStream` and `useReqStream` are properly memoized (deps `[req_id, customFetch]` and `[reqId]` respectively). `useEvent` uses handlerRef pattern so the listener doesn't re-subscribe on closure change (the R5 fix). `Dashboard` pauses polling on `document.hidden`. `FileAttachRail` auto-stops the spec watcher when status leaves `WATCHABLE_STATUSES`. Module-level pubsub in `useTheme`/`useSpace`/`useSettings` correctly cleans up listeners on unmount.

### Notes on prior reviews
- Codex P1-#1 (client-spec skip env gate) is a test infrastructure decision, not a TS code bug; outside this round's scope.
- Codex P1-#2 (`sync_drive` tray toast doesn't navigate) — verified still present in `App.tsx:175-176`. Pure UX nit, not a correctness issue. Leaving for product-decision.
- Codex P1-#3 (`as any` for `__TAURI_INTERNALS__`) — present in `shared/src/api/client.ts:10` and 1 other spot. Pure style nit. Add a `types/tauri-globals.d.ts` shim later if you care about removing it.
- Codex P2-#7 (screenshots.spec tmp name collision) — test infra, not in TS application scope.

Everything else from `reports/codex_review/typescript.md` either remains as a documented-but-not-blocking nit or was already absorbed into R6/R7 work.
