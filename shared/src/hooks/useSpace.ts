/**
 * Active "Space" — which lens onto yqgl is the user looking through right now?
 * "work"     = 接活 / claimant lens, electric purple accent
 * "dispatch" = 派活 / submitter lens, coral accent
 *
 * Roles are per-requirement (same person dispatches some work and claims others),
 * so Space is a UI-only filter on top of one database — it never changes identity
 * or capability. We persist the choice in localStorage (mirrors useTheme), apply
 * it to `<html data-space="...">` so CSS can swap `--accent`, and wrap state
 * updates in `document.startViewTransition()` so the sidebar + hub morph rather
 * than hard-cut between spaces.
 */
import { useEffect, useState } from "react";

export type SpaceMode = "work" | "dispatch";

const KEY = "yqgl.space";

function read(): SpaceMode {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw === "work" || raw === "dispatch") return raw;
  } catch { /* ignore */ }
  return "work";
}

function apply(mode: SpaceMode) {
  document.documentElement.setAttribute("data-space", mode);
}

const listeners = new Set<(m: SpaceMode) => void>();
let current = read();

if (typeof document !== "undefined") {
  apply(current);
}

export function useSpace() {
  const [mode, setMode] = useState<SpaceMode>(current);

  useEffect(() => {
    const handler = (m: SpaceMode) => setMode(m);
    listeners.add(handler);
    return () => {
      listeners.delete(handler);
    };
  }, []);

  const set = (next: SpaceMode) => {
    const run = () => {
      current = next;
      try {
        localStorage.setItem(KEY, next);
      } catch { /* ignore */ }
      apply(next);
      listeners.forEach((l) => l(next));
    };
    // Native View Transitions API gives us a free crossfade + morph between
    // the two sidebars + hub layouts. Falls back to instant swap on older
    // browsers (and WebView2 already supports it since mid-2024).
    const startVT = (document as any).startViewTransition?.bind(document);
    if (typeof startVT === "function") startVT(run); else run();
  };

  return { space: mode, setSpace: set };
}
