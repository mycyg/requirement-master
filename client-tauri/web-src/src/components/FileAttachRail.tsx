import { useCallback, useEffect, useState } from "react";
import { File as FileIcon, FolderOpen, Loader2, Plus, RefreshCw, Watch } from "lucide-react";
import { Badge, Button, Progress, Switch, toast } from "@yqgl/shared";
import { invoke, useEvent } from "@/lib/tauri";
import { listen } from "@/lib/tauri";

// Status values where the submitter can still legitimately add files via
// the spec/ folder watcher. Outside this set (e.g. cancelled, accepted,
// or any worker-claimed state) we auto-stop the watcher to avoid 403/
// 400 storms when notify fires for the user's own local edits.
const WATCHABLE_STATUSES = new Set(["draft", "clarifying", "summary_ready"]);

type Attachment = {
  id: string;
  filename: string;
  size_bytes: number;
  mime: string | null;
  has_parsed_text?: boolean;
  uploaded_at?: string | null;
};

type UploadProgress = {
  req_id: string;
  phase: "init" | "chunk" | "finalize" | "done" | "error";
  sent: number;
  total: number;
};

/**
 * 提交人侧的附件面板。两种入口：
 *   1) 手动按钮 — 系统原生文件选择器 → invoke("upload_attachment", ...) → 5MB 分片
 *   2) 文件夹监听（M6） — 把 {sync_root}/{project_slug}/{code}/spec/ 当 dropbox，
 *      新增/修改的文件自动上传（只增不删）。
 */
export function FileAttachRail({ reqId, reqStatus }: { reqId: string; reqStatus?: string | null }) {
  const [items, setItems] = useState<Attachment[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [watching, setWatching] = useState(false);

  // Auto-stop the spec watcher when the requirement leaves a state in
  // which submitter attachments are accepted. Otherwise the watcher keeps
  // firing on the user's local file edits and every upload 400s with
  // "cannot add attachment in status X" — wastes network + spams logs.
  useEffect(() => {
    if (!watching) return;
    if (reqStatus && !WATCHABLE_STATUSES.has(reqStatus)) {
      invoke("stop_spec_watcher", { reqId })
        .then(() => setWatching(false))
        .catch(() => { /* best-effort */ });
    }
  }, [reqStatus, watching, reqId]);

  const refresh = useCallback(async () => {
    setErr(null);
    try {
      const list = await invoke<Attachment[]>("list_attachments", { reqId });
      setItems(list);
    } catch (e: any) {
      setErr(String(e));
      setItems([]);
    }
  }, [reqId]);

  useEffect(() => { refresh(); }, [refresh]);

  // Subscribe to chunk-upload progress events. The `alive` flag protects
  // against the case where the component unmounts BEFORE `listen` resolves —
  // without it the listener would register after cleanup ran and never be
  // disposed (subscription leak across navigations).
  useEffect(() => {
    let alive = true;
    let off: (() => void) | undefined;
    listen<UploadProgress>("upload-progress", (p) => {
      if (p.req_id !== reqId) return;
      setProgress(p);
      if (p.phase === "done") {
        setProgress(null);
        refresh();
      }
    }).then((d) => {
      if (!alive) d(); else off = d;
    });
    return () => { alive = false; if (off) off(); };
  }, [reqId, refresh]);

  const pickAndUpload = async () => {
    setErr(null);
    setBusy(true);
    try {
      // Native file picker via tauri-plugin-dialog. Multi-select OK.
      const { open } = await import("@tauri-apps/plugin-dialog");
      const picked = await open({ multiple: true, directory: false });
      const paths = Array.isArray(picked) ? picked : picked ? [picked] : [];
      if (paths.length === 0) { setBusy(false); return; }

      // Settle each upload independently — one bad file shouldn't abort
      // the whole batch (and shouldn't cause the user to retry already-
      // uploaded files as duplicates).
      const results = await Promise.allSettled(
        paths.map((p) => invoke("upload_attachment", { reqId, filePath: p })),
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const fail = paths.length - ok;
      if (fail === 0) {
        toast({ title: `已上传 ${ok} 个文件`, tone: "success" });
      } else {
        const firstErr = results.find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
        toast({
          title: `上传完成 ${ok}/${paths.length}`,
          description: `${fail} 个失败${firstErr ? `：${String(firstErr.reason).slice(0, 100)}` : ""}`,
          tone: "warn",
        });
      }
      await refresh();
    } catch (e: any) {
      setErr(String(e));
      toast({ title: "上传失败", description: String(e), tone: "error" });
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  const toggleWatcher = async (next: boolean) => {
    try {
      if (next) {
        await invoke("start_spec_watcher", { reqId });
        toast({ title: "已开启文件夹监听", description: "spec/ 文件夹里新增/修改的文件会自动上传。", tone: "info" });
      } else {
        await invoke("stop_spec_watcher", { reqId });
      }
      setWatching(next);
    } catch (e: any) {
      toast({ title: next ? "开启失败" : "关闭失败", description: String(e), tone: "error" });
    }
  };

  const openSpecFolder = async () => {
    try {
      await invoke("open_spec_folder", { reqId });
    } catch (e: any) {
      toast({ title: "打不开文件夹", description: String(e), tone: "error" });
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <Button variant="accent" size="sm" leftIcon={<Plus className="h-3.5 w-3.5" />} onClick={pickAndUpload} disabled={busy}>
          添加附件
        </Button>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={refresh} leftIcon={<RefreshCw className="h-3.5 w-3.5" />}>
            刷新
          </Button>
        </div>
      </div>

      <div className="glass-sunken p-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Watch className="h-4 w-4 text-ink-muted shrink-0" />
          <div className="min-w-0">
            <div className="text-body-sm text-ink">把 spec 文件夹当我的草稿箱</div>
            <div className="text-caption text-ink-muted truncate">
              新增 / 修改的文件自动同步过来（不删远端）。
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="ghost" size="sm" leftIcon={<FolderOpen className="h-3.5 w-3.5" />} onClick={openSpecFolder}>
            打开
          </Button>
          <Switch
            checked={watching}
            onChange={(e) => toggleWatcher(e.target.checked)}
            aria-label="文件夹监听"
          />
        </div>
      </div>

      {progress && progress.total > 0 && (
        <div className="glass-quiet p-3 space-y-2">
          <div className="flex items-center justify-between text-caption text-ink-muted">
            <span className="flex items-center gap-1.5">
              <Loader2 className="h-3 w-3 animate-spin" />
              {progress.phase === "init" ? "请求授权…" : progress.phase === "finalize" ? "拼装中…" : "上传中"}
            </span>
            <span>{Math.round((progress.sent / progress.total) * 100)}%</span>
          </div>
          <Progress value={(progress.sent / progress.total) * 100} size="sm" tone="accent" />
        </div>
      )}

      {err && <div className="text-caption text-error">{err}</div>}

      {items === null ? (
        <div className="text-caption text-ink-faint text-center py-4">加载附件列表中…</div>
      ) : items.length === 0 ? (
        <div className="text-caption text-ink-faint text-center py-4">
          还没有附件。文档、设计稿、参考截图都可以丢进来。
        </div>
      ) : (
        <ul className="glass-sunken divide-y divide-line/60 overflow-hidden rounded-md">
          {items.map((a) => (
            <li key={a.id} className="flex items-center justify-between px-3 py-2 gap-3">
              <div className="flex items-center gap-2 min-w-0">
                <FileIcon className="h-4 w-4 text-ink-faint shrink-0" />
                <span className="text-body-sm text-ink truncate">{a.filename}</span>
                <span className="text-caption text-ink-faint shrink-0">
                  {(a.size_bytes / 1024).toFixed(1)} KB
                </span>
                {a.has_parsed_text && <Badge tone="success" size="xs">已解析</Badge>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
