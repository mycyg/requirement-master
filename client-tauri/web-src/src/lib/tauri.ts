/**
 * Thin invoke/event helpers — fall back to no-ops when not running inside Tauri
 * (so Vite dev outside the desktop shell stays usable).
 */
import { useEffect } from "react";

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
  useEffect(() => {
    let alive = true;
    let dispose: (() => void) | null = null;
    listen<T>(event, (p) => { if (alive) handler(p); }).then((d) => { dispose = d; });
    return () => {
      alive = false;
      if (dispose) dispose();
    };
    // handler intentionally not in deps — caller passes stable closure or wraps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event]);
}

export { isTauri };

/**
 * Cached worker client_token (filled the first time we read config from Rust).
 * Auto-attached to every clientFetch call so backend `require_local_client`
 * routes work the same as `invoke()`.
 */
let _clientToken: string | null = null;

async function ensureClientToken(): Promise<string | null> {
  if (_clientToken !== null) return _clientToken;
  if (!isTauri()) {
    _clientToken = ""; // browser dev fallback
    return _clientToken;
  }
  try {
    const cfg = await invoke<{ client_token?: string; server_url?: string }>("get_config");
    _clientToken = cfg?.client_token ?? "";
  } catch {
    _clientToken = "";
  }
  return _clientToken;
}

/**
 * Drop-in `fetch` for pages that hit the FastAPI server directly. Injects the
 * worker client_token header in Tauri context so endpoints guarded by
 * `require_local_client` (claim, sync, delivery, …) actually authorize.
 */
export async function clientFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = await ensureClientToken();
  const headers = new Headers(init.headers || {});
  if (token) headers.set("X-YQGL-Client-Token", token);
  return fetch(input, { ...init, credentials: "include", headers });
}

/** Reset the cached token; call after a successful re-login / device-register. */
export function resetClientTokenCache() {
  _clientToken = null;
}
