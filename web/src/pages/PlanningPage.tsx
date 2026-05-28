import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, CalendarClock, Filter, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import type { Project, UserWorkload } from "@/lib/types";

function tone(load: number) {
  if (load >= 100) return "bg-red-700";
  if (load >= 75) return "bg-[#c96442]";
  if (load >= 45) return "bg-[#59758f]";
  return "bg-[#6f7f6b]";
}

export function PlanningPage() {
  const [searchParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(searchParams.get("project_id") || "");
  const [rows, setRows] = useState<UserWorkload[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const selectedProject = useMemo(() => projects.find((item) => item.id === projectId), [projects, projectId]);

  const load = async () => {
    setLoading(true); setErr(null);
    try {
      const [projectRows, workloadRows] = await Promise.all([
        api.listProjects(),
        api.workload({ project_id: projectId || null }),
      ]);
      setProjects(projectRows);
      setRows(workloadRows);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [projectId]);

  const totalHours = rows.reduce((sum, row) => sum + row.estimate_hours, 0);
  const overloaded = rows.filter((row) => row.load_percent >= 100).length;
  const blocked = rows.reduce((sum, row) => sum + row.blocked_count, 0);

  return (
    <main className="app-container">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">资源排期</p>
          <h1 className="mt-2 text-3xl font-semibold text-stone-950">排期 / 负载</h1>
          <p className="mt-2 max-w-2xl text-sm text-stone-500">按接单人、DDL、估算工时和接单状态看负载。忙碌状态按半天产能算，挺现实，也挺扎心。</p>
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
          <div className="text-xs text-stone-500">范围</div>
          <div className="mt-1 truncate text-xl font-semibold text-stone-950">{selectedProject?.name || "全部项目"}</div>
        </div>
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">估算工时</div>
          <div className="mt-1 text-xl font-semibold text-stone-950">{totalHours.toFixed(1)}h</div>
        </div>
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">满载人员</div>
          <div className="mt-1 text-xl font-semibold text-stone-950">{overloaded}</div>
        </div>
        <div className="paper-surface p-4">
          <div className="text-xs text-stone-500">阻塞</div>
          <div className="mt-1 text-xl font-semibold text-stone-950">{blocked}</div>
        </div>
      </div>

      {err && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}
      {loading ? (
        <div className="empty-state mt-6">加载排期...</div>
      ) : (
        <div className="mt-6 grid gap-4 2xl:grid-cols-2">
          {rows.map((row) => (
            <article key={row.user_id} className="paper-surface p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${row.is_online ? "bg-[#6f7f6b]" : "bg-stone-300"}`} />
                    <h2 className="truncate text-base font-semibold text-stone-950">{row.nickname}</h2>
                    <span className="pill">{row.availability_status === "free" ? "空闲" : row.availability_status === "busy" ? "忙碌" : row.availability_text || "自定义"}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-stone-500">
                    <span>{row.task_count} 个任务</span>
                    <span>{row.estimate_hours} / {row.capacity_hours}h</span>
                    {row.overdue_count > 0 && <span className="text-red-700">{row.overdue_count} 逾期</span>}
                    {row.blocked_count > 0 && <span className="text-red-700">{row.blocked_count} 阻塞</span>}
                    {row.due_this_week_count > 0 && <span>{row.due_this_week_count} 本周到期</span>}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-semibold text-stone-950">{row.load_percent}%</div>
                  <div className="text-xs text-stone-400">load</div>
                </div>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-stone-200">
                <div className={`h-full rounded-full ${tone(row.load_percent)}`} style={{ width: `${Math.min(140, row.load_percent)}%` }} />
              </div>
              <div className="mt-4 space-y-2">
                {row.requirements.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-stone-300 p-3 text-sm text-stone-400">
                    <UserRound className="mr-1 inline h-4 w-4" aria-hidden="true" />
                    暂时没排上活。
                  </div>
                ) : row.requirements.map((req) => (
                  <Link key={req.id} to={`/r/${req.id}`} className="block rounded-lg border border-stone-200 bg-[#fffdf8] p-3 text-sm transition hover:border-stone-400">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="font-medium text-stone-950"><span className="mr-2 font-mono text-xs text-stone-400">{req.code}</span>{req.title || "未命名需求"}</div>
                        <div className="mt-1 flex flex-wrap gap-2 text-xs text-stone-500">
                          <span>{req.status}</span>
                          {req.due_at && <span><CalendarClock className="mr-1 inline h-3 w-3" />{new Date(req.due_at).toLocaleString("zh-CN", { hour12: false })}</span>}
                          {req.blocked_reason && <span className="text-red-700"><AlertTriangle className="mr-1 inline h-3 w-3" />阻塞</span>}
                        </div>
                      </div>
                      {req.progress_percent != null && <span className="pill">{req.progress_percent}%</span>}
                    </div>
                  </Link>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
