import { useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { useIdentity } from "./hooks/useIdentity";
import { NicknameDialog } from "./components/NicknameDialog";
import { SettingsDialog } from "./components/SettingsDialog";
import { Home } from "./pages/Home";
import { ProjectView } from "./pages/ProjectView";
import { NewRequirement } from "./pages/NewRequirement";
import { Clarify } from "./pages/Clarify";
import { Dashboard } from "./pages/Dashboard";
import { RequirementDetail } from "./pages/RequirementDetail";

export function App() {
  const { me, identify, loading } = useIdentity();
  const [settingsOpen, setSettingsOpen] = useState(false);

  if (loading) return <main className="p-12 text-slate-500">加载中…</main>;

  if (!me) {
    return <NicknameDialog onSubmit={async (n) => { await identify(n); }} />;
  }

  return (
    <>
      <BrowserRouter>
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
            <div className="flex items-baseline gap-5">
              <Link to="/" className="text-base font-semibold tracking-tight">需求管理大师</Link>
              <Link to="/dashboard" className="text-xs text-slate-500 hover:text-slate-900">接单看板</Link>
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span>👤 {me.nickname}</span>
              <button
                className="rounded px-2 py-1 hover:bg-slate-100"
                title="设置"
                onClick={() => setSettingsOpen(true)}
              >
                ⚙️
              </button>
            </div>
          </div>
        </header>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/p/:id" element={<ProjectView />} />
          <Route path="/p/:id/new" element={<NewRequirement />} />
          <Route path="/r/:id" element={<RequirementDetail />} />
          <Route path="/r/:id/clarify" element={<Clarify />} />
        </Routes>
      </BrowserRouter>
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
