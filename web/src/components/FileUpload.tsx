import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import type { Attachment } from "@/lib/types";

export function FileUpload({ reqId, onUploaded }: { reqId: string; onUploaded: (a: Attachment) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const upload = useCallback(async (files: FileList | null) => {
    if (!files || !files.length) return;
    setErr(null);
    for (const f of Array.from(files)) {
      setBusy(f.name);
      try {
        const att = await api.uploadSimple(reqId, f);
        onUploaded(att);
      } catch (e: any) {
        setErr(String(e));
        break;
      }
    }
    setBusy(null);
  }, [reqId, onUploaded]);

  return (
    <label className="block cursor-pointer rounded-lg border-2 border-dashed border-slate-300 p-6 text-center hover:border-slate-500">
      <input
        type="file"
        multiple
        className="hidden"
        onChange={(e) => upload(e.target.files)}
      />
      <div className="text-sm text-slate-600">
        {busy ? `上传中：${busy}…` : "点击或拖拽文件上传（支持 PDF / Word / Excel / 图片 / 文本 等）"}
      </div>
      {err && <div className="mt-2 text-xs text-red-600">{err}</div>}
    </label>
  );
}
