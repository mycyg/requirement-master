import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import {
  ToastHost,
  WelcomeTour,
  defaultWelcomeSlides,
  toast,
  useFirstRun,
  useSpace,
} from "@yqgl/shared";
import {
  ArrowLeftRight,
  Bell as BellIcon,
  Bot,
  Command as CommandIcon,
  FolderKanban,
  Sparkles,
} from "lucide-react";
import { TitleBar } from "@/components/TitleBar";
import { Sidebar } from "@/components/Sidebar";
import { Hub } from "@/routes/Hub";
import { HubDispatch } from "@/routes/HubDispatch";
import { NewRequirement } from "@/routes/NewRequirement";
import { Clarify } from "@/routes/Clarify";
import { ProjectDrive } from "@/routes/ProjectDrive";
import { ProjectMeetings } from "@/routes/ProjectMeetings";
import { TaskDetail } from "@/routes/TaskDetail";
import { Inbox } from "@/routes/Inbox";
import { Onboarding } from "@/routes/Onboarding";
import { Settings } from "@/routes/Settings";
import { MyWorkload } from "@/routes/MyWorkload";
import { Knowledge } from "@/routes/Knowledge";
import { ProjectPulse } from "@/routes/ProjectPulse";
import { Calendar } from "@/routes/Calendar";
import { FloatingAssistant } from "@/components/FloatingAssistant";
import { invoke, useEvent, isTauri, clientJson, resetClientTokenCache } from "@/lib/tauri";

/**
 * Fire a Windows / OS-level toast through the Tauri notification plugin.
 * Silently falls back to nothing in browser dev. Permission is requested
 * once per process — the plugin caches the answer.
 */
/**
 * Sync the tray tooltip with the current unread notification count so the
 * user knows there's something waiting even with the main window hidden.
 * Debounced — a burst of 10 notifications in 1 second results in ONE fetch
 * 250ms after the last one, not 10 fetches.
 */
let _badgeTimer: ReturnType<typeof setTimeout> | null = null;
function refreshUnreadBadge(): void {
  if (!isTauri()) return;
  if (_badgeTimer) clearTimeout(_badgeTimer);
  _badgeTimer = setTimeout(async () => {
    _badgeTimer = null;
    try {
      const rows = await clientJson<unknown[]>("/api/notifications?status=unread");
      const count = Array.isArray(rows) ? rows.length : 0;
      await invoke("update_tray_unread", { count });
    } catch {
      /* ignore — badge is best-effort. Don't reset to 0 on transient
         errors (nginx 502, brief network drop) or the badge silently lies. */
    }
  }, 250);
}

async function osNotify(title: string, body: string): Promise<void> {
  if (!isTauri()) return;
  try {
    const mod = await import("@tauri-apps/plugin-notification");
    let granted = await mod.isPermissionGranted();
    if (!granted) {
      const p = await mod.requestPermission();
      granted = p === "granted";
    }
    if (granted) {
      await mod.sendNotification({ title, body });
    }
  } catch (e) {
    // No-op — system notifications are nice-to-have, not load-bearing.
    console.warn("osNotify failed", e);
  }
}

/**
 * Routes `/` to either HubWork (接活 / claimant view) or HubDispatch
 * (派活 / submitter view) based on the active Space. The route element is
 * the same — just the page contents change — so URLs stay stable.
 */
function HubRouter() {
  const { space } = useSpace();
  return space === "dispatch" ? <HubDispatch /> : <Hub />;
}

type Cfg = { nickname: string; cookie_token: string; client_token: string };

export function App() {
  const nav = useNavigate();
  const { setSpace } = useSpace();
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [sseConnected, setSseConnected] = useState(false);
  // Welcome tour state — auto-fires the first time a fully-onboarded
  // user reaches the main shell. `markTourSeen` persists to localStorage
  // so subsequent launches skip it. Triggered manually from a future
  // Settings entry too (see Settings.tsx).
  const { seen: tourSeen, markSeen: markTourSeen } = useFirstRun();

  // Ctrl+1 / Ctrl+2 (Cmd on mac, though we ship windows-only) jumps between
  // the 接活 and 派活 spaces. We listen at the document level so it works
  // regardless of focused element — except text inputs, where ctrl+1 might
  // mean something else to a power user.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "1") { e.preventDefault(); setSpace("work"); }
      else if (e.key === "2") { e.preventDefault(); setSpace("dispatch"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setSpace]);

  useEffect(() => {
    if (!isTauri()) {
      // Browser-only dev mode: skip onboarding, go straight to Hub. Useful for `npm run dev`.
      setCfg({ nickname: "dev", cookie_token: "x", client_token: "x" });
      return;
    }
    (async () => {
      const initial = await invoke<Cfg>("get_config").catch(() => null);
      if (!initial) {
        setCfg({ nickname: "", cookie_token: "", client_token: "" });
        return;
      }
      // Auto re-auth on every launch when a nickname is known. The reqwest
      // cookie jar is *always* empty after process restart (it's in-memory
      // only), so we can't trust `cookie_token` as a signal — it's just a
      // sentinel marking "user has onboarded before". identify is idempotent
      // (same nickname → same user_id), and register_device returns the
      // existing token if the device record already exists.
      if (initial.nickname) {
        try {
          await invoke("identify", { nickname: initial.nickname });
          if (!initial.client_token) {
            await invoke("register_device", { deviceName: window.navigator.platform || "tauri" });
          }
          await invoke("set_config", { patch: { cookie_token: "session" } });
          // The cached config used by clientFetch may still hold the EMPTY
          // client_token captured by the very first ensureCfg call earlier
          // in this effect (before register_device ran). Invalidate so the
          // next /api/* call picks up the fresh token from disk.
          resetClientTokenCache();
          const fresh = await invoke<Cfg>("get_config");
          setCfg(fresh);
          return;
        } catch {
          // fall through — user can finish onboarding manually
        }
      }
      setCfg(initial);
    })();
  }, []);

  // Navigate from native side (deep-link, tray menu)
  useEvent<{ path: string }>("navigate", (p) => {
    if (p?.path) nav(p.path);
  });

  useEvent<{ status: string }>("sse-status", (p) => {
    setSseConnected(p.status === "connected");
  });

  useEvent<any>("tray-action", (p) => {
    if (p?.action === "pull_new") {
      toast({ title: "正在刷新…", tone: "info" });
      nav("/inbox");
    } else if (p?.action === "sync_drive") {
      toast({ title: "请选择项目后点击网盘页同步按钮", tone: "info" });
    } else if (p?.action === "do_deliver") {
      toast({ title: "请选择要交付的需求", tone: "info" });
      nav("/inbox");
    }
  });

  // Bridge SSE push events to BOTH an in-app toast AND a Windows system
  // notification (right-bottom desktop popup) — submitters specifically
  // need the OS notification because they often have the window minimized
  // while waiting for someone to deliver.
  useEvent<any>("push-event", (p) => {
    if (p?.event === "requirement.ready") {
      // Org-wide is intentional here: every desktop user is a worker who
      // wants to know new claimable work hit the public pool.
      const title = `新工单来了 ${p.data?.code ?? ""}`;
      const body = p.data?.title ?? "";
      toast({
        title, description: body, tone: "accent",
        action: p.data?.requirement_id ? {
          label: "去看看",
          onClick: () => nav(`/r/${p.data.requirement_id}`),
        } : undefined,
      });
      osNotify(title, body);
    }
    // NOTE: no global `delivery.doc_ready` handler. That event is now also
    // published to `all` (so the DeliveryWizard, which has its own scoped
    // listener, completes), but a delivery-doc completion is only relevant to
    // the submitter — who receives a user-scoped `delivered` notification.created
    // below — and the delivering worker, who sees the wizard's own toast. A
    // global OS popup to every desktop user on every delivery would be noise.
  });

  // notification.created is per-user; fires the moment the backend creates
  // a notification (e.g. submitter's requirement got claimed/delivered).
  useEvent<any>("push-event", (p) => {
    if (p?.event !== "notification.created") return;
    const { title, body, severity, requirement_id } = p.data || {};
    if (!title) return;
    toast({
      title, description: body, tone: severity === "high" ? "accent" : "info",
      action: requirement_id ? {
        label: "去看看",
        onClick: () => nav(`/r/${requirement_id}`),
      } : undefined,
    });
    osNotify(title, body || "");
    refreshUnreadBadge();
  });

  // Initial badge sync — pick up notifications received while the app was
  // closed. Re-runs whenever cfg changes (covers re-onboarding).
  useEffect(() => {
    if (!cfg?.client_token) return;
    refreshUnreadBadge();
  }, [cfg?.client_token]);

  if (!cfg) {
    return (
      <div className="min-h-screen grid place-items-center text-ink-muted">正在加载客户端…</div>
    );
  }

  const needsOnboarding = !cfg.nickname || !cfg.cookie_token || !cfg.client_token;
  // Only auto-open the tour after onboarding is complete — interrupting
  // the 4-step setup wizard with a tour would be incoherent.
  const tourOpen = !needsOnboarding && !tourSeen;

  const tourSlides = defaultWelcomeSlides("client", {
    Sparkles: <Sparkles className="h-7 w-7" aria-hidden="true" />,
    SwitchHorizontal: <ArrowLeftRight className="h-7 w-7" aria-hidden="true" />,
    Bot: <Bot className="h-7 w-7" aria-hidden="true" />,
    Bell: <BellIcon className="h-7 w-7" aria-hidden="true" />,
    Folder: <FolderKanban className="h-7 w-7" aria-hidden="true" />,
    Command: <CommandIcon className="h-7 w-7" aria-hidden="true" />,
  });

  return (
    <div className="flex flex-col h-screen">
      <TitleBar sseConnected={sseConnected} />
      <WelcomeTour
        open={tourOpen}
        onClose={markTourSeen}
        onFinish={markTourSeen}
        slides={tourSlides}
      />
      {needsOnboarding ? (
        <Routes>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="*" element={<Navigate to="/onboarding" replace />} />
        </Routes>
      ) : (
        // Flat routing avoids the v6 "nested <Routes> under /*" pitfall
        // where the child Routes re-match the full pathname.
        <>
        <div className="flex flex-1 min-h-0">
          <Sidebar />
          <div className="flex-1 min-w-0 min-h-0 flex flex-col">
            <Routes>
              <Route path="/" element={<HubRouter />} />
              <Route path="/r/new" element={<NewRequirement />} />
              <Route path="/r/:id/clarify" element={<Clarify />} />
              <Route path="/r/:id" element={<TaskDetail />} />
              <Route path="/p" element={<ProjectDrive />} />
              <Route path="/p/:projectId" element={<ProjectDrive />} />
              <Route path="/p/:projectId/meetings" element={<ProjectMeetings />} />
              <Route path="/inbox" element={<Inbox />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/me/workload" element={<MyWorkload />} />
              <Route path="/me/knowledge" element={<Knowledge />} />
              <Route path="/me/pulse" element={<ProjectPulse />} />
              <Route path="/me/calendar" element={<Calendar />} />
              <Route path="/onboarding" element={<Navigate to="/" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </div>
        <FloatingAssistant />
        </>
      )}
      <ToastHost />
    </div>
  );
}
