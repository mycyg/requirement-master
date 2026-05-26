const STATUS_ZH: Record<string, { label: string; cls: string }> = {
  draft:              { label: "草稿",     cls: "bg-slate-200 text-slate-700" },
  clarifying:         { label: "澄清中",   cls: "bg-blue-100 text-blue-700" },
  ready:              { label: "待接单",   cls: "bg-amber-100 text-amber-700" },
  claimed:            { label: "已接单",   cls: "bg-cyan-100 text-cyan-700" },
  doing:              { label: "处理中",   cls: "bg-violet-100 text-violet-700" },
  ai_processing:      { label: "AI 处理中", cls: "bg-violet-100 text-violet-700 animate-pulse" },
  delivered:          { label: "已交付",   cls: "bg-emerald-100 text-emerald-700" },
  revision_requested: { label: "需返工",   cls: "bg-rose-100 text-rose-700" },
  accepted:           { label: "已验收",   cls: "bg-green-100 text-green-800" },
  cancelled:          { label: "已取消",   cls: "bg-slate-100 text-slate-500" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_ZH[status] ?? { label: status, cls: "bg-slate-100 text-slate-600" };
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-0.5 text-xs font-medium ${s.cls}`}>
      {s.label}
    </span>
  );
}
