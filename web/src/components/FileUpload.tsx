import { useCallback, useState } from "react";
import { AlertCircle, UploadCloud } from "lucide-react";
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
    <label
      className="paper-panel block cursor-pointer border-2 border-dashed border-stone-300 p-6 text-center transition hover:border-stone-500 hover:bg-[#fffdf8]"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        upload(e.dataTransfer.files);
      }}
    >
      <input
        type="file"
        multiple
        className="hidden"
        onChange={(e) => upload(e.target.files)}
      />
      <UploadCloud className="mx-auto h-7 w-7 text-stone-400" aria-hidden="true" />
      <div className="mt-3 text-sm font-medium text-stone-700">
        {busy ? `上传中：${busy}...` : "点击或拖拽文件上传"}
      </div>
      <p className="mt-1 text-xs text-stone-500">支持 PDF / Word / Excel / 图片 / 文本 等</p>
      {err && (
        <div className="mt-3 inline-flex items-center gap-1.5 text-xs text-red-700">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          {err}
        </div>
      )}
    </label>
  );
}
