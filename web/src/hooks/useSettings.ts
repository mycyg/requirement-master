import { useEffect, useState } from "react";

export type Settings = {
  ttsAutoplay: boolean;
  ttsVoice: string;
};

const DEFAULTS: Settings = {
  ttsAutoplay: false,
  ttsVoice: "male",
};

const KEY = "yqgl.settings.v1";

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return DEFAULTS;
  }
}

// Module-level pubsub so multiple useSettings instances stay in sync within a tab
const listeners = new Set<(s: Settings) => void>();
let current = load();

function broadcast(s: Settings) {
  current = s;
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* ignore */ }
  listeners.forEach((l) => l(s));
}

export function useSettings() {
  const [s, setS] = useState<Settings>(current);
  useEffect(() => {
    listeners.add(setS);
    return () => { listeners.delete(setS); };
  }, []);
  return {
    settings: s,
    update: (patch: Partial<Settings>) => broadcast({ ...current, ...patch }),
  };
}
