import { useEffect, useState } from "react";
import { Maximize2, Minus, Monitor, Moon, Sun, X } from "lucide-react";
import { useTheme } from "@yqgl/shared";
import { SpaceSwitcher } from "@/components/SpaceSwitcher";

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
      className="h-9 w-full flex items-center justify-between px-2 select-none border-b border-line/60"
    >
      {/* Left: Space switcher pill. Tauri's drag region honors button events, so the click registers. */}
      <div className="flex items-center gap-2">
        <SpaceSwitcher />
        <span
          className={`inline-block h-2 w-2 rounded-pill ${sseConnected ? "bg-success" : "bg-ink-faint"}`}
          title={sseConnected ? "实时连接已建立" : "实时连接已断开"}
        />
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => setMode(mode === "auto" ? "light" : mode === "light" ? "dark" : "auto")}
          className="h-7 w-7 grid place-items-center rounded-xs text-ink-soft hover:bg-accent-soft"
          title={`外观：${mode}`}
        >
          {mode === "dark" ? <Moon className="h-3.5 w-3.5" /> : mode === "light" ? <Sun className="h-3.5 w-3.5" /> : <Monitor className="h-3.5 w-3.5" />}
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
