import { useEffect, useRef, useState } from "react";
import { useSettings } from "@/hooks/useSettings";

let currentAudio: HTMLAudioElement | null = null;  // module-level: only one plays at a time

function stopCurrent() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    currentAudio = null;
  }
}

/**
 * Speak the given text using the server's TTS service.
 * Set `autoTriggerKey` to play automatically when it changes (used for autoplay).
 */
export function SpeakButton({
  text,
  autoTriggerKey,
  size = "sm",
}: {
  text: string;
  autoTriggerKey?: string;  // when this changes and settings.ttsAutoplay, auto-play
  size?: "sm" | "xs";
}) {
  const { settings } = useSettings();
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const lastTriggerRef = useRef<string | undefined>(undefined);

  const speak = async () => {
    if (!text.trim()) return;
    setErr(null);
    setBusy(true);
    stopCurrent();
    try {
      const r = await fetch("/api/voice/tts", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: settings.ttsVoice }),
      });
      if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = new Audio(url);
      currentAudio = a;
      a.onended = () => { setPlaying(false); URL.revokeObjectURL(url); if (currentAudio === a) currentAudio = null; };
      a.onpause = () => setPlaying(false);
      a.onplay = () => setPlaying(true);
      await a.play();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  // Autoplay when autoTriggerKey changes
  useEffect(() => {
    if (!settings.ttsAutoplay) return;
    if (autoTriggerKey === undefined) return;
    if (lastTriggerRef.current === autoTriggerKey) return;
    lastTriggerRef.current = autoTriggerKey;
    speak();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoTriggerKey, settings.ttsAutoplay]);

  const icon = busy ? "⌛" : playing ? "⏸" : "🔊";
  const sz = size === "xs" ? "h-6 w-6 text-xs" : "h-8 px-2 text-xs";

  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        className={`inline-flex items-center justify-center rounded-md bg-slate-100 ${sz} hover:bg-slate-200`}
        title={`朗读 (${settings.ttsVoice})`}
        disabled={busy}
        onClick={playing ? stopCurrent : speak}
      >
        {icon}
      </button>
      {err && <span className="text-xs text-red-500" title={err}>!</span>}
    </span>
  );
}
