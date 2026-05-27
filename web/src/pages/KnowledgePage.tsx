import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bot, ExternalLink, FileSearch, Filter, Search, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { KnowledgeAskRun, KnowledgeSearchHit, Project } from "@/lib/types";

function internalLink(url: string, label: string) {
  return url.startsWith("/") ? <Link className="link-subtle text-xs" to={url}>{label}<ExternalLink className="h-3 w-3" /></Link> : <a className="link-subtle text-xs" href={url}>{label}</a>;
}

export function KnowledgePage() {
  const [searchParams] = useSearchParams();
  const initialProject = searchParams.get("project_id") || "";
  const initialRun = searchParams.get("run_id");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(initialProject);
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [hits, setHits] = useState<KnowledgeSearchHit[]>([]);
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<KnowledgeAskRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const projectName = useMemo(() => projects.find((item) => item.id === projectId)?.name, [projects, projectId]);

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    if (!initialRun) return;
    api.getKnowledgeRun(initialRun).then(setRun).catch((e) => setErr(String(e)));
  }, [initialRun]);

  const doSearch = async () => {
    if (!query.trim()) return;
    setBusy(true); setErr(null);
    try {
      const out = await api.searchKnowledge({ q: query.trim(), project_id: projectId || null, limit: 40 });
      setHits(out.hits);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const ask = async () => {
    if (!question.trim()) return;
    setBusy(true); setErr(null);
    try {
      const created = await api.askKnowledge({ question: question.trim(), project_id: projectId || null });
      let next = await api.getKnowledgeRun(created.id);
      setRun(next);
      for (let i = 0; i < 8 && next.status === "running"; i += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 900));
        next = await api.getKnowledgeRun(created.id);
        setRun(next);
      }
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="app-container">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">在历史里翻翻</p>
          <h1 className="mt-2 text-3xl font-semibold text-stone-950">历史搜索</h1>
          <p className="mt-2 max-w-2xl text-sm text-stone-500">查项目过去的决策、规则、交付物 —— 在需求、会议、文档里找证据。</p>
        </div>
        <label className="flex min-w-[260px] items-center gap-2">
          <Filter className="h-4 w-4 text-stone-400" aria-hidden="true" />
          <select className="select-field" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">全部项目</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <section className="paper-surface p-4">
          <div className="flex flex-col gap-2 md:flex-row">
            <input
              className="field min-h-11 flex-1"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }}
              placeholder="搜需求编号、会议标题、文件名、接单人、关键句…"
            />
            <button className="button-primary" disabled={busy || !query.trim()} onClick={doSearch}>
              <Search className="h-4 w-4" aria-hidden="true" />
              搜索
            </button>
          </div>
          {projectName && <p className="mt-2 text-xs text-stone-500">当前只搜：{projectName}</p>}
          <div className="mt-4 space-y-3">
            {hits.length === 0 ? (
              <div className="empty-state">还没有命中。换一些关键词试试。</div>
            ) : hits.map((hit) => (
              <article key={`${hit.document_id}-${hit.line_no}`} className="rounded-lg border border-stone-200 bg-[#fffdf8] p-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="pill">{hit.source_type}</span>
                      <span className="text-xs text-stone-400">L{hit.line_no}</span>
                    </div>
                    <h3 className="mt-2 break-words text-sm font-semibold text-stone-950">{hit.title}</h3>
                  </div>
                  {internalLink(hit.source_url, "打开证据")}
                </div>
                <pre className="mt-3 max-h-44 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-3 text-xs leading-5 text-stone-700">{hit.snippet}</pre>
              </article>
            ))}
          </div>
        </section>

        <aside className="paper-surface p-4">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-stone-500" aria-hidden="true" />
            <h2 className="text-base font-semibold text-stone-950">Agent 问答</h2>
          </div>
          <textarea
            className="textarea-field mt-3 min-h-28"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="问一个基于项目历史的问题"
          />
          <button className="button-accent mt-3 w-full" disabled={busy || !question.trim()} onClick={ask}>
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            {busy ? "正在查找证据…" : "让 AI 助理找证据"}
          </button>
          {run && (
            <div className="mt-4 rounded-lg border border-stone-200 bg-[#fffdf8] p-4">
              <div className="mb-2 flex items-center justify-between gap-2 text-xs text-stone-500">
                <span>{run.status}</span>
                <span>{run.citations.length} 条证据</span>
              </div>
              <pre className="whitespace-pre-wrap text-sm leading-6 text-stone-800">{run.answer_md || "正在翻资料…"}</pre>
            </div>
          )}
          {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
          <div className="mt-4 rounded-lg border border-stone-200 bg-[#fffaf1] p-3 text-xs leading-5 text-stone-500">
            <FileSearch className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />
            AI 助理只能基于项目的需求、会议、文档等历史回答；找不到证据时会直接说明。
          </div>
        </aside>
      </div>
    </main>
  );
}
