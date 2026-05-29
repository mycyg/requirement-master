import { useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { clientFetch } from "@/lib/tauri";

/**
 * Press-and-hold to record; on release POSTs the blob to /api/voice/transcribe
 * (via clientFetch so the Tauri webview reaches the backend with auth) and
 * calls onText(text). WebView2 supports getUserMedia/MediaRecorder; the OS
 * shows a one-time mic permission prompt.
 *
 * recordGenRef is a monotonic press generation: getUserMedia can take seconds
 * (permission prompt), and a rapid press→release→press would otherwise leave
 * the first press's resolving stream as an unstoppable hot mic. Each start()
 * claims a generation; stop()/unmount bump it; a stale resolving start() closes
 * its own stream and bails.
 */
export function VoiceButton({ onText }: { onText: (text: string) => void }) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const recordGenRef = useRef(0);

  const start = async () => {
    setErr(null);
    const myGen = ++recordGenRef.current;
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("当前环境不支持录音");
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (myGen !== recordGenRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (streamRef.current === stream) streamRef.current = null;
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setBusy(true);
        try {
          const fd = new FormData();
          fd.append("audio", blob, "voice.webm");
          const r = await clientFetch("/api/voice/transcribe", { method: "POST", body: fd });
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
      if (myGen === recordGenRef.current) setErr(String(e));
    }
  };

  const stop = () => {
    recordGenRef.current++;
    if (mediaRef.current) {
      mediaRef.current.stop();
      mediaRef.current = null;
    } else if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setRecording(false);
  };

  useEffect(() => () => {
    recordGenRef.current++;
    try { mediaRef.current?.stop(); } catch { /* ignore */ }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  return (
    <div className="inline-flex min-w-0 flex-wrap items-center gap-2">
      <button
        type="button"
        className={`inline-flex items-center gap-1.5 h-9 px-3 rounded-sm text-body-sm transition touch-none ${
          recording ? "bg-error text-white" : "glass-quiet text-ink-soft hover:bg-accent-soft hover:text-ink"
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
        {busy ? "转写中…" : recording ? "松手停止" : "按住说话"}
      </button>
      {err && <span className="max-w-[220px] truncate text-caption text-error" title={err}>{err}</span>}
    </div>
  );
}
