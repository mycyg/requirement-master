import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate, useSearchParams } from "react-router-dom";
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
import type { Requirement } from "@yqgl/shared";
import { invoke, useEvent } from "@/lib/tauri";
import { TABS } from "@/routes/HubDispatch";

/**
 * 派活 Space 的左侧栏。布局对称于 SidebarWork，导航项映射到提交人视角：
 * 起草 / 待澄清 / 投递池 / 跟进中 / 待我验收 / 已通过，加上「项目网盘」入口。
 *
 * 工单分组是 `/?dtab=...` 查询参数标签（同一 pathname `/`），激活态必须按
 * dtab 值判断，否则所有标签同时高亮。默认 dtab=review，与 HubDispatch.tsx 一致。
 *
 * 角标（尤其「待我验收」的珊瑚渐变）由本组件自取数据，独立于当前路由——
 * HubDispatch 只在它是当前页时刷新，而角标需要在任何页面都实时反映「已交付待
 * 验收」的数量。数据源与 HubDispatch 相同（list_my mine:true），状态映射复用
 * 导出的 TABS，避免漂移。
 */
const NAV: { to: string; dtab: string; label: string; icon: JSX.Element; emphasize?: boolean }[] = [
  { to: "/?dtab=drafts", dtab: "drafts", label: "起草中", icon: <FilePen className="h-4 w-4 text-ink-muted" /> },
  { to: "/?dtab=clarifying", dtab: "clarifying", label: "待澄清", icon: <MessageCircleQuestion className="h-4 w-4 text-info" /> },
  { to: "/?dtab=ready", dtab: "ready", label: "投递池", icon: <Send className="h-4 w-4 text-warn" /> },
  { to: "/?dtab=working", dtab: "working", label: "跟进中", icon: <Wrench className="h-4 w-4 text-accent" /> },
  { to: "/?dtab=review", dtab: "review", label: "待我验收", icon: <Star className="h-4 w-4 text-accent" />, emphasize: true },
  { to: "/?dtab=accepted", dtab: "accepted", label: "已通过", icon: <CheckCircle2 className="h-4 w-4 text-success" /> },
];

const linkClass = (active: boolean) =>
  `flex items-center gap-2 h-9 px-2.5 rounded-sm text-body-sm transition ${
    active ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft/60 hover:text-ink"
  }`;

export function SidebarDispatch() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { pathname } = useLocation();
  const activeTab = pathname === "/" ? params.get("dtab") || "review" : null;

  const [rows, setRows] = useState<Requirement[] | null>(null);
  const loadCounts = async () => {
    try { setRows(await invoke<Requirement[]>("list_my", { mine: true })); }
    catch { /* badge is best-effort — don't surface errors in the chrome */ }
  };
  useEffect(() => { loadCounts(); }, []);
  // Live: a delivery (requirement.updated → delivered) bumps the 待我验收 count
  // even when the user is on another page.
  useEvent<{ event: string }>("push-event", (p) => {
    if (p?.event === "requirement.updated" || p?.event === "requirement.ready") loadCounts();
  });

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    if (!rows) return c;
    for (const t of TABS) c[t.id] = rows.filter((r) => t.statuses.includes(r.status)).length;
    return c;
  }, [rows]);

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
        <div className="text-eyebrow text-ink-faint px-2 mb-2">需求</div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((n) => {
            const count = counts[n.dtab] ?? 0;
            const showEmphasis = n.emphasize && count > 0;
            return (
              <NavLink key={n.to} to={n.to} className={linkClass(activeTab === n.dtab)}>
                {n.icon}
                <span className="flex-1 truncate">{n.label}</span>
                {count > 0 && (
                  <span
                    className={`text-caption ${
                      showEmphasis ? "px-1.5 py-0.5 rounded-pill text-white" : "text-ink-faint"
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
          <NavLink to="/p" className={({ isActive }) => linkClass(isActive)}>
            <FolderTree className="h-4 w-4" />
            <span className="truncate">项目网盘</span>
          </NavLink>
          <NavLink to="/me/pulse" className={({ isActive }) => linkClass(isActive)}>
            <Inspect className="h-4 w-4" />
            <span className="truncate">项目快报</span>
          </NavLink>
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
