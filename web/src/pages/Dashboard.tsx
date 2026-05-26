import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import type { Requirement } from "@/lib/types";

type Bucket = {
  key: string;
  title: string;
  icon: string;
  statuses: string[];
  tone: string;
  empty: string;
};

const BUCKETS: Bucket[] = [
  { key: "ready", title: "待接单", icon: "🔥", statuses: ["ready"], tone: "border-amber-300 bg-amber-50", empty: "没有待接单需求 🎉" },
  { key: "ai",  title: "AI 处理中", icon: "🤖", statuses: ["ai_processing"], tone: "border-violet-300 bg-violet-50", empty: "无 AI 任务" },
  { key: "doing", title: "进行中", icon: "🛠️", statuses: ["claimed", "doing"], tone: "border-cyan-300 bg-cyan-50", empty: "没有进行中需求" },
  { key: "revision", title: "待返工", icon: "↺", statuses: ["revision_requested"], tone: "border-rose-300 bg-rose-50", empty: "无返工请求" },
  { key: "delivered", title: "已交付待验收", icon: "✅", statuses: ["delivered"], tone: "border-emerald-300 bg-emerald-50", empty: "无待验收交付" },
];

const TICK_MS = 6000;

export function Dashboard() {
  const [items, setItems] = useState<Requirement[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const all: Requirement[] = [];
      for (const s of ["ready", "ai_processing", "claimed", "doing", "revision_requested", "delivered"]) {
        const rows = await api.listRequirements({ status: s });
        all.push(...rows);
      }
      // de-dup by id (same req could in theory appear twice, e.g. if state changed mid-fetch)
      const map = new Map(all.map((r) => [r.id, r]));
      setItems([...map.values()].sort(byUrgency));
      setLastSync(new Date());
      setErr(null);
    } catch (e: any) {
      setErr(String(e));
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, TICK_MS);
    return () => clearInterval(t);
  }, []);

  // SSE driver — refresh on any push event
  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const r = await fetch("/api/push/stream", { credentials: "include", signal: ctrl.signal });
        if (!r.ok || !r.body) { setConnected(false); return; }
        setConnected(true);
        const reader = r.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buf = "";
        let event = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let nl;
          while ((nl = buf.indexOf("\n")) !== -1) {
            const line = buf.slice(0, nl);
            buf = buf.slice(nl + 1);
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line === "" && event) {
              if (event !== "heartbeat") refresh();
              event = "";
            }
          }
        }
      } catch {
        if (!ctrl.signal.aborted) setConnected(false);
      }
    })();
    return () => ctrl.abort();
  }, []);

  return (
    <main className="mx-auto max-w-7xl px-6 py-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">接单看板</h1>
          <p className="mt-1 text-xs text-slate-500">
            自动刷新 (每 {TICK_MS / 1000}s + 实时推送) · {lastSync && `最近同步 ${lastSync.toLocaleTimeString("zh-CN", { hour12: false })}`}
            {" · "}
            <span className={connected ? "text-emerald-600" : "text-slate-400"}>
              {connected ? "● 实时" : "○ 断线"}
            </span>
          </p>
        </div>
        <Link to="/" className="text-sm text-slate-500 hover:underline">所有项目 →</Link>
      </header>

      {err && <div className="mt-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {BUCKETS.map((b) => (
          <BucketCard
            key={b.key}
            bucket={b}
            items={items.filter((r) => b.statuses.includes(r.status))}
          />
        ))}
      </div>
    </main>
  );
}

function byUrgency(a: Requirement, b: Requirement): number {
  const order = { urgent: 0, high: 1, normal: 2, low: 3 } as Record<string, number>;
  const pa = order[a.priority] ?? 2;
  const pb = order[b.priority] ?? 2;
  if (pa !== pb) return pa - pb;
  return b.created_at.localeCompare(a.created_at);
}

function BucketCard({ bucket, items }: { bucket: Bucket; items: Requirement[] }) {
  return (
    <section className={`rounded-xl border-2 ${bucket.tone} p-3`}>
      <div className="mb-2 flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold">
          <span className="mr-1.5">{bucket.icon}</span>
          {bucket.title}
        </h2>
        <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs font-medium">{items.length}</span>
      </div>
      <div className="space-y-2">
        {items.length === 0 && <div className="rounded p-4 text-center text-xs text-slate-400">{bucket.empty}</div>}
        {items.map((r) => <Card key={r.id} r={r} />)}
      </div>
    </section>
  );
}

function Card({ r }: { r: Requirement }) {
  const age = ageString(new Date(r.created_at + "Z"));
  const priorityColor =
    r.priority === "urgent" ? "text-rose-700"
    : r.priority === "high" ? "text-amber-700"
    : "text-slate-500";
  return (
    <Link
      to={`/r/${r.id}`}
      className="block rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-200 transition hover:ring-slate-400"
    >
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-slate-500">{r.code}</span>
          <span className={`text-xs ${priorityColor}`}>● {r.priority}</span>
        </div>
        <StatusBadge status={r.status} />
      </div>
      <div className="mt-1 text-sm font-medium leading-snug">{r.title || r.raw_description?.slice(0, 60) || "(无标题)"}</div>
      <div className="mt-1.5 flex items-center justify-between text-xs text-slate-500">
        <span>由 <b>{r.submitter_nickname}</b> · {r.project_slug}</span>
        <span title={new Date(r.created_at + "Z").toLocaleString("zh-CN")}>{age}</span>
      </div>
    </Link>
  );
}

function ageString(t: Date): string {
  const sec = (Date.now() - t.getTime()) / 1000;
  if (sec < 60) return `${Math.floor(sec)}s 前`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m 前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h 前`;
  return `${Math.floor(sec / 86400)}d 前`;
}
