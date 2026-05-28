import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarOff, Plus } from "lucide-react";
import { Button, Card, EmptyState, Badge } from "@yqgl/shared";
import { clientJson } from "@/lib/tauri";

type Event = {
  id: string;
  title: string;
  description: string | null;
  event_type: "custom" | "requirement_due";
  requirement_id: string | null;
  project_id: string | null;
  start_at: string | null;
  end_at: string;
  participant_user_ids: string[];
};

function startOfWeek(d: Date): Date {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Monday=0
  x.setHours(0, 0, 0, 0);
  x.setDate(x.getDate() - day);
  return x;
}

export function Calendar() {
  const nav = useNavigate();
  const [events, setEvents] = useState<Event[]>([]);
  const [anchor, setAnchor] = useState(new Date());

  useEffect(() => {
    const start = startOfWeek(anchor);
    const end = new Date(start);
    end.setDate(end.getDate() + 7);
    const qs = new URLSearchParams({
      start: start.toISOString(),
      end: end.toISOString(),
      mine: "true",
    });
    clientJson<Event[]>(`/api/calendar/events?${qs}`)
      .then((rows) => setEvents(Array.isArray(rows) ? rows : []))
      .catch(() => setEvents([]));
  }, [anchor]);

  const start = startOfWeek(anchor);
  const days: Date[] = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return d;
  });

  return (
    <div className="flex-1 p-6 overflow-auto">
      <header className="flex items-center justify-between mb-4">
        <h1 className="text-h2 text-ink">我的日程</h1>
        <div className="flex items-center gap-2 text-body-sm">
          <button onClick={() => setAnchor(new Date(anchor.getTime() - 7 * 86400_000))} className="h-8 px-3 rounded-sm hover:bg-accent-soft">← 上周</button>
          <button onClick={() => setAnchor(new Date())} className="h-8 px-3 rounded-sm hover:bg-accent-soft">今天</button>
          <button onClick={() => setAnchor(new Date(anchor.getTime() + 7 * 86400_000))} className="h-8 px-3 rounded-sm hover:bg-accent-soft">下周 →</button>
        </div>
      </header>

      <div className="grid grid-cols-7 gap-2">
        {days.map((d) => {
          const dayEvents = events.filter((e) => {
            const ed = new Date(e.end_at);
            return ed.toDateString() === d.toDateString();
          });
          const isToday = d.toDateString() === new Date().toDateString();
          return (
            <Card key={d.toISOString()} padding="sm" className={isToday ? "ring-2 ring-accent" : ""}>
              <div className="text-caption text-ink-muted mb-1">{d.toLocaleDateString("zh-CN", { weekday: "short", month: "numeric", day: "numeric" })}</div>
              <div className="min-h-[120px] space-y-1">
                {dayEvents.length === 0 && <div className="text-caption text-ink-faint">—</div>}
                {dayEvents.map((e) => {
                  const ed = new Date(e.end_at);
                  const overdue = ed < new Date() && e.event_type === "requirement_due";
                  return (
                    <button
                      key={e.id}
                      onClick={() => e.requirement_id && nav(`/r/${e.requirement_id}`)}
                      className={`w-full text-left p-1.5 rounded-xs text-caption ${
                        e.event_type === "requirement_due"
                          ? overdue ? "bg-error-soft text-error" : "bg-warn-soft text-warn"
                          : "bg-info-soft text-info"
                      }`}
                    >
                      <div className="font-medium">{ed.getHours().toString().padStart(2, "0")}:{ed.getMinutes().toString().padStart(2, "0")}</div>
                      <div className="truncate">{e.title}</div>
                    </button>
                  );
                })}
              </div>
            </Card>
          );
        })}
      </div>

      <Card className="mt-5">
        <h2 className="text-h4 text-ink mb-3">本周事项一览</h2>
        {events.length === 0 ? (
          <EmptyState
            icon={<CalendarOff className="h-8 w-8" />}
            title="本周没有日程"
            description="需求的截止时间会自动出现在这里；也可以手动创建会议或自定义事项。"
            action={
              <Button
                variant="secondary"
                size="sm"
                leftIcon={<Plus className="h-4 w-4" />}
                onClick={() => nav("/r/new")}
              >
                起一条需求（自带截止）
              </Button>
            }
          />
        ) : (
          <div className="space-y-2">
            {events.map((e) => (
              <div key={e.id} className="glass-sunken p-3 flex items-center gap-3">
                <Badge tone={e.event_type === "requirement_due" ? "warn" : "info"} size="xs">
                  {e.event_type === "requirement_due" ? "截止" : "会议"}
                </Badge>
                <div className="flex-1 min-w-0">
                  <div className="text-body text-ink truncate">{e.title}</div>
                  <div className="text-caption text-ink-muted">{new Date(e.end_at).toLocaleString("zh-CN", { hour12: false }).slice(5, 16)}</div>
                </div>
                {e.requirement_id && (
                  <button className="text-caption text-accent hover:underline" onClick={() => nav(`/r/${e.requirement_id}`)}>
                    打开 →
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
