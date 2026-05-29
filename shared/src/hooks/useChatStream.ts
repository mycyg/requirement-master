import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentParsed } from "../api/types";

type StreamState = {
  thinking: string;
  text: string;
  parsed: AgentParsed | null;
  error: string | null;
  done: boolean;
  running: boolean;
};

/**
 * Custom fetch wrapper — caller can pass `clientFetch` (from the Tauri
 * client's lib/tauri.ts) so SSE works inside the desktop webview where
 * the origin isn't the backend. Default = native fetch for the web client.
 */
export type ChatFetch = (input: string, init?: RequestInit) => Promise<Response>;

export function useChatStream(req_id: string, customFetch?: ChatFetch) {
  const [state, setState] = useState<StreamState>({
    thinking: "", text: "", parsed: null, error: null, done: false, running: false,
  });
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setState({ thinking: "", text: "", parsed: null, error: null, done: false, running: false });
  }, []);

  const run = useCallback(async (opts: { force_summarize?: boolean } = {}) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setState({ thinking: "", text: "", parsed: null, error: null, done: false, running: true });

    let resp: Response;
    try {
      const doFetch = customFetch ?? ((u, init) => fetch(u, { ...init, credentials: "include" }));
      resp = await doFetch(`/api/requirements/${req_id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(opts),
        signal: ctrl.signal,
      });
    } catch (e: any) {
      setState((s) => ({ ...s, running: false, error: String(e) }));
      return;
    }

    if (!resp.ok || !resp.body) {
      const body = await resp.text().catch(() => "");
      setState((s) => ({ ...s, running: false, error: `${resp.status} ${resp.statusText}${body ? `: ${body.slice(0, 200)}` : ""}` }));
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buf = "";
    let event = "";
    let data = "";

    const flush = () => {
      if (!event) return;
      // Capture event/data into locals BEFORE resetting them. setState's
      // functional updater runs asynchronously (React 18 batches updates made
      // in this async read-loop and flushes them at await boundaries); if the
      // updater closed over the mutable `event`/`data`, by the time React ran
      // it those vars would have been reset to "" or reassigned by the next
      // SSE event — so deltas got dropped / duplicated / reordered, which is
      // exactly the garbled "thinking" stream seen in the desktop client.
      const ev = event;
      const d = data;
      event = ""; data = "";
      setState((s) => {
        if (ev === "thinking") return { ...s, thinking: s.thinking + d };
        if (ev === "text") return { ...s, text: s.text + d };
        if (ev === "parsed") {
          try {
            return { ...s, parsed: JSON.parse(d) as AgentParsed, running: false };
          } catch {
            return { ...s, error: "parsed event was not valid JSON" };
          }
        }
        if (ev === "error") return { ...s, error: d };
        if (ev === "done") return { ...s, done: true, running: false };
        return s;
      });
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) !== -1) {
          // Strip trailing \r — server may emit \r\n; without this the CR
          // ends up inside event names / data values, breaking matches.
          const line = buf.slice(0, nl).replace(/\r$/, "");
          buf = buf.slice(nl + 1);
          if (line === "") {
            flush();
          } else if (line.startsWith("event:")) {
            event = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            // Per SSE spec: strip ONE leading space, preserve the rest
            // (so JSON-escaped data like `data: " hello"` stays intact).
            const value = line.slice(5).replace(/^ /, "");
            data = (data ? data + "\n" : "") + value;
          }
        }
      }
      flush();
    } catch (e: any) {
      if (ctrl.signal.aborted) return;
      setState((s) => ({ ...s, running: false, error: String(e) }));
    } finally {
      // Release the body lock so the response can be GC'd, even if we
      // bailed before reading EOF (network error, AbortController, etc).
      try { await reader.cancel(); } catch { /* ignore */ }
      setState((s) => s.running ? { ...s, running: false } : s);
    }
  }, [req_id, customFetch]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setState((s) => ({ ...s, running: false }));
  }, []);

  // Cancel any in-flight SSE on unmount so a route change mid-stream doesn't
  // leak the response body lock (and doesn't continue to charge the LLM).
  useEffect(() => () => { abortRef.current?.abort(); }, []);

  return { ...state, run, cancel, reset };
}
