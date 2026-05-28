import { NavLink, useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  FilePen,
  FolderTree,
  Inbox,
  Inspect,
  MessageCircleQuestion,
  Plus,
  Send,
  Settings,
  Star,
  Wrench,
} from "lucide-react";

/**
 * 派活 Space 的左侧栏。布局对称于 SidebarWork，但导航项映射到提交人视角：
 * 起草 / 待澄清 / 投递池 / 在做中 / 待我验收 / 已通过，加上「项目网盘」入口。
 *
 * 顶部 CTA 是「+ 新建需求」big-button — 提交人最常用的动作，珊瑚渐变区分于
 * 接活 Space 的电紫调性。
 */
const NAV: { to: string; label: string; icon: JSX.Element; emphasize?: boolean }[] = [
  { to: "/?dtab=drafts", label: "起草中", icon: <FilePen className="h-4 w-4 text-ink-muted" /> },
  { to: "/?dtab=clarifying", label: "待澄清", icon: <MessageCircleQuestion className="h-4 w-4 text-info" /> },
  { to: "/?dtab=ready", label: "投递池", icon: <Send className="h-4 w-4 text-warn" /> },
  { to: "/?dtab=working", label: "跟进中", icon: <Wrench className="h-4 w-4 text-accent" /> },
  { to: "/?dtab=review", label: "待我验收", icon: <Star className="h-4 w-4 text-accent" />, emphasize: true },
  { to: "/?dtab=accepted", label: "已通过", icon: <CheckCircle2 className="h-4 w-4 text-success" /> },
];

const PROJECT: { to: string; label: string; icon: JSX.Element }[] = [
  { to: "/p", label: "项目网盘", icon: <FolderTree className="h-4 w-4" /> },
];

export function SidebarDispatch({ counts }: { counts?: Record<string, number> }) {
  const nav = useNavigate();
  return (
    <aside
      className="glass-quiet w-56 shrink-0 p-3 flex flex-col gap-4 h-[calc(100vh-2.25rem)]"
      style={{ viewTransitionName: "yqgl-sidebar" }}
    >
      <button
        type="button"
        onClick={() => nav("/r/new")}
        className="flex items-center justify-center gap-2 h-10 rounded-sm text-body-sm font-medium text-white shadow-2 transition hover:opacity-95"
        style={{ background: "linear-gradient(135deg, #FF6E8E 0%, #ffa3b9 100%)" }}
      >
        <Plus className="h-4 w-4" /> 新建需求
      </button>

      <div>
        <div className="text-eyebrow text-ink-faint px-2 mb-2">工单</div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((n) => {
            const count = counts?.[n.to.split("=")[1] ?? ""];
            const showEmphasis = n.emphasize && count != null && count > 0;
            return (
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
                {count != null && (
                  <span
                    className={`text-caption ${
                      showEmphasis
                        ? "px-1.5 py-0.5 rounded-pill text-white"
                        : "text-ink-faint"
                    }`}
                    style={showEmphasis ? { background: "linear-gradient(135deg,#FF6E8E,#ffa3b9)" } : undefined}
                  >
                    {count}
                  </span>
                )}
              </NavLink>
            );
          })}
        </nav>
      </div>

      <div>
        <div className="text-eyebrow text-ink-faint px-2 mb-2">项目</div>
        <nav className="flex flex-col gap-0.5">
          {PROJECT.map((n) => (
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
              <span className="truncate">{n.label}</span>
            </NavLink>
          ))}
          <NavLink
            to="/me/pulse"
            className={({ isActive }) =>
              `flex items-center gap-2 h-9 px-2.5 rounded-sm text-body-sm transition ${
                isActive ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft/60 hover:text-ink"
              }`
            }
          >
            <Inspect className="h-4 w-4" />
            <span className="truncate">项目快报</span>
          </NavLink>
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
