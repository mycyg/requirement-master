import { useEffect, useMemo, useState } from "react";
import { CalendarDays, Clock3, ListChecks, Plus, Trash2, Users } from "lucide-react";
import { api } from "@/lib/api";
import type { ScheduleEvent, UserOption } from "@/lib/types";

type ViewMode = "month" | "week" | "list";

function isoLocal(value: string): string {
  return new Date(value).toISOString();
}

function localInput(value: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

function eventDate(value: string): Date {
  return new Date(value + (value.endsWith("Z") ? "" : "Z"));
}

function tone(event: ScheduleEvent): string {
  if (event.event_type === "requirement_due") {
    const due = eventDate(event.end_at).getTime();
    if (due < Date.now()) return "border-red-200 bg-red-50 text-red-700";
    if (eventDate(event.end_at).toDateString() === new Date().toDateString()) return "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]";
    return "border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]";
  }
  return "border-stone-200 bg-[#fffdf8] text-stone-700";
}

export function CalendarPage() {
  const [view, setView] = useState<ViewMode>("week");
  const [events, setEvents] = useState<ScheduleEvent[]>([]);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [title, setTitle] = useState("");
  const [endAt, setEndAt] = useState(localInput(new Date(Date.now() + 60 * 60 * 1000)));
  const [participantIds, setParticipantIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    const start = new Date();
    start.setDate(start.getDate() - 31);
    const end = new Date();
    end.setDate(end.getDate() + 62);
    const [nextEvents, nextUsers] = await Promise.all([
      api.listCalendarEvents({ start: start.toISOString(), end: end.toISOString() }),
      api.listUsers(""),
    ]);
    setEvents(nextEvents.sort((a, b) => a.end_at.localeCompare(b.end_at)));
    setUsers(nextUsers);
  };

  useEffect(() => { load().catch((e) => setErr(String(e))); }, []);

  const visibleEvents = useMemo(() => {
    const now = new Date();
    const start = new Date(now);
    if (view === "week") start.setDate(now.getDate() - now.getDay() + 1);
    if (view === "month") start.setDate(1);
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(start.getDate() + (view === "month" ? 42 : view === "week" ? 7 : 365));
    if (view === "list") return events;
    return events.filter((e) => {
      const t = eventDate(e.end_at).getTime();
      return t >= start.getTime() && t <= end.getTime();
    });
  }, [events, view]);

  const create = async () => {
    if (!title.trim() || !endAt) return;
    setBusy(true); setErr(null);
    try {
      await api.createCalendarEvent({
        title: title.trim(),
        end_at: isoLocal(endAt),
        participant_user_ids: participantIds,
      });
      setTitle("");
      setParticipantIds([]);
      await load();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (event: ScheduleEvent) => {
    setBusy(true); setErr(null);
    try {
      await api.deleteCalendarEvent(event.id);
      await load();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="app-container">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">Calendar</p>
          <h1 className="mt-2 flex items-center gap-2 text-3xl font-semibold tracking-tight text-stone-950">
            <CalendarDays className="h-7 w-7 text-stone-500" aria-hidden="true" />
            日程表
          </h1>
          <p className="mt-2 text-xs text-stone-500">需求 DDL 和预约事项都在这里，防止“明天要”变成“昨天就要”。</p>
        </div>
        <div className="flex overflow-hidden rounded-lg border border-stone-300 bg-[#fffdf8]">
          {(["week", "month", "list"] as ViewMode[]).map((mode) => (
            <button
              key={mode}
              className={`min-h-9 px-3 text-xs font-medium ${view === mode ? "bg-stone-950 text-[#fffdf8]" : "text-stone-600 hover:bg-stone-900/5"}`}
              onClick={() => setView(mode)}
            >
              {mode === "week" ? "周" : mode === "month" ? "月" : "列表"}
            </button>
          ))}
        </div>
      </header>

      <div className="mt-6 grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <section className="paper-surface p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-900">
            <Plus className="h-4 w-4 text-stone-500" aria-hidden="true" />
            预约日程
          </h2>
          <div className="mt-4 space-y-3">
            <input className="field" placeholder="比如：和接单人开个小会" value={title} onChange={(e) => setTitle(e.target.value)} />
            <input className="field" type="datetime-local" value={endAt} onChange={(e) => setEndAt(e.target.value)} />
            <div className="max-h-44 overflow-auto rounded-lg border border-stone-200 bg-[#fffdf8] p-2 scrollbar-thin-warm">
              {users.map((u) => (
                <label key={u.id} className="flex min-h-8 items-center gap-2 rounded-md px-2 text-xs hover:bg-stone-900/5">
                  <input
                    type="checkbox"
                    checked={participantIds.includes(u.id)}
                    onChange={(e) => {
                      setParticipantIds((xs) => e.target.checked ? [...xs, u.id] : xs.filter((id) => id !== u.id));
                    }}
                  />
                  <span className={`h-2 w-2 rounded-full ${u.is_online ? "bg-[#4f7d45]" : "bg-stone-300"}`} />
                  <span className="truncate">{u.nickname}</span>
                </label>
              ))}
            </div>
            <button className="button-primary w-full" disabled={busy || !title.trim()} onClick={create}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              {busy ? "保存中..." : "保存日程"}
            </button>
          </div>
        </section>

        <section className="paper-surface min-h-[520px] p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-900">
              <ListChecks className="h-4 w-4 text-stone-500" aria-hidden="true" />
              {view === "week" ? "本周事项" : view === "month" ? "本月事项" : "全部事项"}
            </h2>
            <span className="pill">{visibleEvents.length} 件</span>
          </div>
          {err && <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
          <div className={view === "month" ? "grid gap-2 md:grid-cols-2 2xl:grid-cols-3" : "space-y-2"}>
            {visibleEvents.length === 0 && <div className="empty-state">这段时间没有日程。</div>}
            {visibleEvents.map((event) => (
              <article key={event.id} className={`rounded-lg border p-3 ${tone(event)}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="break-words text-sm font-semibold">{event.title}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs opacity-80">
                      <span className="inline-flex items-center gap-1.5">
                        <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                        {eventDate(event.end_at).toLocaleString("zh-CN", { hour12: false })}
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <Users className="h-3.5 w-3.5" aria-hidden="true" />
                        {event.participant_user_ids.length || 1} 人
                      </span>
                    </div>
                  </div>
                  {event.event_type !== "requirement_due" && (
                    <button className="button-ghost min-h-8 w-8 px-0" disabled={busy} title="删除" onClick={() => remove(event)}>
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  )}
                </div>
                {event.description && <p className="mt-2 text-xs leading-5 opacity-80">{event.description}</p>}
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
