import { useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, Pause, Volume2 } from "lucide-react";
import { useSettings } from "@yqgl/shared";
import { clientFetch } from "@/lib/tauri";

let currentAudio: HTMLAudioElement | null = null;  // module-level: only one plays at a time
let currentAudioUrl: string | null = null;
// Monotonic generation: two SpeakButtons racing their TTS fetches would each
// assign currentAudio after their await resolved, leaving overlapping voices.
// After the fetch we bail if a newer speak() superseded us.
let playGeneration = 0;

function stopCurrent() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    currentAudio = null;
  }
  if (currentAudioUrl) {
    URL.revokeObjectURL(currentAudioUrl);
    currentAudioUrl = null;
  }
}

/**
 * Speak `text` via the server TTS (/api/voice/tts, through clientFetch).
 * Set `autoTriggerKey` to auto-play when it changes AND settings.ttsAutoplay
 * is on (default off, so no surprise audio).
 */
export function SpeakButton({
  text,
  autoTriggerKey,
}: {
  text: string;
  autoTriggerKey?: string;
}) {
  const { settings } = useSettings();
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const lastTriggerRef = useRef<string | undefined>(undefined);
  const myAudioRef = useRef<HTMLAudioElement | null>(null);
  const aliveRef = useRef(true);

  const speak = async () => {
    if (!text.trim()) return;
    setErr(null);
    setBusy(true);
    const myGen = ++playGeneration;
    stopCurrent();
    try {
      const r = await clientFetch("/api/voice/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: settings.ttsVoice }),
      });
      if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
      const blob = await r.blob();
      if (myGen !== playGeneration || !aliveRef.current) return;
      const url = URL.createObjectURL(blob);
      stopCurrent();
      const a = new Audio(url);
      currentAudio = a;
      currentAudioUrl = url;
      myAudioRef.current = a;
      a.onended = () => {
        setPlaying(false);
        URL.revokeObjectURL(url);
        if (currentAudio === a) currentAudio = null;
        if (currentAudioUrl === url) currentAudioUrl = null;
        if (myAudioRef.current === a) myAudioRef.current = null;
      };
      a.onpause = () => setPlaying(false);
      a.onplay = () => setPlaying(true);
      await a.play();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => () => {
    aliveRef.current = false;
    if (myAudioRef.current && currentAudio === myAudioRef.current) stopCurrent();
  }, []);

  useEffect(() => {
    if (!settings.ttsAutoplay) return;
    if (autoTriggerKey === undefined) return;
    if (lastTriggerRef.current === autoTriggerKey) return;
    lastTriggerRef.current = autoTriggerKey;
    speak();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoTriggerKey, settings.ttsAutoplay]);

  const icon = busy
    ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
    : playing
      ? <Pause className="h-3.5 w-3.5" aria-hidden="true" />
      : <Volume2 className="h-3.5 w-3.5" aria-hidden="true" />;

  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        className="grid h-8 w-8 place-items-center rounded-sm glass-quiet text-ink-soft hover:bg-accent-soft hover:text-ink transition disabled:opacity-50"
        title={`朗读（${settings.ttsVoice}）`}
        aria-label={playing ? "停止朗读" : "朗读"}
        disabled={busy}
        onClick={playing ? stopCurrent : speak}
      >
        {icon}
      </button>
      {err && <AlertCircle className="h-3.5 w-3.5 text-error" aria-label={err} />}
    </span>
  );
}
