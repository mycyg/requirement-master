import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { FileUpload } from "@/components/FileUpload";
import { VoiceButton } from "@/components/VoiceButton";
import type { Attachment } from "@/lib/types";

export function NewRequirement() {
  const { id: projectId } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [desc, setDesc] = useState("");
  const [priority, setPriority] = useState("normal");
  const [reqId, setReqId] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const createDraft = async () => {
    if (!projectId || !desc.trim()) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.createRequirement(projectId, { raw_description: desc.trim(), priority });
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
    <main className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="text-3xl font-bold tracking-tight">提一个需求</h1>

      <section className="mt-8">
        <label className="text-sm font-medium">需求描述</label>
        <textarea
          className="mt-2 w-full rounded-lg border border-slate-300 p-4 outline-none focus:border-slate-900"
          rows={6}
          placeholder="写清楚你想要什么。可以先大致写，下一步 LLM 会反问澄清。"
          value={desc}
          disabled={!!reqId}
          onChange={(e) => setDesc(e.target.value)}
        />
        <div className="mt-2 flex items-center gap-3">
          <VoiceButton onText={(t) => setDesc((d) => (d ? d + " " : "") + t)} />
          <select
            className="rounded border border-slate-300 px-3 py-1 text-sm"
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

        {!reqId && (
          <button
            className="mt-5 rounded-lg bg-slate-900 px-5 py-2 text-white disabled:opacity-50"
            disabled={busy || !desc.trim()}
            onClick={createDraft}
          >
            {busy ? "创建中…" : "下一步：上传附件"}
          </button>
        )}
        {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
      </section>

      {reqId && (
        <section className="mt-10">
          <h2 className="text-lg font-semibold">附件（可选，但有附件会大幅提升 LLM 理解）</h2>
          <div className="mt-3">
            <FileUpload reqId={reqId} onUploaded={(a) => setAttachments((xs) => [...xs, a])} />
          </div>

          {attachments.length > 0 && (
            <ul className="mt-4 divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
              {attachments.map((a) => (
                <li key={a.id} className="flex items-center justify-between px-4 py-2 text-sm">
                  <span>{a.filename} <span className="ml-2 text-xs text-slate-400">{(a.size_bytes / 1024).toFixed(1)} KB</span></span>
                  {a.has_parsed_text && <span className="rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">已解析</span>}
                </li>
              ))}
            </ul>
          )}

          <button
            className="mt-6 rounded-lg bg-slate-900 px-5 py-2 text-white"
            onClick={startClarify}
          >
            完成 → 开始与 AI 澄清需求
          </button>
        </section>
      )}
    </main>
  );
}
