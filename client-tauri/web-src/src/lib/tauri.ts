/**
 * Thin invoke/event helpers — fall back to no-ops when not running inside Tauri
 * (so Vite dev outside the desktop shell stays usable).
 */
import { useEffect, useRef } from "react";

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  // E2E hook: a playwright spec or storybook can install `__YQGL_MOCK_INVOKE__`
  // on window to short-circuit the real IPC. Production code never sets it.
  const mock = (window as any).__YQGL_MOCK_INVOKE__;
  if (typeof mock === "function") {
    return mock(cmd, args) as Promise<T>;
  }
  if (!isTauri()) {
    throw new Error(`invoke('${cmd}') called outside Tauri runtime`);
  }
  const mod = await import("@tauri-apps/api/core");
  return mod.invoke<T>(cmd, args);
}

export async function listen<T = unknown>(
  event: string,
  handler: (payload: T) => void,
): Promise<() => void> {
  if (!isTauri()) {
    return () => {};
  }
  const mod = await import("@tauri-apps/api/event");
  const un = await mod.listen<T>(event, (e) => handler(e.payload));
  return un;
}

export function useEvent<T = unknown>(event: string, handler: (payload: T) => void) {
  // Hold the latest handler in a ref so the listener always invokes the
  // current closure, not the one captured on first mount. Without this,
  // callers like TaskDetail that close over `id` / `refresh` would keep
  // dispatching to a stale handler after navigating between requirements
  // (deps `[event]` never change, so the effect never re-runs).
  const handlerRef = useRef(handler);
  useEffect(() => { handlerRef.current = handler; });

  useEffect(() => {
    let alive = true;
    let dispose: (() => void) | null = null;
    listen<T>(event, (p) => { if (alive) handlerRef.current(p); }).then((d) => { dispose = d; });
    return () => {
      alive = false;
      if (dispose) dispose();
    };
  }, [event]);
}

export { isTauri };

/**
 * Cached config snapshot (client_token + server_url). The webview's origin in
 * production is `tauri://localhost`, so a bare `fetch('/api/...')` would 404 —
 * we have to prepend the configured backend URL. Vite dev (browser at
 * http://127.0.0.1:5174) has a /api proxy in vite.config.ts so the leading
 * slash works there too; clientFetch keeps that path verbatim in dev.
 */
let _cfgCache: { token: string; baseUrl: string } | null = null;

async function ensureCfg(): Promise<{ token: string; baseUrl: string }> {
  if (_cfgCache) return _cfgCache;
  if (!isTauri()) {
    _cfgCache = { token: "", baseUrl: "" };  // dev: rely on vite proxy
    return _cfgCache;
  }
  try {
    const cfg = await invoke<{ client_token?: string; server_url?: string }>("get_config");
    _cfgCache = {
      token: cfg?.client_token ?? "",
      baseUrl: (cfg?.server_url ?? "").replace(/\/+$/, ""),
    };
  } catch {
    _cfgCache = { token: "", baseUrl: "" };
  }
  return _cfgCache;
}

/**
 * Drop-in `fetch` for pages that hit the FastAPI server directly. Injects the
 * worker client_token header in Tauri context so backend `require_local_client`
 * routes (claim, sync, delivery, …) authorize, AND prepends the configured
 * backend base URL when running inside the Tauri webview (whose origin is not
 * the backend).
 */
export async function clientFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const cfg = await ensureCfg();
  const headers = new Headers(init.headers || {});
  if (cfg.token) headers.set("X-YQGL-Client-Token", cfg.token);
  // Only absolutize when the caller passed a same-origin /api path AND we know
  // a backend URL. Leave full URLs untouched.
  let url = input;
  if (cfg.baseUrl && input.startsWith("/")) {
    url = cfg.baseUrl + input;
  }
  return fetch(url, { ...init, credentials: "include", headers });
}

/** Reset the cached cfg; call after re-login / device-register / settings change. */
export function resetClientTokenCache() {
  _cfgCache = null;
}

/**
 * Fetch + JSON-decode with status check. Mirrors shared/api/client.ts's
 * `json()` so route components that hit FastAPI directly can't accidentally
 * call `setItems(error_body)` on a 4xx/5xx — that's what kills the React
 * tree (see ProjectPulse / Calendar / Inbox regressions). Always prefer
 * this over `clientFetch(...).then(r => r.json())`.
 */
export async function clientJson<T>(input: string, init?: RequestInit): Promise<T> {
  const r = await clientFetch(input, init);
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}${body ? `: ${body.slice(0, 200)}` : ""}`);
  }
  return (await r.json()) as T;
}
