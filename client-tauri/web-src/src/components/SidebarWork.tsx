import { NavLink, useLocation, useSearchParams } from "react-router-dom";
import {
  CalendarDays,
  Flame,
  Hammer,
  HeartPulse,
  Inbox,
  PackageCheck,
  RotateCcw,
  Search,
  Settings,
  TrendingUp,
  CircleCheck,
} from "lucide-react";

// 接活 Space 左侧栏。工单分组是 `/?tab=...` 查询参数标签（同一 pathname `/`），
// 所以激活态必须按 tab 值判断，不能用 NavLink 默认的 pathname 匹配——否则
// 所有标签会同时高亮（pathname 全是 `/`）。默认 tab=public，与 Hub.tsx 一致。
const NAV: { to: string; tab: string; label: string; icon: JSX.Element }[] = [
  { to: "/?tab=public", tab: "public", label: "公共池", icon: <Flame className="h-4 w-4 text-error" /> },
  { to: "/?tab=mine", tab: "mine", label: "派给我的", icon: <Hammer className="h-4 w-4 text-warn" /> },
  { to: "/?tab=active", tab: "active", label: "进行中", icon: <PackageCheck className="h-4 w-4 text-accent" /> },
  { to: "/?tab=revision", tab: "revision", label: "待返工", icon: <RotateCcw className="h-4 w-4 text-error" /> },
  { to: "/?tab=delivered", tab: "delivered", label: "近期交付", icon: <CircleCheck className="h-4 w-4 text-success" /> },
];

const VIEWS = [
  { to: "/me/workload", label: "我的负载", icon: <TrendingUp className="h-4 w-4" /> },
  { to: "/me/calendar", label: "我的日程", icon: <CalendarDays className="h-4 w-4" /> },
  { to: "/me/knowledge", label: "历史检索", icon: <Search className="h-4 w-4" /> },
  { to: "/me/pulse", label: "项目快报", icon: <HeartPulse className="h-4 w-4" /> },
];

const linkClass = (active: boolean) =>
  `flex items-center gap-2 h-9 px-2.5 rounded-sm text-body-sm transition ${
    active ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft/60 hover:text-ink"
  }`;

export function SidebarWork() {
  const [params] = useSearchParams();
  const { pathname } = useLocation();
  // Only one tab is active, and only while we're on the hub route `/`.
  const activeTab = pathname === "/" ? params.get("tab") || "public" : null;

  return (
    <aside
      className="glass-quiet w-56 shrink-0 p-3 flex flex-col gap-4 h-[calc(100vh-2.25rem)]"
      style={{ viewTransitionName: "yqgl-sidebar" }}
    >
      <div>
        <div className="text-eyebrow text-ink-faint px-2 mb-2">需求</div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={linkClass(activeTab === n.tab)}>
              {n.icon}
              <span className="flex-1 truncate">{n.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      <div>
        <div className="text-eyebrow text-ink-faint px-2 mb-2">视角</div>
        <nav className="flex flex-col gap-0.5">
          {VIEWS.map((v) => (
            <NavLink key={v.to} to={v.to} className={({ isActive }) => linkClass(isActive)}>
              {v.icon}
              <span className="truncate">{v.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="mt-auto pt-3 border-t border-line flex flex-col gap-0.5">
        <NavLink to="/inbox" className={({ isActive }) => linkClass(isActive)}>
          <Inbox className="h-4 w-4" /> 通知
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => linkClass(isActive)}>
          <Settings className="h-4 w-4" /> 设置
        </NavLink>
      </div>
    </aside>
  );
}
