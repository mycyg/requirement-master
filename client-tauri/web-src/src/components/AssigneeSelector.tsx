import { useEffect, useMemo, useState } from "react";
import { Crown, Search, UserCheck, UserPlus, Users, X } from "lucide-react";
import { Badge, Input } from "@yqgl/shared";
import { invoke } from "@/lib/tauri";

type UserOption = {
  id: string;
  nickname: string;
  is_online?: boolean;
  availability_status?: "free" | "busy" | "custom";
  availability_text?: string | null;
  last_seen_at?: string | null;
};

type Props = {
  leadUserId: string | null;
  collaboratorUserIds: string[];
  onChange: (next: { leadUserId: string | null; collaboratorUserIds: string[] }) => void;
};

function uniq(xs: string[]): string[] {
  return [...new Set(xs.filter(Boolean))];
}

function availabilityTone(u: UserOption): "success" | "warn" | "info" | "neutral" {
  if (!u.is_online) return "neutral";
  if (u.availability_status === "busy") return "warn";
  if (u.availability_status === "custom") return "info";
  return "success";
}

function availabilityLabel(u: UserOption): string {
  if (!u.is_online) return "未上线";
  if (u.availability_status === "busy") return u.availability_text || "忙碌";
  if (u.availability_status === "custom") return u.availability_text || "自定义";
  return "空闲";
}

export function AssigneeSelector({ leadUserId, collaboratorUserIds, onChange }: Props) {
  const [search, setSearch] = useState("");
  const [users, setUsers] = useState<UserOption[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // Debounce input — searches the backend on each keystroke after 200ms idle.
    const t = setTimeout(() => {
      invoke<UserOption[]>("list_users", { search })
        .then((rows) => { if (alive) { setUsers(rows); setErr(null); } })
        .catch((e) => { if (alive) setErr(String(e)); });
    }, 200);
    return () => { alive = false; clearTimeout(t); };
  }, [search]);

  const knownMap = useMemo(() => {
    const m: Record<string, UserOption> = {};
    users.forEach((u) => { m[u.id] = u; });
    return m;
  }, [users]);

  const selectedIds = useMemo(
    () => uniq([leadUserId || "", ...collaboratorUserIds]),
    [leadUserId, collaboratorUserIds],
  );

  const onlineCount = users.filter((u) => u.is_online).length;

  const sorted = useMemo(() => {
    const rank = (u: UserOption) => {
      if (!u.is_online) return 10;
      if ((u.availability_status || "free") === "free") return 0;
      if (u.availability_status === "custom") return 1;
      return 2;
    };
    return [...users].sort(
      (a, b) => rank(a) - rank(b) || a.nickname.localeCompare(b.nickname, "zh-Hans-CN"),
    );
  }, [users]);

  const setLead = (u: UserOption) => {
    onChange({
      leadUserId: u.id,
      collaboratorUserIds: collaboratorUserIds.filter((id) => id !== u.id),
    });
  };

  const toggleCollab = (u: UserOption) => {
    if (!leadUserId) {
      onChange({ leadUserId: u.id, collaboratorUserIds: [] });
      return;
    }
    if (leadUserId === u.id) return;
    const has = collaboratorUserIds.includes(u.id);
    onChange({
      leadUserId,
      collaboratorUserIds: has
        ? collaboratorUserIds.filter((id) => id !== u.id)
        : uniq([...collaboratorUserIds, u.id]),
    });
  };

  const remove = (id: string) => {
    if (leadUserId === id) {
      const [nextLead, ...rest] = collaboratorUserIds;
      onChange({ leadUserId: nextLead || null, collaboratorUserIds: rest });
    } else {
      onChange({ leadUserId, collaboratorUserIds: collaboratorUserIds.filter((x) => x !== id) });
    }
  };

  return (
    <div className="glass-sunken p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 text-body-sm text-ink">
          <Users className="h-4 w-4 text-ink-muted" />
          <span className="font-medium">接单人</span>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="neutral" size="xs">{onlineCount ? `${onlineCount} 人在线` : "无人在线"}</Badge>
          <Badge tone={selectedIds.length ? "accent" : "neutral"} size="xs">
            {selectedIds.length ? `已选 ${selectedIds.length} 人` : "公开池"}
          </Badge>
        </div>
      </div>

      {selectedIds.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedIds.map((id) => {
            const u = knownMap[id];
            const isLead = leadUserId === id;
            return (
              <span
                key={id}
                className={`inline-flex items-center gap-1.5 h-7 pl-2 pr-1 rounded-pill text-caption ${
                  isLead
                    ? "bg-accent-soft text-accent border border-accent/20"
                    : "glass-quiet text-ink-soft"
                }`}
              >
                {isLead && <Crown className="h-3 w-3" />}
                <span>{u?.nickname || id.slice(0, 6)}</span>
                <button
                  type="button"
                  onClick={() => remove(id)}
                  className="h-5 w-5 grid place-items-center rounded-pill hover:bg-error-soft hover:text-error"
                  aria-label={`移除 ${u?.nickname || id}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            );
          })}
        </div>
      )}

      <Input
        prefixSlot={<Search className="h-4 w-4 text-ink-faint" />}
        placeholder="搜索用户"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {err && <div className="text-caption text-error">{err}</div>}

      <div className="max-h-60 overflow-auto space-y-1 pr-1">
        {sorted.length === 0 ? (
          <div className="text-caption text-ink-faint text-center py-4">
            暂时没人。也可以留空给所有人。
          </div>
        ) : (
          sorted.map((u) => {
            const isLead = leadUserId === u.id;
            const isCollab = collaboratorUserIds.includes(u.id);
            return (
              <div
                key={u.id}
                className="flex items-center justify-between gap-2 px-2 py-1.5 rounded-sm hover:bg-accent-soft/60 transition"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={`h-2 w-2 shrink-0 rounded-pill ${
                      !u.is_online ? "bg-ink-faint" :
                      u.availability_status === "busy" ? "bg-warn" :
                      u.availability_status === "custom" ? "bg-info" : "bg-success"
                    }`}
                  />
                  <span className="text-body-sm text-ink truncate">{u.nickname}</span>
                  <Badge tone={availabilityTone(u) as any} size="xs">{availabilityLabel(u)}</Badge>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={() => setLead(u)}
                    className={`h-7 px-2 rounded-sm text-caption transition flex items-center gap-1 ${
                      isLead ? "bg-accent text-white" : "glass-quiet text-ink-soft hover:text-ink"
                    }`}
                  >
                    <Crown className="h-3 w-3" /> 负责
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleCollab(u)}
                    disabled={isLead}
                    className={`h-7 px-2 rounded-sm text-caption transition flex items-center gap-1 disabled:opacity-40 ${
                      isCollab ? "bg-accent-soft text-accent border border-accent/20" : "glass-quiet text-ink-soft hover:text-ink"
                    }`}
                  >
                    {isCollab ? <UserCheck className="h-3 w-3" /> : <UserPlus className="h-3 w-3" />}
                    协作
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
