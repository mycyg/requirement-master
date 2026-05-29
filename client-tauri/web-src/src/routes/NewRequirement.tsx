import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Bot,
  CalendarClock,
  FolderKanban,
  FolderPlus,
  Paperclip,
  Plus,
  Sparkles,
  Users,
} from "lucide-react";
import { Button, Card, Input, Modal, Stepper, Textarea, toast, type Step } from "@yqgl/shared";
import { invoke } from "@/lib/tauri";
import { AssigneeSelector } from "@/components/AssigneeSelector";
import { FileAttachRail } from "@/components/FileAttachRail";
import { VoiceButton } from "@/components/VoiceButton";

type Priority = "low" | "normal" | "high" | "urgent";

const STEPS: Step[] = [
  { key: "project",  label: "归属项目" },
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
  const [searchParams] = useSearchParams();
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
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [meAdmin, setMeAdmin] = useState(false);

  useEffect(() => {
    invoke<{ is_admin?: boolean } | null>("me").then((m) => setMeAdmin(!!m?.is_admin)).catch(() => {});
  }, []);

  const refreshProjects = async (selectId?: string) => {
    const rows = await invoke<Project[]>("list_my_projects");
    setProjects(rows);
    if (selectId) {
      setProjectId(selectId);
    } else if (rows.length > 0 && !projectId) {
      setProjectId(rows[0].id);
    }
  };

  useEffect(() => {
    // When opened as "基于此新建后续" (?parent_req_id=...), preselect the
    // parent requirement's project so the follow-up lands in the same place.
    const parentId = searchParams.get("parent_req_id");
    (async () => {
      try {
        const rows = await invoke<Project[]>("list_my_projects");
        setProjects(rows);
        let preselect = rows.length > 0 ? rows[0].id : "";
        if (parentId) {
          try {
            const parent = await invoke<{ project_id?: string }>("get_requirement", { reqId: parentId });
            if (parent?.project_id && rows.some((r) => r.id === parent.project_id)) {
              preselect = parent.project_id;
            }
          } catch { /* parent lookup is best-effort */ }
        }
        if (preselect && !projectId) setProjectId(preselect);
      } catch (e: any) {
        setErr(`项目列表加载失败：${e}`);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Step indices: 0=项目, 1=描述, 2=谁来做, 3=截止, 4=附件, 5=投递
  const validateStep = (): string | null => {
    if (step === 0 && !projectId) return "先选一个项目。";
    if (step === 1 && !desc.trim()) return "至少写一句你想做的事。";
    if (step === 3 && !dueAt) return "截止时间是这件事存在的前提，请先填。";
    return null;
  };

  const goNext = async () => {
    // Re-entrancy guard — `loading={busy}` on the button only disables
    // after the next render; a double-click within ~16ms slips through
    // and creates duplicate draft requirements.
    if (busy) return;
    const v = validateStep();
    if (v) { setErr(v); return; }
    setErr(null);

    // Create the draft once we cross the "due date" step — that's when we
    // have all the required fields for a `draft` requirement on the backend.
    if (step === 3 && !reqId) {
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

  const goClarify = () => {
    if (!reqId) { setErr("草稿还没建好。"); return; }
    nav(`/r/${reqId}/clarify`);
  };

  // Admin-only emergency bypass: skip AI clarification entirely. Backend
  // gates this with is_admin, so non-admins get 403.
  const adminSkipAi = async () => {
    if (!reqId) { setErr("草稿还没建好。"); return; }
    if (!confirm("跳过 AI 澄清会让需求直接进入「投递池」 — 接单人看到的就是你刚写的原文。确定？")) return;
    setBusy(true);
    try {
      await invoke("finalize_and_submit", {
        reqId,
        summaryMd: desc.trim() || null,
        title: desc.trim().split(/\r?\n/)[0]?.slice(0, 40) || null,
      });
      toast({ title: "已投递（跳过 AI）", tone: "warn" });
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
              <div className="flex items-start justify-between gap-3">
                <p className="text-body-sm text-ink-muted flex-1">
                  <FolderKanban className="inline h-4 w-4 mr-1 text-ink-faint" />
                  这个需求归属哪个项目？接单人会看到这个项目的标签和归档目录。
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  leftIcon={<FolderPlus className="h-3.5 w-3.5" />}
                  onClick={() => setNewProjectOpen(true)}
                >
                  新建项目
                </Button>
              </div>
              {projects === null ? (
                <div className="text-body-sm text-ink-faint">项目列表加载中…</div>
              ) : projects.length === 0 ? (
                <div className="glass-sunken p-6 text-center">
                  <FolderPlus className="h-8 w-8 mx-auto text-ink-faint mb-2" />
                  <div className="text-body-sm text-ink">还没有项目</div>
                  <div className="text-caption text-ink-muted mt-1 mb-3">
                    项目用来给一组需求做分类和归档，新建一个吧。
                  </div>
                  <Button variant="accent" size="sm" leftIcon={<Plus className="h-3.5 w-3.5" />} onClick={() => setNewProjectOpen(true)}>
                    新建项目
                  </Button>
                </div>
              ) : (
                <div className="grid sm:grid-cols-2 gap-2">
                  {projects.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setProjectId(p.id)}
                      className={`flex items-center gap-3 h-14 px-4 rounded-md text-left transition ${
                        projectId === p.id
                          ? "bg-accent text-white shadow-2"
                          : "glass-quiet text-ink hover:bg-accent-soft/60"
                      }`}
                    >
                      <div className={`grid h-8 w-8 shrink-0 place-items-center rounded-sm ${
                        projectId === p.id ? "bg-white/20" : "bg-accent-soft text-accent"
                      }`}>
                        <FolderKanban className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className={`text-body-sm font-medium truncate ${projectId === p.id ? "text-white" : "text-ink"}`}>
                          {p.name}
                        </div>
                        <div className={`text-caption truncate ${projectId === p.id ? "text-white/80" : "text-ink-muted"}`}>
                          {p.slug}
                        </div>
                      </div>
                    </button>
                  ))}
                  {/* + 新建 tile in the same grid so it lives where the eye is */}
                  <button
                    type="button"
                    onClick={() => setNewProjectOpen(true)}
                    className="flex items-center gap-3 h-14 px-4 rounded-md text-left transition glass-sunken border border-dashed border-line-strong text-ink-muted hover:bg-accent-soft/40 hover:text-ink hover:border-accent/40"
                  >
                    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-sm bg-accent-soft text-accent">
                      <Plus className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-body-sm font-medium">新建项目</div>
                      <div className="text-caption">用于一组新的需求</div>
                    </div>
                  </button>
                </div>
              )}
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-eyebrow text-ink-muted">想说的事</label>
                  <VoiceButton onText={(t) => setDesc((d) => (d.trim() ? `${d.trim()}\n${t}` : t))} />
                </div>
                <Textarea
                  rows={8}
                  placeholder="比如：做一个团队周报模板，每周自动汇总每个人的进度…"
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  autoFocus
                />
                <div className="text-caption text-ink-faint mt-2">
                  简单描述就行 — 接单人接走后还能跟你确认细节。也可以「按住说话」语音输入。
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

          {step === 2 && (
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

          {step === 3 && (
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

          {step === 4 && (
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

          {step === 5 && (
            <div className="space-y-4 text-center">
              <div className="grid h-14 w-14 mx-auto place-items-center rounded-full bg-gradient-to-br from-[#6B5BFF] to-[#FF6E8E] text-white shadow-2">
                <Sparkles className="h-6 w-6" />
              </div>
              <h2 className="text-h3 text-ink">下一步：跟 AI 聊聊</h2>
              <p className="text-body-sm text-ink-muted max-w-md mx-auto">
                AI 助理会跟你聊几轮，把需求打磨清楚，然后你确认投递。
                <br />
                <span className="text-ink-faint text-caption">
                  接单人看到的是 AI 整理后的清晰版本，不是你的草稿原文。
                </span>
              </p>
              <div className="flex justify-center gap-2 pt-2">
                <Button variant="secondary" onClick={() => reqId && nav(`/r/${reqId}`)} disabled={!reqId}>
                  先去看看草稿
                </Button>
                <Button variant="accent" onClick={goClarify} disabled={!reqId} leftIcon={<Bot className="h-4 w-4" />}>
                  跟 AI 聊聊
                </Button>
              </div>
              {meAdmin && (
                <div className="pt-4 text-center">
                  <button
                    type="button"
                    onClick={adminSkipAi}
                    disabled={busy || !reqId}
                    className="text-caption text-ink-faint hover:text-warn underline-offset-4 hover:underline disabled:opacity-50"
                  >
                    跳过 AI 直接投递（不推荐 · 仅管理员）
                  </button>
                </div>
              )}
            </div>
          )}

          {err && (
            <div className="mt-4 flex items-center gap-2 text-body-sm text-error">
              <AlertCircle className="h-4 w-4" /> {err}
            </div>
          )}

          {step < 5 && (
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
                {step === 3 && !reqId ? "保存并继续" : "下一步"}
              </Button>
            </div>
          )}

          {step === 5 && reqId && (
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

      <Modal open={newProjectOpen} onClose={() => setNewProjectOpen(false)} title="新建项目" size="sm">
        <NewProjectForm
          onCancel={() => setNewProjectOpen(false)}
          onCreated={(p) => {
            setNewProjectOpen(false);
            refreshProjects(p.id);
          }}
        />
      </Modal>
    </div>
  );
}

function NewProjectForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (project: Project) => void;
}) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Auto-derive slug from the name as user types (lowercase ASCII + dash).
  // User can still edit the slug field manually.
  const [slugTouched, setSlugTouched] = useState(false);
  const onNameChange = (v: string) => {
    setName(v);
    if (!slugTouched) {
      const auto = v.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24);
      setSlug(auto);
    }
  };

  const submit = async () => {
    setErr(null);
    if (!name.trim()) { setErr("项目名不能空"); return; }
    if (!/^[a-z0-9-]+$/.test(slug)) { setErr("slug 只能用小写字母 / 数字 / 横线"); return; }
    setBusy(true);
    try {
      const p = await invoke<Project>("create_project", { name: name.trim(), slug });
      toast({ title: `项目「${p.name}」已创建`, tone: "success" });
      onCreated(p);
    } catch (e: any) {
      setErr(String(e));
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="text-eyebrow text-ink-muted block mb-1">项目名</span>
        <Input
          autoFocus
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="比如：客户端重构"
        />
      </label>
      <label className="block">
        <span className="text-eyebrow text-ink-muted block mb-1">slug（需求编号前缀）</span>
        <Input
          value={slug}
          onChange={(e) => { setSlug(e.target.value.toLowerCase()); setSlugTouched(true); }}
          placeholder="client"
        />
        <div className="text-caption text-ink-faint mt-1">
          需求会编号为 <span className="font-mono">{(slug || "SLUG").toUpperCase()}-001</span>，定了别再改
        </div>
      </label>
      {err && (
        <div className="flex items-center gap-2 text-body-sm text-error">
          <AlertCircle className="h-4 w-4" /> {err}
        </div>
      )}
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" onClick={onCancel}>取消</Button>
        <Button variant="accent" loading={busy} onClick={submit} leftIcon={<FolderPlus className="h-4 w-4" />}>
          创建
        </Button>
      </div>
    </div>
  );
}
