import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useReqStream } from "@/hooks/useReqStream";
import { AILiveView } from "@/components/AILiveView";
import { ActivityTimeline } from "@/components/ActivityTimeline";
import { CommentsPanel } from "@/components/CommentsPanel";
import { DeliverablesTab } from "@/components/DeliverablesTab";
import { StatusBadge } from "@/components/StatusBadge";
import { SpeakButton } from "@/components/SpeakButton";
import type { Attachment, Requirement } from "@/lib/types";

type Tab = "overview" | "chat" | "attachments" | "deliveries" | "comments" | "activity";

export function RequirementDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [req, setReq] = useState<Requirement | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const { events, latestStatus } = useReqStream(id);

  const refresh = async () => {
    if (!id) return;
    const r = await api.getRequirement(id);
    setReq(r);
    setAttachments(await api.listAttachments(id));
  };

  useEffect(() => { refresh(); }, [id]);
  // Reload from server when SSE says status changed
  useEffect(() => { if (latestStatus) refresh(); }, [latestStatus]);

  if (!id || !req) return <main className="p-12">加载中…</main>;

  const currentStatus = latestStatus || req.status;

  // If still clarifying, redirect to clarify page
  if (currentStatus === "draft" || currentStatus === "clarifying") {
    return (
      <main className="mx-auto max-w-4xl p-12 text-center">
        <p className="text-slate-600">这条需求还在澄清中，自动跳转到对话页…</p>
        <button className="mt-4 text-blue-600 underline" onClick={() => nav(`/r/${id}/clarify`)}>立即前往</button>
      </main>
    );
  }

  const claim = async () => {
    await api.claimRequirement(req.id);
    refresh();
  };

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <Link to={`/p/${req.project_id}`} className="text-sm text-slate-500 hover:underline">← {req.project_slug}</Link>

      <header className="mt-4 flex items-start justify-between">
        <div>
          <div className="font-mono text-xs text-slate-500">{req.code}</div>
          <h1 className="mt-1 text-3xl font-bold">{req.title || "(无标题)"}</h1>
          <div className="mt-2 flex items-center gap-3 text-xs text-slate-500">
            <StatusBadge status={currentStatus} />
            <span>by <b>{req.submitter_nickname}</b></span>
            <span>·</span>
            <span>{new Date(req.created_at + "Z").toLocaleString("zh-CN")}</span>
          </div>
        </div>
        <div className="flex gap-2">
          {currentStatus === "ready" && (
            <button className="rounded-lg bg-cyan-600 px-4 py-2 text-sm text-white" onClick={claim}>
              🙋 接单
            </button>
          )}
          {req.summary_md && (
            <SpeakButton
              text={`${req.title}。${req.summary_md.split("\n\n").slice(0, 2).join("\n\n").replace(/[#*`>\-]/g, "")}`}
            />
          )}
        </div>
      </header>

      {/* AI live view banner if processing */}
      {currentStatus === "ai_processing" && (
        <div className="mt-6">
          <AILiveView events={events} />
        </div>
      )}

      {/* tabs */}
      <nav className="mt-8 flex gap-1 border-b border-slate-200 text-sm">
        {[
          ["overview", "概览"],
          ["chat", "对话历史"],
          ["attachments", `附件 (${attachments.length})`],
          ["deliveries", "交付物"],
          ["comments", "评论"],
          ["activity", "活动"],
        ].map(([k, label]) => (
          <button
            key={k}
            className={`-mb-px border-b-2 px-4 py-2 ${
              tab === k ? "border-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-900"
            }`}
            onClick={() => setTab(k as Tab)}
          >
            {label}
          </button>
        ))}
      </nav>

      <section className="mt-6">
        {tab === "overview" && (
          <div className="rounded-xl bg-white p-6 ring-1 ring-slate-200">
            <h3 className="text-sm font-medium text-emerald-600">需求描述</h3>
            <pre className="mt-3 whitespace-pre-wrap rounded bg-slate-50 p-4 text-sm leading-relaxed">{req.summary_md || req.raw_description || "(空)"}</pre>
          </div>
        )}
        {tab === "chat" && <ChatHistory reqId={id} />}
        {tab === "attachments" && (
          <ul className="divide-y rounded-lg border bg-white">
            {attachments.length === 0 && <li className="p-8 text-center text-slate-500">无附件</li>}
            {attachments.map((a) => (
              <li key={a.id} className="flex items-center justify-between px-4 py-3 text-sm">
                <span>{a.filename} <span className="ml-2 text-xs text-slate-400">{(a.size_bytes / 1024).toFixed(1)} KB</span></span>
                <a className="text-xs text-blue-600 hover:underline" href={`/api/files/${a.id}`} download>下载</a>
              </li>
            ))}
          </ul>
        )}
        {tab === "deliveries" && <DeliverablesTab req={req} onChange={refresh} />}
        {tab === "comments" && <CommentsPanel reqId={id} />}
        {tab === "activity" && <ActivityTimeline reqId={id} />}
      </section>
    </main>
  );
}

function ChatHistory({ reqId }: { reqId: string }) {
  const [msgs, setMsgs] = useState<any[]>([]);
  useEffect(() => { api.listChatMessages(reqId).then(setMsgs); }, [reqId]);
  if (msgs.length === 0) return <div className="text-slate-500">无对话</div>;
  return (
    <div className="space-y-2">
      {msgs.map((m) => {
        const isUser = m.role === "user";
        const text = (() => {
          if (m.kind === "summary") return m.content?.payload?.summary_md ?? "";
          if (m.kind === "question_choice" || m.kind === "question_open") return m.content?.payload?.question ?? "";
          if (m.selected_option_key) return `[选] ${m.selected_option_key}${m.user_other_text ? ` · ${m.user_other_text}` : ""}`;
          return typeof m.content?.text === "string" ? m.content.text : JSON.stringify(m.content);
        })();
        return (
          <div key={m.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
              isUser ? "bg-slate-900 text-white" : "bg-white ring-1 ring-slate-200"
            }`}>
              {text}
            </div>
          </div>
        );
      })}
    </div>
  );
}
