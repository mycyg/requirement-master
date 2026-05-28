import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  FileText,
  Paperclip,
  Sparkles,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { AssigneeSelector } from "@/components/AssigneeSelector";
import { FileUpload } from "@/components/FileUpload";
import { VoiceButton } from "@/components/VoiceButton";
import { Stepper, type Step } from "@yqgl/shared";
import type { Attachment } from "@/lib/types";

type Priority = "low" | "normal" | "high" | "urgent";

const STEPS: Step[] = [
  { key: "desc", label: "想说的事" },
  { key: "assignee", label: "谁来做" },
  { key: "due", label: "截止时间" },
  { key: "files", label: "附件" },
  { key: "ai", label: "跟 AI 聊聊" },
];

const PRIORITY_CHIPS: { value: Priority; label: string; tone: string }[] = [
  { value: "normal", label: "常规", tone: "border-stone-300 bg-[#fffdf8] text-stone-700" },
  { value: "high", label: "重要", tone: "border-[#e0c895] bg-[#fff6dc] text-[#8a5d10]" },
  { value: "urgent", label: "紧急", tone: "border-[#e0b8ad] bg-[#fff0ec] text-[#9f4129]" },
  { value: "low", label: "随时", tone: "border-stone-200 bg-stone-50 text-stone-500" },
];

export function NewRequirement() {
  const { id: projectId } = useParams<{ id: string }>();
  const nav = useNavigate();

  const [step, setStep] = useState(0);
  const [desc, setDesc] = useState("");
  const [priority, setPriority] = useState<Priority>("normal");
  const [leadUserId, setLeadUserId] = useState<string | null>(null);
  const [collaboratorUserIds, setCollaboratorUserIds] = useState<string[]>([]);
  const [startAt, setStartAt] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [estimateHours, setEstimateHours] = useState("");
  const [estimateConfidence, setEstimateConfidence] = useState<"low" | "medium" | "high">("medium");
  const [reqId, setReqId] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canNext =
    (step === 0 && desc.trim().length > 0) ||
    step === 1 ||
    (step === 2 && !!dueAt) ||
    step === 3 ||
    step === 4;

  const goNext = async () => {
    setErr(null);
    // Validate per step
    if (step === 0 && !desc.trim()) {
      setErr("先写一下要做什么。");
      return;
    }
    if (step === 2 && !dueAt) {
      setErr("截止时间是这事情存在的前提，请先填上。");
      return;
    }
    // Create draft right after the due step (we have everything required).
    if (step === 2 && !reqId && projectId) {
      setBusy(true);
      try {
        const r = await api.createRequirement(projectId, {
          raw_description: desc.trim(),
          priority,
          lead_user_id: leadUserId,
          collaborator_user_ids: collaboratorUserIds,
          start_at: startAt ? new Date(startAt).toISOString() : null,
          due_at: dueAt ? new Date(dueAt).toISOString() : null,
          estimate_hours: estimateHours ? Number(estimateHours) : null,
          estimate_confidence: estimateHours ? estimateConfidence : null,
        });
        setReqId(r.id);
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

  const startClarify = () => {
    if (reqId) nav(`/r/${reqId}/clarify`);
  };

  return (
    <main className="narrow-container max-w-4xl">
      <p className="eyebrow">提一条新需求</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-stone-950">
        {STEPS[step].label}
      </h1>

      <div className="mt-6">
        <Stepper steps={STEPS} current={step} onJump={(i) => i <= step && setStep(i)} />
      </div>

      <section className="paper-surface mt-8 p-5 sm:p-6">
        {step === 0 && (
          <div className="space-y-4">
            <p className="text-sm text-stone-500">
              简单描述就行，下一步系统会帮你把细节问清楚。
            </p>
            <textarea
              className="textarea-field"
              rows={8}
              placeholder="比如：做一个团队周报模板，每周自动汇总每个人的进度…"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              autoFocus
            />
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <VoiceButton onText={(t) => setDesc((d) => (d ? d + " " : "") + t)} />
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-stone-500 mr-1">优先级</span>
                {PRIORITY_CHIPS.map((p) => (
                  <button
                    key={p.value}
                    type="button"
                    onClick={() => setPriority(p.value)}
                    className={`inline-flex h-7 items-center rounded-full border px-2.5 text-xs font-medium transition ${
                      priority === p.value ? p.tone : "border-stone-200 bg-white text-stone-500 hover:border-stone-300"
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
          <div className="space-y-4">
            <p className="text-sm text-stone-500">
              <Users className="inline h-4 w-4 mr-1 text-stone-400" aria-hidden="true" />
              你可以指定负责人 + 协作者，或留空让谁都能接。
            </p>
            <AssigneeSelector
              leadUserId={leadUserId}
              collaboratorUserIds={collaboratorUserIds}
              onChange={(next) => {
                setLeadUserId(next.leadUserId);
                setCollaboratorUserIds(next.collaboratorUserIds);
              }}
            />
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <p className="text-sm text-stone-500">
              <CalendarClock className="inline h-4 w-4 mr-1 text-stone-400" aria-hidden="true" />
              至少填截止时间。其它字段可以留空。
            </p>
            <div className="paper-panel p-4 grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="text-xs font-medium text-stone-500">预计开始（可选）</span>
                <input
                  className="field mt-1"
                  type="datetime-local"
                  value={startAt}
                  onChange={(e) => setStartAt(e.target.value)}
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-stone-500">截止时间（必填）</span>
                <input
                  className="field mt-1"
                  type="datetime-local"
                  value={dueAt}
                  onChange={(e) => setDueAt(e.target.value)}
                />
              </label>
            </div>
            <div className="paper-panel p-4 grid gap-3 sm:grid-cols-[1fr_180px]">
              <label className="block">
                <span className="text-xs font-medium text-stone-500">预计工时（可选）</span>
                <input
                  className="field mt-1"
                  type="number"
                  min="0"
                  step="0.5"
                  value={estimateHours}
                  onChange={(e) => setEstimateHours(e.target.value)}
                  placeholder="比如 6"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-stone-500">信心</span>
                <select
                  className="select-field mt-1"
                  value={estimateConfidence}
                  disabled={!estimateHours}
                  onChange={(e) => setEstimateConfidence(e.target.value as "low" | "medium" | "high")}
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
          <div className="space-y-4">
            <p className="text-sm text-stone-500">
              <Paperclip className="inline h-4 w-4 mr-1 text-stone-400" aria-hidden="true" />
              相关资料（可选）。有附件，AI 助理能问得更准。
            </p>
            {reqId ? (
              <>
                <FileUpload reqId={reqId} onUploaded={(a) => setAttachments((xs) => [...xs, a])} />
                {attachments.length > 0 && (
                  <ul className="paper-panel divide-y divide-stone-200/80 overflow-hidden">
                    {attachments.map((a) => (
                      <li key={a.id} className="flex items-center justify-between px-4 py-3 text-sm">
                        <span className="min-w-0 truncate">
                          <FileText className="mr-2 inline h-4 w-4 text-stone-400" aria-hidden="true" />
                          {a.filename}
                          <span className="ml-2 text-xs text-stone-400">{(a.size_bytes / 1024).toFixed(1)} KB</span>
                        </span>
                        {a.has_parsed_text && (
                          <span className="pill w-fit border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]">已解析</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <p className="text-sm text-stone-400">草稿还没创建，先回到上一步填截止时间。</p>
            )}
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <div className="paper-panel p-5 text-center">
              <Sparkles className="mx-auto h-10 w-10 text-[#684b7a]" aria-hidden="true" />
              <h2 className="mt-3 text-lg font-semibold text-stone-950">差不多了。</h2>
              <p className="mt-1 text-sm text-stone-500">
                接下来 AI 助理会跟你聊几轮，把需求打磨成一份清晰的描述，之后再投递给负责人或公开池。
              </p>
              <button className="button-accent mt-5" onClick={startClarify} disabled={!reqId}>
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                下一步：跟 AI 聊聊
              </button>
            </div>
          </div>
        )}

        {err && (
          <p className="mt-4 flex items-center gap-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" aria-hidden="true" />
            {err}
          </p>
        )}

        {step < 4 && (
          <div className="mt-6 flex items-center justify-between gap-3">
            <button className="button-secondary" disabled={step === 0 || busy} onClick={goBack}>
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              上一步
            </button>
            <button className="button-primary" disabled={!canNext || busy} onClick={goNext}>
              {busy ? "保存中…" : step === 2 && !reqId ? "保存并继续" : "下一步"}
              {!busy && <ArrowRight className="h-4 w-4" aria-hidden="true" />}
            </button>
          </div>
        )}
      </section>
    </main>
  );
}
