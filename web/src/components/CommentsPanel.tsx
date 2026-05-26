import { useEffect, useState } from "react";
import { AlertCircle, MessageSquare, Send } from "lucide-react";
import { api } from "@/lib/api";
import type { Comment } from "@/lib/types";
import { VoiceButton } from "@/components/VoiceButton";

export function CommentsPanel({ reqId }: { reqId: string }) {
  const [items, setItems] = useState<Comment[]>([]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = () => api.listComments(reqId).then(setItems);
  useEffect(() => { refresh(); }, [reqId]);

  const send = async () => {
    if (!body.trim()) return;
    setBusy(true); setErr(null);
    try {
      await api.addComment(reqId, body.trim());
      setBody("");
      refresh();
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <ul className="space-y-3">
        {items.length === 0 && <li className="empty-state">还没有评论</li>}
        {items.map((c) => (
          <li key={c.id} className="paper-surface p-4">
            <div className="text-xs">
              <b className="text-stone-900">{c.author_nickname}</b>
              <span className="ml-2 text-stone-400">{new Date(c.created_at + "Z").toLocaleString("zh-CN")}</span>
            </div>
            <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-stone-700">{c.body}</div>
          </li>
        ))}
      </ul>

      <div className="paper-surface p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-stone-900">
          <MessageSquare className="h-4 w-4 text-stone-500" aria-hidden="true" />
          添加评论
        </div>
        <div className="flex flex-col gap-3 lg:flex-row">
          <textarea
            className="textarea-field min-h-24 flex-1"
            rows={3}
            placeholder="写一条评论..."
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex flex-col gap-2 sm:flex-row lg:w-36 lg:flex-col">
            <VoiceButton onText={(t) => setBody((s) => (s ? s + " " : "") + t)} />
            <button
              className="button-primary min-h-9 px-3 py-1.5 text-xs"
              disabled={!body.trim() || busy}
              onClick={send}
            >
              <Send className="h-3.5 w-3.5" aria-hidden="true" />
              发送
            </button>
          </div>
        </div>
        {err && (
          <p className="mt-3 flex items-center gap-2 text-xs text-red-700">
            <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
            {err}
          </p>
        )}
      </div>
    </div>
  );
}
