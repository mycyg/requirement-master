import { useEffect, useRef } from "react";
import type { PushEvent } from "@/hooks/useReqStream";

export function AILiveView({ events }: { events: PushEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Filter only ai.* events
  const aiEvents = events.filter((e) => e.event.startsWith("ai."));

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [aiEvents.length]);

  return (
    <div className="rounded-2xl bg-slate-900 p-5 text-slate-100">
      <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-violet-400">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-violet-400" />
        AI 自动处理中
      </div>
      <div ref={scrollRef} className="max-h-96 overflow-auto space-y-2 font-mono text-xs">
        {aiEvents.map((e, i) => (
          <Line key={i} ev={e} />
        ))}
        {aiEvents.length === 0 && <div className="text-slate-500">等待 AI 启动…</div>}
      </div>
    </div>
  );
}

function Line({ ev }: { ev: PushEvent }) {
  const d = ev.data as any;
  const t = new Date(ev.at).toLocaleTimeString("zh-CN", { hour12: false });

  if (ev.event === "ai.started") {
    return <div className="text-violet-300">[{t}] ▶ 启动 (max_turns={d?.max_turns}, timeout={d?.timeout_s}s)</div>;
  }
  if (ev.event === "ai.thinking") {
    return (
      <div className="text-slate-400">
        [{t}] <span className="text-amber-300">💭 turn {d?.turn}</span>: {d?.text}
      </div>
    );
  }
  if (ev.event === "ai.text") {
    return (
      <div className="text-slate-300">
        [{t}] <span className="text-cyan-300">turn {d?.turn}</span>: {d?.text}
      </div>
    );
  }
  if (ev.event === "ai.tool_call") {
    return (
      <div className="text-emerald-300">
        [{t}] 🔧 turn {d?.turn} <b>{d?.name}</b>({d?.input_preview})
      </div>
    );
  }
  if (ev.event === "ai.done") {
    return <div className="text-violet-300">[{t}] ✓ 完成 ({d?.turns} 轮)</div>;
  }
  if (ev.event === "ai.failed") {
    return <div className="text-red-400">[{t}] ✗ {d?.reason} — {d?.notes}</div>;
  }
  return <div className="text-slate-500">[{t}] {ev.event}: {JSON.stringify(d).slice(0, 200)}</div>;
}
