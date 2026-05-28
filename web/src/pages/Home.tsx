import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, Archive, ArrowRight, FolderOpen, Plus, RotateCcw, Trash2, UserRound, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { ProjectStateConfirm } from "@/components/ProjectStateConfirm";

type ProjectState = "active" | "archived" | "deleted";
type ProjectAction = "archive" | "delete" | "restore";

export function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [state, setState] = useState<ProjectState>("active");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [action, setAction] = useState<{ project: Project; type: ProjectAction } | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const refresh = () => api.listProjects(state).then(setProjects).catch((e) => setErr(String(e)));
  useEffect(() => { refresh(); }, [state]);

  const submit = async () => {
    setErr(null);
    try {
      await api.createProject({ name: name.trim(), slug: slug.trim() });
      setName(""); setSlug(""); setCreating(false);
      refresh();
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const runProjectAction = async () => {
    if (!action) return;
    setActionBusy(true);
    setActionErr(null);
    try {
      if (action.type === "archive") await api.archiveProject(action.project.id);
      if (action.type === "delete") await api.deleteProject(action.project.id);
      if (action.type === "restore") await api.restoreProject(action.project.id);
      setAction(null);
      await refresh();
    } catch (e: any) {
      setActionErr(String(e));
    } finally {
      setActionBusy(false);
    }
  };

  const stateTabs: { key: ProjectState; label: string }[] = [
    { key: "active", label: "正常" },
    { key: "archived", label: "已归档" },
    { key: "deleted", label: "回收站" },
  ];

  return (
    <main className="narrow-container">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">项目</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-stone-950">项目</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-stone-500">
            把需求按项目收口，后续澄清、接单、交付都从这里进入。
          </p>
        </div>
        <button
          className={creating ? "button-secondary" : "button-primary"}
          onClick={() => setCreating((v) => !v)}
        >
          {creating ? <X className="h-4 w-4" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}
          {creating ? "取消" : "新建项目"}
        </button>
      </div>

      {creating && (
        <div className="paper-surface mt-6 p-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              className="field"
              placeholder="项目名（可中文）"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              className="field font-mono"
              placeholder="slug (a-z0-9-_，用于路径/编号前缀)"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
            />
          </div>
          {err && (
            <p className="mt-3 flex items-center gap-2 text-sm text-red-700">
              <AlertCircle className="h-4 w-4" aria-hidden="true" />
              {err}
            </p>
          )}
          <button
            className="button-primary mt-4"
            disabled={!name.trim() || !slug.trim()}
            onClick={submit}
          >
            创建
          </button>
        </div>
      )}

      {!creating && err && (
        <p className="mt-5 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          {err}
        </p>
      )}

      <div className="mt-6 flex flex-wrap gap-2">
        {stateTabs.map((tab) => (
          <button
            key={tab.key}
            className={`button-secondary min-h-9 px-3 py-1.5 text-xs ${state === tab.key ? "border-stone-950 bg-stone-950 text-[#fffdf8]" : ""}`}
            onClick={() => setState(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <ul className="paper-surface mt-8 divide-y divide-stone-200/80 overflow-hidden">
        {projects.length === 0 && (
          <li className="empty-state m-4">
            {state === "active" ? "你还没有项目，建一个开始吧。" : state === "archived" ? "归档夹里是空的。" : "回收站是空的。"}
          </li>
        )}
        {projects.map((p) => (
          <li key={p.id} className="group flex flex-col gap-3 px-4 py-4 transition hover:bg-white sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div className="min-w-0">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <FolderOpen className="h-4 w-4 shrink-0 text-stone-400" aria-hidden="true" />
                <Link to={`/p/${p.id}`} className="truncate text-base font-semibold text-stone-950 group-hover:underline">
                  {p.name}
                </Link>
                <span className="pill font-mono">{p.slug}</span>
                {p.archived && !p.deleted_at && <span className="pill border-[#e0c895] bg-[#fff7e2] text-[#8a5d10]">已归档</span>}
                {p.deleted_at && <span className="pill border-red-200 bg-red-50 text-red-700">回收站</span>}
              </div>
              {p.description && <p className="mt-2 line-clamp-2 text-sm text-stone-500">{p.description}</p>}
              <p className="mt-2 flex items-center gap-1.5 text-xs text-stone-400">
                <UserRound className="h-3.5 w-3.5" aria-hidden="true" />
                {p.owner_nickname}
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              {!p.deleted_at && (
                <Link to={`/p/${p.id}`} className="button-secondary w-full sm:w-auto">
                  打开
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              )}
              {!p.archived && !p.deleted_at && (
                <Link to={`/p/${p.id}/new`} className="button-secondary w-full sm:w-auto">
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  提一条新需求
                </Link>
              )}
              {!p.archived && !p.deleted_at && (
                <button className="button-secondary w-full sm:w-auto" onClick={() => setAction({ project: p, type: "archive" })}>
                  <Archive className="h-4 w-4" aria-hidden="true" />
                  归档
                </button>
              )}
              {(p.archived || p.deleted_at) && (
                <button className="button-primary w-full sm:w-auto" onClick={() => setAction({ project: p, type: "restore" })}>
                  <RotateCcw className="h-4 w-4" aria-hidden="true" />
                  恢复
                </button>
              )}
              {!p.deleted_at && (
                <button className="button-danger w-full sm:w-auto" onClick={() => setAction({ project: p, type: "delete" })}>
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  删除
                </button>
              )}
            </div>
          </li>
        ))}
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
