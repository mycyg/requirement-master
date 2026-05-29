import { useEffect, useState } from "react";

export type PushEvent = { event: string; data: any; at: number };

/**
 * Subscribe to /api/push/stream/req/<id> SSE and accumulate events.
 * Use the returned `latestStatus` for live status changes (it's
 * updated whenever a requirement.updated event arrives).
 *
 * `customFetch` lets the Tauri desktop client pass its `clientFetch`
 * (which prepends the backend base URL + auth) — the webview origin is
 * `tauri://localhost`, so a bare relative `fetch('/api/...')` would 404.
 * The browser app omits it and uses native same-origin fetch.
 */
export type ReqStreamFetch = (input: string, init?: RequestInit) => Promise<Response>;

export function useReqStream(reqId: string | undefined, customFetch?: ReqStreamFetch) {
  const [events, setEvents] = useState<PushEvent[]>([]);
  const [latestStatus, setLatestStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!reqId) return;
    const ctrl = new AbortController();
    let alive = true;
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

    (async () => {
      try {
        const doFetch: ReqStreamFetch =
          customFetch ?? ((u, init) => fetch(u, { ...init, credentials: "include" }));
        const r = await doFetch(`/api/push/stream/req/${reqId}`, {
          signal: ctrl.signal,
        });
        if (!r.ok || !r.body) return;
        reader = r.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buf = "";
        let event = "";
        let dataLines: string[] = [];

        const flush = () => {
          if (!alive) return;  // don't setState after unmount
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
            // Strip trailing \r so a server emitting \r\n line endings
            // doesn't leave the CR inside our event name / data values
            // (the SSE spec treats bare \r as its own terminator too).
            const line = buf.slice(0, nl).replace(/\r$/, "");
            buf = buf.slice(nl + 1);
            if (line === "") flush();
            else if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
          }
        }
      } catch (e) {
        if (!ctrl.signal.aborted) console.warn("req stream error", e);
      }
    })();

    return () => {
      alive = false;
      // Cancel the reader so the underlying body lock releases immediately;
      // without this the GC eventually cleans it up but the response can
      // stay "in-flight" from the browser's POV for seconds.
      if (reader) { try { reader.cancel(); } catch { /* ignore */ } }
      ctrl.abort();
    };
  }, [reqId]);

  return { events, latestStatus };
}
