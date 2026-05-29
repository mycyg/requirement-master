import { useEffect, useState } from "react";
import { Archive, RotateCcw, Trash2, X } from "lucide-react";
import type { Project } from "@/lib/types";

type Action = "archive" | "delete" | "restore";

const ACTION_COPY: Record<Action, {
  title: string;
  body: string;
  button: string;
  tone: string;
}> = {
  archive: {
    title: "归档项目",
    body: "归档后项目会从默认列表隐藏，数据仍然保留，可从已归档列表恢复。",
    button: "确认归档",
    tone: "button-secondary",
  },
  delete: {
    title: "删除项目",
    body: "这是软删除：项目会进入回收站，需求、网盘、会议和交付文件都会保留，可恢复。",
    button: "确认删除",
    tone: "button-danger",
  },
  restore: {
    title: "恢复项目",
    body: "恢复后项目会回到正常项目列表，可以继续提需求和管理资料。",
    button: "确认恢复",
    tone: "button-primary",
  },
};

export function ProjectStateConfirm({
  project,
  action,
  busy = false,
  error,
  onCancel,
  onConfirm,
}: {
  project: Project;
  action: Action;
  busy?: boolean;
  error?: string | null;
  onCancel: () => void;
  onConfirm: () => Promise<void> | void;
}) {
  const [value, setValue] = useState("");
  const copy = ACTION_COPY[action];
  const Icon = action === "archive" ? Archive : action === "delete" ? Trash2 : RotateCcw;
  const canConfirm = value.trim() === project.name && !busy;

  useEffect(() => {
    setValue("");
  }, [project.id, action]);

  // ESC cancels the confirm (only when not mid-submit, so a slow archive
  // can't be half-abandoned). Matches the X button affordance.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-stone-950/30 px-4 backdrop-blur-sm" role="dialog" aria-modal="true">
      <section className="w-full max-w-lg rounded-lg border border-stone-200 bg-[#fffdf8] p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-stone-950">
              <Icon className="h-5 w-5 text-stone-500" aria-hidden="true" />
              {copy.title}
            </h2>
            <p className="mt-2 text-sm leading-6 text-stone-600">{copy.body}</p>
          </div>
          <button className="button-ghost min-h-9 w-9 px-0" aria-label="关闭" onClick={onCancel}>
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <div className="mt-4 rounded-lg border border-stone-200 bg-[#fffaf1] p-3">
          <div className="text-sm font-semibold text-stone-950">{project.name}</div>
          <div className="mt-1 font-mono text-xs text-stone-500">{project.slug}</div>
        </div>
        <label className="mt-4 block text-xs font-medium text-stone-500" htmlFor="project-confirm-name">
          输入项目名确认
        </label>
        <input
          id="project-confirm-name"
          className="field mt-2"
          value={value}
          autoFocus
          onChange={(event) => setValue(event.target.value)}
          placeholder={project.name}
        />
        {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button className="button-secondary" disabled={busy} onClick={onCancel}>取消</button>
          <button className={copy.tone} disabled={!canConfirm} onClick={onConfirm}>
            <Icon className="h-4 w-4" aria-hidden="true" />
            {busy ? "处理中…" : copy.button}
          </button>
        </div>
      </section>
    </div>
  );
}
