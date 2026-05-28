import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Progress, EmptyState, Badge } from "@yqgl/shared";
import { clientJson } from "@/lib/tauri";

type Workload = {
  user_id: string;
  nickname: string;
  task_count: number;
  estimate_hours: number;
  capacity_hours: number;
  load_percent: number;
  overdue_count: number;
  blocked_count: number;
  due_this_week_count: number;
  requirements: { id: string; code: string; title: string | null; status: string; due_at: string | null; progress_percent: number | null; blocked_reason: string | null; }[];
};

export function MyWorkload() {
  const nav = useNavigate();
  const [mine, setMine] = useState<Workload | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      clientJson<Workload[]>("/api/planning/workload"),
      clientJson<{ id: string } | null>("/api/auth/me"),
    ]).then(([list, me]) => {
      const arr = Array.isArray(list) ? list : [];
      setMine(arr.find((w) => w.user_id === me?.id) ?? null);
    }).catch((e) => setErr(String(e)))
      .finally(() => setLoaded(true));
  }, []);

  if (!loaded) return <div className="flex-1 p-6">加载中…</div>;
  if (err) {
    return (
      <div className="flex-1 p-6">
        <h1 className="text-h2 text-ink mb-1">我的负载</h1>
        <div className="glass p-4 mt-4 text-error">{err}</div>
      </div>
    );
  }
  if (!mine) {
    return (
      <div className="flex-1 p-6">
        <h1 className="text-h2 text-ink mb-1">我的负载</h1>
        <div className="text-ink-muted mt-4">你目前还没有承接需求。</div>
      </div>
    );
  }

  const loadTone =
    mine.load_percent >= 100 ? "error" :
    mine.load_percent >= 80 ? "warn" :
    "success";

  return (
    <div className="flex-1 p-6 overflow-auto space-y-5">
      <h1 className="text-h2 text-ink">我的负载</h1>

      <Card variant="glass-strong" padding="lg">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-eyebrow text-ink-faint">本周负载</div>
            <div className="text-display text-ink mt-1">{mine.load_percent}%</div>
          </div>
          <div className="text-right text-body-sm text-ink-muted">
            估算 {mine.estimate_hours.toFixed(1)}h / 产能 {mine.capacity_hours.toFixed(1)}h
          </div>
        </div>
        <div className="mt-3">
          <Progress value={Math.min(140, mine.load_percent)} tone={loadTone as any} />
        </div>
        <div className="mt-4 grid grid-cols-3 gap-3 text-center">
          <div className="glass-sunken p-3">
            <div className="text-h3 text-ink">{mine.task_count}</div>
            <div className="text-caption text-ink-muted">在做</div>
          </div>
          <div className="glass-sunken p-3">
            <div className="text-h3 text-error">{mine.overdue_count}</div>
            <div className="text-caption text-ink-muted">逾期</div>
          </div>
          <div className="glass-sunken p-3">
            <div className="text-h3 text-warn">{mine.blocked_count}</div>
            <div className="text-caption text-ink-muted">阻塞</div>
          </div>
        </div>
        {mine.load_percent >= 100 && (
          <div className="mt-4 glass-sunken p-3 border border-error/30 text-error text-body-sm">
            本周已过载，建议婉拒新单或与 PM 协商工期。
          </div>
        )}
      </Card>

      <Card>
        <h2 className="text-h4 text-ink mb-3">我承接的需求</h2>
        {mine.requirements.length === 0 ? (
          <EmptyState title="目前没有承接的需求" />
        ) : (
          <div className="space-y-2">
            {mine.requirements.map((r) => (
              <button
                key={r.id}
                onClick={() => nav(`/r/${r.id}`)}
                className="w-full text-left glass-sunken p-3 hover:bg-accent-soft transition flex items-center gap-3"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-caption text-ink-faint">{r.code}</span>
                    <Badge size="xs" tone="info">{r.status}</Badge>
                    {r.blocked_reason && <Badge size="xs" tone="error">阻塞</Badge>}
                  </div>
                  <div className="text-body text-ink truncate">{r.title || "(整理中)"}</div>
                  {r.due_at && <div className="text-caption text-ink-muted mt-0.5">截止 {new Date(r.due_at).toLocaleString("zh-CN", { hour12: false }).slice(5, 16)}</div>}
                </div>
                <div className="w-32 shrink-0">
                  <Progress value={r.progress_percent ?? 0} size="sm" />
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
