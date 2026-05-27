import { useState } from "react";
import { Search, Sparkles } from "lucide-react";
import { Button, Card, Input, EmptyState, Skeleton } from "@yqgl/shared";
import { clientFetch } from "@/lib/tauri";

type Hit = {
  document_id: string;
  source_type: string;
  source_id: string;
  title: string;
  source_url: string;
  line_no: number;
  snippet: string;
};

type AskRun = {
  id: string;
  status: "running" | "succeeded" | "failed";
  answer_md: string | null;
  citations: Hit[];
};

export function Knowledge() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [askQ, setAskQ] = useState("");
  const [run, setRun] = useState<AskRun | null>(null);
  const [busy, setBusy] = useState(false);

  const doSearch = async () => {
    if (!q.trim()) return;
    setBusy(true);
    setHits(null);
    try {
      const r = await clientFetch(`/api/knowledge/search?q=${encodeURIComponent(q.trim())}&limit=30`).then((r) => r.json());
      setHits(r.hits || []);
    } catch {
      setHits([]);
    } finally { setBusy(false); }
  };

  const doAsk = async () => {
    if (!askQ.trim()) return;
    setBusy(true);
    try {
      const start = await clientFetch("/api/knowledge/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: askQ.trim() }),
      }).then((r) => r.json());

      let attempts = 0;
      while (attempts < 20) {
        const r: AskRun = await clientFetch(`/api/knowledge/runs/${start.id}`).then((r) => r.json());
        setRun(r);
        if (r.status !== "running") break;
        await new Promise((res) => setTimeout(res, 1000));
        attempts++;
      }
    } catch (e: any) {
      setRun({ id: "", status: "failed", answer_md: String(e), citations: [] });
    } finally { setBusy(false); }
  };

  return (
    <div className="flex-1 p-6 overflow-auto space-y-5">
      <h1 className="text-h2 text-ink">在历史里翻翻</h1>
      <p className="text-body-sm text-ink-muted">
        查项目过去的决策、规则、交付物 —— 在需求、会议、文档里找证据。
      </p>

      <Card>
        <h2 className="text-h4 text-ink mb-3">关键字搜索</h2>
        <div className="flex gap-2">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doSearch()}
            prefixSlot={<Search className="h-4 w-4" />}
            placeholder="搜需求编号、会议标题、文件名、关键句…"
          />
          <Button onClick={doSearch} loading={busy}>搜索</Button>
        </div>
        <div className="mt-4">
          {hits == null ? null : hits.length === 0 ? (
            <EmptyState title="没有命中" description="换一些关键词试试。" />
          ) : (
            <div className="space-y-2">
              {hits.map((h) => (
                <a
                  key={`${h.document_id}-${h.line_no}`}
                  href={h.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block glass-sunken p-3 hover:bg-accent-soft transition"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-caption text-accent uppercase tracking-wider">{h.source_type}</span>
                    <span className="text-body text-ink truncate">{h.title}</span>
                  </div>
                  <pre className="mt-1 text-caption text-ink-muted whitespace-pre-wrap font-mono">{h.snippet}</pre>
                </a>
              ))}
            </div>
          )}
        </div>
      </Card>

      <Card>
        <h2 className="text-h4 text-ink mb-3 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent" /> 问 AI 助理
        </h2>
        <div className="flex gap-2">
          <Input
            value={askQ}
            onChange={(e) => setAskQ(e.target.value)}
            placeholder="问个问题，AI 助理会找证据再回答"
            onKeyDown={(e) => e.key === "Enter" && doAsk()}
          />
          <Button onClick={doAsk} loading={busy}>问</Button>
        </div>
        {run && (
          <div className="mt-4">
            {run.status === "running" && <Skeleton height="h-16" />}
            {run.status === "succeeded" && (
              <>
                <div className="glass-sunken p-3 whitespace-pre-wrap text-body-sm text-ink-soft">{run.answer_md}</div>
                {run.citations.length > 0 && (
                  <div className="mt-3 space-y-1 text-caption text-ink-muted">
                    <div className="text-eyebrow text-ink-faint">引用</div>
                    {run.citations.map((c, i) => (
                      <div key={i}>
                        [{i + 1}] <a className="text-accent hover:underline" href={c.source_url} target="_blank" rel="noreferrer">{c.title}</a>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
            {run.status === "failed" && <div className="text-error text-body-sm">{run.answer_md || "出错了"}</div>}
          </div>
        )}
      </Card>
    </div>
  );
}
