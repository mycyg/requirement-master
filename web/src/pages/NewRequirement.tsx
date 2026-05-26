import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertCircle, ArrowRight, CheckCircle2, FileText, Paperclip } from "lucide-react";
import { api } from "@/lib/api";
import { AssigneeSelector } from "@/components/AssigneeSelector";
import { FileUpload } from "@/components/FileUpload";
import { VoiceButton } from "@/components/VoiceButton";
import type { Attachment } from "@/lib/types";

export function NewRequirement() {
  const { id: projectId } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [desc, setDesc] = useState("");
  const [priority, setPriority] = useState("normal");
  const [leadUserId, setLeadUserId] = useState<string | null>(null);
  const [collaboratorUserIds, setCollaboratorUserIds] = useState<string[]>([]);
  const [reqId, setReqId] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const createDraft = async () => {
    if (!projectId || !desc.trim()) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.createRequirement(projectId, {
        raw_description: desc.trim(),
        priority,
        lead_user_id: leadUserId,
        collaborator_user_ids: collaboratorUserIds,
      });
      setReqId(r.id);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const startClarify = () => {
    if (reqId) nav(`/r/${reqId}/clarify`);
  };

  return (
    <main className="narrow-container max-w-4xl">
      <p className="eyebrow">New Requirement</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-stone-950">提一个需求</h1>

      <section className="paper-surface mt-8 p-5 sm:p-6">
        <label className="text-sm font-semibold text-stone-900">需求描述</label>
        <textarea
          className="textarea-field mt-2"
          rows={6}
          placeholder="写清楚你想要什么。可以先大致写，下一步 LLM 会反问澄清。"
          value={desc}
          disabled={!!reqId}
          onChange={(e) => setDesc(e.target.value)}
        />
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <VoiceButton onText={(t) => setDesc((d) => (d ? d + " " : "") + t)} />
          <select
            className="select-field sm:w-48"
            value={priority}
            disabled={!!reqId}
            onChange={(e) => setPriority(e.target.value)}
          >
            <option value="low">优先级：低</option>
            <option value="normal">优先级：中</option>
            <option value="high">优先级：高</option>
            <option value="urgent">优先级：紧急</option>
          </select>
        </div>

        <div className="mt-5">
          <AssigneeSelector
            leadUserId={leadUserId}
            collaboratorUserIds={collaboratorUserIds}
            disabled={!!reqId}
            onChange={(next) => {
              setLeadUserId(next.leadUserId);
              setCollaboratorUserIds(next.collaboratorUserIds);
            }}
          />
        </div>

        {!reqId && (
          <button
            className="button-primary mt-5 w-full sm:w-auto"
            disabled={busy || !desc.trim()}
            onClick={createDraft}
          >
            {busy ? "创建中..." : "下一步：上传附件"}
            {!busy && <ArrowRight className="h-4 w-4" aria-hidden="true" />}
          </button>
        )}
        {err && (
          <p className="mt-3 flex items-center gap-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" aria-hidden="true" />
            {err}
          </p>
        )}
      </section>

      {reqId && (
        <section className="mt-8">
          <div className="flex items-center gap-2">
            <Paperclip className="h-5 w-5 text-stone-500" aria-hidden="true" />
            <h2 className="text-lg font-semibold text-stone-950">附件（可选，但有附件会大幅提升 LLM 理解）</h2>
          </div>
          <div className="mt-3">
            <FileUpload reqId={reqId} onUploaded={(a) => setAttachments((xs) => [...xs, a])} />
          </div>

          {attachments.length > 0 && (
            <ul className="paper-surface mt-4 divide-y divide-stone-200/80 overflow-hidden">
              {attachments.map((a) => (
                <li key={a.id} className="flex flex-col gap-2 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                  <span className="min-w-0 truncate">
                    <FileText className="mr-2 inline h-4 w-4 text-stone-400" aria-hidden="true" />
                    {a.filename}
                    <span className="ml-2 text-xs text-stone-400">{(a.size_bytes / 1024).toFixed(1)} KB</span>
                  </span>
                  {a.has_parsed_text && <span className="pill w-fit border-[#bdd2b7] bg-[#f1f7ed] text-[#4e7146]">已解析</span>}
                </li>
              ))}
            </ul>
          )}

          <button
            className="button-accent mt-6 w-full sm:w-auto"
            onClick={startClarify}
          >
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            完成，开始与 AI 澄清需求
          </button>
        </section>
      )}
    </main>
  );
}
