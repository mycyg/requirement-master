import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Archive, ArrowLeft, ArrowRight, CalendarClock, ClipboardList, HardDrive, HeartPulse, Mic2, Plus, RotateCcw, Search, Trash2, UserRound, Users } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import type { Project, Requirement } from "@/lib/types";
import { ProjectStateConfirm } from "@/components/ProjectStateConfirm";

type ProjectAction = "archive" | "delete" | "restore";

export function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [reqs, setReqs] = useState<Requirement[]>([]);
  const [action, setAction] = useState<{ project: Project; type: ProjectAction } | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const refresh = async () => {
    if (!id) return;
    const [nextProject, nextReqs] = await Promise.all([
      api.getProject(id),
      api.listRequirements({ project_id: id }),
    ]);
    setProject(nextProject);
    setReqs(nextReqs);
  };

  useEffect(() => { refresh(); }, [id]);

  if (!project) return <main className="narrow-container text-stone-500">加载中…</main>;

  const runProjectAction = async () => {
    if (!action) return;
    setActionBusy(true);
    setActionErr(null);
    try {
      if (action.type === "archive") await api.archiveProject(action.project.id);
      if (action.type === "delete") await api.deleteProject(action.project.id);
      if (action.type === "restore") await api.restoreProject(action.project.id);
      setAction(null);
      if (action.type === "delete") nav("/");
      else await refresh();
    } catch (e: any) {
      setActionErr(String(e));
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <main className="narrow-container">
      <Link to="/" className="link-subtle">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        全部项目
      </Link>
      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="eyebrow">Project</p>
          <h1 className="mt-2 break-words text-3xl font-semibold tracking-tight text-stone-950">{project.name}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            <p className="inline-flex items-center rounded-full border border-stone-200 bg-[#fffdf8] px-2.5 py-1 font-mono text-xs text-stone-500">{project.slug}</p>
            {project.archived && !project.deleted_at && <span className="pill border-[#e0c895] bg-[#fff7e2] text-[#8a5d10]">已归档</span>}
            {project.deleted_at && <span className="pill border-red-200 bg-red-50 text-red-700">回收站</span>}
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {!project.archived && !project.deleted_at && (
            <Link to={`/p/${project.id}/new`} className="button-primary">
              <Plus className="h-4 w-4" aria-hidden="true" />
              提一条新需求
            </Link>
          )}
          {!project.archived && !project.deleted_at && (
            <button className="button-secondary" onClick={() => setAction({ project, type: "archive" })}>
              <Archive className="h-4 w-4" aria-hidden="true" />
              归档
            </button>
          )}
          {(project.archived || project.deleted_at) && (
            <button className="button-primary" onClick={() => setAction({ project, type: "restore" })}>
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              恢复
            </button>
          )}
          {!project.deleted_at && (
            <button className="button-danger" onClick={() => setAction({ project, type: "delete" })}>
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              删除
            </button>
          )}
        </div>
      </div>
      <div className="mt-6 flex gap-2 border-b border-stone-200">
        <Link to={`/p/${project.id}`} className="tab-button border-stone-950 text-stone-950">
          <ClipboardList className="h-4 w-4" aria-hidden="true" />
          需求
        </Link>
        <Link to={`/p/${project.id}/drive`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
          <HardDrive className="h-4 w-4" aria-hidden="true" />
          网盘
        </Link>
        <Link to={`/p/${project.id}/meetings`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
          <Mic2 className="h-4 w-4" aria-hidden="true" />
          会议
        </Link>
        <Link to={`/knowledge?project_id=${project.id}`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
          <Search className="h-4 w-4" aria-hidden="true" />
          知识库
        </Link>
        <Link to={`/planning?project_id=${project.id}`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
          <Users className="h-4 w-4" aria-hidden="true" />
          排期
        </Link>
        <Link to={`/health?project_id=${project.id}`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
          <HeartPulse className="h-4 w-4" aria-hidden="true" />
          健康
        </Link>
      </div>

      <ul className="paper-surface mt-8 divide-y divide-stone-200/80 overflow-hidden">
        {reqs.length === 0 && (
          <li className="empty-state m-4">还没有需求</li>
        )}
        {reqs.map((r) => {
          const lead = r.assignees?.find((a) => a.role === "lead");
          const collaboratorCount = r.assignees?.filter((a) => a.role === "collaborator").length ?? 0;
          const statusProgress: Record<string, number> = {
            ready: 5, claimed: 15, doing: 45, ai_processing: 50, revision_requested: 60,
            delivery_doc_pending: 85, delivered: 90, accepted: 100, cancelled: 0,
          };
          const progress = statusProgress[r.status] ?? 0;
          return (
          <li key={r.id} className="group px-4 py-4 transition hover:bg-white sm:px-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <Link to={`/r/${r.id}`} className="flex min-w-0 items-start gap-2 font-semibold text-stone-950 hover:underline">
                  <ClipboardList className="mt-0.5 h-4 w-4 shrink-0 text-stone-400" aria-hidden="true" />
                  <span className="min-w-0 break-words">
                    <span className="mr-2 font-mono text-xs text-stone-500">{r.code}</span>
                    {r.title || r.raw_description?.slice(0, 60) || "(无标题)"}
                  </span>
                </Link>
                <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-400">
                  <span className="inline-flex items-center gap-1.5">
                    <UserRound className="h-3.5 w-3.5" aria-hidden="true" />
                    {r.submitter_nickname}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <Users className="h-3.5 w-3.5" aria-hidden="true" />
                    {lead ? `负责人 ${lead.nickname}${collaboratorCount > 0 ? ` +${collaboratorCount}` : ""}` : "公开池"}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
                    {new Date(r.created_at + "Z").toLocaleString("zh-CN")}
                  </span>
                </p>
                <div className="mt-3 max-w-md">
                  <div className="flex items-center justify-between text-[11px] text-stone-400">
                    <span>进度</span>
                    <span>{progress}%</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-stone-200">
                    <div className="h-full rounded-full bg-stone-950" style={{ width: `${progress}%` }} />
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between gap-2 sm:justify-end">
                <StatusBadge status={r.status} />
                <ArrowRight className="h-4 w-4 text-stone-300 transition group-hover:translate-x-0.5 group-hover:text-stone-600" aria-hidden="true" />
              </div>
            </div>
          </li>
          );
        })}
      </ul>
      {action && (
        <ProjectStateConfirm
          project={action.project}
          action={action.type}
          busy={actionBusy}
          error={actionErr}
          onCancel={() => setAction(null)}
          onConfirm={runProjectAction}
        />
      )}
    </main>
  );
}
