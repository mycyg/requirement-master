import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { ToastHost, toast } from "@yqgl/shared";
import { TitleBar } from "@/components/TitleBar";
import { Sidebar } from "@/components/Sidebar";
import { Hub } from "@/routes/Hub";
import { TaskDetail } from "@/routes/TaskDetail";
import { Inbox } from "@/routes/Inbox";
import { Onboarding } from "@/routes/Onboarding";
import { Settings } from "@/routes/Settings";
import { MyWorkload } from "@/routes/MyWorkload";
import { Knowledge } from "@/routes/Knowledge";
import { ProjectPulse } from "@/routes/ProjectPulse";
import { Calendar } from "@/routes/Calendar";
import { invoke, useEvent, isTauri } from "@/lib/tauri";

type Cfg = { nickname: string; cookie_token: string; client_token: string };

export function App() {
  const nav = useNavigate();
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [sseConnected, setSseConnected] = useState(false);

  useEffect(() => {
    if (!isTauri()) {
      // Browser-only dev mode: skip onboarding, go straight to Hub. Useful for `npm run dev`.
      setCfg({ nickname: "dev", cookie_token: "x", client_token: "x" });
      return;
    }
    invoke<Cfg>("get_config").then(setCfg).catch(() => setCfg({ nickname: "", cookie_token: "", client_token: "" }));
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
      <Routes>
        {needsOnboarding ? (
          <>
            <Route path="/onboarding" element={<Onboarding />} />
            <Route path="*" element={<Navigate to="/onboarding" replace />} />
          </>
        ) : (
          <>
            <Route
              path="/*"
              element={
                <div className="flex flex-1 min-h-0">
                  <Sidebar />
                  <div className="flex-1 min-w-0 min-h-0 flex flex-col">
                    <Routes>
                      <Route path="/" element={<Hub />} />
                      <Route path="/r/:id" element={<TaskDetail />} />
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
              }
            />
          </>
        )}
      </Routes>
      <ToastHost />
    </div>
  );
}
