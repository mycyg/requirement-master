import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell } from "lucide-react";
import { Button, Card, EmptyState, Badge } from "@yqgl/shared";
import { useEvent } from "@/lib/tauri";

type Notif = {
  id: string;
  type: string;
  severity: string;
  title: string;
  body: string | null;
  target_url: string | null;
  requirement_id: string | null;
  read_at: string | null;
  created_at: string;
};

export function Inbox() {
  const nav = useNavigate();
  const [items, setItems] = useState<Notif[]>([]);
  const [view, setView] = useState<"unread" | "all">("unread");

  const refresh = async () => {
    try {
      const list = await fetch(`/api/notifications?status=${view}`, {
        credentials: "include",
        headers: { "X-YQGL-Client-Token": "" }, // header is added by Rust client; here we just call browser fetch
      }).then((r) => r.json()) as Notif[];
      setItems(list);
    } catch {
      // fallback: invoke a future command if introduced
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [view]);

  useEvent("notification", () => refresh());

  const markRead = async (id: string) => {
    await fetch(`/api/notifications/${id}/read`, { method: "POST", credentials: "include" });
    refresh();
  };

  const readAll = async () => {
    await fetch(`/api/notifications/read-all`, { method: "POST", credentials: "include" });
    refresh();
  };

  return (
    <div className="flex-1 p-6 overflow-auto">
      <header className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-h2 text-ink flex items-center gap-2"><Bell className="h-5 w-5" /> 通知</h1>
          <Badge tone={items.length ? "accent" : "neutral"} size="xs">{items.length}</Badge>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setView("unread")}
            className={`h-8 px-3 rounded-sm text-caption ${view === "unread" ? "bg-accent-soft text-ink" : "text-ink-muted hover:text-ink"}`}
          >
            未读
          </button>
          <button
            onClick={() => setView("all")}
            className={`h-8 px-3 rounded-sm text-caption ${view === "all" ? "bg-accent-soft text-ink" : "text-ink-muted hover:text-ink"}`}
          >
            全部
          </button>
          {view === "unread" && items.length > 0 && (
            <Button size="sm" variant="secondary" onClick={readAll}>全部已读</Button>
          )}
        </div>
      </header>

      {items.length === 0 ? (
        <EmptyState title={view === "unread" ? "没有未读通知" : "暂无通知"} />
      ) : (
        <div className="space-y-2">
          {items.map((n) => (
            <Card key={n.id} interactive padding="sm" onClick={() => {
              if (n.requirement_id) nav(`/r/${n.requirement_id}`);
              if (!n.read_at) markRead(n.id);
            }}>
              <div className="flex items-start gap-3">
                <Badge tone={
                  n.severity === "high" ? "warn" :
                  n.severity === "urgent" ? "error" :
                  "info"
                } size="xs">
                  {n.type}
                </Badge>
                <div className="flex-1 min-w-0">
                  <div className="text-body text-ink truncate">{n.title}</div>
                  {n.body && <div className="text-caption text-ink-muted mt-0.5 line-clamp-2">{n.body}</div>}
                  <div className="text-caption text-ink-faint mt-1">
                    {new Date(n.created_at).toLocaleString("zh-CN", { hour12: false }).slice(5, 16)}
                  </div>
                </div>
                {!n.read_at && (
                  <button
                    className="text-caption text-accent hover:underline"
                    onClick={(e) => { e.stopPropagation(); markRead(n.id); }}
                  >
                    已读
                  </button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
