import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Inbox, Plus, RefreshCw, Sparkles } from "lucide-react";
import { invoke, useEvent } from "@/lib/tauri";
import { TaskCard } from "@/components/TaskCard";
import { Button, EmptyState, Skeleton, toast, useSpace } from "@yqgl/shared";
import type { Requirement } from "@yqgl/shared";

type Tab = "public" | "mine" | "active" | "revision" | "delivered";

export function Hub() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const { setSpace } = useSpace();
  const tab = (params.get("tab") as Tab) || "public";

  const [items, setItems] = useState<Requirement[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Monotonic token: fast tab-mashing fires overlapping IPC calls whose
  // responses can arrive out of order. Only the latest request is allowed
  // to write setItems, so a stale tab's result never lands under the
  // current tab header.
  const reqTokenRef = useRef(0);

  const refresh = async () => {
    const token = ++reqTokenRef.current;
    setErr(null);
    try {
      let list: Requirement[];
      if (tab === "public") {
        list = await invoke<Requirement[]>("list_public_pool");
        list = list.filter((r) => !r.assignees?.length); // truly public — no explicit assignees
      } else if (tab === "mine") {
        list = await invoke<Requirement[]>("list_my", { assignedToMe: true });
        list = list.filter((r) => ["ready", "claimed", "doing", "revision_requested"].includes(r.status));
      } else if (tab === "active") {
        list = await invoke<Requirement[]>("list_my", { assignedToMe: true });
        list = list.filter((r) => ["claimed", "doing"].includes(r.status));
      } else if (tab === "revision") {
        list = await invoke<Requirement[]>("list_my", { assignedToMe: true });
        list = list.filter((r) => r.status === "revision_requested");
      } else {
        list = await invoke<Requirement[]>("list_my", { assignedToMe: true });
        list = list.filter((r) => ["delivered", "accepted"].includes(r.status));
      }
      if (token !== reqTokenRef.current) return; // a newer refresh superseded us
      list.sort((a, b) => (a.due_at || "").localeCompare(b.due_at || ""));
      setItems(list);
    } catch (e: any) {
      if (token !== reqTokenRef.current) return;
      setErr(String(e));
      setItems([]);
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [tab]);

  // Live-refresh on requirement lifecycle events. The Rust client forwards the
  // global `all` SSE topic as `push-event`; without this the "在抓" tab never
  // showed newly-dispatched work appearing (the toast fired but the list stayed
  // stale until a manual refresh). requirement.ready / requirement.updated both
  // arrive via `all`. Debounced implicitly by refresh's own token guard.
  useEvent<{ event: string }>("push-event", (p) => {
    if (p?.event === "requirement.ready" || p?.event === "requirement.updated") {
      refresh();
    }
  });

  const title = useMemo(() => ({
    public: "在抓",
    mine: "找我的",
    active: "进行中",
    revision: "待返工",
    delivered: "近期交付",
  }[tab]), [tab]);

  const claim = async (id: string) => {
    try {
      await invoke("claim", { reqId: id });
      toast({ title: "已接单", tone: "success" });
      refresh();
    } catch (e: any) {
      toast({ title: "接单失败", description: String(e), tone: "error" });
    }
  };

  const startDoing = async (id: string) => {
    try {
      await invoke("patch_status", { reqId: id, status: "doing" });
      toast({ title: "开始做了", tone: "info" });
      refresh();
    } catch (e: any) {
      toast({ title: "状态切换失败", description: String(e), tone: "error" });
    }
  };

  return (
    <div className="flex-1 p-6 overflow-auto" style={{ viewTransitionName: "yqgl-hub" }}>
      <header className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-h2 text-ink">{title}</h1>
          <p className="text-body-sm text-ink-muted mt-1">
            {items == null ? "加载中…" : `${items.length} 条`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={refresh}>刷新</Button>
          <Button variant="secondary" size="sm" onClick={() => setParams({})}>清除过滤</Button>
        </div>
      </header>

      {err && <div className="glass p-4 text-error mb-4">{err}</div>}

      {items == null ? (
        <div className="space-y-3">
          <Skeleton height="h-24" rounded="md" />
          <Skeleton height="h-24" rounded="md" />
          <Skeleton height="h-24" rounded="md" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Inbox className="h-8 w-8" />}
          title={
            tab === "public" ? "公共池暂时没有新单" :
            tab === "mine" ? "没人指派活给你" :
            tab === "active" ? "手上没有进行中的活" :
            tab === "revision" ? "没有待返工的活" :
            "近期没有交付记录"
          }
          description={
            tab === "public" ? "等队友把需求投递过来。或者去派活面板自己起一条。" :
            tab === "mine" ? "可以去「在抓」看看公共池里有没有合适的活。" :
            tab === "active" ? "去「找我的」或「在抓」看看，挑一条开做。" :
            tab === "revision" ? "你目前没有需要返工的需求。" :
            "完成的需求会出现在这里。"
          }
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button variant="secondary" size="sm" leftIcon={<RefreshCw className="h-4 w-4" />} onClick={refresh}>
                刷新
              </Button>
              {(tab === "mine" || tab === "active") && (
                <Button variant="secondary" size="sm" onClick={() => setParams({ tab: "public" })}>
                  去「在抓」逛逛
                </Button>
              )}
              {tab === "public" && (
                <Button
                  variant="accent"
                  size="sm"
                  leftIcon={<Plus className="h-4 w-4" />}
                  onClick={() => { setSpace("dispatch"); nav("/r/new"); }}
                >
                  我自己起一条
                </Button>
              )}
              {tab === "delivered" && (
                <Button variant="secondary" size="sm" leftIcon={<Sparkles className="h-4 w-4" />} onClick={() => setParams({ tab: "active" })}>
                  看进行中的活
                </Button>
              )}
            </div>
          }
        />
      ) : (
        <div className="space-y-3">
          {items.map((r) => (
            <TaskCard
              key={r.id}
              req={r}
              action={
                r.status === "ready" ? (
                  <Button variant="accent" size="sm" onClick={(e) => { e.stopPropagation(); claim(r.id); }}>
                    {tab === "public" ? "抢这单" : "接这单"}
                  </Button>
                ) : r.status === "claimed" ? (
                  <Button variant="accent" size="sm" onClick={(e) => { e.stopPropagation(); startDoing(r.id); }}>
                    开始做
                  </Button>
                ) : null
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
