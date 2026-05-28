import { useEffect, useState } from "react";
import { Download, Laptop, MonitorDown, Sparkles, X } from "lucide-react";

type PlatformDownload = {
  id: string;
  label: string;
  url: string;
  size_bytes?: number;
  mtime?: number;
  external?: boolean;
  note?: string;
};

type Manifest =
  | { available: false; platforms?: PlatformDownload[] }
  | {
      available: true;
      url: string;
      size_bytes?: number;
      mtime?: number;
      version_key?: string;
      platforms?: PlatformDownload[];
    };

const DISMISS_KEY = "yqgl.client_banner_dismissed";

function formatSize(bytes?: number) {
  if (!bytes || bytes <= 0) return "";
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function platformDownloads(manifest: Manifest | null): PlatformDownload[] {
  if (!manifest?.available) return [];
  if (manifest.platforms?.length) return manifest.platforms;
  return [{
    id: "windows",
    label: "Windows",
    url: manifest.url,
    size_bytes: manifest.size_bytes,
    mtime: manifest.mtime,
  }];
}

function manifestVersionKey(manifest: Manifest) {
  if (!manifest.available) return "unavailable";
  if (manifest.version_key) return manifest.version_key;
  return platformDownloads(manifest).map((p) => `${p.id}:${p.mtime || p.url}`).join("|");
}

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
    const load = () => {
      fetch("/api/downloads/manifest")
        .then((r) => r.json())
        .then((m: Manifest) => {
          setManifest(m);
          try {
            if (m.available) {
              const last = localStorage.getItem(DISMISS_KEY) || "";
              // Dismiss applies ONLY to the exact installer set the user saw.
              // Any Windows or macOS package change re-shows the banner.
              setDismissed(last !== "" && last === manifestVersionKey(m));
            }
          } catch { /* ignore */ }
        })
        .catch(() => setManifest({ available: false }));
    };
    load();
    // Re-check when the user returns to the tab — picks up newly published
    // installers without forcing a full reload.
    const onVisible = () => { if (document.visibilityState === "visible") load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  if (!manifest || !manifest.available || dismissed) return null;

  const platforms = platformDownloads(manifest);

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, manifestVersionKey(manifest));
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
      <div className="mx-auto flex w-full max-w-[1760px] flex-wrap items-center gap-3 px-4 py-2 sm:px-6 lg:px-8">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-pill bg-gradient-to-br from-[#6B5BFF] to-[#FF6E8E] text-white shadow-e1">
          <Sparkles className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1 text-sm text-ink">
          <span className="font-medium">网页是临时入口</span>
          <span className="text-ink-muted">
            {" "}— 下载桌面客户端体验更完整（实时通知、文件夹自动同步、托盘常驻、AI 澄清更流畅）。
          </span>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {platforms.map((platform, index) => {
            const isPrimary = platform.id === "windows" || index === 0;
            const Icon = platform.id === "macos" ? Laptop : MonitorDown;
            const size = formatSize(platform.size_bytes);
            return (
              <a
                key={platform.id}
                href={platform.url}
                download={platform.external ? undefined : true}
                target={platform.external ? "_blank" : undefined}
                rel={platform.external ? "noreferrer" : undefined}
                title={platform.note || `下载 ${platform.label} 客户端`}
                className={[
                  "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-sm px-3 text-sm font-medium shadow-e1 transition",
                  isPrimary
                    ? "bg-accent text-white hover:bg-accent-hover"
                    : "border border-accent/25 bg-white/70 text-accent hover:border-accent/40 hover:bg-accent-soft",
                ].join(" ")}
              >
                <Icon className="h-3.5 w-3.5" />
                {platform.label} 客户端
                {size && <span className="ml-1 text-[11px] opacity-80">{size}</span>}
              </a>
            );
          })}
        </div>
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
  const platforms = platformDownloads(manifest);
  if (!platforms.length) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {platforms.slice(0, 2).map((platform) => (
        <a
          key={platform.id}
          href={platform.url}
          download={platform.external ? undefined : true}
          target={platform.external ? "_blank" : undefined}
          rel={platform.external ? "noreferrer" : undefined}
          className="inline-flex items-center gap-1.5 rounded-pill bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent transition hover:bg-accent hover:text-white"
        >
          <Download className="h-3 w-3" /> {platform.label}
        </a>
      ))}
    </span>
  );
}
