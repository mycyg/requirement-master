import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Comment } from "@/lib/types";
import { VoiceButton } from "@/components/VoiceButton";

export function CommentsPanel({ reqId }: { reqId: string }) {
  const [items, setItems] = useState<Comment[]>([]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () => api.listComments(reqId).then(setItems);
  useEffect(() => { refresh(); }, [reqId]);

  const send = async () => {
    if (!body.trim()) return;
    setBusy(true);
    try {
      await api.addComment(reqId, body.trim());
      setBody("");
      refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <ul className="space-y-3">
        {items.length === 0 && <li className="rounded border border-dashed border-slate-200 p-8 text-center text-sm text-slate-500">还没有评论</li>}
        {items.map((c) => (
          <li key={c.id} className="rounded-lg bg-white p-4 ring-1 ring-slate-200">
            <div className="text-xs">
              <b>{c.author_nickname}</b>
              <span className="ml-2 text-slate-400">{new Date(c.created_at + "Z").toLocaleString("zh-CN")}</span>
            </div>
            <div className="mt-2 whitespace-pre-wrap text-sm">{c.body}</div>
          </li>
        ))}
      </ul>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex gap-2">
          <textarea
            className="flex-1 rounded border border-slate-300 p-2 text-sm"
            rows={3}
            placeholder="写一条评论…"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex flex-col gap-2">
            <VoiceButton onText={(t) => setBody((s) => (s ? s + " " : "") + t)} />
            <button
              className="rounded bg-slate-900 px-3 py-1 text-xs text-white disabled:opacity-50"
              disabled={!body.trim() || busy}
              onClick={send}
            >
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
