import { useCallback, useRef, useState } from "react";
import type { AgentParsed } from "@/lib/types";

type StreamState = {
  thinking: string;        // accumulated thinking deltas
  text: string;            // accumulated raw text deltas
  parsed: AgentParsed | null;
  error: string | null;
  done: boolean;
  running: boolean;
};

export function useChatStream(req_id: string) {
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
      resp = await fetch(`/api/requirements/${req_id}/chat`, {
        method: "POST",
        credentials: "include",
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
      setState((s) => {
        if (event === "thinking") return { ...s, thinking: s.thinking + data };
        if (event === "text") return { ...s, text: s.text + data };
        if (event === "parsed") {
          try {
            return { ...s, parsed: JSON.parse(data) as AgentParsed, running: false };
          } catch {
            return { ...s, error: "parsed event was not valid JSON" };
          }
        }
        if (event === "error") return { ...s, error: data };
        if (event === "done") return { ...s, done: true, running: false };
        return s;
      });
      event = ""; data = "";
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) !== -1) {
          const line = buf.slice(0, nl);
          buf = buf.slice(nl + 1);
          if (line === "") {
            flush();
          } else if (line.startsWith("event:")) {
            event = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            data = (data ? data + "\n" : "") + line.slice(5).trim();
          }
        }
      }
      flush();
    } catch (e: any) {
      if (ctrl.signal.aborted) return;
      setState((s) => ({ ...s, running: false, error: String(e) }));
    } finally {
      setState((s) => s.running ? { ...s, running: false } : s);
    }
  }, [req_id]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setState((s) => ({ ...s, running: false }));
  }, []);

  return { ...state, run, cancel, reset };
}
