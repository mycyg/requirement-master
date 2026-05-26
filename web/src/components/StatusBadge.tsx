const STATUS_ZH: Record<string, { label: string; cls: string }> = {
  draft:              { label: "草稿",     cls: "border-stone-300 bg-stone-100 text-stone-700" },
  clarifying:         { label: "澄清中",   cls: "border-[#b9c8d7] bg-[#edf3f7] text-[#405f78]" },
  ready:              { label: "待接单",   cls: "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]" },
  claimed:            { label: "已接单",   cls: "border-[#bbd6d0] bg-[#edf7f4] text-[#376b60]" },
  doing:              { label: "处理中",   cls: "border-[#d3c3b4] bg-[#fbefe4] text-[#8a4b2f]" },
  ai_processing:      { label: "AI 处理中", cls: "border-[#cbb8d8] bg-[#f3edf7] text-[#684b7a] animate-pulse" },
  delivered:          { label: "已交付",   cls: "border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]" },
  revision_requested: { label: "需返工",   cls: "border-[#e0b8ad] bg-[#fff0ec] text-[#9f4129]" },
  accepted:           { label: "已验收",   cls: "border-[#bdd2b7] bg-[#eef7ea] text-[#3f6b38]" },
  cancelled:          { label: "已取消",   cls: "border-stone-200 bg-stone-100 text-stone-500" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_ZH[status] ?? { label: status, cls: "border-stone-200 bg-stone-100 text-stone-600" };
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${s.cls}`}>
      {s.label}
    </span>
  );
}
