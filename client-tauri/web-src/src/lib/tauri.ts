/**
 * Thin invoke/event helpers — fall back to no-ops when not running inside Tauri
 * (so Vite dev outside the desktop shell stays usable).
 */
import { useEffect } from "react";

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T> {
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
