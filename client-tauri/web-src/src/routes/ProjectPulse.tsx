import { useEffect, useState } from "react";
import { Card, EmptyState, Progress, Badge } from "@yqgl/shared";

type Health = {
  project_id: string;
  project_name: string;
  project_slug: string;
  score: number;
  risk_level: "healthy" | "watch" | "risk" | string;
  risks: string[];
  overdue_count: number;
  blocked_count: number;
  unclaimed_count: number;
  due_soon_count: number;
  revision_count: number;
  active_count: number;
  accepted_count: number;
  throughput_30d: number;
  avg_cycle_hours: number | null;
};

export function ProjectPulse() {
  const [list, setList] = useState<Health[] | null>(null);

  useEffect(() => {
    fetch("/api/project-health", { credentials: "include" })
      .then((r) => r.json())
      .then(setList)
      .catch(() => setList([]));
  }, []);

  if (!list) return <div className="flex-1 p-6">加载中…</div>;

  return (
    <div className="flex-1 p-6 overflow-auto">
      <h1 className="text-h2 text-ink mb-1">项目快报</h1>
      <p className="text-body-sm text-ink-muted mb-5">我参与项目的整体健康度。</p>

      {list.length === 0 ? (
        <EmptyState title="还没有项目" />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.map((h) => (
            <Card key={h.project_id} padding="md">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-h4 text-ink truncate">{h.project_name}</h3>
                <Badge tone={h.risk_level === "healthy" ? "success" : h.risk_level === "watch" ? "warn" : "error"} size="xs">
                  {h.risk_level === "healthy" ? "健康" : h.risk_level === "watch" ? "看护中" : "风险高"}
                </Badge>
              </div>
              <div className="mt-3">
                <div className="flex items-baseline justify-between text-caption text-ink-muted mb-1">
                  <span>健康分</span><span className="text-h3 text-ink">{h.score}</span>
                </div>
                <Progress
                  value={h.score}
                  tone={h.score >= 80 ? "success" : h.score >= 60 ? "warn" : "error"}
                />
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center text-caption">
                <div className="glass-sunken p-2">
                  <div className="text-h4 text-ink">{h.active_count}</div>
                  <div className="text-ink-faint">活跃</div>
                </div>
                <div className="glass-sunken p-2">
                  <div className="text-h4 text-success">{h.throughput_30d}</div>
                  <div className="text-ink-faint">30天交付</div>
                </div>
                <div className="glass-sunken p-2">
                  <div className="text-h4 text-error">{h.overdue_count}</div>
                  <div className="text-ink-faint">逾期</div>
                </div>
              </div>
              {h.risks.length > 0 && (
                <div className="mt-3 space-y-1 text-caption text-ink-muted">
                  {h.risks.slice(0, 3).map((r, i) => (
                    <div key={i} className="flex items-start gap-1">• <span className="flex-1">{r}</span></div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
