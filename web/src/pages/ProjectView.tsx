import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { Project, Requirement } from "@/lib/types";

const STATUS_ZH: Record<string, string> = {
  draft: "草稿", clarifying: "澄清中", ready: "待接单", claimed: "已接单",
  doing: "处理中", delivered: "已交付", revision_requested: "返工中",
  accepted: "已验收", cancelled: "已取消",
};

export function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [reqs, setReqs] = useState<Requirement[]>([]);

  useEffect(() => {
    if (!id) return;
    api.listProjects().then((all) => setProject(all.find((p) => p.id === id) ?? null));
    api.listRequirements({ project_id: id }).then(setReqs);
  }, [id]);

  if (!project) return <main className="p-12">加载中…</main>;

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link to="/" className="text-sm text-slate-500 hover:underline">← 全部项目</Link>
      <div className="mt-4 flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{project.name}</h1>
          <p className="mt-1 font-mono text-xs text-slate-500">{project.slug}</p>
        </div>
        <Link
          to={`/p/${project.id}/new`}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white"
        >
          + 提一个需求
        </Link>
      </div>

      <ul className="mt-8 divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {reqs.length === 0 && (
          <li className="px-5 py-8 text-center text-sm text-slate-500">还没有需求</li>
        )}
        {reqs.map((r) => (
          <li key={r.id} className="px-5 py-4">
            <div className="flex items-center justify-between">
              <Link to={`/r/${r.id}`} className="font-medium hover:underline">
                <span className="mr-2 font-mono text-xs text-slate-500">{r.code}</span>
                {r.title || r.raw_description?.slice(0, 60) || "(无标题)"}
              </Link>
              <span className="rounded-full bg-slate-100 px-3 py-0.5 text-xs">{STATUS_ZH[r.status] ?? r.status}</span>
            </div>
            <p className="mt-1 text-xs text-slate-400">by {r.submitter_nickname}  ·  {new Date(r.created_at + "Z").toLocaleString("zh-CN")}</p>
          </li>
        ))}
      </ul>
    </main>
  );
}
