import { useEffect, useMemo, useState } from "react";
import { Search, Star, UserPlus, Users, X } from "lucide-react";
import { api } from "@/lib/api";
import type { UserOption } from "@/lib/types";

type Props = {
  leadUserId: string | null;
  collaboratorUserIds: string[];
  onChange: (next: { leadUserId: string | null; collaboratorUserIds: string[] }) => void;
  selectedUsers?: UserOption[];
  disabled?: boolean;
  label?: string;
  surface?: boolean;
};
const EMPTY_SELECTED_USERS: UserOption[] = [];

function unique(xs: string[]): string[] {
  return [...new Set(xs.filter(Boolean))];
}

function statusLabel(user?: UserOption): string {
  if (!user) return "状态未知";
  const availability = availabilityLabel(user);
  if (user.is_online) return `在线 · ${availability}`;
  if (!user.last_seen_at) return "未上线";
  const seenAt = new Date(user.last_seen_at).getTime();
  if (Number.isNaN(seenAt)) return "离线";
  const diff = Math.max(0, Date.now() - seenAt);
  if (diff < 60_000) return "刚刚在线";
  if (diff < 60 * 60_000) return `${Math.max(1, Math.round(diff / 60_000))} 分钟前`;
  if (diff < 24 * 60 * 60_000) return `${Math.max(1, Math.round(diff / (60 * 60_000)))} 小时前`;
  return "很久没冒泡";
}

function statusDotClass(user?: UserOption): string {
  if (!user?.is_online) return "bg-stone-300";
  if (user.availability_status === "busy") return "bg-[#b95538] shadow-[0_0_0_3px_rgba(185,85,56,0.14)]";
  if (user.availability_status === "custom") return "bg-[#59758f] shadow-[0_0_0_3px_rgba(89,117,143,0.14)]";
  return "bg-[#4f7d45] shadow-[0_0_0_3px_rgba(79,125,69,0.14)]";
}

function availabilityLabel(user?: UserOption): string {
  if (!user) return "状态未知";
  if (user.availability_status === "busy") return user.availability_text || "忙碌";
  if (user.availability_status === "custom") return user.availability_text || "自定义状态";
  return "空闲";
}

function availabilityPillClass(user: UserOption): string {
  if (!user.is_online) return "border-stone-200 bg-stone-100 text-stone-500";
  if (user.availability_status === "busy") return "border-[#e0b8ad] bg-[#fff0ec] text-[#9f4129]";
  if (user.availability_status === "custom") return "border-[#bbd6d0] bg-[#eef8f5] text-[#376b60]";
  return "border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]";
}

export function AssigneeSelector({
  leadUserId,
  collaboratorUserIds,
  onChange,
  selectedUsers = EMPTY_SELECTED_USERS,
  disabled,
  label = "接单人",
  surface = true,
}: Props) {
  const [search, setSearch] = useState("");
  const [users, setUsers] = useState<UserOption[]>([]);
  const [knownUserMap, setKnownUserMap] = useState<Record<string, UserOption>>({});
  const [err, setErr] = useState<string | null>(null);
  const selectedIds = useMemo(() => unique([leadUserId || "", ...collaboratorUserIds]), [leadUserId, collaboratorUserIds]);
  const sortedUsers = useMemo(
    () => {
      const rank = (u: UserOption) => {
        if (!u.is_online) return 10;
        if ((u.availability_status || "free") === "free") return 0;
        if (u.availability_status === "custom") return 1;
        if (u.availability_status === "busy") return 2;
        return 3;
      };
      return [...users].sort((a, b) => rank(a) - rank(b) || a.nickname.localeCompare(b.nickname, "zh-Hans-CN"));
    },
    [users],
  );
  const onlineCount = useMemo(() => users.filter((u) => u.is_online).length, [users]);

  useEffect(() => {
    setKnownUserMap((prev) => {
      const next = { ...prev };
      [...selectedUsers, ...users].forEach((u) => { next[u.id] = u; });
      return next;
    });
  }, [selectedUsers, users]);

  useEffect(() => {
    if (disabled) return;
    let alive = true;
    api.listUsers(search)
      .then((rows) => { if (alive) { setUsers(rows); setErr(null); } })
      .catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, [search, disabled]);

  const nick = (id: string) => knownUserMap[id]?.nickname || id.slice(0, 8);
  const setLead = (user: UserOption) => {
    if (disabled) return;
    onChange({
      leadUserId: user.id,
      collaboratorUserIds: unique(collaboratorUserIds.filter((id) => id !== user.id)),
    });
  };
  const toggleCollaborator = (user: UserOption) => {
    if (disabled) return;
    if (!leadUserId) {
      onChange({ leadUserId: user.id, collaboratorUserIds: [] });
      return;
    }
    if (leadUserId === user.id) return;
    const exists = collaboratorUserIds.includes(user.id);
    onChange({
      leadUserId,
      collaboratorUserIds: exists
        ? collaboratorUserIds.filter((id) => id !== user.id)
        : unique([...collaboratorUserIds, user.id]),
    });
  };
  const remove = (id: string) => {
    if (disabled) return;
    if (leadUserId === id) {
      const [nextLead, ...rest] = collaboratorUserIds;
      onChange({ leadUserId: nextLead || null, collaboratorUserIds: rest });
    } else {
      onChange({ leadUserId, collaboratorUserIds: collaboratorUserIds.filter((x) => x !== id) });
    }
  };

  return (
    <div className={surface ? "paper-panel p-4" : ""}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-stone-900">
            <Users className="h-4 w-4 text-stone-500" aria-hidden="true" />
            {label}
          </div>
          <p className="mt-1 text-xs leading-5 text-stone-500">
            留空就是公开待接单池；选人后，负责人和协作者都能处理和交付。
          </p>
        </div>
        <div className="flex flex-wrap gap-2 sm:justify-end">
          {!disabled && <span className="pill w-fit">{onlineCount ? `${onlineCount} 人在线` : "当前没人亮灯"}</span>}
          <span className="pill w-fit">{selectedIds.length ? `${selectedIds.length} 人` : "公开池"}</span>
        </div>
      </div>

      {selectedIds.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {selectedIds.map((id) => (
            <span key={id} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
              id === leadUserId ? "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]" : "border-stone-200 bg-[#fffdf8] text-stone-600"
            }`}>
              <span className={`h-2 w-2 rounded-full ${statusDotClass(knownUserMap[id])}`} aria-hidden="true" />
              {id === leadUserId && <Star className="h-3.5 w-3.5" aria-hidden="true" />}
              {nick(id)}
              {!disabled && (
                <button className="ml-0.5 rounded-full p-0.5 hover:bg-stone-900/10" aria-label={`移除 ${nick(id)}`} onClick={() => remove(id)}>
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
              )}
            </span>
          ))}
        </div>
      )}

      {!disabled && (
        <>
          <label className="relative mt-4 block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" aria-hidden="true" />
            <input
              className="field pl-9"
              placeholder="搜索已登录用户"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          {err && <p className="mt-2 text-xs text-red-700">{err}</p>}
          <div className="mt-3 max-h-56 space-y-1 overflow-auto pr-1 scrollbar-thin-warm">
            {sortedUsers.length === 0 && <div className="rounded-lg border border-dashed border-stone-300 p-3 text-center text-xs text-stone-400">没人出现。可能大家还没来上班。</div>}
            {sortedUsers.map((u) => {
              const isLead = leadUserId === u.id;
              const isCollaborator = collaboratorUserIds.includes(u.id);
              return (
                <div key={u.id} className={`flex flex-col gap-2 rounded-lg border p-2 sm:flex-row sm:items-center sm:justify-between ${
                  u.is_online ? "border-[#c7d8be] bg-[#f8fbf4]" : "border-stone-200 bg-[#fffdf8]"
                }`}>
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-stone-800">
                      <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusDotClass(u)}`} aria-hidden="true" />
                      <UserPlus className="h-4 w-4 shrink-0 text-stone-400" aria-hidden="true" />
                      <span className="truncate">{u.nickname}</span>
                      <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${availabilityPillClass(u)}`}>
                        {availabilityLabel(u)}
                      </span>
                    </div>
                    <div className="mt-0.5 pl-8 text-[11px] leading-4 text-stone-500">{statusLabel(u)}</div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      className={`button min-h-8 px-2.5 py-1 text-xs ${isLead ? "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]" : "border-stone-300 bg-white text-stone-700 hover:border-stone-500"}`}
                      onClick={() => setLead(u)}
                    >
                      负责人
                    </button>
                    <button
                      className={`button min-h-8 px-2.5 py-1 text-xs ${isCollaborator ? "border-[#bbd6d0] bg-[#edf7f4] text-[#376b60]" : "border-stone-300 bg-white text-stone-700 hover:border-stone-500"}`}
                      disabled={isLead}
                      onClick={() => toggleCollaborator(u)}
                    >
                      协作者
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
