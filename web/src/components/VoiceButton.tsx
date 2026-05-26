import { useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";

/**
 * Press-and-hold to record. On release, POSTs the blob to /api/voice/transcribe
 * and calls onText(text).
 *
 * Stubbed for M5: backend endpoint not yet wired. The UI works (records audio,
 * shows duration) but a graceful "未启用" error will appear if the endpoint
 * returns 404.
 */
export function VoiceButton({ onText }: { onText: (text: string) => void }) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const start = async () => {
    setErr(null);
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("当前浏览器不支持录音");
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setBusy(true);
        try {
          const fd = new FormData();
          fd.append("audio", blob, "voice.webm");
          const r = await fetch("/api/voice/transcribe", {
            method: "POST",
            credentials: "include",
            body: fd,
          });
          if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
          const data = await r.json() as { text: string };
          if (data.text) onText(data.text);
        } catch (e: any) {
          setErr(String(e));
        } finally {
          setBusy(false);
        }
      };
      mr.start();
      mediaRef.current = mr;
      setRecording(true);
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const stop = () => {
    mediaRef.current?.stop();
    mediaRef.current = null;
    setRecording(false);
  };

  return (
    <div className="inline-flex min-w-0 flex-wrap items-center gap-2">
      <button
        type="button"
        className={`button min-h-9 touch-none px-3 py-1.5 text-xs ${
          recording ? "border-red-700 bg-red-700 text-white" : "border-stone-300 bg-[#fffdf8] text-stone-700 hover:border-stone-500"
        } ${busy ? "opacity-50" : ""}`}
        disabled={busy}
        onPointerDown={start}
        onPointerUp={stop}
        onPointerCancel={stop}
        onPointerLeave={() => recording && stop()}
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : recording ? (
          <Square className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <Mic className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {busy ? "转写中..." : recording ? "松手停止" : "按住说话"}
      </button>
      {err && <span className="max-w-[220px] truncate text-xs text-red-700" title={err}>{err}</span>}
    </div>
  );
}
