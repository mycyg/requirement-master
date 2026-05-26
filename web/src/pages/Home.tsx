import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
    <main className="mx-auto max-w-4xl px-6 py-12">
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-bold tracking-tight">项目</h1>
        <button
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white"
          onClick={() => setCreating((v) => !v)}
        >
          {creating ? "取消" : "+ 新建项目"}
        </button>
      </div>

      {creating && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="grid grid-cols-2 gap-3">
            <input
              className="rounded border border-slate-300 px-3 py-2"
              placeholder="项目名（可中文）"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              className="rounded border border-slate-300 px-3 py-2 font-mono"
              placeholder="slug (a-z0-9-_，用于路径/编号前缀)"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
            />
          </div>
          {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
          <button
            className="mt-3 rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
            disabled={!name.trim() || !slug.trim()}
            onClick={submit}
          >
            创建
          </button>
        </div>
      )}

      <ul className="mt-8 divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {projects.length === 0 && (
          <li className="px-5 py-8 text-center text-sm text-slate-500">还没有项目，点右上角"新建项目"开始。</li>
        )}
        {projects.map((p) => (
          <li key={p.id} className="flex items-center justify-between px-5 py-4">
            <div>
              <Link to={`/p/${p.id}`} className="text-base font-medium hover:underline">{p.name}</Link>
              <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-600">{p.slug}</span>
              {p.description && <p className="mt-1 text-sm text-slate-500">{p.description}</p>}
            </div>
            <span className="text-xs text-slate-400">by {p.owner_nickname}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
