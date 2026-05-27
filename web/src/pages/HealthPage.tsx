import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Activity, AlertTriangle, CheckCircle2, Filter, HeartPulse, TimerReset } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "@/lib/api";
import type { Project, ProjectHealth } from "@/lib/types";

function scoreTone(score: number) {
  if (score >= 80) return "text-[#4e7146]";
  if (score >= 60) return "text-[#8a5d10]";
  return "text-red-700";
}

export function HealthPage() {
  const [searchParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(searchParams.get("project_id") || "");
  const [rows, setRows] = useState<ProjectHealth[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const current = useMemo(() => rows.find((row) => row.project_id === projectId) || null, [rows, projectId]);

  useEffect(() => {
    Promise.all([api.listProjects(), api.projectHealth()])
      .then(([projectRows, healthRows]) => {
        setProjects(projectRows);
        setRows(healthRows);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  const displayRows = projectId && current ? [current] : rows;
  const avgScore = rows.length ? Math.round(rows.reduce((sum, row) => sum + row.score, 0) / rows.length) : 100;
  const risky = rows.filter((row) => row.risk_level === "risk").length;
  const overdue = rows.reduce((sum, row) => sum + row.overdue_count, 0);

  return (
    <main className="app-container">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">Project Health</p>
          <h1 className="mt-2 text-3xl font-semibold text-stone-950">项目健康度</h1>
          <p className="mt-2 max-w-2xl text-sm text-stone-500">健康分只负责敲桌子，不会偷偷改需求状态。风险预警和效率统计分开看。</p>
        </div>
        <label className="flex min-w-[260px] items-center gap-2">
          <Filter className="h-4 w-4 text-stone-400" aria-hidden="true" />
          <select className="select-field" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">全部项目</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
      </div>

      <div className="mt-6 grid gap-3 md:grid-cols-4">
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">平均健康分</div>
          <div className={`mt-1 text-2xl font-semibold ${scoreTone(avgScore)}`}>{avgScore}</div>
        </div>
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">风险项目</div>
          <div className="mt-1 text-2xl font-semibold text-stone-950">{risky}</div>
        </div>
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">逾期需求</div>
          <div className="mt-1 text-2xl font-semibold text-stone-950">{overdue}</div>
        </div>
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">项目数</div>
          <div className="mt-1 text-2xl font-semibold text-stone-950">{rows.length}</div>
        </div>
      </div>

      {err && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
      <div className="mt-6 grid gap-4 xl:grid-cols-2">
        {displayRows.map((row) => (
          <article key={row.project_id} className="paper-surface p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <HeartPulse className={`h-5 w-5 ${scoreTone(row.score)}`} aria-hidden="true" />
                  <h2 className="truncate text-lg font-semibold text-stone-950">{row.project_name}</h2>
                  <span className="pill">{row.risk_level}</span>
                </div>
                <p className="mt-1 font-mono text-xs text-stone-400">{row.project_slug}</p>
              </div>
              <div className={`text-4xl font-semibold ${scoreTone(row.score)}`}>{row.score}</div>
            </div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-stone-200">
              <div className={`h-full rounded-full ${row.score >= 80 ? "bg-[#6f7f6b]" : row.score >= 60 ? "bg-[#c96442]" : "bg-red-700"}`} style={{ width: `${row.score}%` }} />
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-3">
              <Metric icon={AlertTriangle} label="风险" value={row.risks.length} />
              <Metric icon={TimerReset} label="30天吞吐" value={row.throughput_30d} />
              <Metric icon={Activity} label="当前负载" value={`${row.load_hours}h`} />
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="paper-panel p-3">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">风险预警</div>
                {row.risks.length === 0 ? (
                  <div className="flex items-center gap-2 text-sm text-[#4e7146]"><CheckCircle2 className="h-4 w-4" />目前没有明显风险</div>
                ) : (
                  <ul className="space-y-1 text-sm text-stone-700">
                    {row.risks.map((risk) => <li key={risk}>· {risk}</li>)}
                  </ul>
                )}
              </div>
              <div className="paper-panel p-3">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">效率统计</div>
                <dl className="grid grid-cols-2 gap-2 text-sm">
                  <dt className="text-stone-500">活跃</dt><dd className="text-right font-medium">{row.active_count}</dd>
                  <dt className="text-stone-500">已完成</dt><dd className="text-right font-medium">{row.accepted_count}</dd>
                  <dt className="text-stone-500">平均周期</dt><dd className="text-right font-medium">{row.avg_cycle_hours ? `${row.avg_cycle_hours}h` : "-"}</dd>
                  <dt className="text-stone-500">需求变动</dt><dd className="text-right font-medium">{row.change_count}</dd>
                </dl>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link className="button-secondary min-h-9 px-3 py-1.5 text-xs" to={`/p/${row.project_id}`}>需求</Link>
              <Link className="button-secondary min-h-9 px-3 py-1.5 text-xs" to={`/planning?project_id=${row.project_id}`}>排期</Link>
              <Link className="button-secondary min-h-9 px-3 py-1.5 text-xs" to={`/knowledge?project_id=${row.project_id}`}>知识库</Link>
            </div>
          </article>
        ))}
      </div>
    </main>
  );
}

function Metric({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-[#fffdf8] p-3">
      <div className="flex items-center gap-2 text-xs text-stone-500">
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold text-stone-950">{value}</div>
    </div>
  );
}
