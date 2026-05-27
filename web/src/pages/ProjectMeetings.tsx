import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertCircle, CalendarClock, CheckCircle2, FileAudio2, HardDrive, Loader2, Mic2, RefreshCw,
  Send, Sparkles, Trash2, UploadCloud,
} from "lucide-react";
import { api } from "@/lib/api";
import type { BackgroundJob, Meeting, MeetingInsight, Project } from "@/lib/types";

const CHUNK_SIZE = 5 * 1024 * 1024;

function dateLabel(value: string): string {
  return new Date(value + (value.endsWith("Z") ? "" : "Z")).toLocaleString("zh-CN", { hour12: false });
}

function insightLabel(insight: MeetingInsight): string {
  if (insight.kind === "new_requirement") return "新增需求";
  if (insight.kind === "requirement_change") return "需求变更";
  return "普通纪要";
}

export function ProjectMeetings() {
  const { id: projectId = "" } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [active, setActive] = useState<Meeting | null>(null);
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    const [projects, rows] = await Promise.all([api.listProjects(), api.listMeetings(projectId)]);
    setProject(projects.find((p) => p.id === projectId) ?? null);
    setMeetings(rows);
    setActive((current) => {
      if (!current) return rows[0] ?? null;
      return rows.find((m) => m.id === current.id) ?? rows[0] ?? null;
    });
  }, [projectId]);

  useEffect(() => { load().catch((e) => setErr(String(e))); }, [load]);

  useEffect(() => {
    if (!active?.job_id || active.status !== "processing") {
      setJob(null);
      return;
    }
    let alive = true;
    const tick = async () => {
      try {
        const next = await api.getJob(active.job_id!);
        if (!alive) return;
        setJob(next);
        if (next.status === "succeeded" || next.status === "failed") await load();
      } catch {
        // keep the meeting pane alive; job polling is only a status nicety
      }
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
      const init = await api.initMeetingUpload(projectId, {
        filename: file.name,
        total_size: file.size,
        total_chunks: totalChunks,
        mime: file.type || "audio/webm",
        title: title.trim() || file.name.replace(/\.[^.]+$/, ""),
      });
      for (let idx = 0; idx < totalChunks; idx += 1) {
        await api.uploadMeetingChunk(projectId, init.upload_id, idx, file.slice(idx * CHUNK_SIZE, Math.min(file.size, (idx + 1) * CHUNK_SIZE)));
      }
      const meeting = await api.finalizeMeetingUpload(projectId, init.upload_id);
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
      await api.confirmMeetingInsight(insight.id);
      if (active) setActive(await api.getMeeting(active.id));
      await load();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  const dismiss = async (insight: MeetingInsight) => {
    setBusy("忽略建议");
    setErr(null);
    try {
      await api.dismissMeetingInsight(insight.id);
      if (active) setActive(await api.getMeeting(active.id));
      await load();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="app-container">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">Project Meetings</p>
          <h1 className="mt-2 flex items-center gap-2 text-3xl font-semibold tracking-tight text-stone-950">
            <Mic2 className="h-7 w-7 text-stone-500" aria-hidden="true" />
            {project?.name || "会议纪要"}
          </h1>
          <p className="mt-2 text-xs text-stone-500">录音先进 ASR，再进纪要，最后让人类点头。少一点“会议上说过”的玄学。</p>
        </div>
        <button className="button-secondary" onClick={() => load()}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          刷新
        </button>
      </header>

      {project && (
        <div className="mt-6 flex gap-2 border-b border-stone-200">
          <Link to={`/p/${project.id}`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
            <CalendarClock className="h-4 w-4" aria-hidden="true" />
            需求
          </Link>
          <Link to={`/p/${project.id}/drive`} className="tab-button border-transparent text-stone-500 hover:text-stone-950">
            <HardDrive className="h-4 w-4" aria-hidden="true" />
            网盘
          </Link>
          <Link to={`/p/${project.id}/meetings`} className="tab-button border-stone-950 text-stone-950">
            <Mic2 className="h-4 w-4" aria-hidden="true" />
            会议
          </Link>
        </div>
      )}

      <div className="mt-6 grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <section className="paper-surface p-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-900">
              <UploadCloud className="h-4 w-4 text-stone-500" aria-hidden="true" />
              导入会议录音
            </h2>
            <input
              className="field mt-3"
              placeholder="会议标题（不写就用文件名）"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <label className="paper-panel mt-3 block cursor-pointer border-2 border-dashed border-stone-300 p-5 text-center transition hover:border-stone-500 hover:bg-[#fffdf8]">
              <FileAudio2 className="mx-auto h-7 w-7 text-stone-400" aria-hidden="true" />
              <div className="mt-2 text-sm font-medium text-stone-700">{busy?.startsWith("上传") ? busy : "选择音频 / 会议转写文本"}</div>
              <p className="mt-1 text-xs text-stone-500">E2E 可用文本 fixture；真实环境走 ASR。</p>
              <input className="hidden" type="file" accept="audio/*,.txt,.md" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
            {err && (
              <p className="mt-3 flex items-center gap-2 text-xs text-red-700">
                <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
                {err}
              </p>
            )}
          </section>

          <section className="paper-surface max-h-[520px] overflow-auto p-2 scrollbar-thin-warm">
            {meetings.length === 0 && <div className="empty-state m-2">还没有会议。终于有个地方不用先开会了。</div>}
            {meetings.map((meeting) => (
              <button
                key={meeting.id}
                className={`mb-1 w-full rounded-lg border p-3 text-left transition hover:bg-white ${
                  active?.id === meeting.id ? "border-stone-950 bg-white" : "border-stone-200 bg-[#fffdf8]"
                }`}
                onClick={() => setActive(meeting)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-stone-900">{meeting.title}</span>
                  <span className={`pill shrink-0 ${
                    meeting.status === "ready" ? "border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]"
                    : meeting.status === "failed" ? "border-red-200 bg-red-50 text-red-700"
                    : ""
                  }`}>{meeting.status === "ready" ? "已生成" : meeting.status === "failed" ? "失败" : "处理中"}</span>
                </div>
                <div className="mt-2 text-xs text-stone-500">{dateLabel(meeting.created_at)} · {meeting.uploaded_by_nickname}</div>
              </button>
            ))}
          </section>
        </aside>

        <section className="min-w-0">
          {!active && <div className="empty-state min-h-[520px]">选一个会议，或者先上传录音。</div>}
          {active && (
            <div className="space-y-4">
              <section className="paper-surface p-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="eyebrow">Meeting</p>
                    <h2 className="mt-2 break-words text-2xl font-semibold text-stone-950">{active.title}</h2>
                    <p className="mt-2 text-xs text-stone-500">{active.audio_filename} · {dateLabel(active.created_at)}</p>
                  </div>
                  {active.status === "processing" && (
                    <span className="pill">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                      {job?.message || "处理中"} · {job?.progress_percent ?? 10}%
                    </span>
                  )}
                </div>
                {active.status === "processing" && (
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-stone-200">
                    <div className="h-full rounded-full bg-stone-950 transition-all" style={{ width: `${job?.progress_percent ?? 10}%` }} />
                  </div>
                )}
              </section>

              <section className="grid gap-4 xl:grid-cols-2">
                <div className="paper-surface p-4">
                  <h3 className="text-sm font-semibold text-stone-900">ASR 转写</h3>
                  <pre className="mt-3 max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-4 text-xs leading-5 text-stone-700 scrollbar-thin-warm">
                    {active.transcript_text || "还在等声音变成文字。"}
                  </pre>
                </div>
                <div className="paper-surface p-4">
                  <h3 className="text-sm font-semibold text-stone-900">会议纪要</h3>
                  <pre className="mt-3 max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-4 text-xs leading-5 text-stone-700 scrollbar-thin-warm">
                    {active.minutes_md || "纪要还没端上来。"}
                  </pre>
                </div>
              </section>

              <section className="paper-surface p-4">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-stone-900">
                  <Sparkles className="h-4 w-4 text-stone-500" aria-hidden="true" />
                  需求评估
                </h3>
                <div className="mt-3 space-y-2">
                  {active.insights.length === 0 && <div className="empty-state p-4">暂时没有识别出要进需求流程的内容。</div>}
                  {active.insights.map((insight) => (
                    <article key={insight.id} className="rounded-lg border border-stone-200 bg-[#fffdf8] p-3">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="pill">{insightLabel(insight)}</span>
                            <span className={`pill ${
                              insight.status === "confirmed" ? "border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]"
                              : insight.status === "dismissed" ? "border-stone-200 bg-stone-100 text-stone-500"
                              : "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]"
                            }`}>{insight.status === "confirmed" ? "已确认" : insight.status === "dismissed" ? "已忽略" : "待人工确认"}</span>
                          </div>
                          <h4 className="mt-2 break-words text-sm font-semibold text-stone-950">{insight.title}</h4>
                          <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-stone-600">{insight.description}</p>
                          {insight.confidence_reason && <p className="mt-2 text-xs text-stone-400">LLM：{insight.confidence_reason}</p>}
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
                          {insight.created_requirement_id && (
                            <Link className="button-secondary min-h-8 px-2.5 py-1 text-xs" to={`/r/${insight.created_requirement_id}/clarify`}>
                              去澄清
                            </Link>
                          )}
                          {insight.status === "pending" && insight.kind !== "normal_note" && (
                            <button className="button-primary min-h-8 px-2.5 py-1 text-xs" disabled={!!busy} onClick={() => confirm(insight)}>
                              <Send className="h-3.5 w-3.5" aria-hidden="true" />
                              进入评估
                            </button>
                          )}
                          {insight.status === "pending" && (
                            <button className="button-secondary min-h-8 px-2.5 py-1 text-xs" disabled={!!busy} onClick={() => dismiss(insight)}>
                              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                              忽略
                            </button>
                          )}
                          {insight.status === "confirmed" && !insight.created_requirement_id && (
                            <span className="pill"><CheckCircle2 className="h-3.5 w-3.5" />已记录</span>
                          )}
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
