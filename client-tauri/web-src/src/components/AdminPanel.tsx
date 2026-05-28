import { useCallback, useEffect, useState } from "react";
import {
  Crown,
  FolderKanban,
  FolderPlus,
  RefreshCw,
  Trash2,
  ShieldOff,
  Users,
  X,
} from "lucide-react";
import { Badge, Button, Card, Input, toast } from "@yqgl/shared";
import { invoke } from "@/lib/tauri";

type Me = { id: string; nickname: string; is_admin?: boolean };
type Project = { id: string; name: string; slug: string; owner_nickname: string; archived?: boolean; deleted_at?: string | null };
type UserRow = { id: string; nickname: string; is_admin?: boolean; is_online?: boolean };

/**
 * Admin-only management surface, rendered at the bottom of Settings.
 * Returns null for non-admins, so the entire UI is invisible / cost-free
 * for everyone else.
 */
export function AdminPanel() {
  const [me, setMe] = useState<Me | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    invoke<Me>("me")
      .then((m) => { setMe(m); setChecked(true); })
      .catch(() => setChecked(true));
  }, []);

  if (!checked) return null;
  if (!me?.is_admin) return null;

  return (
    <Card variant="glass-strong" padding="lg" className="border-2 border-accent/30">
      <div className="flex items-center gap-2 mb-4">
        <div className="grid h-8 w-8 place-items-center rounded-sm bg-accent-soft text-accent">
          <Crown className="h-4 w-4" />
        </div>
        <div>
          <h2 className="text-h3 text-ink">管理员</h2>
          <p className="text-caption text-ink-muted">这些操作影响整个团队 — 谨慎</p>
        </div>
      </div>

      <div className="space-y-5">
        <ProjectsSection />
        <UsersSection meId={me.id} />
        <RequirementDeleteSection />
      </div>
    </Card>
  );
}

// ---------- Projects: list + new + delete ----------

function ProjectsSection() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [newName, setNewName] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    invoke<Project[]>("list_my_projects")
      .then(setProjects)
      .catch((e) => toast({ title: "项目列表加载失败", description: String(e), tone: "error" }));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const createOne = async () => {
    const name = newName.trim();
    const slug = newSlug.trim();
    if (!name || !slug) { toast({ title: "项目名和 slug 都要填", tone: "warn" }); return; }
    if (!/^[a-z0-9-]+$/.test(slug)) { toast({ title: "slug 只能用小写字母/数字/横线", tone: "warn" }); return; }
    setBusy(true);
    try {
      await invoke("create_project", { name, slug });
      toast({ title: `已建项目 ${name}`, tone: "success" });
      setNewName(""); setNewSlug("");
      refresh();
    } catch (e: any) {
      toast({ title: "创建失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const removeOne = async (p: Project) => {
    if (!confirm(`确定归档（软删）项目「${p.name}」吗？项目下的需求不会消失。`)) return;
    try {
      await invoke("delete_project", { projectId: p.id });
      toast({ title: "已归档", tone: "info" });
      refresh();
    } catch (e: any) {
      toast({ title: "归档失败", description: String(e), tone: "error" });
    }
  };

  return (
    <section>
      <h3 className="text-h4 text-ink mb-2 flex items-center gap-2">
        <FolderKanban className="h-4 w-4 text-ink-muted" />
        项目
      </h3>

      <div className="glass-sunken p-3 mb-3">
        <div className="text-caption text-ink-muted mb-2">新建项目</div>
        <div className="grid grid-cols-[1fr_140px_auto] gap-2">
          <Input
            placeholder="项目名（例：客户端重构）"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <Input
            placeholder="slug (例：client)"
            value={newSlug}
            onChange={(e) => setNewSlug(e.target.value.toLowerCase())}
          />
          <Button variant="accent" loading={busy} onClick={createOne} leftIcon={<FolderPlus className="h-4 w-4" />}>
            新建
          </Button>
        </div>
        <div className="text-caption text-ink-faint mt-2">
          slug 决定需求编号前缀（DEMO-001 等），定了就不要改了。
        </div>
      </div>

      <div className="flex items-center justify-between mb-2">
        <div className="text-caption text-ink-muted">
          {projects === null ? "加载中…" : `共 ${projects.length} 个项目`}
        </div>
        <Button variant="ghost" size="xs" leftIcon={<RefreshCw className="h-3 w-3" />} onClick={refresh}>
          刷新
        </Button>
      </div>

      {projects && projects.length > 0 && (
        <ul className="glass-sunken divide-y divide-line/60 rounded-md overflow-hidden">
          {projects.map((p) => (
            <li key={p.id} className="flex items-center justify-between px-3 py-2 gap-3">
              <div className="flex items-center gap-2 min-w-0">
                <FolderKanban className="h-4 w-4 text-ink-faint shrink-0" />
                <div className="min-w-0">
                  <div className="text-body-sm text-ink truncate">{p.name}</div>
                  <div className="text-caption text-ink-muted truncate">
                    {p.slug} · 创建人 {p.owner_nickname}
                    {p.archived && <span className="ml-1 text-warn">· 已归档</span>}
                    {p.deleted_at && <span className="ml-1 text-error">· 已删</span>}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => removeOne(p)}
                disabled={!!p.deleted_at}
                className="h-7 w-7 grid place-items-center rounded-sm text-ink-faint hover:bg-error-soft hover:text-error transition disabled:opacity-30"
                aria-label="归档"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------- Users: search + admin toggle ----------

function UsersSection({ meId }: { meId: string }) {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [search, setSearch] = useState("");
  const [updating, setUpdating] = useState<string | null>(null);

  const refresh = useCallback((q = search) => {
    invoke<UserRow[]>("list_users", { search: q })
      .then(setUsers)
      .catch((e) => toast({ title: "用户列表失败", description: String(e), tone: "error" }));
  }, [search]);

  useEffect(() => {
    const t = setTimeout(() => refresh(search), 200);
    return () => clearTimeout(t);
  }, [search, refresh]);

  const toggle = async (u: UserRow) => {
    const next = !u.is_admin;
    if (!next && u.id === meId) {
      if (!confirm("你正在取消自己的管理员权限。继续？")) return;
    }
    setUpdating(u.id);
    try {
      await invoke("set_user_admin", { userId: u.id, isAdmin: next });
      toast({ title: next ? `${u.nickname} 已设为管理员` : `${u.nickname} 已撤销管理员`, tone: "info" });
      refresh();
    } catch (e: any) {
      toast({ title: "更新失败", description: String(e), tone: "error" });
    } finally { setUpdating(null); }
  };

  return (
    <section>
      <h3 className="text-h4 text-ink mb-2 flex items-center gap-2">
        <Users className="h-4 w-4 text-ink-muted" />
        管理员
      </h3>

      <Input
        placeholder="搜索用户"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        containerClassName="mb-2"
      />

      <ul className="glass-sunken divide-y divide-line/60 rounded-md overflow-hidden max-h-64 overflow-y-auto">
        {users === null && (
          <li className="px-3 py-2 text-caption text-ink-faint">加载中…</li>
        )}
        {users && users.length === 0 && (
          <li className="px-3 py-2 text-caption text-ink-faint">没人匹配。</li>
        )}
        {users && users.map((u) => (
          <li key={u.id} className="flex items-center justify-between px-3 py-2 gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <span className={`h-2 w-2 shrink-0 rounded-pill ${u.is_online ? "bg-success" : "bg-ink-faint"}`} />
              <span className="text-body-sm text-ink truncate">{u.nickname}</span>
              {u.is_admin && <Badge tone="accent" size="xs"><Crown className="h-2.5 w-2.5" />管理员</Badge>}
              {u.id === meId && <Badge tone="neutral" size="xs">你</Badge>}
            </div>
            <Button
              size="xs"
              variant={u.is_admin ? "ghost" : "secondary"}
              loading={updating === u.id}
              leftIcon={u.is_admin ? <ShieldOff className="h-3 w-3" /> : <Crown className="h-3 w-3" />}
              onClick={() => toggle(u)}
            >
              {u.is_admin ? "撤销" : "设为管理员"}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------- Requirement delete by code ----------

function RequirementDeleteSection() {
  const [reqInput, setReqInput] = useState("");
  const [busy, setBusy] = useState(false);

  const removeOne = async () => {
    const id = reqInput.trim();
    if (!id) return;
    if (!confirm(`确定彻底删除需求「${id}」吗？此操作不可撤销。`)) return;
    setBusy(true);
    try {
      // Accept either raw id (uuid hex) or a code; the backend command takes id
      // only. For code-based deletes, look it up first.
      let realId = id;
      if (!/^[a-f0-9]{20,}$/i.test(id)) {
        // looks like a code, e.g. DEMO-001 — resolve via list_my
        const all = await invoke<any[]>("list_my", { mine: true, assignedToMe: true });
        const match = all.find((r) => r.code === id);
        if (!match) { toast({ title: `找不到 code 为 ${id} 的需求`, tone: "error" }); setBusy(false); return; }
        realId = match.id;
      }
      await invoke("delete_requirement", { reqId: realId });
      toast({ title: "已删除", tone: "success" });
      setReqInput("");
    } catch (e: any) {
      toast({ title: "删除失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  return (
    <section>
      <h3 className="text-h4 text-ink mb-2 flex items-center gap-2">
        <X className="h-4 w-4 text-ink-muted" />
        删除需求
      </h3>
      <div className="glass-sunken p-3">
        <div className="text-caption text-ink-muted mb-2">
          输入需求 code（例 DEMO-001）或完整 ID。已派出的需求只有管理员能删。
        </div>
        <div className="flex gap-2">
          <Input
            placeholder="DEMO-001 或 9e65895c703b4da1..."
            value={reqInput}
            onChange={(e) => setReqInput(e.target.value)}
            containerClassName="flex-1"
          />
          <Button variant="danger" loading={busy} onClick={removeOne} leftIcon={<Trash2 className="h-4 w-4" />}>
            删除
          </Button>
        </div>
      </div>
    </section>
  );
}
