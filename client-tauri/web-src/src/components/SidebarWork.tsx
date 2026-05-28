import { NavLink } from "react-router-dom";
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

const NAV: { to: string; label: string; icon: JSX.Element }[] = [
  { to: "/?tab=public", label: "在抓", icon: <Flame className="h-4 w-4 text-error" /> },
  { to: "/?tab=mine", label: "找我的", icon: <Hammer className="h-4 w-4 text-warn" /> },
  { to: "/?tab=active", label: "进行中", icon: <PackageCheck className="h-4 w-4 text-accent" /> },
  { to: "/?tab=revision", label: "待返工", icon: <RotateCcw className="h-4 w-4 text-error" /> },
  { to: "/?tab=delivered", label: "近期交付", icon: <CircleCheck className="h-4 w-4 text-success" /> },
];

const VIEWS = [
  { to: "/me/workload", label: "我的负载", icon: <TrendingUp className="h-4 w-4" /> },
  { to: "/me/calendar", label: "我的日程", icon: <CalendarDays className="h-4 w-4" /> },
  { to: "/me/knowledge", label: "翻历史", icon: <Search className="h-4 w-4" /> },
  { to: "/me/pulse", label: "项目快报", icon: <HeartPulse className="h-4 w-4" /> },
];

export function SidebarWork({ counts }: { counts?: Record<string, number> }) {
  return (
    <aside
      className="glass-quiet w-56 shrink-0 p-3 flex flex-col gap-4 h-[calc(100vh-2.25rem)]"
      style={{ viewTransitionName: "yqgl-sidebar" }}
    >
      <div>
        <div className="text-eyebrow text-ink-faint px-2 mb-2">工单</div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `flex items-center gap-2 h-9 px-2.5 rounded-sm text-body-sm transition ${
                  isActive ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft/60 hover:text-ink"
                }`
              }
            >
              {n.icon}
              <span className="flex-1 truncate">{n.label}</span>
              {counts && counts[n.to.split("=")[1] ?? ""] != null && (
                <span className="text-caption text-ink-faint">{counts[n.to.split("=")[1] ?? ""]}</span>
              )}
            </NavLink>
          ))}
        </nav>
      </div>

      <div>
        <div className="text-eyebrow text-ink-faint px-2 mb-2">视角</div>
        <nav className="flex flex-col gap-0.5">
          {VIEWS.map((v) => (
            <NavLink
              key={v.to}
              to={v.to}
              className={({ isActive }) =>
                `flex items-center gap-2 h-9 px-2.5 rounded-sm text-body-sm transition ${
                  isActive ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft/60 hover:text-ink"
                }`
              }
            >
              {v.icon}
              <span className="truncate">{v.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="mt-auto pt-3 border-t border-line flex flex-col gap-0.5">
        <NavLink
          to="/inbox"
          className={({ isActive }) =>
            `flex items-center gap-2 h-9 px-2.5 rounded-sm text-body-sm transition ${
              isActive ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft/60 hover:text-ink"
            }`
          }
        >
          <Inbox className="h-4 w-4" /> 通知
        </NavLink>
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `flex items-center gap-2 h-9 px-2.5 rounded-sm text-body-sm transition ${
              isActive ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft/60 hover:text-ink"
            }`
          }
        >
          <Settings className="h-4 w-4" /> 设置
        </NavLink>
      </div>
    </aside>
  );
}
