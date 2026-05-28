import { useEffect, useRef, useState } from "react";
import { Briefcase, Check, ChevronDown, Send } from "lucide-react";
import { useSpace, type SpaceMode } from "@yqgl/shared";

type Variant = {
  id: SpaceMode;
  label: string;
  hint: string;
  swatch: string;
  hotkey: string;
  Icon: typeof Briefcase;
};

const VARIANTS: Variant[] = [
  {
    id: "work",
    label: "接活",
    hint: "我手头有什么活",
    swatch: "linear-gradient(135deg, #6B5BFF 0%, #8b7bff 100%)",
    hotkey: "Ctrl+1",
    Icon: Briefcase,
  },
  {
    id: "dispatch",
    label: "派活",
    hint: "我发出去的活怎么样了",
    swatch: "linear-gradient(135deg, #FF6E8E 0%, #ffa3b9 100%)",
    hotkey: "Ctrl+2",
    Icon: Send,
  },
];

export function SpaceSwitcher() {
  const { space, setSpace } = useSpace();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const current = VARIANTS.find((v) => v.id === space) ?? VARIANTS[0];

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative" style={{ viewTransitionName: "yqgl-space-chip" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 h-7 pl-1.5 pr-2 rounded-pill glass-quiet text-caption text-ink hover:bg-accent-soft transition"
        title="切换工作空间 (Ctrl+1 / Ctrl+2)"
      >
        <span
          className="grid h-4 w-4 place-items-center rounded-pill text-white"
          style={{ background: current.swatch }}
        >
          <current.Icon className="h-2.5 w-2.5" />
        </span>
        <span className="text-body-sm font-medium">{current.label}</span>
        <ChevronDown className={`h-3 w-3 text-ink-muted transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute top-9 left-0 z-50 w-56 glass-strong p-1.5 anim-fade-up">
          {VARIANTS.map((v) => {
            const active = v.id === space;
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => { setSpace(v.id); setOpen(false); }}
                className={`w-full flex items-center gap-2.5 px-2 py-2 rounded-sm text-left transition ${
                  active ? "bg-accent-soft" : "hover:bg-accent-soft/60"
                }`}
              >
                <span
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-sm text-white"
                  style={{ background: v.swatch }}
                >
                  <v.Icon className="h-3.5 w-3.5" />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-body-sm text-ink font-medium">{v.label}</span>
                    {active && <Check className="h-3 w-3 text-accent" />}
                  </div>
                  <div className="text-caption text-ink-muted truncate">{v.hint}</div>
                </div>
                <span className="text-caption text-ink-faint shrink-0">{v.hotkey}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
