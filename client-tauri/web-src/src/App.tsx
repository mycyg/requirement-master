import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { ToastHost, toast, useSpace } from "@yqgl/shared";
import { TitleBar } from "@/components/TitleBar";
import { Sidebar } from "@/components/Sidebar";
import { Hub } from "@/routes/Hub";
import { HubDispatch } from "@/routes/HubDispatch";
import { NewRequirement } from "@/routes/NewRequirement";
import { Clarify } from "@/routes/Clarify";
import { ProjectDrive } from "@/routes/ProjectDrive";
import { TaskDetail } from "@/routes/TaskDetail";
import { Inbox } from "@/routes/Inbox";
import { Onboarding } from "@/routes/Onboarding";
import { Settings } from "@/routes/Settings";
import { MyWorkload } from "@/routes/MyWorkload";
import { Knowledge } from "@/routes/Knowledge";
import { ProjectPulse } from "@/routes/ProjectPulse";
import { Calendar } from "@/routes/Calendar";
import { invoke, useEvent, isTauri } from "@/lib/tauri";

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
      toast({ title: "正在拉新需求…", tone: "info" });
    } else if (p?.action === "sync_drive") {
      toast({ title: "正在同步网盘…", tone: "info" });
    } else if (p?.action === "do_deliver") {
      toast({ title: "请选择要交付的需求", tone: "info" });
    }
  });

  useEvent<any>("push-event", (p) => {
    if (p?.event === "requirement.ready") {
      toast({
        title: `新工单来了 ${p.data?.code ?? ""}`,
        description: p.data?.title ?? "",
        tone: "accent",
        action: p.data?.requirement_id ? {
          label: "去看看",
          onClick: () => nav(`/r/${p.data.requirement_id}`),
        } : undefined,
      });
    } else if (p?.event === "delivery.doc_ready") {
      toast({ title: "AI 助理写完交付文档了", tone: "success" });
    }
  });

  if (!cfg) {
    return (
      <div className="min-h-screen grid place-items-center text-ink-muted">正在加载客户端…</div>
    );
  }

  const needsOnboarding = !cfg.nickname || !cfg.cookie_token || !cfg.client_token;

  return (
    <div className="flex flex-col h-screen">
      <TitleBar sseConnected={sseConnected} />
      {needsOnboarding ? (
        <Routes>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="*" element={<Navigate to="/onboarding" replace />} />
        </Routes>
      ) : (
        // Flat routing avoids the v6 "nested <Routes> under /*" pitfall
        // where the child Routes re-match the full pathname.
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
      )}
      <ToastHost />
    </div>
  );
}
