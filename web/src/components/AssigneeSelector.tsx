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
        <span className="pill w-fit">{selectedIds.length ? `${selectedIds.length} 人` : "公开池"}</span>
      </div>

      {selectedIds.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {selectedIds.map((id) => (
            <span key={id} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
              id === leadUserId ? "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]" : "border-stone-200 bg-[#fffdf8] text-stone-600"
            }`}>
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
            {users.length === 0 && <div className="rounded-lg border border-dashed border-stone-300 p-3 text-center text-xs text-stone-400">没人出现。可能大家还没来上班。</div>}
            {users.map((u) => {
              const isLead = leadUserId === u.id;
              const isCollaborator = collaboratorUserIds.includes(u.id);
              return (
                <div key={u.id} className="flex flex-col gap-2 rounded-lg border border-stone-200 bg-[#fffdf8] p-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 text-sm font-medium text-stone-800">
                    <UserPlus className="mr-1.5 inline h-4 w-4 text-stone-400" aria-hidden="true" />
                    {u.nickname}
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
