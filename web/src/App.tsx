import { useState } from "react";
import { BrowserRouter, Link, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import {
  ArrowLeftRight,
  Bell,
  Bot,
  CalendarDays,
  ChevronDown,
  Command,
  FolderKanban,
  Gauge,
  HeartPulse,
  HelpCircle,
  LayoutDashboard,
  Monitor,
  Moon,
  Search,
  Settings,
  Sparkles,
  Sun,
  UserRound,
  Users,
} from "lucide-react";
import { useIdentity } from "./hooks/useIdentity";
import { NicknameDialog } from "./components/NicknameDialog";
import { SettingsDialog } from "./components/SettingsDialog";
import { ClientDownloadBanner } from "./components/ClientDownloadBanner";
import { Home } from "./pages/Home";
import { ProjectView } from "./pages/ProjectView";
import { NewRequirement } from "./pages/NewRequirement";
import { Clarify } from "./pages/Clarify";
import { Dashboard } from "./pages/Dashboard";
import { RequirementDetail } from "./pages/RequirementDetail";
import { DriveHome } from "./pages/DriveHome";
import { ProjectDrive } from "./pages/ProjectDrive";
import { CalendarPage } from "./pages/CalendarPage";
import { ProjectMeetings } from "./pages/ProjectMeetings";
import { KnowledgePage } from "./pages/KnowledgePage";
import { PlanningPage } from "./pages/PlanningPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { HealthPage } from "./pages/HealthPage";
import {
  DropdownMenu,
  DropdownItem,
  DropdownLabel,
  DropdownDivider,
  ToastHost,
  CommandMenu,
  useCommandMenu,
  useFirstRun,
  useTheme,
  WelcomeTour,
  defaultWelcomeSlides,
  type CommandItem,
} from "@yqgl/shared";

export function App() {
  const { me, identify, loading } = useIdentity();
  const [settingsOpen, setSettingsOpen] = useState(false);
  // First-run welcome tour state. `seen` is hydrated from localStorage so
  // returning users never see the tour flash. `reset` is exposed via the
  // command palette + Settings so users can re-open it.
  const { seen: tourSeen, markSeen: markTourSeen, reset: resetTour } = useFirstRun();
  const [tourOpenManual, setTourOpenManual] = useState(false);
  // Auto-show right after a successful identify (i.e. once we have `me`
  // and the user has never seen it). Manual re-opens are separate.
  const tourOpen = (!!me && !tourSeen) || tourOpenManual;

  if (loading) {
    return (
      <main className="app-shell grid place-items-center px-6 text-stone-500">
        <div className="paper-surface px-5 py-4 text-sm">正在打开…</div>
      </main>
    );
  }

  if (!me) {
    return <NicknameDialog onSubmit={async (n) => { await identify(n); }} />;
  }

  const slides = defaultWelcomeSlides("web", {
    Sparkles: <Sparkles className="h-7 w-7" aria-hidden="true" />,
    SwitchHorizontal: <ArrowLeftRight className="h-7 w-7" aria-hidden="true" />,
    Bot: <Bot className="h-7 w-7" aria-hidden="true" />,
    Bell: <Bell className="h-7 w-7" aria-hidden="true" />,
    Folder: <FolderKanban className="h-7 w-7" aria-hidden="true" />,
    Command: <Command className="h-7 w-7" aria-hidden="true" />,
  });

  return (
    <>
      <BrowserRouter>
        <Shell
          nickname={me.nickname}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenWelcome={() => { resetTour(); setTourOpenManual(true); }}
        />
      </BrowserRouter>
      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onShowWelcome={() => { setSettingsOpen(false); resetTour(); setTourOpenManual(true); }}
      />
      <WelcomeTour
        open={tourOpen}
        onClose={() => { markTourSeen(); setTourOpenManual(false); }}
        onFinish={markTourSeen}
        slides={slides}
      />
      <ToastHost />
    </>
  );
}

/** Shell = top nav + routes + global ⌘K command menu. Needs to live under <BrowserRouter>. */
function Shell({
  nickname,
  onOpenSettings,
  onOpenWelcome,
}: {
  nickname: string;
  onOpenSettings: () => void;
  onOpenWelcome: () => void;
}) {
  const nav = useNavigate();
  const { open, setOpen, close } = useCommandMenu();

  const commands: CommandItem[] = [
    { id: "home", label: "回到项目首页", group: "导航", searchText: "首页 项目 home", onSelect: () => nav("/") },
    { id: "dashboard", label: "打开派活看板", group: "导航", searchText: "看板 派活 dashboard", onSelect: () => nav("/dashboard") },
    { id: "planning", label: "资源排期", group: "导航", searchText: "排期 负载 planning", onSelect: () => nav("/planning") },
    { id: "health", label: "项目健康度", group: "导航", searchText: "健康 health", onSelect: () => nav("/health") },
    { id: "knowledge", label: "历史搜索", group: "导航", searchText: "知识库 搜索 历史", onSelect: () => nav("/knowledge") },
    { id: "calendar", label: "我的日程", group: "导航", searchText: "日程 日历 calendar", onSelect: () => nav("/calendar") },
    { id: "notif", label: "通知中心", group: "导航", searchText: "通知 inbox", onSelect: () => nav("/notifications") },
    { id: "settings", label: "设置", group: "操作", searchText: "设置 settings", onSelect: onOpenSettings },
    { id: "welcome", label: "再看一遍新手引导", group: "操作", searchText: "引导 教程 帮助 welcome tour help", onSelect: onOpenWelcome },
  ];

  return (
    <div className="app-shell">
      <ClientDownloadBanner />
      <TopNav
        nickname={nickname}
        onOpenSettings={onOpenSettings}
        onOpenCommand={() => setOpen(true)}
        onOpenWelcome={onOpenWelcome}
      />
      <Routes>
        <Route path="/" element={<Home />} />
        {/* Boards: PM/派活方视角 — 网页保留这些工具，客户端会自带更聚焦的"我的"视图 */}
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/local-workbench" element={<Dashboard />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/planning" element={<PlanningPage />} />
        <Route path="/health" element={<HealthPage />} />
        {/* Project / requirement flows */}
        <Route path="/drive" element={<DriveHome />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/p/:id" element={<ProjectView />} />
        <Route path="/p/:id/drive" element={<ProjectDrive />} />
        <Route path="/p/:id/meetings" element={<ProjectMeetings />} />
        <Route path="/p/:id/new" element={<NewRequirement />} />
        <Route path="/r/:id" element={<RequirementDetail />} />
        <Route path="/r/:id/clarify" element={<Clarify />} />
        {/* Catch-all: an unknown URL (stale bookmark, mistyped path, or a
            deep-link to a route that no longer exists) renders a friendly
            not-found with a way back instead of a blank white page. */}
        <Route path="*" element={<NotFound />} />
      </Routes>
      <CommandMenu open={open} onClose={close} items={commands} />
    </div>
  );
}

/**
 * Top nav (sticky glass bar).
 * 4 主入口：项目 · 日程 · 通知 · 设置；二级"看板"下拉包含 全员看板 / 资源排期 / 项目健康度 / 知识库。
 * 删除原来的"派活看板/本地工作台"主入口 —— 接单方动作仅在桌面客户端发生。
 */
function TopNav({
  nickname,
  onOpenSettings,
  onOpenCommand,
  onOpenWelcome,
}: {
  nickname: string;
  onOpenSettings: () => void;
  onOpenCommand: () => void;
  onOpenWelcome: () => void;
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-line glass-quiet">
      <div className="mx-auto flex w-full max-w-[1760px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-4">
          <Link to="/" className="flex min-w-0 items-center gap-2 text-base font-semibold text-ink">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-sm bg-accent text-white shadow-e1">
              <FolderKanban className="h-4 w-4" aria-hidden="true" />
            </span>
            <span className="truncate">需求管理大师</span>
          </Link>
          <nav className="flex items-center gap-1">
            <NavItem to="/" icon={<FolderKanban className="h-4 w-4" />}>项目</NavItem>
            <BoardsMenu />
            <NavItem to="/calendar" icon={<CalendarDays className="h-4 w-4" />}>日程</NavItem>
            <NavItem to="/notifications" icon={<Bell className="h-4 w-4" />}>通知</NavItem>
          </nav>
        </div>
        <div className="flex min-w-0 items-center gap-2 text-xs text-ink-muted">
          <button
            className="button-ghost h-9 px-2.5 text-xs gap-1.5"
            onClick={onOpenCommand}
            title="搜索 / 命令面板（⌘K）"
            aria-label="命令面板"
          >
            <Command className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">搜索…</span>
            <kbd className="hidden sm:inline-block ml-2 rounded-xs border border-line px-1 text-[10px]">⌘K</kbd>
          </button>
          <ThemeToggle />
          <span className="pill max-w-[48vw] sm:max-w-none">
            <UserRound className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{nickname}</span>
          </span>
          <button
            className="button-ghost min-h-9 w-9 px-0"
            title="新手引导"
            aria-label="新手引导"
            onClick={onOpenWelcome}
          >
            <HelpCircle className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            className="button-ghost min-h-9 w-9 px-0"
            title="设置"
            aria-label="设置"
            onClick={onOpenSettings}
          >
            <Settings className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
  );
}

function NotFound() {
  return (
    <main className="narrow-container">
      <div className="paper-surface mt-10 p-8 text-center">
        <p className="eyebrow">404</p>
        <h1 className="mt-2 text-2xl font-semibold text-stone-950">这个页面不存在</h1>
        <p className="mt-3 text-sm text-stone-500">链接可能过期了，或者地址打错了。</p>
        <Link to="/" className="button-primary mt-6 inline-flex">回到项目首页</Link>
      </div>
    </main>
  );
}

function ThemeToggle() {
  const { mode, setMode } = useTheme();
  const next = mode === "auto" ? "light" : mode === "light" ? "dark" : "auto";
  const icon =
    mode === "auto" ? <Monitor className="h-4 w-4" /> :
    mode === "light" ? <Sun className="h-4 w-4" /> :
    <Moon className="h-4 w-4" />;
  return (
    <button
      onClick={() => setMode(next)}
      className="button-ghost min-h-9 w-9 px-0"
      title={`外观：${mode === "auto" ? "跟随系统" : mode === "light" ? "亮" : "暗"} — 点击切换`}
      aria-label="切换外观"
    >
      {icon}
    </button>
  );
}

function NavItem({ to, icon, children }: { to: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `button-ghost min-h-9 px-3 py-1.5 text-xs ${isActive ? "bg-accent-soft text-ink" : ""}`
      }
    >
      {icon}
      {children}
    </NavLink>
  );
}

/** PM/派活方工具的二级菜单：派活看板 / 资源排期 / 项目健康度 / 知识库。 */
function BoardsMenu() {
  const nav = useNavigate();
  const go = (path: string) => nav(path);
  return (
    <DropdownMenu
      trigger={
        <button className="button-ghost min-h-9 px-3 py-1.5 text-xs">
          <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
          看板
          <ChevronDown className="h-3.5 w-3.5 opacity-70" aria-hidden="true" />
        </button>
      }
    >
      <DropdownLabel>派活方工具</DropdownLabel>
      <DropdownItem onClick={() => go("/dashboard")}>
        <Gauge className="h-4 w-4" /> 派活看板
      </DropdownItem>
      <DropdownItem onClick={() => go("/planning")}>
        <Users className="h-4 w-4" /> 资源排期
      </DropdownItem>
      <DropdownItem onClick={() => go("/health")}>
        <HeartPulse className="h-4 w-4" /> 项目健康度
      </DropdownItem>
      <DropdownDivider />
      <DropdownItem onClick={() => go("/knowledge")}>
        <Search className="h-4 w-4" /> 历史搜索
      </DropdownItem>
    </DropdownMenu>
  );
}
