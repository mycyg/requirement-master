import { useEffect, useState } from "react";
import { Maximize2, Minus, X, Sparkles } from "lucide-react";
import { useTheme } from "@yqgl/shared";

export function TitleBar({ sseConnected }: { sseConnected: boolean }) {
  const [winApi, setWinApi] = useState<any>(null);
  const { mode, setMode } = useTheme();

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    import("@tauri-apps/api/window").then((m) => {
      setWinApi(m.getCurrentWindow());
    }).catch(() => {});
  }, []);

  return (
    <div
      data-tauri-drag-region
      className="h-9 w-full flex items-center justify-between px-3 select-none border-b border-line/60"
    >
      <div className="flex items-center gap-2 text-caption text-ink-muted">
        <span className="grid h-5 w-5 place-items-center rounded-xs bg-gradient-to-br from-[#6B5BFF] to-[#FF6E8E] text-white">
          <Sparkles className="h-3 w-3" />
        </span>
        <span>需求管理大师 · 本地工作台</span>
        <span
          className={`ml-2 inline-block h-2 w-2 rounded-pill ${sseConnected ? "bg-success" : "bg-ink-faint"}`}
          title={sseConnected ? "已连接" : "已断开"}
        />
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => setMode(mode === "auto" ? "light" : mode === "light" ? "dark" : "auto")}
          className="h-7 w-7 grid place-items-center rounded-xs text-ink-soft hover:bg-accent-soft"
          title={`外观：${mode}`}
        >
          {mode === "dark" ? "🌙" : mode === "light" ? "☀️" : "🖥"}
        </button>
        <button
          onClick={() => winApi?.minimize?.()}
          className="h-7 w-7 grid place-items-center rounded-xs text-ink-soft hover:bg-accent-soft"
          aria-label="最小化"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => winApi?.toggleMaximize?.()}
          className="h-7 w-7 grid place-items-center rounded-xs text-ink-soft hover:bg-accent-soft"
          aria-label="最大化"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => winApi?.hide?.()}
          className="h-7 w-7 grid place-items-center rounded-xs text-ink-soft hover:bg-error-soft hover:text-error"
          aria-label="关闭"
          title="隐藏到托盘"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
