import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bot,
  Clock3,
  Flame,
  Gauge,
  Hammer,
  PackageCheck,
  RefreshCw,
  RotateCcw,
  UserRound,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import type { Requirement } from "@/lib/types";

type Bucket = {
  key: string;
  title: string;
  Icon: LucideIcon;
  statuses: string[];
  tone: string;
  empty: string;
};

const BUCKETS: Bucket[] = [
  { key: "ready", title: "待接单", Icon: Flame, statuses: ["ready"], tone: "border-[#e0c895] bg-[#fff7e2]", empty: "没有待接单需求" },
  { key: "ai", title: "AI 处理中", Icon: Bot, statuses: ["ai_processing"], tone: "border-[#cbb8d8] bg-[#f5eef8]", empty: "无 AI 任务" },
  { key: "doing", title: "进行中", Icon: Hammer, statuses: ["claimed", "doing"], tone: "border-[#bbd6d0] bg-[#eef8f5]", empty: "没有进行中需求" },
  { key: "revision", title: "待返工", Icon: RotateCcw, statuses: ["revision_requested"], tone: "border-[#e0b8ad] bg-[#fff0ec]", empty: "无返工请求" },
  { key: "delivered", title: "交付中/待验收", Icon: PackageCheck, statuses: ["delivery_doc_pending", "delivered"], tone: "border-[#bdd2b7] bg-[#f1f7ed]", empty: "无交付中事项" },
];

const DASHBOARD_STATUSES = ["ready", "ai_processing", "claimed", "doing", "revision_requested", "delivery_doc_pending", "delivered"];
const TICK_MS = 6000;

export function Dashboard() {
  const [items, setItems] = useState<Requirement[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const groups = await Promise.all(DASHBOARD_STATUSES.map((s) => api.listRequirements({ status: s })));
      const all = groups.flat();
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
        if (!ctrl.signal.aborted) setConnected(false);
      } catch {
        if (!ctrl.signal.aborted) setConnected(false);
      }
    })();
    return () => ctrl.abort();
  }, []);

  return (
    <main className="app-container">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">Dispatch Board</p>
          <h1 className="mt-2 flex items-center gap-2 text-3xl font-semibold tracking-tight text-stone-950">
            <Gauge className="h-7 w-7 text-stone-500" aria-hidden="true" />
            接单看板
          </h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-500">
            <span className="inline-flex items-center gap-1.5">
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              每 {TICK_MS / 1000}s 自动刷新
            </span>
            {lastSync && (
              <span className="inline-flex items-center gap-1.5">
                <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                最近同步 {lastSync.toLocaleTimeString("zh-CN", { hour12: false })}
              </span>
            )}
            <span className={connected ? "text-[#4e7146]" : "text-stone-400"}>
              {connected ? "实时在线" : "推送断线"}
            </span>
          </p>
        </div>
        <Link to="/" className="button-secondary">所有项目</Link>
      </header>

      {err && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-[repeat(5,minmax(260px,1fr))]">
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
  const Icon = bucket.Icon;
  return (
    <section className={`border ${bucket.tone} p-3 shadow-[0_1px_0_rgba(31,30,28,0.04)]`} style={{ borderRadius: 8 }}>
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-900">
          <Icon className="h-4 w-4 text-stone-600" aria-hidden="true" />
          {bucket.title}
        </h2>
        <span className="rounded-full border border-stone-200 bg-[#fffdf8]/80 px-2 py-0.5 text-xs font-medium text-stone-600">{items.length}</span>
      </div>
      <div className="space-y-2">
        {items.length === 0 && <div className="rounded-lg border border-dashed border-stone-300/80 p-4 text-center text-xs text-stone-400">{bucket.empty}</div>}
        {items.map((r) => <Card key={r.id} r={r} />)}
      </div>
    </section>
  );
}

function Card({ r }: { r: Requirement }) {
  const age = ageString(new Date(r.created_at + "Z"));
  const lead = r.assignees?.find((a) => a.role === "lead");
  const collaboratorCount = r.assignees?.filter((a) => a.role === "collaborator").length ?? 0;
  const assigneeText = lead
    ? `负责人 ${lead.nickname}${collaboratorCount > 0 ? ` +${collaboratorCount}` : ""}`
    : "公开待接单池";
  const priorityColor =
    r.priority === "urgent" ? "text-red-700"
    : r.priority === "high" ? "text-[#8a5d10]"
    : "text-stone-500";
  return (
    <Link
      to={`/r/${r.id}`}
      className="block rounded-lg border border-stone-200 bg-[#fffdf8] p-3 shadow-sm transition hover:-translate-y-0.5 hover:border-stone-400 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-stone-500">{r.code}</span>
          <span className={`text-xs ${priorityColor}`}>● {r.priority}</span>
        </div>
        <StatusBadge status={r.status} />
      </div>
      <div className="mt-2 break-words text-sm font-semibold leading-snug text-stone-950">{r.title || r.raw_description?.slice(0, 60) || "(无标题)"}</div>
      <div className="mt-2 flex flex-col gap-1 text-xs text-stone-500 sm:flex-row sm:items-center sm:justify-between">
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <UserRound className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="truncate">{r.submitter_nickname} · {r.project_slug}</span>
        </span>
        <span title={new Date(r.created_at + "Z").toLocaleString("zh-CN")}>{age}</span>
      </div>
      <div className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border border-stone-200 bg-[#fffdf8] px-2 py-1 text-xs text-stone-500">
        <Users className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate">{assigneeText}</span>
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
