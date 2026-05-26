import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ArrowRight, FolderOpen, Plus, UserRound, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const refresh = () => api.listProjects().then(setProjects).catch((e) => setErr(String(e)));
  useEffect(() => { refresh(); }, []);

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

  return (
    <main className="narrow-container">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">Projects</p>
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

      <ul className="paper-surface mt-8 divide-y divide-stone-200/80 overflow-hidden">
        {projects.length === 0 && (
          <li className="empty-state m-4">还没有项目，点右上角“新建项目”开始。</li>
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
              </div>
              {p.description && <p className="mt-2 line-clamp-2 text-sm text-stone-500">{p.description}</p>}
              <p className="mt-2 flex items-center gap-1.5 text-xs text-stone-400">
                <UserRound className="h-3.5 w-3.5" aria-hidden="true" />
                {p.owner_nickname}
              </p>
            </div>
            <Link to={`/p/${p.id}`} className="button-secondary w-full sm:w-auto">
              打开
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
