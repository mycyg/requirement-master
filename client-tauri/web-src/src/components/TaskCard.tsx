import { useNavigate } from "react-router-dom";
import { CalendarClock } from "lucide-react";
import { Card, AvatarGroup, StatusBadge, Progress, Badge } from "@yqgl/shared";
import type { Requirement } from "@yqgl/shared";

export function TaskCard({ req, action }: { req: Requirement; action?: React.ReactNode }) {
  const nav = useNavigate();
  const lead = req.assignees?.find((a) => a.role === "lead");
  const collabs = req.assignees?.filter((a) => a.role !== "lead") ?? [];
  const users = [
    ...(lead ? [{ nickname: lead.nickname }] : []),
    ...collabs.map((c) => ({ nickname: c.nickname })),
  ];

  const due = req.due_at ? new Date(req.due_at) : null;
  const overdue = !!(due && due.getTime() < Date.now());
  const dueTone =
    overdue ? "error" :
    due && (due.getTime() - Date.now()) < 24 * 3600 * 1000 ? "warn" : "info";

  return (
    <Card
      interactive
      padding="md"
      className="anim-fade-up"
      onClick={() => nav(`/r/${req.id}`)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-caption text-ink-faint">{req.code}</span>
            <StatusBadge status={req.status} size="xs" />
            {req.priority === "urgent" && <Badge tone="error" size="xs">紧急</Badge>}
            {req.priority === "high" && <Badge tone="warn" size="xs">重要</Badge>}
          </div>
          <h3 className="text-h4 text-ink truncate">{req.title || "(整理中)"}</h3>
        </div>
        {users.length > 0 && <AvatarGroup users={users} size="sm" />}
      </div>

      <div className="mt-3 flex items-center gap-3 text-caption text-ink-muted">
        <span>{req.project_slug}</span>
        {due && (
          <Badge tone={dueTone as any} size="xs">
            <CalendarClock className="h-3 w-3" />
            {overdue ? `已逾期 ${humanDelta(due)}` : `截止 ${due.toLocaleString("zh-CN", { hour12: false }).slice(5, 16)}`}
          </Badge>
        )}
      </div>

      <div className="mt-3">
        <Progress value={progressFor(req.status)} size="sm" tone="accent" />
      </div>

      {action && <div className="mt-3 flex justify-end">{action}</div>}
    </Card>
  );
}

function progressFor(status: string): number {
  const map: Record<string, number> = {
    draft: 0, clarifying: 8, summary_ready: 18, ready: 25, claimed: 30,
    doing: 55, ai_processing: 60, delivery_doc_pending: 80, delivered: 90,
    revision_requested: 70, accepted: 100, cancelled: 0,
  };
  return map[status] ?? 0;
}

function humanDelta(d: Date): string {
  const ms = Date.now() - d.getTime();
  const mins = Math.round(ms / 60000);
  if (Math.abs(mins) < 60) return `${Math.abs(mins)} 分钟`;
  const hrs = Math.round(mins / 60);
  if (Math.abs(hrs) < 48) return `${Math.abs(hrs)} 小时`;
  return `${Math.round(hrs / 24)} 天`;
}
