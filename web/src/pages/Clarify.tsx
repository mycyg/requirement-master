import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useChatStream } from "@/hooks/useChatStream";
import { VoiceButton } from "@/components/VoiceButton";
import { SpeakButton } from "@/components/SpeakButton";
import type { AgentParsed, Attachment, Requirement, StoredChatMessage } from "@/lib/types";

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

export function Clarify() {
  const { id: reqId } = useParams<{ id: string }>();
  const nav = useNavigate();

  const [req, setReq] = useState<Requirement | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [history, setHistory] = useState<StoredChatMessage[]>([]);
  const stream = useChatStream(reqId || "");

  const refresh = async () => {
    if (!reqId) return;
    setReq(await api.getRequirement(reqId));
    setAttachments(await api.listAttachments(reqId));
    setHistory(await api.listChatMessages(reqId));
  };

  useEffect(() => { refresh(); }, [reqId]);

  // when a stream completes with a `done` event we want to refresh
  useEffect(() => {
    if (stream.done) refresh();
  }, [stream.done]);

  // auto-start the first turn if no assistant messages yet
  useEffect(() => {
    if (!req || stream.running || stream.parsed) return;
    if (history.length === 0 && req.status !== "ready") {
      stream.run({ force_summarize: false });
    }
  }, [req, history.length]);

  if (!reqId || !req) return <main className="p-12">加载中…</main>;

  const isFinal = req.status === "ready" || stream.parsed?.action === "summarize";

  const answer = async (body: { selected_option_key?: string; other_text?: string; text?: string }) => {
    await api.postAnswer(reqId, body);
    stream.reset();
    await stream.run({ force_summarize: false });
  };

  return (
    <main className="mx-auto grid max-w-6xl grid-cols-[280px_1fr] gap-6 px-6 py-8">
      {/* left: attachments + meta */}
      <aside className="space-y-4">
        <Link to={`/p/${req.project_id}`} className="text-sm text-slate-500 hover:underline">← 项目</Link>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="font-mono text-xs text-slate-500">{req.code}</div>
          <div className="mt-1 text-lg font-semibold">{req.title || "(澄清中)"}</div>
          <div className="mt-2 text-xs text-slate-500">状态: {req.status}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-xs font-medium uppercase text-slate-500">附件</div>
          <ul className="mt-2 space-y-1 text-sm">
            {attachments.length === 0 && <li className="text-slate-400">（无）</li>}
            {attachments.map((a) => (
              <li key={a.id} className="flex items-center justify-between">
                <span className="truncate">{a.filename}</span>
                {a.has_parsed_text && <span className="ml-1 rounded bg-emerald-50 px-1 text-xs text-emerald-700">已解析</span>}
              </li>
            ))}
          </ul>
        </div>
        {!isFinal && (
          <button
            className="w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            disabled={stream.running}
            onClick={() => { stream.reset(); stream.run({ force_summarize: true }); }}
          >
            ✅ 够了，开始整理
          </button>
        )}
      </aside>

      {/* right: chat thread */}
      <section className="space-y-4">
        {history.map((m) => (
          <Bubble key={m.id} msg={m} />
        ))}

        {/* live stream */}
        {(stream.running || stream.thinking || stream.text) && (
          <LiveBubble thinking={stream.thinking} text={stream.text} done={!stream.running && !stream.parsed} />
        )}

        {/* current parsed question / summary */}
        {stream.parsed && !stream.running && (
          stream.parsed.action === "summarize"
            ? <SummaryCard
                parsed={stream.parsed}
                onDeliver={async ({ tryAi }) => {
                  if (tryAi) {
                    await api.autoProcess(reqId);
                  } else {
                    await api.submitRequirement(reqId);
                  }
                  nav(`/r/${reqId}`);
                }}
              />
            : <QuestionCard parsed={stream.parsed} onAnswer={answer} />
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
      <div className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed ${
        isUser ? "bg-slate-900 text-white" : "bg-white text-slate-900 ring-1 ring-slate-200"
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
    <div className="rounded-2xl bg-white p-4 ring-1 ring-slate-200">
      {thinking && (
        <details open className="mb-2">
          <summary className="cursor-pointer text-xs font-medium text-slate-500">💭 思考中…</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-600">{thinking}</pre>
        </details>
      )}
      {!done && !text && !thinking && <div className="text-sm text-slate-400">等待回应…</div>}
      {text && <pre className="whitespace-pre-wrap text-xs text-slate-500">{text}</pre>}
    </div>
  );
}

function QuestionCard({ parsed, onAnswer }: { parsed: AgentParsed; onAnswer: (b: any) => Promise<void> }) {
  const [other, setOther] = useState("");
  const [open, setOpen] = useState("");

  if (parsed.action === "ask_choice") {
    const p = parsed.payload;
    return (
      <div className="rounded-2xl bg-white p-5 ring-1 ring-slate-200">
        <div className="flex items-start gap-2">
          <div className="flex-1 text-base font-medium">{p.question}</div>
          <SpeakButton text={p.question} size="xs" />
        </div>
        <div className="mt-4 space-y-2">
          {p.options.map((o) => (
            <button
              key={o.key}
              className="w-full rounded-lg border border-slate-200 px-4 py-3 text-left text-sm hover:border-slate-900"
              onClick={() => onAnswer({ selected_option_key: o.key })}
            >
              {o.label}
            </button>
          ))}
        </div>
        {p.allow_other && (
          <div className="mt-4">
            <div className="text-xs font-medium uppercase text-slate-500">其他</div>
            <div className="mt-2 flex gap-2">
              <input
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="写一个自己的答案"
                value={other}
                onChange={(e) => setOther(e.target.value)}
              />
              <VoiceButton onText={(t) => setOther((s) => (s ? s + " " : "") + t)} />
              <button
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
                disabled={!other.trim()}
                onClick={() => onAnswer({ selected_option_key: "other", other_text: other.trim() })}
              >
                提交
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (parsed.action === "ask_open") {
    const p = parsed.payload;
    return (
      <div className="rounded-2xl bg-white p-5 ring-1 ring-slate-200">
        <div className="flex items-start gap-2">
          <div className="flex-1 text-base font-medium">{p.question}</div>
          <SpeakButton text={p.question} size="xs" />
        </div>
        <div className="mt-3 flex gap-2">
          <textarea
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            rows={2}
            placeholder={p.placeholder || ""}
            value={open}
            onChange={(e) => setOpen(e.target.value)}
          />
          <div className="flex flex-col gap-2">
            <VoiceButton onText={(t) => setOpen((s) => (s ? s + " " : "") + t)} />
            <button
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
              disabled={!open.trim()}
              onClick={() => onAnswer({ text: open.trim() })}
            >
              发送
            </button>
          </div>
        </div>
      </div>
    );
  }

  return null;
}

function SummaryCard({ parsed, onDeliver }: { parsed: AgentParsed; onDeliver: (o: { tryAi: boolean }) => void }) {
  const [tryAi, setTryAi] = useState<boolean | null>(null);
  if (parsed.action !== "summarize") return null;
  const p = parsed.payload;
  const recommended = !!p.ai_doable;
  const finalTryAi = tryAi === null ? recommended : tryAi;

  return (
    <div className="rounded-2xl bg-white p-6 ring-1 ring-slate-200">
      <div className="flex items-baseline justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2 text-xs font-medium uppercase">
            <span className="text-emerald-600">最终需求</span>
            {p.complexity && (
              <span className={`rounded px-2 py-0.5 text-[10px] ${
                p.complexity === "low" ? "bg-emerald-100 text-emerald-700"
                : p.complexity === "medium" ? "bg-amber-100 text-amber-700"
                : "bg-rose-100 text-rose-700"
              }`}>
                复杂度 · {p.complexity}
              </span>
            )}
            {p.ai_doable && (
              <span className="rounded bg-violet-100 px-2 py-0.5 text-[10px] text-violet-700">
                🤖 AI 可处理
              </span>
            )}
          </div>
          <h2 className="mt-1 text-2xl font-bold">{p.title}</h2>
          {p.ai_reason && <p className="mt-1 text-xs text-slate-500">AI 判断：{p.ai_reason}</p>}
        </div>
        <SpeakButton text={`${p.title}。${p.summary_md.split("\n\n").slice(0, 2).join("\n\n").replace(/[#*`>\-]/g, "")}`} />
      </div>

      <pre className="mt-5 whitespace-pre-wrap rounded-lg bg-slate-50 p-4 text-sm leading-relaxed">{p.summary_md}</pre>

      <div className="mt-5 flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-violet-600"
            checked={finalTryAi}
            onChange={(e) => setTryAi(e.target.checked)}
          />
          <span>让 AI 先试一下（失败自动转人工）{recommended && tryAi === null && <span className="text-violet-600">· AI 推荐</span>}</span>
        </label>
        <button
          className={`rounded-lg px-5 py-2 text-sm font-medium text-white ${
            finalTryAi ? "bg-violet-600 hover:bg-violet-700" : "bg-emerald-600 hover:bg-emerald-700"
          }`}
          onClick={() => onDeliver({ tryAi: finalTryAi })}
        >
          {finalTryAi ? "🤖 投递并交给 AI" : "投递给我（人工处理）"} →
        </button>
      </div>
    </div>
  );
}
