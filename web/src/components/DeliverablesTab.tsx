import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Download, FileText, Package, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import type { Delivery, Requirement } from "@/lib/types";
import { VoiceButton } from "@/components/VoiceButton";

export function DeliverablesTab({ req, onChange }: { req: Requirement; onChange: () => void }) {
  const [deliveries, setDeliveries] = useState<Delivery[] | null>(null);
  const [showRevision, setShowRevision] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = () => api.listDeliveries(req.id).then(setDeliveries).catch((e) => setErr(String(e)));
  useEffect(() => { refresh(); }, [req.id, req.status]);

  if (!deliveries && err) {
    return (
      <div className="empty-state flex items-center justify-center gap-2 text-red-700">
        <AlertCircle className="h-4 w-4" aria-hidden="true" />
        {err}
      </div>
    );
  }
  if (!deliveries) return <div className="p-6 text-stone-500">加载中...</div>;
  if (deliveries.length === 0) {
    return <div className="empty-state">还没有交付物</div>;
  }

  const accept = async () => {
    setBusy(true); setErr(null);
    try {
      await api.acceptDelivery(req.id);
      onChange();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const submitRevision = async () => {
    if (!reason.trim()) return;
    setBusy(true); setErr(null);
    try {
      await api.requestRevision(req.id, reason.trim());
      setShowRevision(false);
      setReason("");
      onChange();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      {deliveries.map((d, idx) => (
        <div key={d.id} className="paper-surface p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">
                <Package className="h-4 w-4" aria-hidden="true" />
                第 {d.round} 轮交付
              </div>
              <div className="mt-1 text-sm">
                <b className="text-stone-900">{d.submitted_by_nickname}</b>
                <span className="ml-2 text-stone-500">{new Date(d.created_at + "Z").toLocaleString("zh-CN")}</span>
              </div>
            </div>
            <a
              href={`/api/deliveries/${d.id}/package`}
              className="button-primary min-h-9 px-3 py-1.5 text-xs"
              download
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              下载整包 ({(d.package_size / 1024).toFixed(1)} KB)
            </a>
          </div>

          {d.delivery_doc_md && (
            <details open={idx === 0} className="mt-4">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.12em] text-[#4e7146]">
                <FileText className="mr-1.5 inline h-3.5 w-3.5" aria-hidden="true" />
                交付文档
              </summary>
              <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffaf1] p-4 text-sm leading-relaxed text-stone-700">{d.delivery_doc_md}</pre>
            </details>
          )}

          {d.files.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">文件清单 ({d.files.length})</summary>
              <ul className="mt-2 space-y-1">
                {d.files.map((f) => (
                  <li key={f.name} className="flex flex-col gap-2 rounded-lg px-2 py-2 text-sm hover:bg-stone-900/5 sm:flex-row sm:items-center sm:justify-between">
                    <span className="min-w-0 break-all font-mono">{f.name}</span>
                    <span className="flex shrink-0 items-center gap-3">
                      <span className="text-xs text-stone-400">{f.size}B</span>
                      <a
                        href={`/api/deliveries/${d.id}/files/${encodeURI(f.name)}`}
                        className="link-subtle text-xs text-[#405f78]"
                        download
                      >
                        <Download className="h-3.5 w-3.5" aria-hidden="true" />
                        下载
                      </a>
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {idx === 0 && req.status === "delivered" && (
            <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-stone-200 pt-4">
              <button
                className="button border-[#4e7146] bg-[#5f8358] text-white hover:bg-[#4e7146]"
                disabled={busy}
                onClick={accept}
              >
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                接受交付
              </button>
              <button
                className="button-accent"
                disabled={busy}
                onClick={() => setShowRevision((v) => !v)}
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                申请返工
              </button>
              {showRevision && (
                <div className="mt-3 w-full">
                  <div className="flex flex-col gap-3 lg:flex-row">
                    <textarea
                      className="textarea-field min-h-24 flex-1"
                      rows={3}
                      placeholder="说说哪里需要返工...（语音也行）"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                    <div className="flex flex-col gap-2 sm:flex-row lg:w-36 lg:flex-col">
                      <VoiceButton onText={(t) => setReason((s) => (s ? s + " " : "") + t)} />
                      <button
                        className="button-accent min-h-9 px-3 py-1.5 text-xs"
                        disabled={!reason.trim() || busy}
                        onClick={submitRevision}
                      >
                        提交返工
                      </button>
                    </div>
                  </div>
                </div>
              )}
              {err && (
                <div className="flex w-full items-center gap-2 text-sm text-red-700">
                  <AlertCircle className="h-4 w-4" aria-hidden="true" />
                  {err}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
