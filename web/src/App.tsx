import { useState } from "react";
import { BrowserRouter, Link, NavLink, Route, Routes } from "react-router-dom";
import { FolderKanban, Gauge, HardDrive, Settings, UserRound } from "lucide-react";
import { useIdentity } from "./hooks/useIdentity";
import { NicknameDialog } from "./components/NicknameDialog";
import { SettingsDialog } from "./components/SettingsDialog";
import { Home } from "./pages/Home";
import { ProjectView } from "./pages/ProjectView";
import { NewRequirement } from "./pages/NewRequirement";
import { Clarify } from "./pages/Clarify";
import { Dashboard } from "./pages/Dashboard";
import { RequirementDetail } from "./pages/RequirementDetail";
import { DriveHome } from "./pages/DriveHome";
import { ProjectDrive } from "./pages/ProjectDrive";

export function App() {
  const { me, identify, loading } = useIdentity();
  const [settingsOpen, setSettingsOpen] = useState(false);

  if (loading) {
    return (
      <main className="app-shell grid place-items-center px-6 text-stone-500">
        <div className="paper-surface px-5 py-4 text-sm">加载工作台...</div>
      </main>
    );
  }

  if (!me) {
    return <NicknameDialog onSubmit={async (n) => { await identify(n); }} />;
  }

  return (
    <>
      <BrowserRouter>
        <div className="app-shell">
          <header className="sticky top-0 z-40 border-b border-stone-200/90 bg-[#fffdf8]/90 backdrop-blur-xl">
            <div className="mx-auto flex w-full max-w-[1760px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
              <div className="flex min-w-0 items-center gap-4">
                <Link to="/" className="flex min-w-0 items-center gap-2 text-base font-semibold text-stone-950">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-stone-300 bg-stone-950 text-[#fffdf8]">
                    <FolderKanban className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <span className="truncate">需求管理大师</span>
                </Link>
                <nav className="flex items-center gap-1">
                  <NavLink
                    to="/"
                    className={({ isActive }) =>
                      `button-ghost min-h-9 px-3 py-1.5 text-xs ${isActive ? "bg-stone-900/10 text-stone-950" : ""}`
                    }
                  >
                    <FolderKanban className="h-4 w-4" aria-hidden="true" />
                    项目
                  </NavLink>
                  <NavLink
                    to="/dashboard"
                    className={({ isActive }) =>
                      `button-ghost min-h-9 px-3 py-1.5 text-xs ${isActive ? "bg-stone-900/10 text-stone-950" : ""}`
                    }
                  >
                    <Gauge className="h-4 w-4" aria-hidden="true" />
                    看板
                  </NavLink>
                  <NavLink
                    to="/drive"
                    className={({ isActive }) =>
                      `button-ghost min-h-9 px-3 py-1.5 text-xs ${isActive ? "bg-stone-900/10 text-stone-950" : ""}`
                    }
                  >
                    <HardDrive className="h-4 w-4" aria-hidden="true" />
                    网盘
                  </NavLink>
                </nav>
              </div>
              <div className="flex min-w-0 items-center gap-2 text-xs text-stone-500">
                <span className="pill max-w-[48vw] sm:max-w-none">
                  <UserRound className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span className="truncate">{me.nickname}</span>
                </span>
                <button
                  className="button-ghost min-h-9 w-9 px-0"
                  title="设置"
                  aria-label="设置"
                  onClick={() => setSettingsOpen(true)}
                >
                  <Settings className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            </div>
          </header>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/drive" element={<DriveHome />} />
            <Route path="/p/:id" element={<ProjectView />} />
            <Route path="/p/:id/drive" element={<ProjectDrive />} />
            <Route path="/p/:id/new" element={<NewRequirement />} />
            <Route path="/r/:id" element={<RequirementDetail />} />
            <Route path="/r/:id/clarify" element={<Clarify />} />
          </Routes>
        </div>
      </BrowserRouter>
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
