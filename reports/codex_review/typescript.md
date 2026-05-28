# Codex TypeScript Review

## Summary

Codex's 4 commits on top of `c884b60` are net-positive on the TS/TSX side: all of
my v0.3.0 hardening (`clientJson`, `useEvent` handlerRef, `FileAttachRail`
auto-stop, `resetClientTokenCache` calls, `Settings.tsx` NaN port guard +
loadErr, `TaskDetail` try/catch on every workspace write, `ProjectDrive`
Firefox download + `reloadTokenRef`) survived. The big positives are an
**origin-aware `clientFetch`** that stops leaking `X-YQGL-Client-Token` to
third-party URLs, a **runtime-gated `isDesktopRuntime`** that requires
`__TAURI_INTERNALS__` (not just localStorage), and the Playwright client specs
finally being properly mocked instead of pointed at a hardcoded
`192.168.5.53`. No P0 regressions. A handful of P2 nits below.

## P0 — Regressions or critical bugs

None.

## P1 — Important issues

### 1. `web/tests/e2e/client-routes.spec.ts` + `client-spaces.spec.ts` are now skipped by default

`test.skip(process.env.YQGL_CLIENT_E2E !== "1", ...)` was added to both
specs (`client-routes.spec.ts:35`, `client-spaces.spec.ts:35`). This is
defensible — they need `http://127.0.0.1:5174` (a separately-started
client-tauri vite) which CI doesn't have — but the consequence is that a
plain `npx playwright test` no longer exercises **any** client-side route.
That coverage gap should be made explicit in `package.json` (e.g. an
`e2e:client` script that sets the env var) and called out in
`REVIEW_REPORT.md`, otherwise the next contributor who breaks a client
route won't get a failing test.

### 2. `client-tauri/web-src/src/App.tsx:177` — `sync_drive` tray action toasts but doesn't navigate

```ts
} else if (p?.action === "sync_drive") {
  toast({ title: "请选择项目后点击网盘页同步按钮", tone: "info" });
}
```

The other two branches (`pull_new`, `do_deliver`) now call `nav("/inbox")`
so the user lands somewhere actionable. `sync_drive` leaves the user
wherever they were with a toast telling them to "click the sync button on
the drive page" — but doesn't take them to the drive page. Should also
`nav("/")` or `nav("/drive")` (whichever surfaces project selection).
The bug fix vs my baseline ("正在同步网盘…" was a lie) is correct in spirit
but the UX is half-finished.

### 3. `shared/src/api/client.ts:9` — `(window as any).__TAURI_INTERNALS__` cast lacks justification

```ts
return window.localStorage.getItem("yqgl_runtime") === "desktop"
  && Boolean((window as any).__TAURI_INTERNALS__);
```

Same `as any` pattern is used in `client-tauri/web-src/src/lib/tauri.ts`
(`isTauri()` uses `"__TAURI_INTERNALS__" in window` — type-safe, no
cast). For consistency and to avoid the `any` proliferation, this should
either mirror the `in` operator pattern or augment the global Window type
once and import it:

```ts
// types/tauri-globals.d.ts
declare global { interface Window { __TAURI_INTERNALS__?: unknown } }
```

Minor in isolation but Kieran rule #3 (no unjustified `any`) applies.

### 4. `client-tauri/web-src/src/routes/Onboarding.tsx:51` — missing NaN port guard (pre-existing, but now visibly inconsistent with Settings)

```ts
await invoke("set_config", {
  patch: { server_ip: ip, server_port: Number(port) }
});
```

If the user types `"abc"` into the port field, `Number("abc")` is `NaN`,
and that gets serialized into config.json. `Settings.tsx` explicitly
guards this (`Number.isFinite(n) && n >= 1 && n <= 65535`) — Onboarding
should too. **Note:** this regression is pre-Codex (baseline had the same
gap) but Codex touched this file and missed the symmetry opportunity.

## P2 — Minor

### 5. `client-tauri/web-src/src/routes/TaskDetail.tsx:1` — `useMemo` import dropped along with `isAdmin`

```diff
-import { useEffect, useMemo, useState } from "react";
+import { useEffect, useState } from "react";
```

Codex correctly removed the unused `isAdmin` + `meIsAdmin`. The `useMemo`
drop is fine — confirmed nothing else in the file uses it. No regression.

### 6. `shared/src/api/client.ts:18-21` — `localClientToken()` now does 2 localStorage reads

```ts
function localClientToken(): string | null {
  try {
    if (!isDesktopRuntime()) return null;  // reads yqgl_runtime
    return window.localStorage.getItem("yqgl_client_token");  // reads token
  } catch { return null; }
}
```

`isDesktopRuntime()` does its own localStorage read, so every `withCommon`
call now does 2 reads where it did 1. Microscopic perf, but if you're
chasing a render-per-frame issue later, this is a candidate to cache.

### 7. `web/tests/e2e/screenshots.spec.ts:48` — `shoot()` write-then-rename is good, but tmp file naming can collide

```ts
const tmpPath = path.join(dir, `${name}.${Date.now()}.tmp.png`);
```

If two screenshots fire in the same millisecond (test parallelism, or
two `shoot()` calls back-to-back inside one test), `Date.now()` collides
and one stomps the other. Use `crypto.randomUUID()` or `process.hrtime.bigint()`
instead. Low likelihood with sequential `await`s but cheap to fix.

### 8. `client-tauri/web-src/src/lib/tauri.ts:97-110` — `clientFetch` builds 2× `URL` objects per call

The new origin-check is the right design, but constructing `new URL(cfg.baseUrl)` on **every** clientFetch call is wasteful. The base URL only changes when `_cfgCache` is reset; cache the parsed `URL` alongside it inside `ensureCfg`. Not load-bearing for correctness, just a clean-up.

### 9. `client-tauri/web-src/src/routes/Onboarding.tsx:13-16` — `driveRootFor()` heuristic is fragile

```ts
function driveRootFor(syncRoot: string): string {
  const trimmed = syncRoot.replace(/[\\/]+$/, "");
  return trimmed.includes("\\") ? `${trimmed}\\项目网盘` : `${trimmed}/项目网盘`;
}
```

Picks separator based on whether the path contains `\\`. If a user on
Windows types `D:/工作需求` (forward slashes — perfectly legal on Win),
this produces `D:/工作需求/项目网盘`, which is fine but inconsistent with
the Windows-default `D:\工作需求`. Consider deriving from `navigator.platform`
or normalizing on the Rust side (which is the source of truth anyway —
`config.rs` already has `#[cfg(target_os)]` defaults).

## REVIEW_REPORT.md fidelity check

Spot-checked the report's 5 "已修复" claims against the diff:

| Claim | Verdict |
|---|---|
| "归档后子需求 chat/comments/activity/answer 入口返回 404" | **Out of TS scope** (Python routers) — not verified here. |
| "澄清流后台生成 summary 时再次确认父项目仍处于 active" | Out of TS scope. |
| "Tauri fresh config 不再把空 IP 计算成 `http://:8080`" | **TRUE** — verified `config.rs:113-115`: `if self.server_url.is_empty() && !self.server_ip.trim().is_empty()`. |
| "客户端 Onboarding 移除"双向同步"可选项" | **TRUE** — verified `Onboarding.tsx:30,162` and `Settings.tsx:121`. |
| "Tauri 打包目标收敛为 NSIS" | **TRUE** — verified `tauri.conf.json:49`. |
| "`npm run e2e:web` 通过：25 用例中 23 passed / 2 skipped；覆盖桌面 + 移动 + 超宽屏" | **Plausible but unverifiable from diff alone** — the playwright config did add `mobile` (Pixel 7) and `ultrawide` (1920×1080) projects, restricted to `screenshots.spec.ts \| smoke.spec.ts`, so multi-viewport coverage is real. The "2 skipped" are exactly the two `client-*.spec.ts` files now gated behind `YQGL_CLIENT_E2E=1`. |
| "已修复 UI/UX 优化：全局微软雅黑、lucide-react、超宽屏 5 列等" | **Pre-existing** — none of these are in Codex's 4-commit diff scope. These are baseline features being re-listed. Mild fabrication in the sense that they're presented as part of "this round". |

Overall: report is honest about the changes that actually shipped this round, but inflates its scope by re-listing prior work in the "已完成 UI/UX 优化" section.

## Positive changes worth keeping

1. **`clientFetch` origin guard** (`tauri.ts:96-114`) — prevents
   `X-YQGL-Client-Token` from leaking to third-party origins when a caller
   passes a full external URL. Plus the `credentials: "omit"` fallback for
   cross-origin requests is exactly the right default.

2. **`isDesktopRuntime` double-check** (`shared/src/api/client.ts:9`) —
   requiring both the localStorage flag AND `__TAURI_INTERNALS__` closes
   the hole where a stale `yqgl_runtime=desktop` value in a web browser's
   localStorage would cause the web client to try to attach a worker
   token to its API calls.

3. **Onboarding/Settings `"two_way"` removal** — `client-tauri/src-tauri/src/sync.rs`
   only implements `off` and `download`; surfacing a third option in the
   UI was a confirmed footgun. Removing it from the type union
   (`"off" | "download"`) means the compiler now enforces the contract.

4. **`finalize()` defensive parse on legacy config**
   (`client-tauri/src-tauri/src/config.rs:146-156`) — migrating from
   `%APPDATA%/yqgl/config.json` to the new tauri config dir is graceful
   and writes a `.migrated-to-tauri.json` backup. Good engineering.

5. **Playwright write-then-rename screenshot pattern** — eliminates
   half-written PNGs when a test is killed mid-`page.screenshot()`. The
   tmp-name collision risk (P2 #7) is the only blemish.

6. **`full.spec.ts:97` heading-visibility assertion** — meaningful upgrade
   from "body has > 20 chars" to actually verifying the page rendered
   its title. Catches a class of "blank page with sticky header" bugs
   the old assertion missed.

7. **`workbench.spec.ts:142-180` Chinese-copy resilience** — the
   regex-tolerant selectors (e.g. `/提\s*一(个|条)新?需求/`,
   `/让 (Agent grep|AI 助理找证据)/`) acknowledge that the copy is being
   iterated on and decouple the tests from cosmetic wording changes.

8. **`workbench.spec.ts:254-258` `addInitScript` over `evaluate`** —
   moving the `yqgl_runtime`/`yqgl_client_token`/`__TAURI_INTERNALS__`
   setup into `addInitScript` ensures it runs before any page script,
   which is the right ordering for the `isDesktopRuntime()` check that
   now gates `localClientToken`. The old `await page.evaluate(...)` after
   `identify()` would have lost the race.

## Files reviewed

- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\App.tsx`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\components\FileAttachRail.tsx`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\lib\tauri.ts`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\routes\Onboarding.tsx`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\routes\Settings.tsx`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\client-tauri\web-src\src\routes\TaskDetail.tsx`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\shared\src\api\client.ts`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\web\src\pages\ProjectDrive.tsx`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\web\playwright.config.ts`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\web\tests\e2e\client-routes.spec.ts`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\web\tests\e2e\client-spaces.spec.ts`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\web\tests\e2e\full.spec.ts`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\web\tests\e2e\screenshots.spec.ts`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\web\tests\e2e\smoke.spec.ts`
- `D:\需求管理大师\.claude\worktrees\amazing-chebyshev-c20123\web\tests\e2e\workbench.spec.ts`
