import { useEffect, useState } from "react";

export type PushEvent = { event: string; data: any; at: number };

/**
 * Subscribe to /api/push/stream/req/<id> SSE and accumulate events.
 * Use the returned `latestStatus` for live status changes (it's
 * updated whenever a requirement.updated event arrives).
 */
export function useReqStream(reqId: string | undefined) {
  const [events, setEvents] = useState<PushEvent[]>([]);
  const [latestStatus, setLatestStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!reqId) return;
    const ctrl = new AbortController();
    let alive = true;

    (async () => {
      try {
        const r = await fetch(`/api/push/stream/req/${reqId}`, {
          credentials: "include",
          signal: ctrl.signal,
        });
        if (!r.ok || !r.body) return;
        const reader = r.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buf = "";
        let event = "";
        let dataLines: string[] = [];

        const flush = () => {
          if (!event) return;
          const raw = dataLines.join("\n");
          let data: any = raw;
          try { data = JSON.parse(raw); } catch { /* keep raw */ }
          if (event === "requirement.updated" && data && typeof data === "object" && data.status) {
            setLatestStatus(data.status);
          }
          setEvents((xs) => [...xs.slice(-200), { event, data, at: Date.now() }]);
          event = "";
          dataLines = [];
        };

        while (alive) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let nl;
          while ((nl = buf.indexOf("\n")) !== -1) {
            const line = buf.slice(0, nl);
            buf = buf.slice(nl + 1);
            if (line === "") flush();
            else if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
        }
      } catch (e) {
        if (!ctrl.signal.aborted) console.warn("req stream error", e);
      }
    })();

    return () => { alive = false; ctrl.abort(); };
  }, [reqId]);

  return { events, latestStatus };
}
