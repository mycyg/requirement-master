import { useEffect, useRef } from "react";
import { Bot, CheckCircle2, CircleAlert, Loader2, Terminal, Wrench } from "lucide-react";
import type { PushEvent } from "@/hooks/useReqStream";

export function AILiveView({ events }: { events: PushEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Filter only ai.* events
  const aiEvents = events.filter((e) => e.event.startsWith("ai."));

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [aiEvents.length]);

  return (
    <div className="rounded-lg bg-stone-950 p-5 text-stone-100 shadow-[0_18px_60px_rgba(31,30,28,0.22)]">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-[#d7c2a6]">
        <Bot className="h-4 w-4" aria-hidden="true" />
        AI 助理处理中
      </div>
      <div ref={scrollRef} className="scrollbar-thin-warm max-h-96 space-y-2 overflow-auto font-mono text-xs">
        {aiEvents.map((e, i) => (
          <Line key={i} ev={e} />
        ))}
        {aiEvents.length === 0 && <div className="text-stone-500">AI 助理准备中…</div>}
      </div>
    </div>
  );
}

function Line({ ev }: { ev: PushEvent }) {
  const d = ev.data as any;
  const t = new Date(ev.at).toLocaleTimeString("zh-CN", { hour12: false });

  if (ev.event === "ai.started") {
    return <div className="flex gap-2 text-[#d7c2a6]"><Loader2 className="mt-0.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />[{t}] 启动 (max_turns={d?.max_turns}, timeout={d?.timeout_s}s)</div>;
  }
  if (ev.event === "ai.thinking") {
    return (
      <div className="flex gap-2 text-stone-400">
        <Terminal className="mt-0.5 h-3.5 w-3.5 text-[#d6b36b]" aria-hidden="true" />
        <span>[{t}] <span className="text-[#d6b36b]">turn {d?.turn}</span>: {d?.text}</span>
      </div>
    );
  }
  if (ev.event === "ai.text") {
    return (
      <div className="flex gap-2 text-stone-300">
        <Terminal className="mt-0.5 h-3.5 w-3.5 text-[#94b7c9]" aria-hidden="true" />
        <span>[{t}] <span className="text-[#94b7c9]">turn {d?.turn}</span>: {d?.text}</span>
      </div>
    );
  }
  if (ev.event === "ai.tool_call") {
    return (
      <div className="flex gap-2 text-[#a8c5a0]">
        <Wrench className="mt-0.5 h-3.5 w-3.5" aria-hidden="true" />
        <span>[{t}] turn {d?.turn} <b>{d?.name}</b>({d?.input_preview})</span>
      </div>
    );
  }
  if (ev.event === "ai.done") {
    return <div className="flex gap-2 text-[#a8c5a0]"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5" aria-hidden="true" />[{t}] 完成 ({d?.turns} 轮)</div>;
  }
  if (ev.event === "ai.failed") {
    return <div className="flex gap-2 text-red-300"><CircleAlert className="mt-0.5 h-3.5 w-3.5" aria-hidden="true" />[{t}] {d?.reason} - {d?.notes}</div>;
  }
  return <div className="text-stone-500">[{t}] {ev.event}: {JSON.stringify(d).slice(0, 200)}</div>;
}
