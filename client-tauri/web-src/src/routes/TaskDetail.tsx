import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Bot, FolderOpen, Hammer, Play, PackageCheck, RefreshCw, UserCheck } from "lucide-react";
import { invoke, useEvent } from "@/lib/tauri";
import {
  Avatar,
  AvatarGroup,
  Badge,
  Button,
  Card,
  EmptyState,
  Progress,
  Skeleton,
  StatusBadge,
  Tab,
  Tabs,
  TabsList,
  TabsPanel,
  Textarea,
  toast,
  isSubmitter,
  isAssignee as isAssigneeFn,
  isAdmin,
  useSpace,
} from "@yqgl/shared";
import type { Requirement, RequirementWorkspace } from "@yqgl/shared";
import { DeliveryWizard } from "@/components/DeliveryWizard";
import { ActionRailDispatch } from "@/components/ActionRailDispatch";

export function TaskDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const { space } = useSpace();
  const [req, setReq] = useState<Requirement | null>(null);
  const [workspaces, setWorkspaces] = useState<RequirementWorkspace[]>([]);
  const [tab, setTab] = useState("overview");
  const [me, setMe] = useState<{ id: string; nickname: string; is_admin?: boolean } | null>(null);
  const [deliveryOpen, setDeliveryOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Submitter who also happens to be assigned must explicitly opt in to
  // see worker UI. Default false avoids "wait why is there a 接单 button on
  // my own requirement" confusion.
  const [workerView, setWorkerView] = useState(false);

  const refresh = async () => {
    if (!id) return;
    try {
      const [r, ws, identity] = await Promise.all([
        invoke<Requirement>("get_requirement", { reqId: id }),
        invoke<RequirementWorkspace[]>("list_workspaces", { reqId: id }).catch(() => []),
        invoke<{ id: string; nickname: string; is_admin?: boolean } | null>("me").catch(() => null),
      ]);
      setReq(r);
      setWorkspaces(ws);
      setMe(identity);
    } catch (e: any) {
      toast({ title: "加载失败", description: String(e), tone: "error" });
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [id]);

  useEvent<{ event: string; data: any }>("push-event", (p) => {
    if (!p?.data?.requirement_id || p.data.requirement_id !== id) return;
    if (p.event === "requirement.updated" || p.event === "workspace.updated") {
      refresh();
    }
  });

  if (!req) {
    return (
      <div className="flex-1 p-6 space-y-3">
        <Skeleton height="h-24" />
        <Skeleton height="h-48" />
      </div>
    );
  }

  const myWs = workspaces.find((w) => me && w.user_id === me.id) ?? null;
  const meIsSubmitter = isSubmitter(req, me);
  const meIsAssignee = isAssigneeFn(req, me);
  const meIsAdmin = isAdmin(me);
  // Show worker UI when viewer is an assignee AND not viewing as a submitter
  // (unless they explicitly opt in via the "我也来做" toggle). Admins viewing
  // someone else's req act as observers — no worker UI unless they're also
  // assignees.
  const showWorkerUi = meIsAssignee && (!meIsSubmitter || workerView);
  // Back link: context-aware. Submitters / observers in 派活 Space →派活 hub.
  // Otherwise → 接活 hub.
  const backHref = space === "dispatch" ? "/?dtab=ready" : "/?tab=mine";

  const claim = async () => {
    setBusy(true);
    try {
      await invoke("claim", { reqId: id });
      toast({ title: "已接单", tone: "success" });
      await refresh();
    } catch (e: any) {
      toast({ title: "接单失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const startDoing = async () => {
    setBusy(true);
    try {
      await invoke("patch_status", { reqId: id, status: "doing" });
      toast({ title: "已开始", tone: "info" });
      await refresh();
    } catch (e: any) {
      toast({ title: "状态切换失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const reSync = async () => {
    setBusy(true);
    try {
      await invoke("trigger_sync", { reqId: id });
      toast({ title: "已发起同步", tone: "info" });
    } catch (e: any) {
      toast({ title: "同步失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const openLocal = async () => {
    const cfg = await invoke<{ sync_root: string }>("get_config");
    const path = `${cfg.sync_root}\\${req.project_slug}\\${req.code}`;
    await invoke("open_folder", { path });
  };

  return (
    <div className="flex-1 p-6 overflow-auto">
      <button
        onClick={() => nav(backHref)}
        className="inline-flex items-center gap-1.5 text-body-sm text-ink-muted hover:text-ink mb-4"
      >
        <ArrowLeft className="h-4 w-4" /> 返回工单
      </button>

      {/* Submitter / admin operations card up top so verify/revise/delete
          affordances are impossible to miss. ActionRailDispatch internally
          gates on viewer role. */}
      <ActionRailDispatch req={req} me={me} onChange={refresh} />

      <Card variant="glass-strong" padding="lg" className="mb-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <span className="font-mono text-caption text-ink-faint">{req.code}</span>
              <StatusBadge status={req.status} size="sm" />
            </div>
            <h1 className="text-h2 text-ink break-words">{req.title || "(整理中)"}</h1>
            <div className="mt-2 flex items-center gap-3 text-caption text-ink-muted">
              <span>提交人 {req.submitter_nickname}</span>
              {req.due_at && <span>截止 {new Date(req.due_at).toLocaleString("zh-CN", { hour12: false })}</span>}
            </div>
            {req.assignees?.length ? (
              <div className="mt-3">
                <AvatarGroup users={req.assignees.map((a) => ({ nickname: a.nickname }))} size="sm" />
              </div>
            ) : (
              <Badge tone="warn" size="xs" className="mt-3">等人接</Badge>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" leftIcon={<FolderOpen className="h-4 w-4" />} onClick={openLocal}>
              打开本地目录
            </Button>
            <Button variant="secondary" size="sm" leftIcon={<RefreshCw className="h-4 w-4" />} loading={busy} onClick={reSync}>
              重新同步
            </Button>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <span className="text-caption text-ink-muted whitespace-nowrap">总体进度</span>
          <Progress
            value={
              workspaces.length
                ? Math.round(workspaces.reduce((s, w) => s + w.progress_percent, 0) / workspaces.length)
                : 0
            }
            tone="accent"
            showLabel
          />
        </div>

        {/* Worker actions — claim/start/deliver. Hidden for submitter who
            hasn't opted into worker view (avoids "wait why am I seeing
            接单 on my own requirement"). */}
        {req.status === "ready" && (!meIsSubmitter || workerView) && (
          <div className="mt-4">
            <Button variant="accent" leftIcon={<Hammer className="h-4 w-4" />} loading={busy} onClick={claim}>
              接这单
            </Button>
          </div>
        )}
        {req.status === "claimed" && showWorkerUi && (
          <div className="mt-4">
            <Button variant="accent" leftIcon={<Play className="h-4 w-4" />} loading={busy} onClick={startDoing}>
              开始做
            </Button>
          </div>
        )}
        {req.status === "doing" && showWorkerUi && (
          <div className="mt-4">
            <Button variant="accent" leftIcon={<PackageCheck className="h-4 w-4" />} onClick={() => setDeliveryOpen(true)}>
              完成并交付
            </Button>
          </div>
        )}

        {/* Submitter who is also assigned: opt-in to worker view */}
        {meIsSubmitter && meIsAssignee && !workerView && (
          <div className="mt-4 flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<UserCheck className="h-3.5 w-3.5" />}
              onClick={() => setWorkerView(true)}
            >
              我也来做（切到接单人视角）
            </Button>
            <span className="text-caption text-ink-faint">你既是发起人也是负责人</span>
          </div>
        )}
        {meIsSubmitter && meIsAssignee && workerView && (
          <div className="mt-4">
            <button
              type="button"
              onClick={() => setWorkerView(false)}
              className="text-caption text-ink-faint hover:text-ink underline-offset-4 hover:underline"
            >
              ← 切回发起人视角
            </button>
          </div>
        )}

        {/* Submitter prompt to start AI clarification if status is still draft/clarifying */}
        {meIsSubmitter && (req.status === "draft" || req.status === "clarifying") && (
          <div className="mt-4">
            <Button
              variant="accent"
              leftIcon={<Bot className="h-4 w-4" />}
              onClick={() => nav(`/r/${req.id}/clarify`)}
            >
              {req.status === "draft" ? "去跟 AI 聊聊" : "继续澄清"}
            </Button>
          </div>
        )}
        {meIsSubmitter && req.status === "summary_ready" && (
          <div className="mt-4 flex gap-2">
            <Button
              variant="accent"
              leftIcon={<Bot className="h-4 w-4" />}
              onClick={() => nav(`/r/${req.id}/clarify`)}
            >
              查看摘要并投递
            </Button>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-[1.5fr_1fr] gap-5">
        {/* Left column */}
        <div className="space-y-5">
          <Card>
            <Tabs value={tab} onChange={setTab}>
              <TabsList>
                <Tab value="overview">概览</Tab>
                <Tab value="comments">评论</Tab>
                <Tab value="activity">活动</Tab>
              </TabsList>
              <TabsPanel value="overview" className="mt-4">
                {req.summary_md ? (
                  <div className="prose prose-sm max-w-none whitespace-pre-wrap text-ink-soft">
                    {req.summary_md}
                  </div>
                ) : (
                  <EmptyState title="还没有需求摘要" description="提需求方完成澄清后会出现在这里。" />
                )}
              </TabsPanel>
              <TabsPanel value="comments" className="mt-4">
                <EmptyState title="评论" description="评论列表 — 待对接 /api/requirements/{id}/comments" />
              </TabsPanel>
              <TabsPanel value="activity" className="mt-4">
                <EmptyState title="活动" description="活动时间轴 — 待对接 /api/requirements/{id}/activity" />
              </TabsPanel>
            </Tabs>
          </Card>

          {workspaces.length > 0 && (
            <Card>
              <h3 className="text-h4 text-ink mb-3">队友进度（只读）</h3>
              <div className="space-y-2">
                {workspaces.filter((w) => !me || w.user_id !== me.id).map((w) => (
                  <div key={w.id} className="glass-sunken p-3 flex items-center gap-3">
                    <Avatar nickname={w.nickname} size="sm" />
                    <div className="flex-1 min-w-0">
                      <div className="text-body-sm text-ink truncate">{w.nickname}</div>
                      <div className="text-caption text-ink-muted">阶段：{w.phase}</div>
                    </div>
                    <Progress value={w.progress_percent} size="sm" className="w-24" />
                  </div>
                ))}
                {workspaces.filter((w) => !me || w.user_id !== me.id).length === 0 && (
                  <div className="text-caption text-ink-faint">没有其他协作人。</div>
                )}
              </div>
            </Card>
          )}
        </div>

        {/* Right column: my workspace — only visible to assignees (or
            submitter who opted into worker view). Submitters monitoring
            their own requirement don't need this clutter. */}
        {showWorkerUi && (
        <div className="space-y-5">
          {myWs ? (
            <MyWorkspace ws={myWs} reqId={id} onChange={refresh} />
          ) : (
            <Card>
              <EmptyState
                title="还没有你的工作区"
                description="接单后这里会出现你的进度、清单、动态。"
              />
            </Card>
          )}
        </div>
        )}
      </div>

      <DeliveryWizard
        open={deliveryOpen}
        onClose={() => setDeliveryOpen(false)}
        reqId={id}
        projectSlug={req.project_slug}
        code={req.code}
      />
    </div>
  );
}

function MyWorkspace({
  ws,
  reqId,
  onChange,
}: {
  ws: RequirementWorkspace;
  reqId: string;
  onChange: () => void;
}) {
  const [phase, setPhase] = useState(ws.phase);
  const [pct, setPct] = useState(ws.progress_percent);
  const [note, setNote] = useState(ws.status_note ?? "");
  const [blocked, setBlocked] = useState(ws.blocked_reason ?? "");
  const [newItem, setNewItem] = useState("");
  const [newUpdate, setNewUpdate] = useState("");

  // All workspace writes surface errors via toast — previously every
  // failure (network drop, status conflict) was silently swallowed and
  // the user's edit was lost without any feedback.
  const save = async (patch: Record<string, any>) => {
    try {
      await invoke("patch_my_workspace", { reqId, patch });
    } catch (e: any) {
      toast({ title: "保存失败", description: String(e), tone: "error" });
    }
  };

  const addItem = async () => {
    if (!newItem.trim()) return;
    try {
      await invoke("add_workspace_item", { reqId, title: newItem.trim() });
      setNewItem("");
      onChange();
    } catch (e: any) {
      toast({ title: "添加失败", description: String(e), tone: "error" });
    }
  };

  const toggleItem = async (itemId: string, status: "todo" | "doing" | "done") => {
    try {
      await invoke("patch_workspace_item", { itemId, patch: { status } });
      onChange();
    } catch (e: any) {
      toast({ title: "更新失败", description: String(e), tone: "error" });
    }
  };

  const addUpdate = async () => {
    if (!newUpdate.trim()) return;
    try {
      await invoke("add_workspace_update", { reqId, body: newUpdate.trim() });
      setNewUpdate("");
      onChange();
    } catch (e: any) {
      toast({ title: "记笔记失败", description: String(e), tone: "error" });
    }
  };

  return (
    <Card>
      <h3 className="text-h4 text-ink mb-3">我的工作区</h3>

      <label className="block mb-3">
        <span className="text-caption text-ink-muted">阶段</span>
        <input
          className="field mt-1"
          value={phase}
          onChange={(e) => setPhase(e.target.value)}
          onBlur={() => save({ phase })}
        />
      </label>

      <label className="block mb-3">
        <span className="text-caption text-ink-muted">进度：{pct}%</span>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={pct}
          onChange={(e) => setPct(Number(e.target.value))}
          onMouseUp={() => save({ progress_percent: pct })}
          className="w-full mt-1 accent-[#6B5BFF]"
        />
      </label>

      <label className="block mb-3">
        <span className="text-caption text-ink-muted">当前进展</span>
        <Textarea
          autosize
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => save({ status_note: note })}
          rows={2}
        />
      </label>

      <label className="block mb-4">
        <span className="text-caption text-ink-muted">遇到的阻碍（没有可空）</span>
        <Textarea
          autosize
          value={blocked}
          onChange={(e) => setBlocked(e.target.value)}
          onBlur={() => save({ blocked_reason: blocked || null })}
          rows={2}
        />
      </label>

      <div className="mb-4">
        <div className="text-caption text-ink-muted mb-1">个人清单</div>
        <div className="space-y-1">
          {ws.items?.map((it) => (
            <label key={it.id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={it.status === "done"}
                onChange={() => toggleItem(it.id, it.status === "done" ? "todo" : "done")}
              />
              <span className={`text-body-sm ${it.status === "done" ? "line-through text-ink-faint" : "text-ink"}`}>
                {it.title}
              </span>
            </label>
          ))}
          <div className="flex gap-2 mt-2">
            <input
              className="field flex-1"
              placeholder="加一项…"
              value={newItem}
              onChange={(e) => setNewItem(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addItem()}
            />
            <Button size="sm" variant="secondary" onClick={addItem}>加</Button>
          </div>
        </div>
      </div>

      <div>
        <div className="text-caption text-ink-muted mb-1">记一笔</div>
        <Textarea
          autosize
          value={newUpdate}
          onChange={(e) => setNewUpdate(e.target.value)}
          rows={2}
          placeholder="记一条进展…"
        />
        <div className="mt-1 flex justify-end">
          <Button size="sm" onClick={addUpdate} disabled={!newUpdate.trim()}>记一笔</Button>
        </div>
        <div className="mt-3 space-y-2 max-h-48 overflow-auto">
          {ws.updates?.slice(0, 10).map((u) => (
            <div key={u.id} className="glass-sunken p-2 text-caption">
              <div className="text-ink-faint">{u.actor_nickname} · {new Date(u.created_at).toLocaleString("zh-CN", { hour12: false }).slice(5, 16)}</div>
              <div className="text-ink-soft">{u.body}</div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
