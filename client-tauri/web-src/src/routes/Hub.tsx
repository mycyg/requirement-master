import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { invoke } from "@/lib/tauri";
import { TaskCard } from "@/components/TaskCard";
import { Button, EmptyState, Skeleton, toast } from "@yqgl/shared";
import type { Requirement } from "@yqgl/shared";

type Tab = "public" | "mine" | "active" | "revision" | "delivered";

export function Hub() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "public";

  const [items, setItems] = useState<Requirement[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
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
      list.sort((a, b) => (a.due_at || "").localeCompare(b.due_at || ""));
      setItems(list);
    } catch (e: any) {
      setErr(String(e));
      setItems([]);
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [tab]);

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
    <div className="flex-1 p-6 overflow-auto">
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
          title="这里没有工单"
          description={
            tab === "public" ? "公开池里暂时没有等接的需求。" :
            tab === "mine" ? "暂时没有指派给你的需求。" :
            tab === "active" ? "你没有正在做的需求。可以去「找我的」或「在抓」看看。" :
            tab === "revision" ? "目前没有待返工的需求。" :
            "近期没有交付记录。"
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
