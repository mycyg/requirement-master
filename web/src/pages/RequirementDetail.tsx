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
  Save,
  Settings2,
  Star,
  UserCheck,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "@/lib/api";
import { AssigneeSelector } from "@/components/AssigneeSelector";
import { useReqStream } from "@/hooks/useReqStream";
import { AILiveView } from "@/components/AILiveView";
import { ActivityTimeline } from "@/components/ActivityTimeline";
import { CommentsPanel } from "@/components/CommentsPanel";
import { DeliverablesTab } from "@/components/DeliverablesTab";
import { StatusBadge } from "@/components/StatusBadge";
import { SpeakButton } from "@/components/SpeakButton";
import type { Attachment, Identity, Requirement } from "@/lib/types";

type Tab = "overview" | "chat" | "attachments" | "deliveries" | "comments" | "activity";
const DETAIL_TABS: { key: Tab; label: string; Icon: LucideIcon }[] = [
  { key: "overview", label: "概览", Icon: FileText },
  { key: "chat", label: "对话历史", Icon: Bot },
  { key: "attachments", label: "附件", Icon: Paperclip },
  { key: "deliveries", label: "交付物", Icon: PackageCheck },
  { key: "comments", label: "评论", Icon: MessageSquare },
  { key: "activity", label: "活动", Icon: Activity },
];
const ASSIGNEE_MANAGE_STATUSES = new Set(["ready", "claimed", "doing", "revision_requested"]);

export function RequirementDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [req, setReq] = useState<Requirement | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [me, setMe] = useState<Identity | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [manageLeadUserId, setManageLeadUserId] = useState<string | null>(null);
  const [manageCollaboratorUserIds, setManageCollaboratorUserIds] = useState<string[]>([]);
  const { events, latestStatus } = useReqStream(id);
  const currentStatus = latestStatus || req?.status;

  const refresh = async () => {
    if (!id) return;
    const r = await api.getRequirement(id);
    setReq(r);
    setAttachments(await api.listAttachments(id));
  };

  useEffect(() => { refresh(); }, [id]);
  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);
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

  const assignees = req.assignees ?? [];
  const lead = assignees.find((a) => a.role === "lead");
  const collaboratorCount = assignees.filter((a) => a.role === "collaborator").length;
  const assignedIds = new Set(assignees.map((a) => a.user_id));
  const isWorker = !!me && (assignedIds.has(me.id) || req.claimed_by_user_id === me.id);
  const canClaim = currentStatus === "ready" && !!me && (assignees.length === 0 || isWorker);
  const canStartDoing = currentStatus === "claimed" && isWorker;
  const canManageAssignees = !!me && me.nickname === req.submitter_nickname && ASSIGNEE_MANAGE_STATUSES.has(currentStatus);
  const mustKeepLead = ["claimed", "doing", "revision_requested"].includes(currentStatus);
  const selectedUsers = assignees.map((a) => ({ id: a.user_id, nickname: a.nickname }));

  const openManage = () => {
    setManageLeadUserId(lead?.user_id ?? null);
    setManageCollaboratorUserIds(assignees.filter((a) => a.role === "collaborator").map((a) => a.user_id));
    setManageOpen(true);
    setActionErr(null);
  };

  const claim = async () => {
    setActionBusy(true);
    setActionErr(null);
    try {
      await api.claimRequirement(req.id);
      await refresh();
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
      await refresh();
    } catch (e: any) {
      setActionErr(String(e));
    } finally {
      setActionBusy(false);
    }
  };

  const saveAssignees = async () => {
    setActionBusy(true);
    setActionErr(null);
    try {
      await api.updateAssignees(req.id, {
        lead_user_id: manageLeadUserId,
        collaborator_user_ids: manageCollaboratorUserIds,
      });
      setManageOpen(false);
      await refresh();
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
            {lead ? (
              <span>负责人 <b>{lead.nickname}</b>{collaboratorCount > 0 ? ` +${collaboratorCount}` : ""}</span>
            ) : (
              <span>公开待接单池</span>
            )}
            <span>·</span>
            <span>{new Date(req.created_at + "Z").toLocaleString("zh-CN")}</span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {assignees.length === 0 ? (
              <span className="pill border-[#e0c895] bg-[#fff7e2] text-[#8a5d10]">
                <Users className="h-3.5 w-3.5" aria-hidden="true" />
                公开池
              </span>
            ) : assignees.map((a) => (
              <span
                key={a.user_id}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
                  a.role === "lead"
                    ? "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]"
                    : "border-stone-200 bg-[#fffdf8] text-stone-600"
                }`}
              >
                {a.role === "lead" ? <Star className="h-3.5 w-3.5" aria-hidden="true" /> : <Users className="h-3.5 w-3.5" aria-hidden="true" />}
                {a.nickname}
              </span>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {canManageAssignees && (
            <button className="button-secondary" disabled={actionBusy} onClick={openManage}>
              <Settings2 className="h-4 w-4" aria-hidden="true" />
              管理接单人
            </button>
          )}
          {canClaim && (
            <button className="button-accent" disabled={actionBusy} onClick={claim}>
              <UserCheck className="h-4 w-4" aria-hidden="true" />
              {actionBusy ? "处理中..." : "接单"}
            </button>
          )}
          {canStartDoing && (
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

      {manageOpen && (
        <section className="mt-5">
          <AssigneeSelector
            label="管理接单人"
            leadUserId={manageLeadUserId}
            collaboratorUserIds={manageCollaboratorUserIds}
            selectedUsers={selectedUsers}
            onChange={(next) => {
              setManageLeadUserId(next.leadUserId);
              setManageCollaboratorUserIds(next.collaboratorUserIds);
            }}
          />
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-stone-500">
              {mustKeepLead ? "进行中的需求需要保留负责人；协作者拥有同等处理和交付权限。" : "清空后会回到公开待接单池。"}
            </p>
            <div className="flex gap-2">
              <button className="button-secondary" disabled={actionBusy} onClick={() => setManageOpen(false)}>
                <X className="h-4 w-4" aria-hidden="true" />
                取消
              </button>
              <button
                className="button-primary"
                disabled={actionBusy || (mustKeepLead && !manageLeadUserId)}
                onClick={saveAssignees}
              >
                <Save className="h-4 w-4" aria-hidden="true" />
                {actionBusy ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        </section>
      )}

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
        {tab === "deliveries" && <DeliverablesTab req={req} canReview={me?.nickname === req.submitter_nickname} onChange={refresh} />}
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
