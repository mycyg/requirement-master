import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, FolderKanban, HardDrive } from "lucide-react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export function DriveHome() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setErr(null);
    api.listProjects()
      .then((rows) => { if (alive) setProjects(rows); })
      // Without the catch, a failed load silently rendered "还没有项目" — a load
      // error looked identical to a brand-new install with no projects.
      .catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, [reloadTick]);

  return (
    <main className="narrow-container">
      <p className="eyebrow">项目网盘</p>
      <h1 className="mt-2 flex items-center gap-2 text-3xl font-semibold tracking-tight text-stone-950">
        <HardDrive className="h-7 w-7" aria-hidden="true" />
        项目网盘
      </h1>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-500">
        先选项目，再进对应网盘。每个项目的文件分开管理，方便查找和同步。
      </p>

      <ul className="paper-surface mt-8 divide-y divide-stone-200/80 overflow-hidden">
        {err ? (
          <li className="m-4 text-sm text-red-700">
            项目加载失败：{err}
            <button className="ml-2 underline" onClick={() => setReloadTick((t) => t + 1)}>重试</button>
          </li>
        ) : projects.length === 0 ? (
          <li className="empty-state m-4">还没有项目，先建一个项目再用网盘。</li>
        ) : null}
        {projects.map((project) => (
          <li key={project.id} className="group px-4 py-4 transition hover:bg-white sm:px-5">
            <Link to={`/p/${project.id}/drive`} className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2 font-semibold text-stone-950">
                  <FolderKanban className="h-4 w-4 shrink-0 text-stone-400" aria-hidden="true" />
                  <span className="truncate">{project.name}</span>
                </div>
                <div className="mt-1 font-mono text-xs text-stone-400">{project.slug}</div>
              </div>
              <ArrowRight className="h-4 w-4 text-stone-300 transition group-hover:translate-x-0.5 group-hover:text-stone-600" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
