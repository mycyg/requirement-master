import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, Bot, CalendarClock, FileText, Loader2, Send } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Input,
  StatusBadge,
  Textarea,
  toast,
  useChatStream,
} from "@yqgl/shared";
import type {
  AgentParsed,
  Requirement,
  StoredChatMessage,
  SummarizePayload,
} from "@yqgl/shared";
import { invoke, clientFetch } from "@/lib/tauri";
import { VoiceButton } from "@/components/VoiceButton";
import { SpeakButton } from "@/components/SpeakButton";

/**
 * 派活 Space 的 AI 澄清页面 — 移植自 [web/src/pages/Clarify.tsx] but Aurora-Glass
 * styled, voice/TTS deferred, manage-assignees moved to TaskDetail.
 *
 * Workflow:
 *   1. Load requirement + history
 *   2. If draft/clarifying and no history → auto-start first AI turn (SSE)
 *   3. AI streams "thinking" / "text" / parsed event (ask_choice | ask_open | summarize)
 *   4. User answers questions; each answer triggers next AI turn
 *   5. When AI emits `summarize`, backend auto-transitions clarifying → summary_ready
 *   6. SummaryCard renders → user confirms DDL → invokes submit OR auto_process
 */
function parsedFromHistory(msg: StoredChatMessage | undefined): AgentParsed | null {
  if (!msg || msg.role !== "assistant" || !msg.content || typeof msg.content !== "object") return null;
  const c: any = msg.content;
  if (msg.kind === "question_choice" && c.action === "ask_choice") return c as AgentParsed;
  if (msg.kind === "question_open" && c.action === "ask_open") return c as AgentParsed;
  if (msg.kind === "summary" && c.action === "summarize") return c as AgentParsed;
  return null;
}

function parsedKey(parsed: AgentParsed): string {
  return `${parsed.action}:${JSON.stringify(parsed.payload).slice(0, 160)}`;
}

export function Clarify() {
  const { id: reqId = "" } = useParams<{ id: string }>();
  const nav = useNavigate();

  const [req, setReq] = useState<Requirement | null>(null);
  const [history, setHistory] = useState<StoredChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const autoStartedRef = useRef<string | null>(null);

  // Tauri client's clientFetch handles base-URL + token. Pass to the shared
  // hook so SSE works inside the webview.
  const stream = useChatStream(reqId, clientFetch);

  const refresh = async () => {
    if (!reqId) return;
    try {
      const [r, h] = await Promise.all([
        invoke<Requirement>("get_requirement", { reqId }),
        invoke<StoredChatMessage[]>("chat_messages", { reqId }),
      ]);
      setReq(r);
      setHistory(h);
      setLoaded(true);
    } catch (e: any) {
      toast({ title: "加载失败", description: String(e), tone: "error" });
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [reqId]);
  useEffect(() => { autoStartedRef.current = null; }, [reqId]);
  useEffect(() => { if (stream.done) refresh(); /* eslint-disable-next-line */ }, [stream.done]);

  // Auto-start first turn if nothing in history and status is draft/clarifying.
  useEffect(() => {
    if (!req || !loaded) return;
    if (stream.running || stream.parsed) return;
    if (history.length > 0) return;
    if (req.status !== "draft" && req.status !== "clarifying") return;
    if (autoStartedRef.current === req.id) return;
    autoStartedRef.current = req.id;
    stream.run({ force_summarize: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req, loaded, history.length, stream.running, stream.parsed]);

  const answer = async (body: { selected_option_key?: string; other_text?: string; text?: string }) => {
    await invoke("post_chat_answer", { reqId, body });
    stream.reset();
    await stream.run({ force_summarize: false });
  };

  const forceSummarize = async () => {
    stream.reset();
    await stream.run({ force_summarize: true });
  };

  if (!req) {
    return <div className="flex-1 p-6 text-ink-muted">加载中…</div>;
  }

  // Pick the right thing to display: live stream's parsed > stored summary
  // (when status=summary_ready) > most recent assistant message.
  const latestHistoryMsg = history[history.length - 1];
  const latestHistoryParsed = parsedFromHistory(latestHistoryMsg);
  const storedSummary = [...history].reverse()
    .find((m) => m.kind === "summary" && (m.content as any)?.action === "summarize")
    ?.content as AgentParsed | undefined;
  const canActInClarify = req.status === "draft" || req.status === "clarifying" || req.status === "summary_ready";
  const restoredParsed = !stream.running && canActInClarify ? latestHistoryParsed : null;
  const activeParsed = stream.parsed ??
    (req.status === "summary_ready" && storedSummary?.action === "summarize" ? storedSummary : restoredParsed);
  const showingSummary = activeParsed?.action === "summarize";
  const activeKey = activeParsed ? parsedKey(activeParsed) : null;
  const canRequestSummary = req.status === "draft" || req.status === "clarifying";

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-3xl mx-auto">
        <button
          onClick={() => nav(`/r/${reqId}`)}
          className="inline-flex items-center gap-1.5 text-body-sm text-ink-muted hover:text-ink mb-4"
        >
          <ArrowLeft className="h-4 w-4" /> 返回需求
        </button>

        <Card variant="glass-strong" padding="md" className="mb-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-mono text-caption text-ink-faint">{req.code}</div>
              <h1 className="text-h2 text-ink mt-1 break-words">{req.title || "(澄清中)"}</h1>
              <div className="mt-2"><StatusBadge status={req.status} size="sm" /></div>
            </div>
            {canRequestSummary && !stream.running && (
              <Button variant="ghost" size="sm" onClick={forceSummarize} leftIcon={<FileText className="h-3.5 w-3.5" />}>
                够了，直接总结
              </Button>
            )}
          </div>
        </Card>

        {/* Chat transcript */}
        <div className="space-y-3 mb-3">
          {history.map((m) => {
            const mp = parsedFromHistory(m);
            const isActive = activeKey && mp && parsedKey(mp) === activeKey;
            if (isActive) return null;
            if (showingSummary && m.kind === "summary") return null;
            return <Bubble key={m.id} msg={m} />;
          })}

          {!activeParsed && (stream.running || stream.thinking || stream.text) && (
            <LiveBubble thinking={stream.thinking} text={stream.text} done={!stream.running && !stream.parsed} />
          )}

          {activeParsed && !stream.running && (
            activeParsed.action === "summarize"
              ? <SummaryCard
                  key={parsedKey(activeParsed)}
                  payload={activeParsed.payload}
                  dueAt={req.due_at}
                  reqId={reqId}
                  onDone={() => nav(`/r/${reqId}`)}
                />
              : <QuestionCard key={parsedKey(activeParsed)} parsed={activeParsed} onAnswer={answer} />
          )}

          {stream.error && (
            <div className="glass-quiet p-3 text-body-sm text-error border border-error/30">
              <AlertCircle className="inline h-4 w-4 mr-1.5" /> {stream.error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- atoms ----------

function Bubble({ msg }: { msg: StoredChatMessage }) {
  const isUser = msg.role === "user";
  const c: any = msg.content;
  const text = (() => {
    if (msg.kind === "summary") return c?.payload?.summary_md ?? "";
    if (msg.kind === "question_choice") return c?.payload?.question ?? "";
    if (msg.kind === "question_open") return c?.payload?.question ?? "";
    if (msg.selected_option_key) {
      return `[选择] ${msg.selected_option_key}${msg.user_other_text ? `\n[补充] ${msg.user_other_text}` : ""}`;
    }
    if (typeof c?.text === "string") return c.text;
    return JSON.stringify(c);
  })();

  return (
    <div className={`flex items-end gap-2 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <div className="shrink-0 grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-[#6B5BFF] to-[#FF6E8E] text-white shadow-2">
          <Bot className="h-4 w-4" />
        </div>
      )}
      <div
        className={`max-w-[min(86%,640px)] whitespace-pre-wrap px-4 py-3 text-body-sm leading-relaxed transition ${
          isUser
            ? "rounded-md rounded-br-sm bg-accent text-white shadow-1"
            : "rounded-md rounded-bl-sm bg-accent-2-soft text-ink border border-accent-2/20"
        }`}
      >
        {text}
      </div>
    </div>
  );
}

function LiveBubble({ thinking, text, done }: { thinking: string; text: string; done: boolean }) {
  return (
    <Card variant="glass-quiet" padding="md">
      {thinking && (
        <details className="mb-2">
          <summary className="cursor-pointer text-caption text-ink-muted font-medium">
            <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />
            AI 助理正在思考…
          </summary>
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-sm glass-sunken p-3 text-caption text-ink-muted">{thinking}</pre>
        </details>
      )}
      {!done && !text && !thinking && (
        <div className="text-body-sm text-ink-faint inline-flex items-center gap-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 让我想一下…
        </div>
      )}
      {text && <pre className="whitespace-pre-wrap text-caption text-ink-muted">{text}</pre>}
    </Card>
  );
}

function QuestionCard({ parsed, onAnswer }: { parsed: AgentParsed; onAnswer: (b: any) => Promise<void> }) {
  const [other, setOther] = useState("");
  const [open, setOpen] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (body: any) => {
    if (busy) return;
    setBusy(true); setErr(null);
    try { await onAnswer(body); }
    catch (e: any) { setErr(String(e)); }
    finally { setBusy(false); }
  };

  if (parsed.action === "ask_choice") {
    const p = parsed.payload;
    return (
      <Card variant="glass" padding="lg">
        <div className="flex items-start justify-between gap-2">
          <div className="text-h4 text-ink leading-7">{p.question}</div>
          <SpeakButton text={p.question} autoTriggerKey={p.question} />
        </div>
        <div className="mt-4 space-y-2">
          {p.options.map((o) => (
            <button
              key={o.key}
              className="w-full glass-quiet rounded-sm px-4 py-3 text-left text-body-sm text-ink hover:bg-accent-soft hover:border-accent/40 transition disabled:opacity-50"
              disabled={busy}
              onClick={() => submit({ selected_option_key: o.key })}
            >
              {o.label}
            </button>
          ))}
        </div>
        {p.allow_other && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1">
              <div className="text-eyebrow text-ink-muted">其他</div>
              <VoiceButton onText={(t) => setOther((o) => (o.trim() ? `${o.trim()} ${t}` : t))} />
            </div>
            <div className="flex gap-2">
              <Input
                placeholder="写一个自己的答案"
                value={other}
                onChange={(e) => setOther(e.target.value)}
                containerClassName="flex-1"
              />
              <Button
                variant="accent"
                disabled={busy || !other.trim()}
                loading={busy}
                leftIcon={<Send className="h-4 w-4" />}
                onClick={() => submit({ selected_option_key: "other", other_text: other.trim() })}
              >
                提交
              </Button>
            </div>
          </div>
        )}
        {err && <div className="mt-3 text-body-sm text-error"><AlertCircle className="inline h-4 w-4 mr-1.5" />{err}</div>}
      </Card>
    );
  }

  if (parsed.action === "ask_open") {
    const p = parsed.payload;
    return (
      <Card variant="glass" padding="lg">
        <div className="flex items-start justify-between gap-2">
          <div className="text-h4 text-ink leading-7">{p.question}</div>
          <SpeakButton text={p.question} autoTriggerKey={p.question} />
        </div>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <Textarea
            autosize
            rows={2}
            placeholder={p.placeholder || ""}
            value={open}
            onChange={(e) => setOpen(e.target.value)}
            className="flex-1"
          />
          <Button
            variant="accent"
            disabled={busy || !open.trim()}
            loading={busy}
            leftIcon={<Send className="h-4 w-4" />}
            onClick={() => submit({ text: open.trim() })}
          >
            发送
          </Button>
        </div>
        <div className="mt-2">
          <VoiceButton onText={(t) => setOpen((o) => (o.trim() ? `${o.trim()} ${t}` : t))} />
        </div>
        {err && <div className="mt-3 text-body-sm text-error"><AlertCircle className="inline h-4 w-4 mr-1.5" />{err}</div>}
      </Card>
    );
  }

  return null;
}

function toLocalInput(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function SummaryCard({
  payload,
  dueAt,
  reqId,
  onDone,
}: {
  payload: SummarizePayload;
  dueAt?: string | null;
  reqId: string;
  onDone: () => void;
}) {
  const [tryAi, setTryAi] = useState<boolean | null>(null);
  const [ddl, setDdl] = useState(toLocalInput(dueAt));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const recommended = !!payload.ai_doable;
  const finalTryAi = tryAi === null ? recommended : tryAi;

  const deliver = async () => {
    setErr(null);
    if (!ddl) { setErr("请先填截止时间"); return; }
    setBusy(true);
    try {
      // 1. Confirm/update due date
      await invoke("patch_schedule", { reqId, body: { start_at: null, due_at: new Date(ddl).toISOString() } });
      // 2. submit OR auto_process
      if (finalTryAi) {
        await invoke("auto_process", { reqId });
        toast({ title: "AI 助理已开始处理", description: "完成后你会收到通知", tone: "accent" });
      } else {
        await invoke("submit_requirement", { reqId });
        toast({ title: "已投递", description: "等接单人接走", tone: "success" });
      }
      onDone();
    } catch (e: any) {
      setErr(String(e));
    } finally { setBusy(false); }
  };

  return (
    <Card variant="glass-strong" padding="lg">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 mb-2">
            <Badge tone="success" size="xs">最终需求</Badge>
            {payload.complexity && (
              <Badge
                tone={payload.complexity === "low" ? "success" : payload.complexity === "medium" ? "warn" : "error"}
                size="xs"
              >
                复杂度 · {payload.complexity}
              </Badge>
            )}
            {payload.ai_doable && <Badge tone="accent" size="xs"><Bot className="h-3 w-3" /> AI 可处理</Badge>}
          </div>
          <h2 className="text-h2 text-ink break-words">{payload.title}</h2>
          {payload.ai_reason && <p className="mt-2 text-caption text-ink-muted">AI 判断：{payload.ai_reason}</p>}
        </div>
      </div>

      <pre className="mt-4 overflow-auto whitespace-pre-wrap rounded-sm glass-sunken p-4 text-body-sm leading-relaxed text-ink-soft">{payload.summary_md}</pre>

      <div className="glass-sunken p-3 mt-4">
        <label className="block">
          <span className="flex items-center gap-1.5 text-body-sm text-ink font-medium">
            <CalendarClock className="h-4 w-4 text-ink-muted" />
            投递 DDL
          </span>
          <Input
            type="datetime-local"
            value={ddl}
            onChange={(e) => setDdl(e.target.value)}
            containerClassName="mt-2"
          />
        </label>
      </div>

      <div className="mt-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <label className="flex items-center gap-2 text-body-sm text-ink-soft">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={finalTryAi}
            onChange={(e) => setTryAi(e.target.checked)}
          />
          <span>让 AI 助理先试一遍（失败会自动转给人）
            {recommended && tryAi === null && <span className="text-accent"> · 建议</span>}
          </span>
        </label>
        <Button
          variant="accent"
          loading={busy}
          leftIcon={finalTryAi ? <Bot className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
          onClick={deliver}
        >
          {finalTryAi ? "让 AI 助理先试" : "投递给负责人"}
        </Button>
      </div>

      {err && <div className="mt-3 text-body-sm text-error"><AlertCircle className="inline h-4 w-4 mr-1.5" />{err}</div>}
    </Card>
  );
}
