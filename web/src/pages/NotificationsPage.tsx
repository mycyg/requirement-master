import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, CheckCheck, ExternalLink, Inbox } from "lucide-react";
import { api } from "@/lib/api";
import type { Notification as AppNotification } from "@/lib/types";

function target(to: string | null) {
  if (!to) return null;
  return to.startsWith("/") ? (
    <Link className="link-subtle text-xs" to={to}>去看看<ExternalLink className="h-3 w-3" /></Link>
  ) : (
    <a className="link-subtle text-xs" href={to}>去看看<ExternalLink className="h-3 w-3" /></a>
  );
}

export function NotificationsPage() {
  const [status, setStatus] = useState<"unread" | "all">("unread");
  const [rows, setRows] = useState<AppNotification[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    setBusy(true); setErr(null);
    try {
      setRows(await api.listNotifications(status));
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(); }, [status]);

  const markRead = async (id: string) => {
    await api.readNotification(id);
    await load();
  };
  const readAll = async () => {
    await api.readAllNotifications();
    await load();
  };

  const unreadCount = rows.filter((row) => !row.read_at).length;

  return (
    <main className="app-container max-w-5xl">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">通知中心</p>
          <h1 className="mt-2 text-3xl font-semibold text-stone-950">通知中心</h1>
          <p className="mt-2 text-sm text-stone-500">指派、DDL、阻塞、返工、Agent 完成，全在这里排队等你审判。</p>
        </div>
        <button className="button-secondary" disabled={busy || unreadCount === 0} onClick={readAll}>
          <CheckCheck className="h-4 w-4" aria-hidden="true" />
          全部已读
        </button>
      </div>

      <div className="mt-6 flex gap-2 border-b border-stone-200">
        <button className={`tab-button ${status === "unread" ? "border-stone-950 text-stone-950" : "border-transparent text-stone-500"}`} onClick={() => setStatus("unread")}>
          <Bell className="h-4 w-4" aria-hidden="true" />
          未读
        </button>
        <button className={`tab-button ${status === "all" ? "border-stone-950 text-stone-950" : "border-transparent text-stone-500"}`} onClick={() => setStatus("all")}>
          <Inbox className="h-4 w-4" aria-hidden="true" />
          全部
        </button>
      </div>

      {err && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
      <section className="paper-surface mt-6 divide-y divide-stone-200/80 overflow-hidden">
        {rows.length === 0 ? (
          <div className="empty-state m-4">暂时没有通知。系统终于学会闭嘴了。</div>
        ) : rows.map((row) => (
          <article key={row.id} className={`p-4 ${row.read_at ? "bg-[#fffdf8]/60" : "bg-[#fffdf8]"}`}>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`pill ${row.severity === "high" || row.severity === "urgent" ? "border-red-200 bg-red-50 text-red-700" : ""}`}>
                    {row.severity}
                  </span>
                  <span className="text-xs text-stone-400">{new Date(row.created_at).toLocaleString("zh-CN", { hour12: false })}</span>
                </div>
                <h2 className="mt-2 break-words text-sm font-semibold text-stone-950">{row.title}</h2>
                {row.body && <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-stone-600">{row.body}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {target(row.target_url)}
                {!row.read_at && (
                  <button className="button-secondary min-h-8 px-3 py-1 text-xs" disabled={busy} onClick={() => markRead(row.id)}>
                    已读
                  </button>
                )}
              </div>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
