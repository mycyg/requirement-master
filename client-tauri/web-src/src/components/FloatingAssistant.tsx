import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Bot, Loader2, Send, Sparkles, X } from "lucide-react";
import { Button, toast } from "@yqgl/shared";
import { clientFetch, invoke } from "@/lib/tauri";

type DraftPayload = { project_id?: string; title?: string; raw_description: string; answer_md?: string };
type Msg = { role: "user" | "assistant"; content: string; draft?: DraftPayload };

/** Pull the active project id from a /p/<id>... route so project questions
 *  get grep-grounded; undefined elsewhere (the assistant still answers
 *  system/usage questions). */
function currentProjectId(pathname: string): string | undefined {
  const m = pathname.match(/^\/p\/([^/]+)/);
  return m ? decodeURIComponent(m[1]) : undefined;
}

/**
 * Floating AI assistant bubble (bottom-right, both spaces). Answers
 * system/usage questions, project questions (grep-grounded server-side), and
 * can turn a description into a requirement draft → hands off to the existing
 * 澄清 flow. Streams over /api/assistant/chat with the same SSE contract as
 * clarify (thinking/text/parsed/error/done).
 */
export function FloatingAssistant() {
  const nav = useNavigate();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [thinking, setThinking] = useState("");
  const [creating, setCreating] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [history.length, thinking, running]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = async () => {
    const text = input.trim();
    if (!text || running) return;
    setInput("");
    const nextHistory: Msg[] = [...history, { role: "user", content: text }];
    setHistory(nextHistory);
    setRunning(true);
    setThinking("");

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const resp = await clientFetch("/api/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: nextHistory.map((m) => ({ role: m.role, content: m.content })),
          project_id: currentProjectId(pathname) ?? null,
        }),
        signal: ctrl.signal,
      });
      if (!resp.ok || !resp.body) throw new Error(`${resp.status} ${resp.statusText}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "", event = "", data = "";
      let parsed: any = null;
      const flush = () => {
        if (!event) return;
        // capture before reset — setState updaters run async (see useChatStream)
        const ev = event, d = data;
        event = ""; data = "";
        if (ev === "thinking") setThinking((t) => t + d);
        else if (ev === "parsed") { try { parsed = JSON.parse(d); } catch { /* ignore */ } }
        else if (ev === "error") parsed = { action: "answer", payload: { answer_md: `出错了：${d}` } };
      };
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) !== -1) {
          const line = buf.slice(0, nl).replace(/\r$/, "");
          buf = buf.slice(nl + 1);
          if (line === "") flush();
          else if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data = (data ? data + "\n" : "") + line.slice(5).replace(/^ /, "");
        }
      }
      flush();

      const payload = parsed?.payload ?? {};
      const answer: string = payload.answer_md || "（没有回复）";
      const draft: DraftPayload | undefined = parsed?.action === "draft_requirement" && payload.raw_description
        ? { project_id: payload.project_id, title: payload.title, raw_description: payload.raw_description }
        : undefined;
      setHistory((h) => [...h, { role: "assistant", content: answer, draft }]);
    } catch (e: any) {
      if (!ctrl.signal.aborted) {
        setHistory((h) => [...h, { role: "assistant", content: `连接失败：${String(e)}` }]);
      }
    } finally {
      setRunning(false);
      setThinking("");
    }
  };

  const createFromDraft = async (draft: DraftPayload) => {
    setCreating(true);
    try {
      const projects = await invoke<{ id: string }[]>("list_my_projects");
      const pid = draft.project_id && projects.some((p) => p.id === draft.project_id)
        ? draft.project_id
        : projects[0]?.id;
      if (!pid) { toast({ title: "请先创建一个项目", tone: "warn" }); return; }
      const r = await invoke<{ id: string }>("create_requirement", {
        projectId: pid,
        body: { raw_description: draft.raw_description, priority: "normal", lead_user_id: null, collaborator_user_ids: [] },
      });
      setOpen(false);
      toast({ title: "已创建草稿，进入澄清完善", tone: "success" });
      nav(`/r/${r.id}/clarify`);
    } catch (e: any) {
      toast({ title: "创建失败", description: String(e), tone: "error" });
    } finally { setCreating(false); }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-5 right-5 z-50 grid h-12 w-12 place-items-center rounded-full text-white shadow-2 transition hover:scale-105"
        style={{ background: "linear-gradient(135deg,#6B5BFF,#FF6E8E)" }}
        title="AI 助理"
        aria-label="AI 助理"
      >
        {open ? <X className="h-5 w-5" /> : <Sparkles className="h-5 w-5" />}
      </button>

      {open && (
        <div className="fixed bottom-20 right-5 z-50 flex h-[520px] max-h-[calc(100vh-8rem)] w-[380px] max-w-[calc(100vw-2.5rem)] flex-col rounded-md glass-strong shadow-2 anim-fade-up">
          <div className="flex items-center gap-2 border-b border-line px-4 py-3">
            <div className="grid h-7 w-7 place-items-center rounded-full text-white" style={{ background: "linear-gradient(135deg,#6B5BFF,#FF6E8E)" }}>
              <Bot className="h-4 w-4" />
            </div>
            <div className="text-body-sm font-medium text-ink">AI 助理</div>
            <span className="text-caption text-ink-faint">问功能 · 问项目 · 帮你提需求</span>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-auto p-3">
            {history.length === 0 && !running && (
              <div className="glass-sunken rounded-sm p-3 text-caption text-ink-muted">
                你好，我能解答「这个功能怎么用」、基于项目资料回答问题，或者把你的想法直接整理成需求草稿。试试问我点什么？
              </div>
            )}
            {history.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] whitespace-pre-wrap rounded-md px-3 py-2 text-body-sm ${
                  m.role === "user" ? "bg-accent text-white" : "glass-sunken text-ink-soft"
                }`}>
                  {m.content}
                  {m.draft && (
                    <div className="mt-2">
                      <Button variant="accent" size="sm" loading={creating} leftIcon={<Sparkles className="h-3.5 w-3.5" />} onClick={() => createFromDraft(m.draft!)}>
                        新建为需求
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {running && (
              <div className="flex justify-start">
                <div className="max-w-[85%] glass-sunken rounded-md px-3 py-2 text-caption text-ink-muted">
                  <div className="mb-1 flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" /> 思考中…</div>
                  {thinking && <div className="whitespace-pre-wrap opacity-80">{thinking.slice(-400)}</div>}
                </div>
              </div>
            )}
          </div>

          <div className="flex gap-2 border-t border-line p-3">
            <textarea
              className="field flex-1 resize-none"
              rows={2}
              placeholder="问我点什么…（Enter 发送）"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            />
            <Button variant="accent" loading={running} disabled={!input.trim()} leftIcon={<Send className="h-4 w-4" />} onClick={send}>
              发送
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
