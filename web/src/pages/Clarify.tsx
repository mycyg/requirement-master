import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Bot,
  CalendarClock,
  CheckCircle2,
  FileText,
  Paperclip,
  Save,
  Send,
  Settings2,
  Star,
  Users,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { AssigneeSelector } from "@/components/AssigneeSelector";
import { StatusBadge } from "@/components/StatusBadge";
import { useChatStream } from "@/hooks/useChatStream";
import { VoiceButton } from "@/components/VoiceButton";
import { SpeakButton } from "@/components/SpeakButton";
import type { AgentParsed, Attachment, Identity, Requirement, StoredChatMessage } from "@/lib/types";

function speakableText(parsed: AgentParsed): string {
  if (parsed.action === "ask_choice") {
    const opts = parsed.payload.options.map((o, i) => `${i + 1}. ${o.label}`).join("。");
    return `${parsed.payload.question}。可选：${opts}`;
  }
  if (parsed.action === "ask_open") return parsed.payload.question;
  if (parsed.action === "summarize") {
    // speak only the first paragraph + title to keep audio short
    const md = parsed.payload.summary_md || "";
    const firstPara = md.split("\n\n").slice(0, 2).join("\n\n");
    return `已整理需求：${parsed.payload.title}。${firstPara.replace(/[#*`>\-]/g, "")}`;
  }
  return "";
}

function parsedFromHistory(msg: StoredChatMessage | undefined): AgentParsed | null {
  if (!msg || msg.role !== "assistant" || !msg.content || typeof msg.content !== "object") return null;
  if (msg.kind === "question_choice" && msg.content.action === "ask_choice") return msg.content as AgentParsed;
  if (msg.kind === "question_open" && msg.content.action === "ask_open") return msg.content as AgentParsed;
  if (msg.kind === "summary" && msg.content.action === "summarize") return msg.content as AgentParsed;
  return null;
}

function parsedKey(parsed: AgentParsed): string {
  return `${parsed.action}:${JSON.stringify(parsed.payload).slice(0, 160)}`;
}

export function Clarify() {
  const { id: reqId } = useParams<{ id: string }>();
  const nav = useNavigate();

  const [req, setReq] = useState<Requirement | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [history, setHistory] = useState<StoredChatMessage[]>([]);
  const [me, setMe] = useState<Identity | null>(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [manageLeadUserId, setManageLeadUserId] = useState<string | null>(null);
  const [manageCollaboratorUserIds, setManageCollaboratorUserIds] = useState<string[]>([]);
  const [manageBusy, setManageBusy] = useState(false);
  const [manageErr, setManageErr] = useState<string | null>(null);
  const [loadedReqId, setLoadedReqId] = useState<string | null>(null);
  const autoStartedRef = useRef<string | null>(null);
  const stream = useChatStream(reqId || "");

  const refresh = async () => {
    if (!reqId) return;
    setLoadedReqId(null);
    const [nextReq, nextAttachments, nextHistory] = await Promise.all([
      api.getRequirement(reqId),
      api.listAttachments(reqId),
      api.listChatMessages(reqId),
    ]);
    setReq(nextReq);
    setAttachments(nextAttachments);
    setHistory(nextHistory);
    setLoadedReqId(reqId);
  };

  useEffect(() => { refresh(); }, [reqId]);
  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => { autoStartedRef.current = null; }, [reqId]);

  // when a stream completes with a `done` event we want to refresh
  useEffect(() => {
    if (stream.done) refresh();
  }, [stream.done]);

  // auto-start the first turn if no assistant messages yet
  useEffect(() => {
    if (!req || stream.running || stream.parsed) return;
    if (loadedReqId !== req.id) return;
    if (history.length === 0 && (req.status === "draft" || req.status === "clarifying")) {
      if (autoStartedRef.current === req.id) return;
      autoStartedRef.current = req.id;
      stream.run({ force_summarize: false });
    }
  }, [req, loadedReqId, history.length, stream.running, stream.parsed]);

  if (!reqId || !req) return <main className="narrow-container text-stone-500">加载中...</main>;

  const latestHistoryMsg = history[history.length - 1];
  const latestHistoryParsed = parsedFromHistory(latestHistoryMsg);
  const storedSummary = [...history]
    .reverse()
    .find((m) => m.kind === "summary" && m.content?.action === "summarize")
    ?.content as AgentParsed | undefined;
  const canActInClarify = req.status === "draft" || req.status === "clarifying" || req.status === "summary_ready";
  const restoredParsed = !stream.running && canActInClarify ? latestHistoryParsed : null;
  const activeParsed = stream.parsed ??
    (req.status === "summary_ready" && storedSummary?.action === "summarize" ? storedSummary : restoredParsed);
  const showingSummaryCard = activeParsed?.action === "summarize";
  const activeParsedKey = activeParsed ? parsedKey(activeParsed) : null;
  const isFinal = req.status === "ready" || req.status === "summary_ready" || showingSummaryCard;
  const canRequestSummary = req.status === "draft" || req.status === "clarifying";
  const assignees = req.assignees ?? [];
  const lead = assignees.find((a) => a.role === "lead");
  const selectedUsers = assignees.map((a) => ({ id: a.user_id, nickname: a.nickname }));
  const canManageAssignees = !!me && me.nickname === req.submitter_nickname && canActInClarify;

  const openManage = () => {
    setManageLeadUserId(lead?.user_id ?? null);
    setManageCollaboratorUserIds(assignees.filter((a) => a.role === "collaborator").map((a) => a.user_id));
    setManageOpen(true);
    setManageErr(null);
  };

  const saveAssignees = async () => {
    if (!reqId) return;
    setManageBusy(true);
    setManageErr(null);
    try {
      await api.updateAssignees(reqId, {
        lead_user_id: manageLeadUserId,
        collaborator_user_ids: manageCollaboratorUserIds,
      });
      setManageOpen(false);
      await refresh();
    } catch (e: any) {
      setManageErr(String(e));
    } finally {
      setManageBusy(false);
    }
  };

  const answer = async (body: { selected_option_key?: string; other_text?: string; text?: string }) => {
    await api.postAnswer(reqId, body);
    stream.reset();
    await stream.run({ force_summarize: false });
  };

  return (
    <main className="app-container grid grid-cols-1 gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
      {/* left: attachments + meta */}
      <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
        <Link to={`/p/${req.project_id}`} className="link-subtle">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          项目
        </Link>
        <div className="paper-surface p-4">
          <div className="font-mono text-xs text-stone-500">{req.code}</div>
          <div className="mt-1 break-words text-lg font-semibold text-stone-950">{req.title || "(澄清中)"}</div>
          <div className="mt-3">
            <StatusBadge status={req.status} />
          </div>
        </div>
        <div className="paper-surface p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">
              <Users className="h-4 w-4" aria-hidden="true" />
              接单人
            </div>
            {canManageAssignees && !manageOpen && (
              <button className="button-ghost min-h-8 px-2 py-1 text-xs" onClick={openManage}>
                <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
                管理
              </button>
            )}
          </div>
          {!manageOpen && (
            <div className="mt-3 flex flex-wrap gap-2">
              {assignees.length === 0 ? (
                <span className="pill border-[#e0c895] bg-[#fff7e2] text-[#8a5d10]">公开池</span>
              ) : assignees.map((a) => (
                <span
                  key={a.user_id}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
                    a.role === "lead"
                      ? "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]"
                      : "border-stone-200 bg-[#fffdf8] text-stone-600"
                  }`}
                >
                  {a.role === "lead" && <Star className="h-3.5 w-3.5" aria-hidden="true" />}
                  {a.nickname}
                </span>
              ))}
            </div>
          )}
          {manageOpen && (
            <div className="mt-3 space-y-3">
              <AssigneeSelector
                leadUserId={manageLeadUserId}
                collaboratorUserIds={manageCollaboratorUserIds}
                selectedUsers={selectedUsers}
                surface={false}
                onChange={(next) => {
                  setManageLeadUserId(next.leadUserId);
                  setManageCollaboratorUserIds(next.collaboratorUserIds);
                }}
              />
              <div className="flex gap-2">
                <button className="button-secondary min-h-9 flex-1 px-3 py-1.5 text-xs" disabled={manageBusy} onClick={() => setManageOpen(false)}>
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                  取消
                </button>
                <button className="button-primary min-h-9 flex-1 px-3 py-1.5 text-xs" disabled={manageBusy} onClick={saveAssignees}>
                  <Save className="h-3.5 w-3.5" aria-hidden="true" />
                  {manageBusy ? "保存中..." : "保存"}
                </button>
              </div>
              {manageErr && <p className="text-xs text-red-700">{manageErr}</p>}
            </div>
          )}
        </div>
        <div className="paper-surface p-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">
            <Paperclip className="h-4 w-4" aria-hidden="true" />
            附件
          </div>
          <ul className="mt-2 space-y-1 text-sm">
            {attachments.length === 0 && <li className="text-stone-400">（无）</li>}
            {attachments.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">{a.filename}</span>
                {a.has_parsed_text && <span className="pill shrink-0 border-[#bdd2b7] bg-[#f1f7ed] px-2 py-0.5 text-[#4e7146]">已解析</span>}
              </li>
            ))}
          </ul>
        </div>
        {!isFinal && canRequestSummary && (
          <button
            className="button-accent w-full"
            disabled={stream.running}
            onClick={() => { stream.reset(); stream.run({ force_summarize: true }); }}
          >
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            够了，开始整理
          </button>
        )}
      </aside>

      {/* right: chat thread */}
      <section className="min-w-0 space-y-4">
        {history.map((m) => {
          const msgParsed = parsedFromHistory(m);
          const isActiveHistoryMsg = activeParsedKey && msgParsed && parsedKey(msgParsed) === activeParsedKey;
          return isActiveHistoryMsg || (showingSummaryCard && m.kind === "summary") ? null : <Bubble key={m.id} msg={m} />;
        })}

        {/* live stream */}
        {!activeParsed && (stream.running || stream.thinking || stream.text) && (
          <LiveBubble thinking={stream.thinking} text={stream.text} done={!stream.running && !stream.parsed} />
        )}

        {/* current parsed question / summary */}
        {activeParsed && !stream.running && (
          activeParsed.action === "summarize"
            ? <SummaryCard
                key={parsedKey(activeParsed)}
                parsed={activeParsed}
                dueAt={req.due_at}
                onSchedule={async (dueAt) => {
                  await api.updateRequirementSchedule(reqId, {
                    start_at: req.start_at,
                    due_at: dueAt,
                  });
                  await refresh();
                }}
                onDeliver={async ({ tryAi }) => {
                  if (tryAi) {
                    await api.autoProcess(reqId);
                  } else {
                    await api.submitRequirement(reqId);
                  }
                  nav(`/r/${reqId}`);
                }}
              />
            : <QuestionCard key={parsedKey(activeParsed)} parsed={activeParsed} onAnswer={answer} />
        )}

        {/* hidden autoplay driver — re-fires whenever a new parsed arrives */}
        {stream.parsed && !stream.running && (
          <div className="hidden">
            <SpeakButton
              text={speakableText(stream.parsed)}
              autoTriggerKey={JSON.stringify(stream.parsed.payload).slice(0, 64)}
            />
          </div>
        )}

        {stream.error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {stream.error}
          </div>
        )}
      </section>
    </main>
  );
}

// ---------- bubbles ----------

function Bubble({ msg }: { msg: StoredChatMessage }) {
  const isUser = msg.role === "user";
  const text = (() => {
    if (msg.kind === "summary") return msg.content?.payload?.summary_md ?? "";
    if (msg.kind === "question_choice") return msg.content?.payload?.question ?? "";
    if (msg.kind === "question_open") return msg.content?.payload?.question ?? "";
    if (msg.selected_option_key) {
      return `[选择] ${msg.selected_option_key}${msg.user_other_text ? `\n[补充] ${msg.user_other_text}` : ""}`;
    }
    if (typeof msg.content?.text === "string") return msg.content.text;
    return JSON.stringify(msg.content);
  })();

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[min(86%,760px)] whitespace-pre-wrap rounded-lg px-4 py-3 text-sm leading-relaxed shadow-sm ${
        isUser ? "bg-stone-950 text-[#fffdf8]" : "border border-stone-200 bg-[#fffdf8] text-stone-900"
      }`}>
        {text}
        {!isUser && text && (
          <div className="mt-2 flex justify-end">
            <SpeakButton text={text} size="xs" />
          </div>
        )}
      </div>
    </div>
  );
}

function LiveBubble({ thinking, text, done }: { thinking: string; text: string; done: boolean }) {
  return (
    <div className="paper-surface p-4">
      {thinking && (
        <details className="mb-2">
          <summary className="cursor-pointer text-xs font-semibold text-stone-500">
            <Bot className="mr-1.5 inline h-3.5 w-3.5" aria-hidden="true" />
            正在整理上下文...
          </summary>
          <pre className="scrollbar-thin-warm mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-3 text-xs text-stone-600">{thinking}</pre>
        </details>
      )}
      {!done && !text && !thinking && <div className="text-sm text-stone-400">等待回应...</div>}
      {text && <pre className="whitespace-pre-wrap text-xs text-stone-500">{text}</pre>}
    </div>
  );
}

function QuestionCard({ parsed, onAnswer }: { parsed: AgentParsed; onAnswer: (b: any) => Promise<void> }) {
  const [other, setOther] = useState("");
  const [open, setOpen] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (body: any) => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await onAnswer(body);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (parsed.action === "ask_choice") {
    const p = parsed.payload;
    return (
      <div className="paper-surface p-5">
        <div className="flex items-start gap-2">
          <div className="flex-1 text-base font-semibold leading-7 text-stone-950">{p.question}</div>
          <SpeakButton text={p.question} size="xs" />
        </div>
        <div className="mt-4 space-y-2">
          {p.options.map((o) => (
            <button
              key={o.key}
              className="w-full rounded-lg border border-stone-200 bg-[#fffdf8] px-4 py-3 text-left text-sm text-stone-800 transition hover:border-stone-900 hover:bg-white"
              disabled={busy}
              onClick={() => submit({ selected_option_key: o.key })}
            >
              {o.label}
            </button>
          ))}
        </div>
        {p.allow_other && (
          <div className="mt-4">
            <div className="eyebrow">其他</div>
            <div className="mt-2 flex flex-col gap-2 md:flex-row">
              <input
                className="field flex-1"
                placeholder="写一个自己的答案"
                value={other}
                onChange={(e) => setOther(e.target.value)}
              />
              <VoiceButton onText={(t) => setOther((s) => (s ? s + " " : "") + t)} />
              <button
                className="button-primary"
                disabled={busy || !other.trim()}
                onClick={() => submit({ selected_option_key: "other", other_text: other.trim() })}
              >
                <Send className="h-4 w-4" aria-hidden="true" />
                {busy ? "提交中..." : "提交"}
              </button>
            </div>
          </div>
        )}
        {err && <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
      </div>
    );
  }

  if (parsed.action === "ask_open") {
    const p = parsed.payload;
    return (
      <div className="paper-surface p-5">
        <div className="flex items-start gap-2">
          <div className="flex-1 text-base font-semibold leading-7 text-stone-950">{p.question}</div>
          <SpeakButton text={p.question} size="xs" />
        </div>
        <div className="mt-3 flex flex-col gap-3 md:flex-row">
          <textarea
            className="textarea-field min-h-24 flex-1"
            rows={2}
            placeholder={p.placeholder || ""}
            value={open}
            onChange={(e) => setOpen(e.target.value)}
          />
          <div className="flex flex-col gap-2 sm:flex-row md:w-32 md:flex-col">
            <VoiceButton onText={(t) => setOpen((s) => (s ? s + " " : "") + t)} />
            <button
              className="button-primary"
              disabled={busy || !open.trim()}
              onClick={() => submit({ text: open.trim() })}
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              {busy ? "发送中..." : "发送"}
            </button>
          </div>
        </div>
        {err && <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
      </div>
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
  parsed,
  dueAt,
  onSchedule,
  onDeliver,
}: {
  parsed: AgentParsed;
  dueAt?: string | null;
  onSchedule: (dueAt: string) => Promise<void>;
  onDeliver: (o: { tryAi: boolean }) => Promise<void>;
}) {
  const [tryAi, setTryAi] = useState<boolean | null>(null);
  const [ddl, setDdl] = useState(toLocalInput(dueAt));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (parsed.action !== "summarize") return null;
  const p = parsed.payload;
  const recommended = !!p.ai_doable;
  const finalTryAi = tryAi === null ? recommended : tryAi;

  return (
    <div className="paper-surface p-5 sm:p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em]">
            <span className="text-[#4e7146]">最终需求</span>
            {p.complexity && (
              <span className={`rounded-full border px-2 py-0.5 text-[10px] ${
                p.complexity === "low" ? "border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]"
                : p.complexity === "medium" ? "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]"
                : "border-[#e0b8ad] bg-[#fff0ec] text-[#9f4129]"
              }`}>
                复杂度 · {p.complexity}
              </span>
            )}
            {p.ai_doable && (
              <span className="inline-flex items-center gap-1 rounded-full border border-[#cbb8d8] bg-[#f5eef8] px-2 py-0.5 text-[10px] text-[#684b7a]">
                <Bot className="h-3 w-3" aria-hidden="true" />
                AI 可处理
              </span>
            )}
          </div>
          <h2 className="mt-2 break-words text-2xl font-semibold text-stone-950">{p.title}</h2>
          {p.ai_reason && <p className="mt-2 text-xs leading-5 text-stone-500">AI 判断：{p.ai_reason}</p>}
        </div>
        <SpeakButton text={`${p.title}。${p.summary_md.split("\n\n").slice(0, 2).join("\n\n").replace(/[#*`>\-]/g, "")}`} />
      </div>

      <pre className="mt-5 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-4 text-sm leading-relaxed text-stone-700">{p.summary_md}</pre>

      <div className="paper-panel mt-5 p-4">
        <label className="block">
          <span className="flex items-center gap-2 text-sm font-semibold text-stone-900">
            <CalendarClock className="h-4 w-4 text-stone-500" aria-hidden="true" />
            投递 DDL
          </span>
          <input
            className="field mt-2"
            type="datetime-local"
            value={ddl}
            onChange={(e) => setDdl(e.target.value)}
          />
        </label>
        <p className="mt-2 text-xs text-stone-500">没有 DDL 不能投递，防止需求变成一张长期饭票。</p>
      </div>

      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <label className="flex items-center gap-2 text-sm text-stone-700">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[#684b7a]"
            checked={finalTryAi}
            onChange={(e) => setTryAi(e.target.checked)}
          />
          <span>让 AI 先试一下（失败自动转人工）{recommended && tryAi === null && <span className="text-[#684b7a]"> · AI 推荐</span>}</span>
        </label>
        <button
          className={`button w-full sm:w-auto ${
            finalTryAi ? "border-[#684b7a] bg-[#684b7a] text-white hover:bg-[#563d65]" : "border-[#4e7146] bg-[#5f8358] text-white hover:bg-[#4e7146]"
          }`}
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setErr(null);
            try {
              if (!ddl) {
                setErr("先填 DDL，再投递。");
                return;
              }
              await onSchedule(new Date(ddl).toISOString());
              await onDeliver({ tryAi: finalTryAi });
            } catch (e: any) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {finalTryAi ? <Bot className="h-4 w-4" aria-hidden="true" /> : <FileText className="h-4 w-4" aria-hidden="true" />}
          {busy ? "处理中..." : finalTryAi ? "投递并交给 AI" : "投递给我（人工处理）"}
        </button>
      </div>
      {err && <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
    </div>
  );
}
