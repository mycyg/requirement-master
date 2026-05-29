import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  CloudUpload,
  Download,
  File as FileIcon,
  FolderKanban,
  Folder as FolderIcon,
  Loader2,
  Mic2,
  PackageCheck,
  Plus,
  RefreshCw,
} from "lucide-react";
import { Button, Card, EmptyState, Progress, Skeleton, StatusBadge, toast } from "@yqgl/shared";
import { invoke, listen, clientJson } from "@/lib/tauri";

type Project = { id: string; name: string; slug: string };

type DriveItem = {
  id: string;
  name: string;
  kind: "folder" | "file";
  size_bytes?: number | null;
  mime?: string | null;
  updated_at?: string | null;
};

type DriveList = {
  items: DriveItem[];
  current?: { id: string | null; name: string } | null;
};

type UploadProgress = {
  req_id: string;
  phase: string;
  sent: number;
  total: number;
};

type ProjectDelivery = {
  delivery_id: string;
  requirement_id: string;
  requirement_code: string;
  requirement_title: string | null;
  requirement_status: string;
  round: number;
  package_size: number;
  file_count: number;
  submitted_by_nickname: string;
  created_at: string;
};

/**
 * 派活 Space 的「项目网盘」路由。两种入口形态：
 *  - /p              → 项目列表，点一个进入它的网盘
 *  - /p/:projectId   → 该项目的根目录列表 + 上传按钮
 *
 * 这是最小可用版本 —— 只展示根目录、只支持上传到根、不做层级浏览。
 * Web 端有完整的网盘交互；这里主要是为了让客户端用户也能丢规格文档。
 */
export function ProjectDrive() {
  const nav = useNavigate();
  const { projectId } = useParams<{ projectId?: string }>();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [items, setItems] = useState<DriveItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [deliveries, setDeliveries] = useState<ProjectDelivery[] | null>(null);
  const [dlBusy, setDlBusy] = useState<string | null>(null);

  useEffect(() => {
    invoke<Project[]>("list_my_projects")
      .then(setProjects)
      .catch((e) => setErr(`项目列表加载失败：${e}`));
  }, []);

  useEffect(() => {
    if (!projectId) { setItems(null); return; }
    setErr(null);
    // Guard against fast project-switch races — if the user clicks A then
    // immediately B, the slower A response would overwrite B's items.
    let alive = true;
    invoke<DriveList>("list_drive_root", { projectId })
      .then((d) => { if (alive) setItems(d.items ?? []); })
      .catch((e) => { if (alive) { setErr(String(e)); setItems([]); } });
    return () => { alive = false; };
  }, [projectId]);

  // Read-only deliverables for this project (latest delivery per requirement).
  useEffect(() => {
    if (!projectId) { setDeliveries(null); return; }
    let alive = true;
    clientJson<ProjectDelivery[]>(`/api/projects/${projectId}/deliveries`)
      .then((d) => { if (alive) setDeliveries(d); })
      .catch(() => { if (alive) setDeliveries([]); });
    return () => { alive = false; };
  }, [projectId]);

  const downloadDelivery = async (d: ProjectDelivery) => {
    setDlBusy(d.delivery_id);
    try {
      const res = await invoke<{ saved_path?: string }>("download_delivery", { reqId: d.requirement_id });
      toast({ title: "已下载到本地", description: res?.saved_path || "", tone: "success" });
    } catch (e: any) {
      toast({ title: "下载失败", description: String(e), tone: "error" });
    } finally { setDlBusy(null); }
  };

  // upload progress
  useEffect(() => {
    // `alive` guards against fast unmount: in React StrictMode dev mode (and
    // genuine fast navigation), this effect's cleanup can run BEFORE listen()
    // resolves, leaving `off` undefined. The async resolve then registers a
    // listener with no one to clean it up. Mirror FileAttachRail's pattern.
    let alive = true;
    let off: (() => void) | undefined;
    listen<UploadProgress>("drive-upload-progress", (p) => {
      if (!alive) return;
      setProgress(p);
      if (p.phase === "done") setTimeout(() => { if (alive) setProgress(null); }, 600);
    }).then((d) => {
      if (!alive) { d(); return; }
      off = d;
    });
    return () => { alive = false; if (off) off(); };
  }, []);

  const currentProject = projects?.find((p) => p.id === projectId) || null;

  const pickAndUpload = async () => {
    if (!projectId) return;
    setErr(null);
    setBusy(true);
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const picked = await open({ multiple: true, directory: false });
      const paths = Array.isArray(picked) ? picked : picked ? [picked] : [];
      if (paths.length === 0) { setBusy(false); return; }
      for (const p of paths) {
        await invoke("upload_drive_item", { projectId, filePath: p });
      }
      toast({ title: `已上传 ${paths.length} 个文件`, tone: "success" });
      const fresh = await invoke<DriveList>("list_drive_root", { projectId });
      setItems(fresh.items ?? []);
    } catch (e: any) {
      setErr(String(e));
      toast({ title: "上传失败", description: String(e), tone: "error" });
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  // No projectId — show project picker
  if (!projectId) {
    return (
      <div className="flex-1 overflow-auto p-6">
        <header className="mb-5">
          <h1 className="text-h2 text-ink">项目网盘</h1>
          <p className="text-body-sm text-ink-muted mt-1">
            选一个项目，进入它的共享文件区。
          </p>
        </header>

        {err && <div className="glass p-4 text-error mb-4">{err}</div>}

        {projects === null ? (
          <div className="space-y-2">
            <Skeleton height="h-16" rounded="md" />
            <Skeleton height="h-16" rounded="md" />
          </div>
        ) : projects.length === 0 ? (
          <EmptyState title="你还没加入任何项目" description="可以让管理员把你加进项目。" />
        ) : (
          <div className="grid sm:grid-cols-2 gap-3">
            {projects.map((p) => (
              <Card
                key={p.id}
                interactive
                onClick={() => nav(`/p/${p.id}`)}
                className="flex items-center gap-3"
              >
                <div className="grid h-10 w-10 place-items-center rounded-md bg-accent-soft text-accent">
                  <FolderKanban className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <div className="text-body text-ink truncate">{p.name}</div>
                  <div className="text-caption text-ink-muted truncate">{p.slug}</div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Project drive root list
  return (
    <div className="flex-1 overflow-auto p-6">
      <button
        onClick={() => nav("/p")}
        className="inline-flex items-center gap-1.5 text-body-sm text-ink-muted hover:text-ink mb-4"
      >
        <ArrowLeft className="h-4 w-4" /> 返回项目列表
      </button>

      <header className="flex items-end justify-between mb-5 gap-4">
        <div>
          <h1 className="text-h2 text-ink">
            {currentProject?.name ?? "项目网盘"}
          </h1>
          <p className="text-body-sm text-ink-muted mt-1">
            团队共享文件，所有成员可见。
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<Mic2 className="h-3.5 w-3.5" />}
            onClick={() => nav(`/p/${projectId}/meetings`)}
          >
            会议纪要
          </Button>
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={() => {
              setErr(null);
              invoke<DriveList>("list_drive_root", { projectId })
                .then((d) => setItems(d.items ?? []))
                .catch((e) => setErr(String(e)));
            }}
          >
            刷新
          </Button>
          <Button
            variant="accent"
            size="sm"
            leftIcon={<Plus className="h-3.5 w-3.5" />}
            loading={busy}
            onClick={pickAndUpload}
          >
            上传文件
          </Button>
        </div>
      </header>

      {progress && progress.total > 0 && (
        <Card variant="glass-quiet" padding="md" className="mb-4">
          <div className="flex items-center justify-between text-caption text-ink-muted mb-1">
            <span className="flex items-center gap-1.5">
              <Loader2 className="h-3 w-3 animate-spin" />
              {progress.phase === "finalize" ? "拼装中…" : "上传中"}
            </span>
            <span>{Math.round((progress.sent / progress.total) * 100)}%</span>
          </div>
          <Progress value={(progress.sent / progress.total) * 100} size="sm" tone="accent" />
        </Card>
      )}

      {err && <div className="glass p-4 text-error mb-4">{err}</div>}

      {items === null ? (
        <div className="space-y-2">
          <Skeleton height="h-12" rounded="md" />
          <Skeleton height="h-12" rounded="md" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="网盘是空的"
          description="点右上「上传文件」上传你的第一份共享文档。"
          action={
            <Button variant="accent" size="sm" leftIcon={<CloudUpload className="h-3.5 w-3.5" />} onClick={pickAndUpload}>
              上传文件
            </Button>
          }
        />
      ) : (
        <ul className="glass-quiet divide-y divide-line/60 rounded-md overflow-hidden">
          {items.map((it) => (
            <li key={it.id} className="flex items-center justify-between px-4 py-3 gap-3">
              <div className="flex items-center gap-3 min-w-0">
                {it.kind === "folder"
                  ? <FolderIcon className="h-4 w-4 text-warn shrink-0" />
                  : <FileIcon className="h-4 w-4 text-ink-faint shrink-0" />}
                <span className="text-body-sm text-ink truncate">{it.name}</span>
              </div>
              <span className="text-caption text-ink-faint shrink-0">
                {it.size_bytes ? `${(it.size_bytes / 1024).toFixed(1)} KB` : it.kind === "folder" ? "目录" : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      {deliveries && deliveries.length > 0 && (
        <div className="mt-6">
          <div className="flex items-center gap-2 mb-3">
            <PackageCheck className="h-4 w-4 text-success" />
            <h2 className="text-h4 text-ink">交付物</h2>
            <span className="text-caption text-ink-faint">只读 · 来自需求交付</span>
          </div>
          <ul className="glass-quiet divide-y divide-line/60 rounded-md overflow-hidden">
            {deliveries.map((d) => (
              <li key={d.delivery_id} className="flex items-center justify-between px-4 py-3 gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-caption text-ink-faint">{d.requirement_code}</span>
                    <StatusBadge status={d.requirement_status} size="sm" />
                  </div>
                  <div className="text-body-sm text-ink truncate">{d.requirement_title || "(未命名)"}</div>
                  <div className="text-caption text-ink-muted">
                    第 {d.round} 轮 · {d.file_count} 个文件 · {(d.package_size / 1024).toFixed(0)} KB · {d.submitted_by_nickname}
                  </div>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  leftIcon={<Download className="h-3.5 w-3.5" />}
                  loading={dlBusy === d.delivery_id}
                  onClick={() => downloadDelivery(d)}
                >
                  下载
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
