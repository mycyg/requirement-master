import { useEffect, useState } from "react";
import { Download, MonitorDown, Sparkles, X } from "lucide-react";

type Manifest =
  | { available: false }
  | { available: true; url: string; size_bytes: number; mtime: number };

const DISMISS_KEY = "yqgl.client_banner_dismissed";

/**
 * Sticky banner shown above the top nav. Tells web users this is the temporary
 * entry point and offers the desktop client installer. Dismissed state is
 * remembered in localStorage so the banner doesn't keep nagging — but it
 * re-shows when the installer manifest's mtime changes (new version).
 */
export function ClientDownloadBanner() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    fetch("/api/downloads/manifest")
      .then((r) => r.json())
      .then((m: Manifest) => {
        setManifest(m);
        try {
          if (m.available) {
            const last = Number(localStorage.getItem(DISMISS_KEY) || "0");
            // Re-show if the installer was updated after the last dismissal.
            setDismissed(last > 0 && last >= m.mtime);
          }
        } catch { /* ignore */ }
      })
      .catch(() => setManifest({ available: false }));
  }, []);

  if (!manifest || !manifest.available || dismissed) return null;

  const sizeMb = (manifest.size_bytes / (1024 * 1024)).toFixed(1);

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, String(manifest.mtime));
    } catch { /* ignore */ }
    setDismissed(true);
  };

  return (
    <div
      className="sticky top-0 z-50 border-b border-accent/30"
      style={{
        background: "linear-gradient(90deg, rgba(107,91,255,0.10) 0%, rgba(255,110,142,0.10) 100%)",
        backdropFilter: "blur(16px) saturate(150%)",
        WebkitBackdropFilter: "blur(16px) saturate(150%)",
      }}
    >
      <div className="mx-auto flex w-full max-w-[1760px] items-center gap-3 px-4 py-2 sm:px-6 lg:px-8">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-pill bg-gradient-to-br from-[#6B5BFF] to-[#FF6E8E] text-white shadow-e1">
          <Sparkles className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1 text-sm text-ink">
          <span className="font-medium">网页是临时入口</span>
          <span className="text-ink-muted">
            {" "}— 下载桌面客户端体验更完整（实时通知、文件夹自动同步、托盘常驻、AI 澄清更流畅）。
          </span>
        </div>
        <a
          href={manifest.url}
          download
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-sm bg-accent px-3 text-sm font-medium text-white shadow-e1 transition hover:bg-accent-hover"
        >
          <MonitorDown className="h-3.5 w-3.5" />
          下载客户端
          <span className="ml-1 text-[11px] opacity-80">{sizeMb} MB</span>
        </a>
        <button
          onClick={dismiss}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-sm text-ink-muted hover:bg-accent-soft hover:text-ink transition"
          aria-label="不再提示（直到新版发布）"
          title="不再提示（直到新版发布）"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

/** Compact variant for places where the full banner is too wide. */
export function ClientDownloadPill() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  useEffect(() => {
    fetch("/api/downloads/manifest").then((r) => r.json()).then(setManifest).catch(() => {});
  }, []);
  if (!manifest?.available) return null;
  return (
    <a
      href={manifest.url}
      download
      className="inline-flex items-center gap-1.5 rounded-pill bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent transition hover:bg-accent hover:text-white"
    >
      <Download className="h-3 w-3" /> 下载客户端
    </a>
  );
}
