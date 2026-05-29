import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  Bot,
  BriefcaseBusiness,
  CalendarClock,
  CheckSquare,
  ClipboardCheck,
  FileText,
  ListChecks,
  MessageSquare,
  PackageCheck,
  Paperclip,
  Play,
  Save,
  Settings2,
  Square,
  Star,
  UserCheck,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { parseServerDate } from "@yqgl/shared";
import { api, isDesktopRuntime } from "@/lib/api";
import { AssigneeSelector } from "@/components/AssigneeSelector";
import { useReqStream } from "@/hooks/useReqStream";
import { AILiveView } from "@/components/AILiveView";
import { ActivityTimeline } from "@/components/ActivityTimeline";
import { CommentsPanel } from "@/components/CommentsPanel";
import { DeliverablesTab } from "@/components/DeliverablesTab";
import { StatusBadge } from "@/components/StatusBadge";
import { SpeakButton } from "@/components/SpeakButton";
import type { Attachment, Identity, Requirement, RequirementAcceptanceItem, RequirementWorkspace, TaskPlan } from "@/lib/types";

type Tab = "overview" | "workspace" | "decomposition" | "chat" | "attachments" | "deliveries" | "comments" | "activity";

type TabEntry = { key: Tab; label: string; Icon: LucideIcon; desktopOnly?: boolean };

const ALL_DETAIL_TABS: TabEntry[] = [
  { key: "overview", label: "概览", Icon: FileText },
  // workspace & worker-stage decomposition are接单方动作 — 仅在桌面客户端展示。
  // 网页上提需求方/PM 看不到 tab；详情仍可在客户端打开。
  { key: "workspace", label: "我的工作区", Icon: BriefcaseBusiness, desktopOnly: true },
  { key: "decomposition", label: "拆解", Icon: ListChecks },
  { key: "chat", label: "对话历史", Icon: Bot },
  { key: "attachments", label: "附件", Icon: Paperclip },
  { key: "deliveries", label: "交付物", Icon: PackageCheck },
  { key: "comments", label: "评论", Icon: MessageSquare },
  { key: "activity", label: "活动", Icon: Activity },
];

/** Tabs visible to the current runtime (web vs desktop client). */
function visibleDetailTabs(): TabEntry[] {
  const desktop = isDesktopRuntime();
  return ALL_DETAIL_TABS.filter((t) => desktop || !t.desktopOnly);
}

const DETAIL_TABS = visibleDetailTabs();
const ASSIGNEE_MANAGE_STATUSES = new Set(["ready", "claimed", "doing", "revision_requested"]);

function formatServerDate(value?: string | null): string {
  const date = parseServerDate(value);
  return date ? date.toLocaleString("zh-CN", { hour12: false }) : "-";
}

export function RequirementDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const [req, setReq] = useState<Requirement | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [workspaces, setWorkspaces] = useState<RequirementWorkspace[]>([]);
  const [taskPlans, setTaskPlans] = useState<TaskPlan[]>([]);
  const [acceptanceItems, setAcceptanceItems] = useState<RequirementAcceptanceItem[]>([]);
  const [me, setMe] = useState<Identity | null>(null);
  const [tab, setTab] = useState<Tab>((searchParams.get("tab") as Tab) || "overview");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [manageLeadUserId, setManageLeadUserId] = useState<string | null>(null);
  const [manageCollaboratorUserIds, setManageCollaboratorUserIds] = useState<string[]>([]);
  const { events, latestStatus } = useReqStream(id);
  const currentStatus = latestStatus || req?.status;
  const desktopRuntime = isDesktopRuntime();

  // Token-based cancel guard: when the user navigates /r/A → /r/B mid-fetch,
  // A's in-flight Promise.all could resolve AFTER B's setReq landed and
  // overwrite B's attachments/workspaces/taskPlans/acceptanceItems with
  // A's data while req still shows B. Each refresh bumps the token; only
  // the latest token's writes are accepted.
  const refreshTokenRef = useRef(0);
  const refresh = async () => {
    if (!id) return;
    const myToken = ++refreshTokenRef.current;
    const isCurrent = () => refreshTokenRef.current === myToken;
    try {
      const r = await api.getRequirement(id);
      if (!isCurrent()) return;
      setReq(r);
      setLoadErr(null);
      const [nextAttachments, nextWorkspaces, nextPlans, nextAcceptance] = await Promise.all([
        api.listAttachments(id),
        api.listRequirementWorkspaces(id).catch(() => []),
        api.listTaskPlans(id).catch(() => []),
        api.listAcceptanceItems(id).catch(() => []),
      ]);
      if (!isCurrent()) return;
      setAttachments(nextAttachments);
      setWorkspaces(nextWorkspaces);
      setTaskPlans(nextPlans);
      setAcceptanceItems(nextAcceptance);
    } catch (e: any) {
      if (!isCurrent()) return;
      // Without this, a 404 / 401 left `req` null forever and the user
      // stared at "加载中…" with no escape route.
      setLoadErr(String(e));
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [id]);
  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    const nextTab = searchParams.get("tab") as Tab | null;
    if (nextTab && DETAIL_TABS.some((item) => item.key === nextTab)) setTab(nextTab);
  }, [searchParams]);
  // Reload from server when SSE says status changed
  useEffect(() => { if (latestStatus) refresh(); }, [latestStatus]);
  useEffect(() => {
    if (!id || (currentStatus !== "draft" && currentStatus !== "clarifying" && currentStatus !== "summary_ready")) return;
    const t = window.setTimeout(() => nav(`/r/${id}/clarify`), 900);
    return () => window.clearTimeout(t);
  }, [currentStatus, id, nav]);

  if (loadErr) {
    return (
      <main className="narrow-container">
        <div className="paper-surface mt-6 p-5 text-sm text-red-700">
          加载需求失败：{loadErr}
          <div className="mt-3">
            <button className="button-secondary" onClick={refresh}>重试</button>
          </div>
        </div>
      </main>
    );
  }
  if (!id || !req || !currentStatus) return <main className="narrow-container text-stone-500">加载中…</main>;

  // If still clarifying, redirect to clarify page
  if (currentStatus === "draft" || currentStatus === "clarifying" || currentStatus === "summary_ready") {
    return (
      <main className="narrow-container text-center">
        <div className="paper-surface p-8">
          <p className="text-stone-600">这条需求还在沟通中，正在跳转…</p>
          <button className="button-primary mt-4" onClick={() => nav(`/r/${id}/clarify`)}>现在去</button>
        </div>
      </main>
    );
  }

  const assignees = req.assignees ?? [];
  const lead = assignees.find((a) => a.role === "lead");
  const collaboratorCount = assignees.filter((a) => a.role === "collaborator").length;
  const assignedIds = new Set(assignees.map((a) => a.user_id));
  const isWorker = !!me && (assignedIds.has(me.id) || req.claimed_by_user_id === me.id);
  const canClaim = desktopRuntime && currentStatus === "ready" && !!me && (assignees.length === 0 || isWorker);
  const canStartDoing = desktopRuntime && currentStatus === "claimed" && isWorker;
  const canManageAssignees = !!me && me.nickname === req.submitter_nickname && ASSIGNEE_MANAGE_STATUSES.has(currentStatus);
  const mustKeepLead = ["claimed", "doing", "revision_requested"].includes(currentStatus);
  const selectedUsers = assignees.map((a) => ({ id: a.user_id, nickname: a.nickname }));
  const due = parseServerDate(req.due_at);
  const statusProgress: Record<string, number> = {
    ready: 5, claimed: 15, doing: 45, ai_processing: 50, revision_requested: 60,
    delivery_doc_pending: 85, delivered: 90, accepted: 100, cancelled: 0,
  };
  const aggregateProgress = workspaces.length
    ? Math.round(workspaces.reduce((sum, workspace) => sum + workspace.progress_percent, 0) / workspaces.length)
    : statusProgress[currentStatus] ?? 0;
  const blockedCount = workspaces.filter((workspace) => !!workspace.blocked_reason).length;
  const dueTone = due && due.getTime() < Date.now()
    ? "border-red-200 bg-red-50 text-red-700"
    : due && due.toDateString() === new Date().toDateString()
      ? "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]"
      : "border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]";

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
              <span>等人接</span>
            )}
            <span>·</span>
            <span>{formatServerDate(req.created_at)}</span>
          </div>
          <div className="mt-3">
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${dueTone}`}>
              <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
              {due ? `截止 ${due.toLocaleString("zh-CN", { hour12: false })}` : "没写截止时间"}
            </span>
          </div>
          <div className="mt-4 max-w-xl">
            <div className="flex items-center justify-between gap-3 text-xs text-stone-500">
              <span className="inline-flex items-center gap-1.5">
                <BriefcaseBusiness className="h-3.5 w-3.5" aria-hidden="true" />
                工作区进度
              </span>
              <span>{aggregateProgress}%{blockedCount ? ` · ${blockedCount} 个阻塞` : ""}</span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-stone-200">
              <div className="h-full rounded-full bg-stone-950 transition-all" style={{ width: `${aggregateProgress}%` }} />
            </div>
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
              改派接单人
            </button>
          )}
          {canClaim && (
            <button className="button-accent" disabled={actionBusy} onClick={claim}>
              <UserCheck className="h-4 w-4" aria-hidden="true" />
              {actionBusy ? "处理中…" : "接这单"}
            </button>
          )}
          {canStartDoing && (
            <button className="button-accent" disabled={actionBusy} onClick={startDoing}>
              <Play className="h-4 w-4" aria-hidden="true" />
              {actionBusy ? "处理中…" : "开始做"}
            </button>
          )}
          {!desktopRuntime && isWorker && ["ready", "claimed", "doing", "revision_requested"].includes(currentStatus) && (
            <a
              href={`yqgl://r/${req.id}`}
              className="button-accent"
              title="在桌面客户端中打开此需求"
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              在桌面客户端继续 →
            </a>
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
            label="改派接单人"
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
              {mustKeepLead ? "进行中的需求需要保留负责人；协作者拥有同等处理和交付权限。" : "清空后会回到等人接的公开池。"}
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
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="paper-surface p-4">
                <div className="text-xs text-stone-500">估算工时</div>
                <div className="mt-1 text-2xl font-semibold text-stone-950">{req.estimate_hours ?? "-"}h</div>
              </div>
              <div className="paper-surface p-4">
                <div className="text-xs text-stone-500">估算信心</div>
                <div className="mt-1 text-2xl font-semibold text-stone-950">{req.estimate_confidence || "-"}</div>
              </div>
              <div className="paper-surface p-4">
                <div className="text-xs text-stone-500">验收标准</div>
                <div className="mt-1 text-2xl font-semibold text-stone-950">{acceptanceItems.length}</div>
              </div>
            </div>
            {req.planning_note && (
              <div className="paper-panel p-4 text-sm leading-6 text-stone-700">
                <div className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">Planning note</div>
                {req.planning_note}
              </div>
            )}
            {acceptanceItems.length > 0 && (
              <div className="paper-surface p-4">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-[#4e7146]">
                  <ClipboardCheck className="h-4 w-4" aria-hidden="true" />
                  验收标准
                </h3>
                <ul className="mt-3 space-y-2">
                  {acceptanceItems.map((item) => (
                    <li key={item.id} className="rounded-lg border border-stone-200 bg-[#fffdf8] p-3 text-sm">
                      <div className="font-medium text-stone-950">{item.title}</div>
                      {item.description && <p className="mt-1 text-stone-500">{item.description}</p>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="paper-surface p-6">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-[#4e7146]">
                <ClipboardCheck className="h-4 w-4" aria-hidden="true" />
                需求描述
              </h3>
              <pre className="mt-3 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-4 text-sm leading-relaxed text-stone-700">{req.summary_md || req.raw_description || "(空)"}</pre>
            </div>
          </div>
        )}
        {tab === "workspace" && <WorkspaceBoard req={req} me={me} workspaces={workspaces} isDesktop={desktopRuntime} onChange={refresh} />}
        {tab === "decomposition" && <DecompositionPanel req={req} me={me} plans={taskPlans} isDesktop={desktopRuntime} onChange={refresh} />}
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
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setErr(null);
    api.listChatMessages(reqId)
      .then((rows) => { if (alive) setMsgs(rows); })
      // Without the catch a failed load silently showed "无对话" — making a
      // load error indistinguishable from a genuinely empty conversation.
      .catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, [reqId]);
  if (err) return <div className="text-sm text-red-700">对话加载失败：{err}</div>;
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

function DecompositionPanel({
  req,
  me,
  plans,
  isDesktop,
  onChange,
}: {
  req: Requirement;
  me: Identity | null;
  plans: TaskPlan[];
  isDesktop: boolean;
  onChange: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const assignedIds = new Set(req.assignees.map((item) => item.user_id));
  const canDispatch = me?.nickname === req.submitter_nickname;
  const canWorker = isDesktop && !!me && (assignedIds.has(me.id) || req.claimed_by_user_id === me.id);

  const trigger = async (stage: "dispatch" | "worker") => {
    setBusy(`create-${stage}`);
    setErr(null);
    try {
      await api.createTaskPlan(req.id, stage);
      await onChange();
      window.setTimeout(() => onChange(), 1400);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const confirm = async (planId: string) => {
    setBusy(`confirm-${planId}`);
    setErr(null);
    try {
      await api.confirmTaskPlan(planId);
      await onChange();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const dismiss = async (planId: string) => {
    setBusy(`dismiss-${planId}`);
    setErr(null);
    try {
      await api.dismissTaskPlan(planId);
      await onChange();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="paper-surface p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-base font-semibold text-stone-950">两阶段 Agent 拆解</h3>
            <p className="mt-1 text-sm text-stone-500">投递前拆验收，接单后拆个人清单；都要人工确认才落库。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {canDispatch && (
              <button className="button-secondary" disabled={!!busy} onClick={() => trigger("dispatch")}>
                <ListChecks className="h-4 w-4" aria-hidden="true" />
                {busy === "create-dispatch" ? "拆解中..." : "生成投递拆解"}
              </button>
            )}
            {canWorker && (
              <button className="button-primary" disabled={!!busy} onClick={() => trigger("worker")}>
                <BriefcaseBusiness className="h-4 w-4" aria-hidden="true" />
                {busy === "create-worker" ? "拆解中..." : "生成我的清单"}
              </button>
            )}
            {!isDesktop && !!me && (assignedIds.has(me.id) || req.claimed_by_user_id === me.id) && (
              <span className="pill border-[#bbd6d0] bg-[#eef8f5] text-[#4e7146]">个人清单在本地工作台生成</span>
            )}
          </div>
        </div>
        {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
      </div>

      {plans.length === 0 ? (
        <div className="empty-state">还没有拆解草稿。放心，按钮按下去之前它不会假装自己很懂。</div>
      ) : plans.map((plan) => {
        const canConfirm = plan.status === "draft" && (
          (plan.stage === "dispatch" && canDispatch) ||
          (plan.stage === "worker" && isDesktop && plan.target_user_id === me?.id)
        );
        const grouped = {
          task: plan.items.filter((item) => item.item_type === "task"),
          acceptance: plan.items.filter((item) => item.item_type === "acceptance"),
          risk: plan.items.filter((item) => item.item_type === "risk"),
        };
        return (
          <section key={plan.id} className="paper-surface p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="pill">{plan.stage === "dispatch" ? "投递前" : "接单后"}</span>
                  <span className="pill">{plan.status}</span>
                  {plan.target_nickname && <span className="pill">给 {plan.target_nickname}</span>}
                </div>
                <h4 className="mt-3 text-lg font-semibold text-stone-950">{plan.summary || "拆解还在生成中"}</h4>
                {plan.risks && <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-stone-600">{plan.risks}</p>}
              </div>
              {canConfirm && (
                <div className="flex gap-2">
                  <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" disabled={!!busy} onClick={() => dismiss(plan.id)}>
                    忽略
                  </button>
                  <button className="button-accent min-h-9 px-3 py-1.5 text-xs" disabled={!!busy || plan.items.length === 0} onClick={() => confirm(plan.id)}>
                    确认写入
                  </button>
                </div>
              )}
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-3">
              {([
                ["task", "任务"],
                ["acceptance", "验收"],
                ["risk", "风险"],
              ] as const).map(([key, label]) => (
                <div key={key} className="paper-panel p-3">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">{label}</div>
                  <div className="space-y-2">
                    {grouped[key].length === 0 && <div className="text-xs text-stone-400">空</div>}
                    {grouped[key].map((item) => (
                      <div key={item.id} className="rounded-lg border border-stone-200 bg-[#fffdf8] p-3 text-sm">
                        <div className="font-medium text-stone-950">{item.title}</div>
                        {item.description && <p className="mt-1 text-xs leading-5 text-stone-500">{item.description}</p>}
                        {item.estimate_hours != null && <p className="mt-2 text-xs text-stone-400">{item.estimate_hours}h</p>}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function WorkspaceBoard({
  req,
  me,
  workspaces,
  isDesktop,
  onChange,
}: {
  req: Requirement;
  me: Identity | null;
  workspaces: RequirementWorkspace[];
  isDesktop: boolean;
  onChange: () => Promise<void>;
}) {
  if (workspaces.length === 0) {
    return <div className="empty-state">还没有个人工作区。接单后这里会出现进度、清单和动态。</div>;
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">参与者</div>
          <div className="mt-1 text-2xl font-semibold text-stone-950">{workspaces.length}</div>
        </div>
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">平均进度</div>
          <div className="mt-1 text-2xl font-semibold text-stone-950">
            {Math.round(workspaces.reduce((sum, item) => sum + item.progress_percent, 0) / workspaces.length)}%
          </div>
        </div>
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">阻塞</div>
          <div className="mt-1 text-2xl font-semibold text-stone-950">{workspaces.filter((item) => item.blocked_reason).length}</div>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {workspaces.map((workspace) => (
          <WorkspaceCard
            key={workspace.id}
            req={req}
            workspace={workspace}
            canEdit={isDesktop && me?.id === workspace.user_id}
            onChange={onChange}
          />
        ))}
      </div>
    </div>
  );
}

function WorkspaceCard({
  req,
  workspace,
  canEdit,
  onChange,
}: {
  req: Requirement;
  workspace: RequirementWorkspace;
  canEdit: boolean;
  onChange: () => Promise<void>;
}) {
  const [phase, setPhase] = useState(workspace.phase);
  const [progress, setProgress] = useState(workspace.progress_percent);
  const [note, setNote] = useState(workspace.status_note || "");
  const [blocked, setBlocked] = useState(workspace.blocked_reason || "");
  const [newItem, setNewItem] = useState("");
  const [updateText, setUpdateText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Track unsaved edits so an incoming SSE-triggered refresh doesn't
  // clobber the user's in-flight typing. Previously every workspace prop
  // change blindly reset all four fields → user typed, partner pushed an
  // unrelated update via SSE, user's text vanished.
  const [dirty, setDirty] = useState(false);
  const lastSyncedKeyRef = useRef("");

  useEffect(() => {
    // Sync local edit state only when the server-side workspace ACTUALLY
    // changed (different updated_at), AND the user isn't actively editing.
    const key = `${workspace.id}:${workspace.updated_at || ""}`;
    if (key === lastSyncedKeyRef.current) return;
    if (dirty) return;
    lastSyncedKeyRef.current = key;
    setPhase(workspace.phase);
    setProgress(workspace.progress_percent);
    setNote(workspace.status_note || "");
    setBlocked(workspace.blocked_reason || "");
  }, [workspace, dirty]);

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      await api.patchMyWorkspace(req.id, {
        phase,
        progress_percent: progress,
        status_note: note || null,
        blocked_reason: blocked || null,
      });
      // Edits are now persisted server-side; let the next refresh sync
      // any concurrent changes from teammates without us losing context.
      setDirty(false);
      await onChange();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const addItem = async () => {
    if (!newItem.trim()) return;
    setBusy(true); setErr(null);
    try {
      await api.createWorkspaceItem(req.id, { title: newItem.trim(), sort_order: workspace.items.length + 1 });
      setNewItem("");
      await onChange();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const addUpdate = async () => {
    if (!updateText.trim()) return;
    setBusy(true); setErr(null);
    try {
      await api.addWorkspaceUpdate(req.id, updateText.trim());
      setUpdateText("");
      await onChange();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const patchItem = async (itemId: string, status: "todo" | "doing" | "done") => {
    setBusy(true); setErr(null);
    try {
      await api.patchWorkspaceItem(itemId, { status });
      await onChange();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`paper-surface p-4 ${workspace.blocked_reason ? "border-red-200" : ""}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-stone-950">{workspace.nickname}</h3>
          <p className="mt-1 text-xs text-stone-500">{canEdit ? "我的个人区" : "个人区只读"}</p>
        </div>
        <span className={`pill ${workspace.blocked_reason ? "border-red-200 bg-red-50 text-red-700" : ""}`}>
          {workspace.phase} · {workspace.progress_percent}%
        </span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-stone-200">
        <div className="h-full rounded-full bg-stone-950 transition-all" style={{ width: `${workspace.progress_percent}%` }} />
      </div>

      {canEdit ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_120px]">
          <input className="field" value={phase} onChange={(e) => { setPhase(e.target.value); setDirty(true); }} placeholder="阶段" />
          <input className="field" type="number" min={0} max={100} value={progress} onChange={(e) => { setProgress(Number(e.target.value)); setDirty(true); }} />
          <textarea className="textarea-field min-h-20 sm:col-span-2" value={note} onChange={(e) => { setNote(e.target.value); setDirty(true); }} placeholder="现在干到哪了？" />
          <textarea className="textarea-field min-h-16 sm:col-span-2" value={blocked} onChange={(e) => { setBlocked(e.target.value); setDirty(true); }} placeholder="有阻塞就写，没有就留空" />
          <button className="button-primary sm:col-span-2" disabled={busy || !phase.trim() || !dirty} onClick={save}>
            <Save className="h-4 w-4" aria-hidden="true" />
            {busy ? "保存中..." : dirty ? "保存进度" : "已保存"}
          </button>
        </div>
      ) : (
        <div className="mt-4 space-y-2 text-sm text-stone-700">
          {workspace.status_note && <p className="whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-3">{workspace.status_note}</p>}
          {workspace.blocked_reason && <p className="whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 p-3 text-red-700">阻塞：{workspace.blocked_reason}</p>}
        </div>
      )}

      <div className="mt-4">
        <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">清单</h4>
        <div className="mt-2 space-y-1">
          {workspace.items.length === 0 && <div className="rounded-lg border border-dashed border-stone-300 p-3 text-xs text-stone-400">清单还空着。</div>}
          {workspace.items.map((item) => (
            <div key={item.id} className="flex items-center gap-2 rounded-lg border border-stone-200 bg-[#fffdf8] px-3 py-2 text-sm">
              {item.status === "done" ? <CheckSquare className="h-4 w-4 text-[#4e7146]" /> : <Square className="h-4 w-4 text-stone-300" />}
              <span className={`min-w-0 flex-1 break-words ${item.status === "done" ? "text-stone-400 line-through" : "text-stone-800"}`}>{item.title}</span>
              {canEdit && (
                <select className="select-field min-h-8 w-24 py-1 text-xs" value={item.status} disabled={busy} onChange={(e) => patchItem(item.id, e.target.value as "todo" | "doing" | "done")}>
                  <option value="todo">待办</option>
                  <option value="doing">进行</option>
                  <option value="done">完成</option>
                </select>
              )}
            </div>
          ))}
        </div>
        {canEdit && (
          <div className="mt-2 flex gap-2">
            <input className="field min-h-9 flex-1" value={newItem} onChange={(e) => setNewItem(e.target.value)} placeholder="加一个待办" />
            <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" disabled={busy || !newItem.trim()} onClick={addItem}>添加</button>
          </div>
        )}
      </div>

      <div className="mt-4">
        <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">动态</h4>
        {canEdit && (
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <input className="field min-h-9 flex-1" value={updateText} onChange={(e) => setUpdateText(e.target.value)} placeholder="写一句进展" />
            <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" disabled={busy || !updateText.trim()} onClick={addUpdate}>发布</button>
          </div>
        )}
        <div className="mt-2 space-y-1">
          {workspace.updates.length === 0 && <div className="text-xs text-stone-400">还没有动态。</div>}
          {workspace.updates.map((update) => (
            <div key={update.id} className="rounded-lg border border-stone-200 bg-[#fffdf8] p-2 text-xs text-stone-600">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-stone-800">{update.actor_nickname}</span>
                <span className="text-stone-400">{formatServerDate(update.created_at)}</span>
              </div>
              <p className="mt-1 whitespace-pre-wrap">{update.body}</p>
            </div>
          ))}
        </div>
      </div>
      {err && <p className="mt-3 text-xs text-red-700">{err}</p>}
    </section>
  );
}
