import { useCallback, useEffect, useState } from "react";

/**
 * Persist a "this user has seen the welcome tour" flag in localStorage.
 *
 * Versioned (`:v1`) so a future redesign can bump the suffix and force the
 * whole user base back through an updated tour without needing a migration.
 *
 * Returns:
 * - `seen`: boolean (true after `markSeen`, or after `reset(true)`)
 * - `loading`: true on the very first render before we've read localStorage
 *   (avoids SSR/hydration flash, but also covers privacy-mode browsers
 *    where localStorage throws — we still resolve `loading=false` so the
 *    UI doesn't deadlock).
 * - `markSeen()`: persist seen=true.
 * - `reset()`: clear the flag (so the tour can re-show — e.g. when the
 *   user clicks "再看一遍引导" in Settings).
 */
const STORAGE_KEY = "yqgl.welcomeShown:v1";

function readSeen(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    // privacy mode / disabled storage — treat as not seen so the tour
    // still shows once per session at most (we won't persist below either).
    return false;
  }
}

function writeSeen(seen: boolean): void {
  try {
    if (seen) window.localStorage.setItem(STORAGE_KEY, "1");
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore — see readSeen */
  }
}

export function useFirstRun() {
  // Initialize from localStorage SYNCHRONOUSLY so the tour doesn't
  // briefly flash on page load for returning users. SSR-safety: in a
  // browser context window is always defined; the try/catch covers
  // privacy mode.
  const [seen, setSeen] = useState<boolean>(() =>
    typeof window === "undefined" ? true : readSeen(),
  );

  // Sync across tabs — if the user opens a second tab and dismisses
  // the tour there, the first tab should follow.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setSeen(e.newValue === "1");
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const markSeen = useCallback(() => {
    writeSeen(true);
    setSeen(true);
  }, []);

  const reset = useCallback(() => {
    writeSeen(false);
    setSeen(false);
  }, []);

  return { seen, markSeen, reset };
}
