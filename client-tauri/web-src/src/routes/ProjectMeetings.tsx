import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle, ArrowLeft, CheckCircle2, FileAudio2, Loader2, Mic2, RefreshCw,
  Send, Sparkles, Trash2, UploadCloud,
} from "lucide-react";
import { Button, Card, EmptyState, Progress, Skeleton, toast } from "@yqgl/shared";
import type { BackgroundJob, Meeting, MeetingInsight } from "@yqgl/shared";
import { clientFetch, clientJson, invoke } from "@/lib/tauri";

const CHUNK_SIZE = 5 * 1024 * 1024;

type Project = { id: string; name: string; slug: string };

function dateLabel(value: string): string {
  return new Date(value + (value.endsWith("Z") ? "" : "Z")).toLocaleString("zh-CN", { hour12: false });
}

function insightLabel(insight: MeetingInsight): string {
  if (insight.kind === "new_requirement") return "新增需求";
  if (insight.kind === "requirement_change") return "需求变更";
  return "普通纪要";
}

// ── thin API helpers over clientFetch/clientJson (webview → backend w/ auth) ──
const listMeetings = (pid: string) => clientJson<Meeting[]>(`/api/projects/${pid}/meetings`);
const getMeeting = (id: string) => clientJson<Meeting>(`/api/meetings/${id}`);
const getJob = (id: string) => clientJson<BackgroundJob>(`/api/jobs/${id}`);
const initUpload = (pid: string, body: unknown) =>
  clientJson<{ upload_id: string }>(`/api/projects/${pid}/meetings/upload/init`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
const putChunk = async (pid: string, uid: string, idx: number, blob: Blob) => {
  const r = await clientFetch(`/api/projects/${pid}/meetings/upload/${uid}/chunk/${idx}`, { method: "PUT", body: blob });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
};
const finalizeUpload = (pid: string, uid: string) =>
  clientJson<Meeting>(`/api/projects/${pid}/meetings/upload/${uid}/finalize`, { method: "POST" });
const confirmInsight = (id: string) => clientJson<MeetingInsight>(`/api/meeting-insights/${id}/confirm`, { method: "POST" });
const dismissInsight = (id: string) => clientJson<MeetingInsight>(`/api/meeting-insights/${id}/dismiss`, { method: "POST" });

export function ProjectMeetings() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const nav = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [active, setActive] = useState<Meeting | null>(null);
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const loadTokenRef = useRef(0);
  const load = useCallback(async () => {
    if (!projectId) return;
    const token = ++loadTokenRef.current;
    const [projects, rows] = await Promise.all([
      invoke<Project[]>("list_my_projects"),
      listMeetings(projectId),
    ]);
    if (token !== loadTokenRef.current) return;
    setProject(projects.find((p) => p.id === projectId) ?? null);
    setMeetings(rows);
    setActive((current) => {
      if (!current) return rows[0] ?? null;
      return rows.find((m) => m.id === current.id) ?? rows[0] ?? null;
    });
  }, [projectId]);

  useEffect(() => { load().catch((e) => setErr(String(e))); }, [load]);

  // Poll the background job while a meeting is processing (ASR + LLM analysis).
  useEffect(() => {
    if (!active?.job_id || active.status !== "processing") { setJob(null); return; }
    let alive = true;
    const tick = async () => {
      try {
        const next = await getJob(active.job_id!);
        if (!alive) return;
        setJob(next);
        if (next.status === "succeeded" || next.status === "failed") await load();
      } catch { /* polling is best-effort */ }
    };
    tick();
    const timer = window.setInterval(tick, 1500);
    return () => { alive = false; window.clearInterval(timer); };
  }, [active?.job_id, active?.status, load]);

  const upload = async (file: File) => {
    if (!projectId || file.size <= 0) return;
    setBusy(`上传 ${file.name}`);
    setErr(null);
    try {
      const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
      const init = await initUpload(projectId, {
        filename: file.name,
        total_size: file.size,
        total_chunks: totalChunks,
        mime: file.type || "audio/webm",
        title: title.trim() || file.name.replace(/\.[^.]+$/, ""),
      });
      for (let idx = 0; idx < totalChunks; idx += 1) {
        await putChunk(projectId, init.upload_id, idx, file.slice(idx * CHUNK_SIZE, Math.min(file.size, (idx + 1) * CHUNK_SIZE)));
      }
      const meeting = await finalizeUpload(projectId, init.upload_id);
      setTitle("");
      setActive(meeting);
      await load();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const confirm = async (insight: MeetingInsight) => {
    setBusy("确认需求评估");
    setErr(null);
    try {
      await confirmInsight(insight.id);
      if (active) setActive(await getMeeting(active.id));
      await load();
      toast({ title: "已进入需求评估", tone: "success" });
    } catch (e: any) {
      setErr(String(e));
    } finally { setBusy(null); }
  };

  const dismiss = async (insight: MeetingInsight) => {
    setBusy("忽略建议");
    setErr(null);
    try {
      await dismissInsight(insight.id);
      if (active) setActive(await getMeeting(active.id));
      await load();
    } catch (e: any) {
      setErr(String(e));
    } finally { setBusy(null); }
  };

  return (
    <div className="flex-1 overflow-auto p-6">
      <button
        onClick={() => nav(`/p/${projectId}`)}
        className="inline-flex items-center gap-1.5 text-body-sm text-ink-muted hover:text-ink mb-4"
      >
        <ArrowLeft className="h-4 w-4" /> 返回项目网盘
      </button>

      <header className="flex items-end justify-between mb-5 gap-4">
        <div>
          <h1 className="text-h2 text-ink flex items-center gap-2">
            <Mic2 className="h-6 w-6 text-ink-muted" /> {project?.name || "会议纪要"}
          </h1>
          <p className="text-body-sm text-ink-muted mt-1">
            上传录音 → 自动转写 → AI 助理整理纪要 → 人工确认 → 生成需求草稿。
          </p>
        </div>
        <Button variant="ghost" size="sm" leftIcon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => load().catch((e) => setErr(String(e)))}>
          刷新
        </Button>
      </header>

      <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <Card variant="glass-quiet" padding="md">
            <h2 className="flex items-center gap-2 text-body-sm font-medium text-ink mb-3">
              <UploadCloud className="h-4 w-4 text-ink-muted" /> 导入会议录音
            </h2>
            <input
              className="field mb-3"
              placeholder="会议标题（不写就用文件名）"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <label className="glass-sunken block cursor-pointer rounded-sm border border-dashed border-line p-5 text-center transition hover:bg-accent-soft/40">
              <FileAudio2 className="mx-auto h-7 w-7 text-ink-faint" />
              <div className="mt-2 text-body-sm text-ink">{busy?.startsWith("上传") ? busy : "选择音频 / 会议转写文本"}</div>
              <p className="mt-1 text-caption text-ink-faint">支持音频走 ASR；也可直接传 .txt/.md 文本。</p>
              <input className="hidden" type="file" accept="audio/*,.txt,.md" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
            {err && (
              <p className="mt-3 flex items-center gap-2 text-caption text-error">
                <AlertCircle className="h-3.5 w-3.5" /> {err}
              </p>
            )}
          </Card>

          <Card variant="glass-quiet" padding="sm" className="max-h-[520px] overflow-auto">
            {meetings === null ? (
              <div className="space-y-2 p-1"><Skeleton height="h-14" rounded="md" /><Skeleton height="h-14" rounded="md" /></div>
            ) : meetings.length === 0 ? (
              <div className="text-caption text-ink-faint p-3">还没有会议录音，点上方上传试一下。</div>
            ) : meetings.map((meeting) => (
              <button
                key={meeting.id}
                className={`mb-1 w-full rounded-sm p-3 text-left transition ${
                  active?.id === meeting.id ? "bg-accent-soft" : "hover:bg-accent-soft/60"
                }`}
                onClick={() => setActive(meeting)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-body-sm text-ink font-medium">{meeting.title}</span>
                  <span className={`text-caption shrink-0 ${
                    meeting.status === "ready" ? "text-success" : meeting.status === "failed" ? "text-error" : "text-warn"
                  }`}>{meeting.status === "ready" ? "已生成" : meeting.status === "failed" ? "失败" : "处理中"}</span>
                </div>
                <div className="mt-1 text-caption text-ink-muted">{dateLabel(meeting.created_at)} · {meeting.uploaded_by_nickname}</div>
              </button>
            ))}
          </Card>
        </aside>

        <section className="min-w-0">
          {!active ? (
            <EmptyState icon={<Mic2 className="h-8 w-8" />} title="选一个会议，或先上传录音" />
          ) : (
            <div className="space-y-4">
              <Card variant="glass-strong" padding="lg">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h2 className="break-words text-h3 text-ink">{active.title}</h2>
                    <p className="mt-1 text-caption text-ink-muted">{active.audio_filename} · {dateLabel(active.created_at)}</p>
                  </div>
                  {active.status === "processing" && (
                    <span className="inline-flex items-center gap-1.5 text-caption text-ink-muted whitespace-nowrap">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" /> {job?.message || "处理中"} · {job?.progress_percent ?? 10}%
                    </span>
                  )}
                </div>
                {active.status === "processing" && (
                  <div className="mt-4"><Progress value={job?.progress_percent ?? 10} size="sm" tone="accent" /></div>
                )}
              </Card>

              <div className="grid gap-4 xl:grid-cols-2">
                <Card variant="glass-quiet" padding="md">
                  <h3 className="text-h4 text-ink mb-2">ASR 转写</h3>
                  <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap glass-sunken rounded-sm p-3 text-caption leading-5 text-ink-soft">
                    {active.transcript_text || "还在把声音变成文字…"}
                  </pre>
                </Card>
                <Card variant="glass-quiet" padding="md">
                  <h3 className="text-h4 text-ink mb-2">会议纪要</h3>
                  <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap glass-sunken rounded-sm p-3 text-caption leading-5 text-ink-soft">
                    {active.minutes_md || "纪要生成中…"}
                  </pre>
                </Card>
              </div>

              <Card variant="glass-quiet" padding="md">
                <h3 className="flex items-center gap-2 text-h4 text-ink mb-3">
                  <Sparkles className="h-4 w-4 text-accent" /> 需求评估
                </h3>
                <div className="space-y-2">
                  {active.insights.length === 0 && (
                    <div className="text-caption text-ink-faint p-3">暂时没有识别出要进需求流程的内容。</div>
                  )}
                  {active.insights.map((insight) => (
                    <div key={insight.id} className="glass-sunken rounded-sm p-3">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-caption text-accent">{insightLabel(insight)}</span>
                            <span className={`text-caption ${
                              insight.status === "confirmed" ? "text-success"
                              : insight.status === "dismissed" ? "text-ink-faint" : "text-warn"
                            }`}>{insight.status === "confirmed" ? "已确认" : insight.status === "dismissed" ? "已忽略" : "待人工确认"}</span>
                          </div>
                          <h4 className="mt-2 break-words text-body-sm font-medium text-ink">{insight.title}</h4>
                          <p className="mt-2 whitespace-pre-wrap text-caption leading-5 text-ink-muted">{insight.description}</p>
                          {insight.confidence_reason && <p className="mt-2 text-caption text-ink-faint">AI 判断：{insight.confidence_reason}</p>}
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
                          {insight.created_requirement_id && (
                            <Button variant="secondary" size="sm" onClick={() => nav(`/r/${insight.created_requirement_id}/clarify`)}>
                              去澄清
                            </Button>
                          )}
                          {insight.status === "pending" && insight.kind !== "normal_note" && (
                            <Button variant="accent" size="sm" leftIcon={<Send className="h-3.5 w-3.5" />} disabled={!!busy} onClick={() => confirm(insight)}>
                              进入评估
                            </Button>
                          )}
                          {insight.status === "pending" && (
                            <Button variant="ghost" size="sm" leftIcon={<Trash2 className="h-3.5 w-3.5" />} disabled={!!busy} onClick={() => dismiss(insight)}>
                              忽略
                            </Button>
                          )}
                          {insight.status === "confirmed" && !insight.created_requirement_id && (
                            <span className="inline-flex items-center gap-1 text-caption text-success"><CheckCircle2 className="h-3.5 w-3.5" />已记录</span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
