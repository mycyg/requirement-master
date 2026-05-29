import { useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, Pause, Volume2 } from "lucide-react";
import { useSettings } from "@/hooks/useSettings";

let currentAudio: HTMLAudioElement | null = null;  // module-level: only one plays at a time
let currentAudioUrl: string | null = null;
// Monotonic generation: each speak() claims one synchronously. Two SpeakButtons
// (e.g. several on the Clarify screen) racing their TTS fetches would otherwise
// each assign `currentAudio` after their await resolved — the later assignment
// clobbered the earlier audio's reference without stopping it, leaving two
// overlapping voices, one of them unstoppable. After the fetch we bail if a
// newer speak() superseded us.
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
  const myAudioRef = useRef<HTMLAudioElement | null>(null);
  const aliveRef = useRef(true);

  const speak = async () => {
    if (!text.trim()) return;
    setErr(null);
    setBusy(true);
    const myGen = ++playGeneration;  // claim "latest" synchronously, before any await
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
      // Bail if a newer speak() superseded us OR this component unmounted
      // mid-fetch — otherwise the clip would play on a dead component with no
      // UI left to stop it.
      if (myGen !== playGeneration || !aliveRef.current) return;
      const url = URL.createObjectURL(blob);
      stopCurrent();  // stop anything that started between our claim and now
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

  // Unmount: flip aliveRef so an in-flight speak() fetch that resolves after
  // unmount bails instead of playing on a dead component, AND if this
  // component's clip is the one currently playing, stop it so navigating away
  // mid-speech doesn't leave a disembodied voice running.
  useEffect(() => () => {
    aliveRef.current = false;
    if (myAudioRef.current && currentAudio === myAudioRef.current) stopCurrent();
  }, []);

  // Autoplay when autoTriggerKey changes
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
  const sz = size === "xs" ? "h-7 w-7 px-0" : "h-9 px-3";

  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        className={`button-secondary min-h-0 ${sz} text-xs`}
        title={`朗读 (${settings.ttsVoice})`}
        aria-label={playing ? "停止朗读" : "朗读"}
        disabled={busy}
        onClick={playing ? stopCurrent : speak}
      >
        {icon}
      </button>
      {err && <AlertCircle className="h-3.5 w-3.5 text-red-700" aria-label={err} />}
    </span>
  );
}
