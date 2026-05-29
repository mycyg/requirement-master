import { useEffect } from "react";
import { toast } from "@yqgl/shared";

type NotifPayload = {
  id?: string;
  title?: string;
  body?: string | null;
  severity?: string;
  target_url?: string | null;
};

/**
 * Live notification toasts for the WEB surface.
 *
 * The web previously opened NO cookie-scoped notification stream, so a
 * submitter waiting on "等你验收" got no live signal — the inbox only updated
 * on a manual page reload. The Tauri client already consumes `/stream/me`;
 * this brings the browser to parity. Mounted once at the app shell.
 *
 * Reconnects with capped exponential backoff (proxy timeout / server restart)
 * and parses the backend's per-line `data:` framing (a notification body may
 * contain newlines — joined with `\n` per the SSE spec).
 */
export function useNotificationToasts() {
  useEffect(() => {
    const ctrl = new AbortController();
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    (async () => {
      let backoff = 1000;
      while (!ctrl.signal.aborted) {
        try {
          const r = await fetch("/api/push/stream/me", { credentials: "include", signal: ctrl.signal });
          if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
          backoff = 1000;
          reader = r.body.getReader();
          const decoder = new TextDecoder("utf-8");
          let buf = "";
          let event = "";
          let dataLines: string[] = [];
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            let nl: number;
            while ((nl = buf.indexOf("\n")) !== -1) {
              const line = buf.slice(0, nl).replace(/\r$/, "");
              buf = buf.slice(nl + 1);
              if (line.startsWith("event:")) {
                event = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                // Preserve a single leading space strip only (per SSE spec),
                // keep the rest verbatim so multi-line bodies round-trip.
                dataLines.push(line.slice(5).replace(/^ /, ""));
              } else if (line === "") {
                if (event === "notification.created" && dataLines.length) {
                  try {
                    const n: NotifPayload = JSON.parse(dataLines.join("\n"));
                    const high = n.severity === "high" || n.severity === "urgent";
                    toast({
                      title: n.title || "新通知",
                      description: n.body || undefined,
                      tone: high ? "warn" : "info",
                    });
                  } catch {
                    /* malformed payload — ignore rather than crash the stream */
                  }
                }
                event = "";
                dataLines = [];
              }
            }
          }
        } catch {
          if (ctrl.signal.aborted) return;
        }
        if (ctrl.signal.aborted) return;
        await new Promise((res) => setTimeout(res, backoff));
        backoff = Math.min(backoff * 2, 30_000);
      }
    })();
    return () => {
      ctrl.abort();
      if (reader) {
        try { reader.cancel(); } catch { /* ignore */ }
      }
    };
  }, []);
}
