import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { Button, EmptyState, Skeleton, toast } from "@yqgl/shared";
import type { Requirement } from "@yqgl/shared";
import { invoke } from "@/lib/tauri";
import { TaskCard } from "@/components/TaskCard";

/**
 * 派活 Space 的首页 — 提交人视角的工单看板。Tabs 映射到 SidebarDispatch
 * 的 dtab 参数（drafts/clarifying/ready/working/review/accepted），数据源
 * 统一从 `list_my({mine:true})` 派生，前端按 status 切片。
 *
 * 「待我验收」是核心导流入口 — 这是提交人最容易遗忘的事项（已交付但还没点
 * 通过/打回），在 Sidebar 的徽章会用珊瑚渐变标出。
 */
type DTab = "drafts" | "clarifying" | "ready" | "working" | "review" | "accepted";

const TABS: { id: DTab; label: string; statuses: string[] }[] = [
  { id: "drafts",     label: "起草中",   statuses: ["draft"] },
  { id: "clarifying", label: "待澄清",   statuses: ["clarifying", "summary_ready"] },
  { id: "ready",      label: "投递池",   statuses: ["ready"] },
  { id: "working",    label: "跟进中",   statuses: ["claimed", "doing", "ai_processing", "delivery_doc_pending", "revision_requested"] },
  { id: "review",     label: "待我验收", statuses: ["delivered"] },
  { id: "accepted",   label: "已通过",   statuses: ["accepted"] },
];

export function HubDispatch() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const dtab = (params.get("dtab") as DTab) || "review";

  const [all, setAll] = useState<Requirement[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    setErr(null);
    try {
      const list = await invoke<Requirement[]>("list_my", { mine: true });
      setAll(list);
    } catch (e: any) {
      setErr(String(e));
      setAll([]);
    }
  };

  useEffect(() => { refresh(); }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    if (!all) return c;
    for (const t of TABS) {
      c[t.id] = all.filter((r) => t.statuses.includes(r.status)).length;
    }
    return c;
  }, [all]);

  const current = TABS.find((t) => t.id === dtab) ?? TABS[4];
  const items = useMemo(
    () => (all ?? []).filter((r) => current.statuses.includes(r.status))
      .sort((a, b) => (a.due_at || "").localeCompare(b.due_at || "")),
    [all, current],
  );

  return (
    <div className="flex-1 p-6 overflow-auto" style={{ viewTransitionName: "yqgl-hub" }}>
      <header className="flex items-end justify-between mb-4 gap-4">
        <div>
          <h1 className="text-h2 text-ink">派活台</h1>
          <p className="text-body-sm text-ink-muted mt-1">
            管理你发起的需求 — 起草、投递、跟进、验收
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={refresh} leftIcon={<RefreshCw className="h-3.5 w-3.5" />}>
            刷新
          </Button>
          <Button variant="accent" size="sm" onClick={() => nav("/r/new")} leftIcon={<Plus className="h-3.5 w-3.5" />}>
            新建需求
          </Button>
        </div>
      </header>

      {/* Tab strip — keyed off ?dtab=… */}
      <div className="glass-quiet rounded-md p-1 mb-4 inline-flex gap-0.5">
        {TABS.map((t) => {
          const active = t.id === dtab;
          const count = counts[t.id] ?? 0;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setParams({ dtab: t.id })}
              className={`flex items-center gap-1.5 h-7 px-3 rounded-sm text-body-sm transition ${
                active ? "bg-accent text-white shadow-1" : "text-ink-soft hover:bg-accent-soft"
              }`}
            >
              <span>{t.label}</span>
              {count > 0 && (
                <span className={`text-caption ${active ? "text-white/85" : "text-ink-faint"}`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {err && <div className="glass p-4 text-error mb-4">{err}</div>}

      {all == null ? (
        <div className="space-y-3">
          <Skeleton height="h-24" rounded="md" />
          <Skeleton height="h-24" rounded="md" />
          <Skeleton height="h-24" rounded="md" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title={emptyTitle(dtab)}
          description={emptyDesc(dtab)}
          action={dtab === "drafts" ? (
            <Button variant="accent" size="sm" onClick={() => nav("/r/new")}>新建一条</Button>
          ) : undefined}
        />
      ) : (
        <div className="space-y-3">
          {items.map((r) => <TaskCard key={r.id} req={r} />)}
        </div>
      )}
    </div>
  );
}

function emptyTitle(t: DTab): string {
  return {
    drafts: "还没有草稿",
    clarifying: "没有需要澄清的需求",
    ready: "投递池是空的",
    working: "没有需要跟进的需求",
    review: "没有需要你验收的交付",
    accepted: "近期没有已通过的需求",
  }[t];
}

function emptyDesc(t: DTab): string {
  return {
    drafts: "点右上「新建需求」起一条。",
    clarifying: "需求已经投递出去，或还没创建。",
    ready: "投递后等接单人接走，会出现在这里。",
    working: "你发起的需求里没有正在被人做的。",
    review: "等接单人完成交付后，需要你点「通过」或「打回」。",
    accepted: "30 天内验收通过的需求会出现在这里。",
  }[t];
}
