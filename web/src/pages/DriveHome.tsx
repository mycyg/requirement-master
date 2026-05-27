import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, FolderKanban, HardDrive } from "lucide-react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export function DriveHome() {
  const [projects, setProjects] = useState<Project[]>([]);

  useEffect(() => {
    api.listProjects().then(setProjects);
  }, []);

  return (
    <main className="narrow-container">
      <p className="eyebrow">Project Drive</p>
      <h1 className="mt-2 flex items-center gap-2 text-3xl font-semibold tracking-tight text-stone-950">
        <HardDrive className="h-7 w-7" aria-hidden="true" />
        项目网盘
      </h1>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-500">
        先选项目，再进对应网盘。别把所有文件堆成一锅粥，系统会装作没看见，但人会崩。
      </p>

      <ul className="paper-surface mt-8 divide-y divide-stone-200/80 overflow-hidden">
        {projects.length === 0 && <li className="empty-state m-4">还没有项目，网盘暂时只能对着空气营业。</li>}
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
