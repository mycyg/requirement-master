import { useEffect, useState } from "react";

export type ThemeMode = "auto" | "light" | "dark";

const KEY = "yqgl.theme";

function read(): ThemeMode {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw === "light" || raw === "dark" || raw === "auto") return raw;
  } catch { /* ignore */ }
  return "auto";
}

function resolvedTheme(mode: ThemeMode): "light" | "dark" {
  if (mode !== "auto") return mode;
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(mode: ThemeMode) {
  const html = document.documentElement;
  html.setAttribute("data-theme", resolvedTheme(mode));
  html.dataset.themeMode = mode;
}

const listeners = new Set<(m: ThemeMode) => void>();
let current = read();

if (typeof document !== "undefined") {
  apply(current);
  if (window.matchMedia) {
    const mm = window.matchMedia("(prefers-color-scheme: dark)");
    mm.addEventListener("change", () => {
      if (current === "auto") apply("auto");
    });
  }
}

export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(current);

  useEffect(() => {
    const handler = (m: ThemeMode) => setMode(m);
    listeners.add(handler);
    return () => {
      listeners.delete(handler);
    };
  }, []);

  const set = (next: ThemeMode) => {
    current = next;
    try {
      localStorage.setItem(KEY, next);
    } catch { /* ignore */ }
    apply(next);
    listeners.forEach((l) => l(next));
  };

  return { mode, setMode: set, resolved: resolvedTheme(mode) };
}
