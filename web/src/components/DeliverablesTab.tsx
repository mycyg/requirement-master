import { useEffect, useState } from "react";
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

  if (!deliveries) return <div className="p-6 text-slate-500">加载中…</div>;
  if (deliveries.length === 0) {
    return <div className="rounded-lg border border-dashed border-slate-200 p-12 text-center text-slate-500">还没有交付物</div>;
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
        <div key={d.id} className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase text-slate-500">第 {d.round} 轮交付</div>
              <div className="mt-1 text-sm">
                <b>{d.submitted_by_nickname}</b>
                <span className="ml-2 text-slate-500">{new Date(d.created_at + "Z").toLocaleString("zh-CN")}</span>
              </div>
            </div>
            <a
              href={`/api/deliveries/${d.id}/package`}
              className="rounded bg-slate-900 px-4 py-2 text-xs text-white"
              download
            >
              ⬇ 下载整包 ({(d.package_size / 1024).toFixed(1)} KB)
            </a>
          </div>

          {d.delivery_doc_md && (
            <details open={idx === 0} className="mt-4">
              <summary className="cursor-pointer text-xs font-medium uppercase text-emerald-600">交付文档</summary>
              <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-4 text-sm leading-relaxed">{d.delivery_doc_md}</pre>
            </details>
          )}

          {d.files.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium uppercase text-slate-500">文件清单 ({d.files.length})</summary>
              <ul className="mt-2 space-y-1">
                {d.files.map((f) => (
                  <li key={f.name} className="flex items-center justify-between rounded px-2 py-1 text-sm hover:bg-slate-50">
                    <span className="font-mono">{f.name}</span>
                    <span className="flex items-center gap-3">
                      <span className="text-xs text-slate-400">{f.size}B</span>
                      <a
                        href={`/api/deliveries/${d.id}/files/${encodeURI(f.name)}`}
                        className="text-xs text-blue-600 hover:underline"
                        download
                      >
                        下载
                      </a>
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {idx === 0 && req.status === "delivered" && (
            <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
              <button
                className="rounded-lg bg-emerald-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-50"
                disabled={busy}
                onClick={accept}
              >
                ✅ 接受交付
              </button>
              <button
                className="rounded-lg bg-amber-500 px-5 py-2 text-sm font-medium text-white disabled:opacity-50"
                disabled={busy}
                onClick={() => setShowRevision((v) => !v)}
              >
                ↺ 申请返工
              </button>
              {showRevision && (
                <div className="mt-3 w-full">
                  <div className="flex gap-2">
                    <textarea
                      className="flex-1 rounded border border-slate-300 p-2 text-sm"
                      rows={3}
                      placeholder="说说哪里需要返工…（语音也行）"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                    <div className="flex flex-col gap-2">
                      <VoiceButton onText={(t) => setReason((s) => (s ? s + " " : "") + t)} />
                      <button
                        className="rounded bg-amber-500 px-3 py-1 text-xs text-white disabled:opacity-50"
                        disabled={!reason.trim() || busy}
                        onClick={submitRevision}
                      >
                        提交返工
                      </button>
                    </div>
                  </div>
                </div>
              )}
              {err && <div className="w-full text-sm text-red-600">{err}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
