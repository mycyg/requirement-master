import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  FolderKanban,
  Paperclip,
  Rocket,
  Users,
} from "lucide-react";
import { Button, Card, Input, Stepper, Textarea, toast, type Step } from "@yqgl/shared";
import { invoke } from "@/lib/tauri";
import { AssigneeSelector } from "@/components/AssigneeSelector";
import { FileAttachRail } from "@/components/FileAttachRail";

type Priority = "low" | "normal" | "high" | "urgent";

const STEPS: Step[] = [
  { key: "desc",     label: "想说的事" },
  { key: "assignee", label: "谁来做" },
  { key: "due",      label: "截止时间" },
  { key: "files",    label: "附件" },
  { key: "submit",   label: "投递" },
];

const PRIORITY: { value: Priority; label: string; tone: string }[] = [
  { value: "low",    label: "随时", tone: "border border-line text-ink-muted hover:bg-accent-soft/60" },
  { value: "normal", label: "常规", tone: "border border-line text-ink hover:bg-accent-soft/60" },
  { value: "high",   label: "重要", tone: "border border-warn/30 bg-warn-soft text-warn" },
  { value: "urgent", label: "紧急", tone: "border border-error/30 bg-error-soft text-error" },
];

type Project = { id: string; name: string; slug: string };

/**
 * 派活 Space 的「新建需求」5 步 wizard。结构对照 web/src/pages/NewRequirement.tsx
 * 但视觉用 Aurora Glass tokens 重写，IPC 走 invoke() 而不是 fetch()。
 *
 * 草稿在「截止时间」这步保存（因为 ready 状态需要 due_at）。文件上传是
 * M4 提供的 FileAttachRail。最后一步「投递」直接调 submit_requirement，
 * 触发后端发 SSE `requirement.ready`，对应的 claimant 看到新工单弹窗。
 */
export function NewRequirement() {
  const nav = useNavigate();
  const [step, setStep] = useState(0);

  // form state
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectId, setProjectId] = useState<string>("");
  const [desc, setDesc] = useState("");
  const [priority, setPriority] = useState<Priority>("normal");
  const [leadUserId, setLeadUserId] = useState<string | null>(null);
  const [collabIds, setCollabIds] = useState<string[]>([]);
  const [dueAt, setDueAt] = useState("");
  const [startAt, setStartAt] = useState("");
  const [estimateHours, setEstimateHours] = useState("");
  const [confidence, setConfidence] = useState<"low" | "medium" | "high">("medium");

  // draft state
  const [reqId, setReqId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    invoke<Project[]>("list_my_projects")
      .then((rows) => {
        setProjects(rows);
        if (rows.length > 0 && !projectId) setProjectId(rows[0].id);
      })
      .catch((e) => setErr(`项目列表加载失败：${e}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const validateStep = (): string | null => {
    if (step === 0) {
      if (!projectId) return "先选一个项目。";
      if (!desc.trim()) return "至少写一句你想做的事。";
    }
    if (step === 2 && !dueAt) return "截止时间是这件事存在的前提，请先填。";
    return null;
  };

  const goNext = async () => {
    const v = validateStep();
    if (v) { setErr(v); return; }
    setErr(null);

    // Create the draft once we cross the "due date" step — that's when we
    // have all the required fields for a `draft` requirement on the backend.
    if (step === 2 && !reqId) {
      setBusy(true);
      try {
        const body: Record<string, unknown> = {
          raw_description: desc.trim(),
          priority,
          lead_user_id: leadUserId,
          collaborator_user_ids: collabIds,
          start_at: startAt ? new Date(startAt).toISOString() : null,
          due_at: new Date(dueAt).toISOString(),
        };
        if (estimateHours) {
          body.estimate_hours = Number(estimateHours);
          body.estimate_confidence = confidence;
        }
        const r = await invoke<{ id: string; code?: string }>("create_requirement", { projectId, body });
        setReqId(r.id);
        toast({ title: `草稿已存：${r.code ?? r.id.slice(0, 8)}`, tone: "success" });
      } catch (e: any) {
        setErr(String(e));
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  };

  const goBack = () => setStep((s) => Math.max(0, s - 1));

  const doSubmit = async () => {
    if (!reqId) { setErr("草稿还没建好。"); return; }
    setBusy(true);
    try {
      await invoke("submit_requirement", { reqId });
      toast({ title: "已投递", description: "等接单人接走，会在「投递池」里看到。", tone: "success" });
      nav(`/r/${reqId}`);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-3xl mx-auto">
        <header className="mb-6">
          <p className="text-eyebrow text-ink-muted">提一条新需求</p>
          <h1 className="text-h2 text-ink mt-1">{STEPS[step].label}</h1>
        </header>

        <Card variant="glass-quiet" padding="md" className="mb-6">
          <Stepper steps={STEPS} current={step} onJump={(i) => i <= step && setStep(i)} />
        </Card>

        <Card variant="glass" padding="lg" className="anim-fade-up">
          {step === 0 && (
            <div className="space-y-4">
              <div>
                <label className="text-eyebrow text-ink-muted block mb-2">
                  <FolderKanban className="inline h-3.5 w-3.5 mr-1" />
                  归属项目
                </label>
                {projects === null ? (
                  <div className="text-body-sm text-ink-faint">项目列表加载中…</div>
                ) : projects.length === 0 ? (
                  <div className="text-body-sm text-error">你还没加入任何项目。</div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {projects.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => setProjectId(p.id)}
                        className={`h-8 px-3 rounded-sm text-body-sm transition ${
                          projectId === p.id
                            ? "bg-accent text-white"
                            : "glass-quiet text-ink-soft hover:text-ink hover:bg-accent-soft/60"
                        }`}
                      >
                        {p.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label className="text-eyebrow text-ink-muted block mb-2">想说的事</label>
                <Textarea
                  rows={8}
                  placeholder="比如：做一个团队周报模板，每周自动汇总每个人的进度…"
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  autoFocus
                />
                <div className="text-caption text-ink-faint mt-2">
                  简单描述就行 — 接单人接走后还能跟你确认细节。
                </div>
              </div>

              <div>
                <label className="text-eyebrow text-ink-muted block mb-2">优先级</label>
                <div className="flex flex-wrap gap-1.5">
                  {PRIORITY.map((p) => (
                    <button
                      key={p.value}
                      type="button"
                      onClick={() => setPriority(p.value)}
                      className={`h-8 px-3 rounded-sm text-body-sm transition ${
                        priority === p.value ? p.tone : "border border-line text-ink-muted hover:bg-accent-soft/60"
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-3">
              <p className="text-body-sm text-ink-muted">
                <Users className="inline h-4 w-4 mr-1 text-ink-faint" />
                指定负责人 + 协作者，或留空让谁都能接。
              </p>
              <AssigneeSelector
                leadUserId={leadUserId}
                collaboratorUserIds={collabIds}
                onChange={({ leadUserId: l, collaboratorUserIds: c }) => {
                  setLeadUserId(l);
                  setCollabIds(c);
                }}
              />
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-body-sm text-ink-muted">
                <CalendarClock className="inline h-4 w-4 mr-1 text-ink-faint" />
                至少填截止时间，预计开始 / 工时可选。
              </p>
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-eyebrow text-ink-muted block mb-1">预计开始（可选）</span>
                  <Input
                    type="datetime-local"
                    value={startAt}
                    onChange={(e) => setStartAt(e.target.value)}
                  />
                </label>
                <label className="block">
                  <span className="text-eyebrow text-ink-muted block mb-1">截止时间（必填）</span>
                  <Input
                    type="datetime-local"
                    value={dueAt}
                    onChange={(e) => setDueAt(e.target.value)}
                  />
                </label>
              </div>
              <div className="grid sm:grid-cols-[1fr_140px] gap-3">
                <label className="block">
                  <span className="text-eyebrow text-ink-muted block mb-1">预计工时（小时，可选）</span>
                  <Input
                    type="number"
                    min="0"
                    step="0.5"
                    value={estimateHours}
                    onChange={(e) => setEstimateHours(e.target.value)}
                    placeholder="比如 6"
                  />
                </label>
                <label className="block">
                  <span className="text-eyebrow text-ink-muted block mb-1">信心</span>
                  <select
                    className="w-full h-10 px-3 bg-surface-strong border border-line rounded-sm text-body text-ink disabled:opacity-60"
                    value={confidence}
                    disabled={!estimateHours}
                    onChange={(e) => setConfidence(e.target.value as "low" | "medium" | "high")}
                  >
                    <option value="low">低</option>
                    <option value="medium">中</option>
                    <option value="high">高</option>
                  </select>
                </label>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3">
              <p className="text-body-sm text-ink-muted">
                <Paperclip className="inline h-4 w-4 mr-1 text-ink-faint" />
                相关资料（可选）。接单人接走后能直接看到附件，无需另外发。
              </p>
              {reqId ? (
                <FileAttachRail reqId={reqId} />
              ) : (
                <div className="glass-sunken p-4 text-body-sm text-ink-muted">
                  草稿还没建好。回到上一步填截止时间再过来。
                </div>
              )}
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4 text-center">
              <div className="grid h-12 w-12 mx-auto place-items-center rounded-full bg-accent-soft text-accent">
                <Rocket className="h-5 w-5" />
              </div>
              <h2 className="text-h3 text-ink">就差最后一步</h2>
              <p className="text-body-sm text-ink-muted max-w-md mx-auto">
                投递后接单人会立刻收到通知。你随时可以在「派活 · 投递池」里追踪。
              </p>
              <div className="flex justify-center gap-2 pt-2">
                <Button variant="secondary" onClick={() => reqId && nav(`/r/${reqId}`)} disabled={!reqId}>
                  先去看看草稿
                </Button>
                <Button variant="accent" onClick={doSubmit} loading={busy} leftIcon={<Rocket className="h-4 w-4" />}>
                  立即投递
                </Button>
              </div>
            </div>
          )}

          {err && (
            <div className="mt-4 flex items-center gap-2 text-body-sm text-error">
              <AlertCircle className="h-4 w-4" /> {err}
            </div>
          )}

          {step < 4 && (
            <div className="mt-6 flex items-center justify-between">
              <Button
                variant="secondary"
                disabled={step === 0 || busy}
                onClick={goBack}
                leftIcon={<ArrowLeft className="h-4 w-4" />}
              >
                上一步
              </Button>
              <Button
                variant="accent"
                onClick={goNext}
                loading={busy}
                rightIcon={!busy ? <ArrowRight className="h-4 w-4" /> : undefined}
              >
                {step === 2 && !reqId ? "保存并继续" : "下一步"}
              </Button>
            </div>
          )}

          {step === 4 && reqId && (
            <div className="mt-6 flex items-center">
              <Button
                variant="ghost"
                onClick={goBack}
                leftIcon={<ArrowLeft className="h-4 w-4" />}
              >
                返回修改
              </Button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
