import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArchiveRestore, CheckSquare, ChevronRight, Clipboard, Copy, Download, Eye, File, FileCode2,
  Folder, FolderInput, Grid3X3, HardDrive, List, Loader2, MessageSquare, MoreHorizontal, Plus, RotateCcw,
  Scissors, Search, Send, Square, Trash2, UploadCloud, X, Mic2,
} from "lucide-react";
import { api } from "@/lib/api";
import type { DriveComment, DriveItem, DriveList, DrivePreview, DriveTreeNode, Project } from "@/lib/types";

const CHUNK_SIZE = 5 * 1024 * 1024;

type ViewMode = "list" | "grid" | "tree";
type ClipState = { mode: "copy" | "cut"; itemIds: string[] } | null;

function sizeLabel(bytes?: number | null): string {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function dateLabel(value: string): string {
  return new Date(value + (value.endsWith("Z") ? "" : "Z")).toLocaleString("zh-CN");
}

function fileIcon(item: DriveItem) {
  return item.kind === "folder"
    ? <Folder className="h-4 w-4 text-[#8a6d2d]" aria-hidden="true" />
    : <FileCode2 className="h-4 w-4 text-stone-500" aria-hidden="true" />;
}

function flattenTree(nodes: DriveTreeNode[], depth = 0): Array<{ node: DriveTreeNode; depth: number }> {
  return nodes.flatMap((node) => [{ node, depth }, ...flattenTree(node.children, depth + 1)]);
}

function TreeButton({
  node,
  activeId,
  onOpen,
  depth = 0,
}: {
  node: DriveTreeNode;
  activeId: string | null;
  onOpen: (id: string | null) => void;
  depth?: number;
}) {
  return (
    <div>
      <button
        className={`flex min-h-8 w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs transition hover:bg-stone-900/5 ${
          activeId === node.id ? "bg-stone-900/10 text-stone-950" : "text-stone-600"
        }`}
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => onOpen(node.id)}
      >
        <Folder className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate">{node.name}</span>
      </button>
      {node.children.map((child) => (
        <TreeButton key={child.id} node={child} activeId={activeId} onOpen={onOpen} depth={depth + 1} />
      ))}
    </div>
  );
}

export function ProjectDrive({ explicitProjectId }: { explicitProjectId?: string }) {
  const params = useParams<{ id: string }>();
  const projectId = explicitProjectId || params.id || "";
  const [project, setProject] = useState<Project | null>(null);
  const [drive, setDrive] = useState<DriveList | null>(null);
  const [tree, setTree] = useState<DriveTreeNode[]>([]);
  const [parentId, setParentId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [trash, setTrash] = useState(false);
  const [view, setView] = useState<ViewMode>("list");
  const [selected, setSelected] = useState<string[]>([]);
  const [clipboard, setClipboard] = useState<ClipState>(null);
  const [preview, setPreview] = useState<DrivePreview | null>(null);
  const [htmlRender, setHtmlRender] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [comments, setComments] = useState<DriveComment[]>([]);
  const [commentText, setCommentText] = useState("");
  const [commentBusy, setCommentBusy] = useState(false);

  const selectedItems = useMemo(
    () => drive?.items.filter((item) => selected.includes(item.id)) ?? [],
    [drive, selected],
  );
  const flatTree = useMemo(() => flattenTree(tree), [tree]);

  // Monotonic counter so a late-arriving stale `reload()` (e.g. user
  // typed in search, fired reload, then typed more before the first
  // resolved) can't overwrite a newer one's state.
  const reloadTokenRef = useRef(0);
  const reload = useCallback(async () => {
    if (!projectId) return;
    const myToken = ++reloadTokenRef.current;
    try {
      const [projects, nextDrive, nextTree] = await Promise.all([
        api.listProjects(),
        api.listDrive(projectId, { parent_id: parentId, search, trash }),
        api.driveTree(projectId),
      ]);
      if (myToken !== reloadTokenRef.current) return;  // superseded
      setProject(projects.find((p) => p.id === projectId) ?? null);
      setDrive(nextDrive);
      setTree(nextTree);
      setSelected([]);
      const nextComments = await api.listDriveComments(projectId, trash ? null : parentId);
      if (myToken !== reloadTokenRef.current) return;
      setComments(nextComments);
    } catch (e: any) {
      if (myToken === reloadTokenRef.current) setErr(String(e));
    }
  }, [projectId, parentId, search, trash]);

  const submitComment = async () => {
    if (!projectId || !commentText.trim() || trash) return;
    setCommentBusy(true);
    setErr(null);
    try {
      const comment = await api.addDriveComment(projectId, parentId, commentText.trim());
      setComments((xs) => [comment, ...xs]);
      setCommentText("");
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setCommentBusy(false);
    }
  };

  useEffect(() => {
    reload().catch((e) => setErr(String(e)));
  }, [reload]);

  const openFolder = (id: string | null) => {
    setTrash(false);
    setParentId(id);
  };

  const toggleSelected = (id: string) => {
    setSelected((xs) => xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]);
  };

  const createFolder = async () => {
    const name = window.prompt("新文件夹叫什么？", "新文件夹");
    if (!name?.trim() || !projectId) return;
    setBusy("新建文件夹");
    try {
      await api.createDriveFolder(projectId, { name: name.trim(), parent_id: parentId });
      await reload();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const uploadFiles = async (files: FileList | File[]) => {
    if (!projectId || trash) return;
    setErr(null);
    for (const file of Array.from(files)) {
      if (file.size <= 0) {
        setErr(`空文件先放过它：${file.name}`);
        continue;
      }
      setBusy(`上传 ${file.name}`);
      try {
        let conflict: "cancel" | "replace" | "rename" = "cancel";
        let existingId: string | null = null;
        let init = await api.initDriveUpload(projectId, {
          filename: file.name,
          total_size: file.size,
          total_chunks: Math.max(1, Math.ceil(file.size / CHUNK_SIZE)),
          mime: file.type || null,
          parent_id: parentId,
          conflict,
        });
        if (init.conflict === "name_exists") {
          const choice = window.prompt(
            `同名文件已经在这里蹲着了：${file.name}\n输入 r 替换，n 存为新名称，c 取消。`,
            "n",
          );
          if (!choice || choice.toLowerCase().startsWith("c")) continue;
          conflict = choice.toLowerCase().startsWith("r") ? "replace" : "rename";
          existingId = init.existing_item?.id ?? null;
          init = await api.initDriveUpload(projectId, {
            filename: file.name,
            total_size: file.size,
            total_chunks: Math.max(1, Math.ceil(file.size / CHUNK_SIZE)),
            mime: file.type || null,
            parent_id: parentId,
            conflict,
            existing_item_id: existingId,
          });
        }
        if (!init.upload_id) continue;
        for (let idx = 0; idx < Math.max(1, Math.ceil(file.size / init.chunk_size)); idx += 1) {
          await api.uploadDriveChunk(projectId, init.upload_id, idx, file.slice(idx * init.chunk_size, Math.min(file.size, (idx + 1) * init.chunk_size)));
        }
        await api.finalizeDriveUpload(projectId, init.upload_id);
      } catch (e: any) {
        setErr(String(e));
        break;
      } finally {
        setBusy(null);
      }
    }
    await reload();
  };

  const previewItem = async (item: DriveItem) => {
    if (item.kind === "folder") {
      openFolder(item.id);
      return;
    }
    setBusy("读取预览");
    setHtmlRender(false);
    try {
      setPreview(await api.previewDriveItem(item.id));
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const downloadSelected = async () => {
    if (selectedItems.length === 1 && selectedItems[0].kind === "file") {
      window.open(api.driveDownloadUrl(selectedItems[0].id), "_blank");
      return;
    }
    if (!selectedItems.length) return;
    setBusy("打包下载");
    try {
      const blob = await api.bulkDownloadDrive(selected);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "project-drive.zip";
      // Firefox requires the anchor to be in the DOM for click() to
      // trigger a download. Chrome works either way; previous code
      // skipped the appendChild and silently no-op'd on Firefox.
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const deleteSelected = async () => {
    if (!selected.length) return;
    setBusy("丢进回收站");
    try {
      await api.bulkDeleteDriveItems(selected);
      await reload();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const restoreSelected = async () => {
    setBusy("恢复文件");
    try {
      for (const id of selected) await api.restoreDriveItem(id);
      await reload();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const paste = async () => {
    if (!clipboard || !projectId || trash) return;
    setBusy(clipboard.mode === "copy" ? "复制中" : "移动中");
    try {
      await api.pasteDriveItems(projectId, {
        item_ids: clipboard.itemIds,
        target_parent_id: parentId,
        mode: clipboard.mode,
      });
      if (clipboard.mode === "cut") setClipboard(null);
      await reload();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const undo = async () => {
    if (!projectId) return;
    setBusy("撤回");
    try {
      await api.undoDrive(projectId);
      await reload();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const commitRename = async () => {
    if (!renaming) return;
    const target = drive?.items.find((item) => item.id === renaming.id);
    if (!target || target.name === renaming.name.trim()) {
      setRenaming(null);
      return;
    }
    setBusy("重命名");
    try {
      await api.patchDriveItem(renaming.id, { name: renaming.name.trim() });
      setRenaming(null);
      await reload();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el?.tagName === "INPUT" || el?.tagName === "TEXTAREA" || el?.isContentEditable) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c" && selected.length) {
        e.preventDefault(); setClipboard({ mode: "copy", itemIds: selected });
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "x" && selected.length) {
        e.preventDefault(); setClipboard({ mode: "cut", itemIds: selected });
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") {
        e.preventDefault(); paste();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault(); undo();
      } else if (e.key === "Delete") {
        e.preventDefault();
        if (trash) {
          restoreSelected();
        } else if (selected.length === 0) {
          // nothing to delete
        } else {
          // Confirm before destructive action — `Delete` is too easy to
          // hit by accident, and although files go to Trash first,
          // hitting it on a folder full of files is jarring.
          const ok = window.confirm(`确定把选中的 ${selected.length} 项放到回收站？`);
          if (ok) deleteSelected();
        }
      } else if (e.key === "F2" && selected.length === 1) {
        e.preventDefault();
        const item = drive?.items.find((x) => x.id === selected[0]);
        if (item) setRenaming({ id: item.id, name: item.name });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, clipboard, parentId, projectId, trash, drive]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!projectId) return <main className="narrow-container text-stone-500">先选个项目，网盘才知道该在哪儿安家。</main>;

  return (
    <main
      className="app-container"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
      }}
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">项目网盘</p>
          <h1 className="mt-2 flex items-center gap-2 text-3xl font-semibold tracking-tight text-stone-950">
            <HardDrive className="h-7 w-7" aria-hidden="true" />
            {project?.name || "项目网盘"}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-stone-500">
            {(drive?.breadcrumbs ?? [{ id: null, name: "项目网盘" }]).map((crumb, idx, arr) => (
              <button key={`${crumb.id || "root"}-${idx}`} className="link-subtle text-xs" onClick={() => openFolder(crumb.id)}>
                {crumb.name}
                {idx < arr.length - 1 && <ChevronRight className="h-3 w-3" aria-hidden="true" />}
              </button>
            ))}
            {trash && <span className="pill border-red-200 bg-red-50 text-red-700">回收站</span>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" onClick={() => setTrash((v) => !v)}>
            {trash ? <Folder className="h-4 w-4" /> : <Trash2 className="h-4 w-4" />}
            {trash ? "返回网盘" : "回收站"}
          </button>
          <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" onClick={undo}>
            <RotateCcw className="h-4 w-4" />
            撤回
          </button>
        </div>
      </div>
      {project && (
        <div className="mt-6 flex gap-2 border-b border-stone-200">
          <Link to={`/p/${project.id}`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
            <File className="h-4 w-4" aria-hidden="true" />
            需求
          </Link>
          <Link to={`/p/${project.id}/drive`} className="tab-button border-stone-950 text-stone-950">
            <HardDrive className="h-4 w-4" aria-hidden="true" />
            网盘
          </Link>
          <Link to={`/p/${project.id}/meetings`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
            <Mic2 className="h-4 w-4" aria-hidden="true" />
            会议
          </Link>
        </div>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="paper-surface max-h-[calc(100vh-190px)] overflow-auto p-3 scrollbar-thin-warm">
          <button
            className={`flex min-h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm font-medium ${!parentId && !trash ? "bg-stone-900/10" : "hover:bg-stone-900/5"}`}
            onClick={() => openFolder(null)}
          >
            <HardDrive className="h-4 w-4" />
            项目网盘
          </button>
          <div className="mt-2">
            {tree.length === 0 && <div className="rounded-md border border-dashed border-stone-300 p-3 text-xs text-stone-400">还没有文件夹</div>}
            {tree.map((node) => <TreeButton key={node.id} node={node} activeId={parentId} onOpen={openFolder} />)}
          </div>
        </aside>

        <section className="min-w-0">
          <div className="paper-surface overflow-hidden">
            <div className="flex flex-col gap-3 border-b border-stone-200/80 p-3 lg:flex-row lg:items-center lg:justify-between">
              <label className="relative block min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
                <input className="field min-h-9 pl-9" placeholder="搜索这个项目的文件" value={search} onChange={(e) => setSearch(e.target.value)} />
              </label>
              <div className="flex flex-wrap gap-2">
                {!trash && (
                  <>
                    <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" onClick={createFolder}>
                      <Plus className="h-4 w-4" />
                      新建文件夹
                    </button>
                    <label className="button-primary min-h-9 cursor-pointer px-3 py-1.5 text-xs">
                      <UploadCloud className="h-4 w-4" />
                      上传
                      <input className="hidden" type="file" multiple onChange={(e) => e.target.files && uploadFiles(e.target.files)} />
                    </label>
                  </>
                )}
                <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" disabled={!selected.length} onClick={() => setClipboard({ mode: "copy", itemIds: selected })}>
                  <Copy className="h-4 w-4" />
                  复制
                </button>
                <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" disabled={!selected.length || trash} onClick={() => setClipboard({ mode: "cut", itemIds: selected })}>
                  <Scissors className="h-4 w-4" />
                  剪切
                </button>
                <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" disabled={!clipboard || trash} onClick={paste}>
                  <Clipboard className="h-4 w-4" />
                  粘贴
                </button>
                <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" disabled={!selected.length} onClick={downloadSelected}>
                  <Download className="h-4 w-4" />
                  下载
                </button>
                {trash ? (
                  <button className="button-secondary min-h-9 px-3 py-1.5 text-xs" disabled={!selected.length} onClick={restoreSelected}>
                    <ArchiveRestore className="h-4 w-4" />
                    恢复
                  </button>
                ) : (
                  <button className="button-danger min-h-9 px-3 py-1.5 text-xs" disabled={!selected.length} onClick={deleteSelected}>
                    <Trash2 className="h-4 w-4" />
                    删除
                  </button>
                )}
                <div className="flex overflow-hidden rounded-lg border border-stone-300 bg-[#fffdf8]">
                  {[
                    ["list", List],
                    ["grid", Grid3X3],
                    ["tree", MoreHorizontal],
                  ].map(([mode, Icon]) => (
                    <button
                      key={mode as string}
                      className={`grid h-9 w-9 place-items-center ${view === mode ? "bg-stone-900 text-[#fffdf8]" : "text-stone-600 hover:bg-stone-900/5"}`}
                      title={mode === "list" ? "列表" : mode === "grid" ? "平铺" : "树"}
                      onClick={() => setView(mode as ViewMode)}
                    >
                      <Icon className="h-4 w-4" />
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {(busy || err || clipboard) && (
              <div className="flex flex-wrap items-center gap-2 border-b border-stone-200/80 px-4 py-2 text-xs">
                {busy && <span className="pill"><Loader2 className="h-3.5 w-3.5 animate-spin" />{busy}</span>}
                {clipboard && <span className="pill">{clipboard.mode === "copy" ? "复制" : "剪切"}了 {clipboard.itemIds.length} 项</span>}
                {err && <span className="pill border-red-200 bg-red-50 text-red-700">{err}<button onClick={() => setErr(null)}><X className="h-3 w-3" /></button></span>}
              </div>
            )}

            <div className="min-h-[460px] p-3">
              {drive?.items.length === 0 && (
                <div className="empty-state">这里还没有文件。拖文件进来，或新建一个文件夹。</div>
              )}

              {view === "grid" && (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-6">
                  {drive?.items.map((item) => (
                    <button
                      key={item.id}
                      className={`min-h-32 rounded-lg border p-3 text-left transition hover:-translate-y-0.5 hover:bg-white ${
                        selected.includes(item.id) ? "border-stone-950 bg-white" : "border-stone-200 bg-[#fffdf8]"
                      }`}
                      onClick={(e) => e.detail === 2 ? previewItem(item) : toggleSelected(item.id)}
                    >
                      <div className="flex items-center justify-between">
                        {fileIcon(item)}
                        {selected.includes(item.id) ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4 text-stone-300" />}
                      </div>
                      <div className="mt-4 truncate text-sm font-semibold text-stone-900">{item.name}</div>
                      <div className="mt-1 text-xs text-stone-500">{item.kind === "folder" ? "文件夹" : sizeLabel(item.size_bytes)}</div>
                    </button>
                  ))}
                </div>
              )}

              {view === "tree" && (
                <div className="space-y-1">
                  {flatTree.map(({ node, depth }) => (
                    <button key={node.id} className="flex min-h-9 w-full items-center gap-2 rounded-md px-3 text-left text-sm hover:bg-stone-900/5" style={{ paddingLeft: 12 + depth * 22 }} onClick={() => openFolder(node.id)}>
                      <FolderInput className="h-4 w-4 text-[#8a6d2d]" />
                      {node.name}
                    </button>
                  ))}
                  {flatTree.length === 0 && <div className="empty-state">树也空了，像一份还没开会的规划。</div>}
                </div>
              )}

              {view === "list" && (
                <div className="overflow-auto scrollbar-thin-warm">
                  <table className="w-full min-w-[760px] text-left text-sm">
                    <thead className="text-xs uppercase text-stone-400">
                      <tr>
                        <th className="w-10 px-2 py-2">
                          <button onClick={() => setSelected(selected.length === drive?.items.length ? [] : (drive?.items.map((i) => i.id) ?? []))}>
                            {selected.length && selected.length === drive?.items.length ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                          </button>
                        </th>
                        <th className="px-2 py-2">名称</th>
                        <th className="px-2 py-2">大小</th>
                        <th className="px-2 py-2">版本</th>
                        <th className="px-2 py-2">更新</th>
                        <th className="px-2 py-2">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-stone-200/80">
                      {drive?.items.map((item) => (
                        <tr key={item.id} className={`group ${selected.includes(item.id) ? "bg-white" : "hover:bg-white/70"}`}>
                          <td className="px-2 py-2">
                            <button onClick={() => toggleSelected(item.id)}>{selected.includes(item.id) ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4 text-stone-300" />}</button>
                          </td>
                          <td className="max-w-[360px] px-2 py-2">
                            <div className="flex min-w-0 items-center gap-2">
                              {fileIcon(item)}
                              {renaming?.id === item.id ? (
                                <input
                                  className="field min-h-8 py-1"
                                  value={renaming.name}
                                  autoFocus
                                  onChange={(e) => setRenaming({ id: item.id, name: e.target.value })}
                                  onBlur={commitRename}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") commitRename();
                                    if (e.key === "Escape") setRenaming(null);
                                  }}
                                />
                              ) : (
                                <button className="truncate font-medium hover:underline" onDoubleClick={() => previewItem(item)} onClick={() => item.kind === "folder" ? openFolder(item.id) : previewItem(item)}>
                                  {item.name}
                                </button>
                              )}
                            </div>
                          </td>
                          <td className="px-2 py-2 text-stone-500">{item.kind === "folder" ? "-" : sizeLabel(item.size_bytes)}</td>
                          <td className="px-2 py-2 text-stone-500">{item.version_no ? `v${item.version_no}` : "-"}</td>
                          <td className="px-2 py-2 text-stone-500">{dateLabel(item.updated_at)}</td>
                          <td className="px-2 py-2">
                            <div className="flex gap-1">
                              {item.kind === "file" && <button className="button-ghost min-h-8 w-8 px-0" title="预览" onClick={() => previewItem(item)}><Eye className="h-4 w-4" /></button>}
                              {item.kind === "file" && <a className="button-ghost min-h-8 w-8 px-0" title="下载" href={api.driveDownloadUrl(item.id)}><Download className="h-4 w-4" /></a>}
                              <button className="button-ghost min-h-8 w-8 px-0" title="重命名" onClick={() => setRenaming({ id: item.id, name: item.name })}><File className="h-4 w-4" /></button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      {!trash && (
        <section className="paper-surface mt-4 p-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-900">
                <MessageSquare className="h-4 w-4 text-stone-500" aria-hidden="true" />
                文件夹留言板
              </h2>
              <p className="mt-1 text-xs text-stone-500">留言会先过一遍 LLM；像需求变动的，会自动生成需求草稿。</p>
            </div>
            <span className="pill">同步：客户端本地开关控制</span>
          </div>
          <div className="mt-3 flex flex-col gap-2 md:flex-row">
            <textarea
              className="textarea-field min-h-20 flex-1"
              placeholder="在这个文件夹留句话。普通吐槽进留言板，像需求的会被拎去走澄清流程。"
              value={commentText}
              onChange={(e) => setCommentText(e.target.value)}
            />
            <button className="button-primary md:self-start" disabled={commentBusy || !commentText.trim()} onClick={submitComment}>
              {commentBusy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
              {commentBusy ? "审核中..." : "留言"}
            </button>
          </div>
          <div className="mt-4 space-y-2">
            {comments.length === 0 && <div className="empty-state p-4">还没人留言。这个文件夹暂时保持沉默。</div>}
            {comments.map((comment) => (
              <article key={comment.id} className="rounded-lg border border-stone-200 bg-[#fffdf8] p-3 text-sm">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="font-semibold text-stone-900">{comment.author_nickname}</div>
                    <p className="mt-1 whitespace-pre-wrap break-words leading-6 text-stone-700">{comment.body}</p>
                    {comment.llm_reason && <p className="mt-2 text-xs text-stone-500">LLM：{comment.llm_reason}</p>}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
                    <span className={`pill ${
                      comment.status === "draft_created" ? "border-[#cbb8d8] bg-[#f5eef8] text-[#684b7a]"
                      : comment.status === "review_failed" ? "border-red-200 bg-red-50 text-red-700"
                      : "border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]"
                    }`}>
                      {comment.status === "draft_created" ? "已生成草稿" : comment.status === "review_failed" ? "审核失败" : "已入板"}
                    </span>
                    {comment.draft_requirement_id && (
                      <Link className="button-secondary min-h-8 px-2.5 py-1 text-xs" to={`/r/${comment.draft_requirement_id}/clarify`}>
                        去澄清
                      </Link>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {preview && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-stone-950/45 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
          <div className="paper-surface flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-stone-200/80 px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-stone-950">{preview.name}</div>
                <div className="text-xs text-stone-500">{preview.preview_type} · {preview.version_no ? `v${preview.version_no}` : "v?"}</div>
              </div>
              <div className="flex gap-2">
                {preview.preview_type === "html" && (
                  <button className="button-secondary min-h-8 px-2.5 py-1 text-xs" onClick={() => setHtmlRender((v) => !v)}>
                    {htmlRender ? "看源码" : "沙盒预览"}
                  </button>
                )}
                <a className="button-secondary min-h-8 px-2.5 py-1 text-xs" href={preview.download_url}>
                  <Download className="h-4 w-4" />
                  下载
                </a>
                <button className="button-ghost min-h-8 w-8 px-0" onClick={() => setPreview(null)} aria-label="关闭预览">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="min-h-[60vh] overflow-auto bg-[#fffdf8] p-4 scrollbar-thin-warm">
              {preview.preview_type === "pdf" && preview.render_url && <iframe title={preview.name} src={preview.render_url} className="h-[72vh] w-full rounded-md border border-stone-200" />}
              {preview.preview_type === "html" && htmlRender && preview.render_url && <iframe title={preview.name} src={preview.render_url} sandbox="" className="h-[72vh] w-full rounded-md border border-stone-200 bg-white" />}
              {(preview.preview_type === "code" || preview.preview_type === "markdown" || (preview.preview_type === "html" && !htmlRender) || preview.preview_type === "unsupported") && (
                <pre className="whitespace-pre-wrap break-words rounded-md border border-stone-200 bg-stone-950 p-4 text-xs leading-5 text-stone-100">{preview.content || "（文件没有可预览内容）"}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
