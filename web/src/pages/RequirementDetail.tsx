import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  Bot,
  ClipboardCheck,
  FileText,
  MessageSquare,
  PackageCheck,
  Paperclip,
  Play,
  UserCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
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
const DETAIL_TABS: { key: Tab; label: string; Icon: LucideIcon }[] = [
  { key: "overview", label: "概览", Icon: FileText },
  { key: "chat", label: "对话历史", Icon: Bot },
  { key: "attachments", label: "附件", Icon: Paperclip },
  { key: "deliveries", label: "交付物", Icon: PackageCheck },
  { key: "comments", label: "评论", Icon: MessageSquare },
  { key: "activity", label: "活动", Icon: Activity },
];

export function RequirementDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [req, setReq] = useState<Requirement | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const { events, latestStatus } = useReqStream(id);
  const currentStatus = latestStatus || req?.status;

  const refresh = async () => {
    if (!id) return;
    const r = await api.getRequirement(id);
    setReq(r);
    setAttachments(await api.listAttachments(id));
  };

  useEffect(() => { refresh(); }, [id]);
  // Reload from server when SSE says status changed
  useEffect(() => { if (latestStatus) refresh(); }, [latestStatus]);
  useEffect(() => {
    if (!id || (currentStatus !== "draft" && currentStatus !== "clarifying" && currentStatus !== "summary_ready")) return;
    const t = window.setTimeout(() => nav(`/r/${id}/clarify`), 900);
    return () => window.clearTimeout(t);
  }, [currentStatus, id, nav]);

  if (!id || !req || !currentStatus) return <main className="narrow-container text-stone-500">加载中...</main>;

  // If still clarifying, redirect to clarify page
  if (currentStatus === "draft" || currentStatus === "clarifying" || currentStatus === "summary_ready") {
    return (
      <main className="narrow-container text-center">
        <div className="paper-surface p-8">
          <p className="text-stone-600">这条需求还在澄清或等待确认投递，正在前往对话页...</p>
          <button className="button-primary mt-4" onClick={() => nav(`/r/${id}/clarify`)}>立即前往</button>
        </div>
      </main>
    );
  }

  const claim = async () => {
    setActionBusy(true);
    setActionErr(null);
    try {
      await api.claimRequirement(req.id);
      refresh();
    } catch (e: any) {
      setActionErr(String(e));
    } finally {
      setActionBusy(false);
    }
  };
  const startDoing = async () => {
    setActionBusy(true);
    setActionErr(null);
    try {
      await api.patchStatus(req.id, "doing");
      refresh();
    } catch (e: any) {
      setActionErr(String(e));
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <main className="narrow-container max-w-6xl">
      <Link to={`/p/${req.project_id}`} className="link-subtle">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        {req.project_slug}
      </Link>

      <header className="mt-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="font-mono text-xs text-stone-500">{req.code}</div>
          <h1 className="mt-2 break-words text-3xl font-semibold text-stone-950">{req.title || "(无标题)"}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-stone-500">
            <StatusBadge status={currentStatus} />
            <span>by <b>{req.submitter_nickname}</b></span>
            {req.claimed_by_nickname && <span>接单 <b>{req.claimed_by_nickname}</b></span>}
            <span>·</span>
            <span>{new Date(req.created_at + "Z").toLocaleString("zh-CN")}</span>
          </div>
        </div>
        <div className="flex gap-2">
          {currentStatus === "ready" && (
            <button className="button-accent" disabled={actionBusy} onClick={claim}>
              <UserCheck className="h-4 w-4" aria-hidden="true" />
              {actionBusy ? "处理中..." : "接单"}
            </button>
          )}
          {currentStatus === "claimed" && (
            <button className="button-accent" disabled={actionBusy} onClick={startDoing}>
              <Play className="h-4 w-4" aria-hidden="true" />
              {actionBusy ? "处理中..." : "开始处理"}
            </button>
          )}
          {req.summary_md && (
            <SpeakButton
              text={`${req.title}。${req.summary_md.split("\n\n").slice(0, 2).join("\n\n").replace(/[#*`>\-]/g, "")}`}
            />
          )}
        </div>
      </header>
      {actionErr && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{actionErr}</div>}

      {/* AI live view banner if processing */}
      {currentStatus === "ai_processing" && (
        <div className="mt-6">
          <AILiveView events={events} />
        </div>
      )}

      {/* tabs */}
      <nav className="scrollbar-thin-warm mt-8 flex gap-1 overflow-x-auto border-b border-stone-200 text-sm">
        {DETAIL_TABS.map(({ key, label, Icon }) => (
          <button
            key={key}
            className={`tab-button -mb-px shrink-0 ${
              tab === key ? "border-stone-950 text-stone-950" : "border-transparent text-stone-500 hover:text-stone-900"
            }`}
            onClick={() => setTab(key)}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            {key === "attachments" ? `${label} (${attachments.length})` : label}
          </button>
        ))}
      </nav>

      <section className="mt-6">
        {tab === "overview" && (
          <div className="paper-surface p-6">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-[#4e7146]">
              <ClipboardCheck className="h-4 w-4" aria-hidden="true" />
              需求描述
            </h3>
            <pre className="mt-3 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-4 text-sm leading-relaxed text-stone-700">{req.summary_md || req.raw_description || "(空)"}</pre>
          </div>
        )}
        {tab === "chat" && <ChatHistory reqId={id} />}
        {tab === "attachments" && (
          <ul className="paper-surface divide-y divide-stone-200/80 overflow-hidden">
            {attachments.length === 0 && <li className="empty-state m-4">无附件</li>}
            {attachments.map((a) => (
              <li key={a.id} className="flex flex-col gap-2 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                <span className="min-w-0 break-all">{a.filename} <span className="ml-2 text-xs text-stone-400">{(a.size_bytes / 1024).toFixed(1)} KB</span></span>
                <a className="link-subtle text-xs text-[#405f78]" href={`/api/files/${a.id}`} download>下载</a>
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
  if (msgs.length === 0) return <div className="empty-state">无对话</div>;
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
            <div className={`max-w-[min(86%,760px)] whitespace-pre-wrap rounded-lg px-4 py-3 text-sm leading-6 shadow-sm ${
              isUser ? "bg-stone-950 text-[#fffdf8]" : "border border-stone-200 bg-[#fffdf8] text-stone-900"
            }`}>
              {text}
            </div>
          </div>
        );
      })}
    </div>
  );
}
