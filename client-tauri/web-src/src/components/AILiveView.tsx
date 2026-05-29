import { useEffect, useRef } from "react";
import { Bot, CheckCircle2, CircleAlert, Loader2, Terminal, Wrench } from "lucide-react";
import type { PushEvent } from "@yqgl/shared";

/**
 * Live "what is the AI worker doing" log. Renders the `ai.*` events the
 * backend autonomous agent publishes on the `req:<id>` SSE topic
 * (ai.started / ai.thinking / ai.text / ai.tool_call / ai.done / ai.failed).
 * Mounted in TaskDetail while status === "ai_processing".
 */
export function AILiveView({ events }: { events: PushEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const aiEvents = events.filter((e) => e.event.startsWith("ai."));

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [aiEvents.length]);

  return (
    <div className="glass-sunken rounded-md p-4">
      <div className="mb-3 flex items-center gap-2 text-eyebrow text-accent-2">
        <Bot className="h-4 w-4" aria-hidden="true" />
        AI 助理实时进度
      </div>
      <div ref={scrollRef} className="max-h-80 space-y-1.5 overflow-auto font-mono text-caption text-ink-soft">
        {aiEvents.map((e, i) => (
          <Line key={i} ev={e} />
        ))}
        {aiEvents.length === 0 && <div className="text-ink-faint">AI 助理准备中…</div>}
      </div>
    </div>
  );
}

function Line({ ev }: { ev: PushEvent }) {
  const d = ev.data as any;
  const t = new Date(ev.at).toLocaleTimeString("zh-CN", { hour12: false });

  if (ev.event === "ai.started") {
    return (
      <div className="flex gap-2 text-accent-2">
        <Loader2 className="mt-0.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        <span>[{t}] 启动（最多 {d?.max_turns} 轮 · 超时 {d?.timeout_s}s）</span>
      </div>
    );
  }
  if (ev.event === "ai.thinking") {
    return (
      <div className="flex gap-2 text-ink-muted">
        <Terminal className="mt-0.5 h-3.5 w-3.5 text-warn" aria-hidden="true" />
        <span>[{t}] <span className="text-warn">第 {d?.turn} 轮思考</span>：{d?.text}</span>
      </div>
    );
  }
  if (ev.event === "ai.text") {
    return (
      <div className="flex gap-2 text-ink-muted">
        <Terminal className="mt-0.5 h-3.5 w-3.5 text-info" aria-hidden="true" />
        <span>[{t}] <span className="text-info">第 {d?.turn} 轮</span>：{d?.text}</span>
      </div>
    );
  }
  if (ev.event === "ai.tool_call") {
    return (
      <div className="flex gap-2 text-success">
        <Wrench className="mt-0.5 h-3.5 w-3.5" aria-hidden="true" />
        <span>[{t}] 第 {d?.turn} 轮 <b>{d?.name}</b>（{d?.input_preview}）</span>
      </div>
    );
  }
  if (ev.event === "ai.done") {
    return (
      <div className="flex gap-2 text-success">
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5" aria-hidden="true" />
        <span>[{t}] 完成（共 {d?.turns} 轮）</span>
      </div>
    );
  }
  if (ev.event === "ai.failed") {
    return (
      <div className="flex gap-2 text-error">
        <CircleAlert className="mt-0.5 h-3.5 w-3.5" aria-hidden="true" />
        <span>[{t}] {d?.reason} — {d?.notes}</span>
      </div>
    );
  }
  return <div className="text-ink-faint">[{t}] {ev.event}: {JSON.stringify(d).slice(0, 200)}</div>;
}
