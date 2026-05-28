import { useEffect, useState } from "react";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  ClipboardCheck,
  FileUp,
  MessageSquare,
  RefreshCw,
  RotateCcw,
  Send,
  UserCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "@/lib/api";
import type { Activity } from "@/lib/types";

const ACTION_META: Record<string, { label: string; Icon: LucideIcon }> = {
  created: { label: "创建需求", Icon: ClipboardCheck },
  clarified: { label: "AI 完成澄清", Icon: CheckCircle2 },
  submitted: { label: "投递", Icon: Send },
  claimed: { label: "接单", Icon: UserCheck },
  status_changed: { label: "状态变更", Icon: RefreshCw },
  commented: { label: "评论", Icon: MessageSquare },
  file_added: { label: "上传附件", Icon: FileUp },
  synced: { label: "客户端已同步", Icon: CheckCircle2 },
  ai_started: { label: "AI 开始处理", Icon: Bot },
  ai_delivered: { label: "AI 交付", Icon: Bot },
  ai_failed: { label: "AI 处理失败", Icon: CircleAlert },
  accepted: { label: "验收", Icon: CheckCircle2 },
  revision_requested: { label: "申请返工", Icon: RotateCcw },
};

export function ActivityTimeline({ reqId }: { reqId: string }) {
  const [items, setItems] = useState<Activity[] | null>(null);

  useEffect(() => {
    api.listActivity(reqId).then(setItems);
  }, [reqId]);

  if (!items) return <div className="text-stone-500">加载中…</div>;
  if (items.length === 0) return <div className="empty-state">还没有动态。</div>;

  return (
    <ol className="relative space-y-4 border-l border-stone-300 pl-6">
      {items.map((a) => {
        let detail: any = null;
        try { detail = a.detail_json ? JSON.parse(a.detail_json) : null; } catch { /* ignore */ }
        const meta = ACTION_META[a.action] ?? { label: a.action, Icon: RefreshCw };
        const Icon = meta.Icon;
        return (
          <li key={a.id} className="relative">
            <span className="absolute -left-[35px] top-0.5 grid h-5 w-5 place-items-center rounded-full border border-stone-300 bg-[#fffdf8] ring-4 ring-[#f7f5ef]">
              <Icon className="h-3 w-3 text-stone-500" aria-hidden="true" />
            </span>
            <div className="text-sm">
              <span className="font-semibold text-stone-900">{meta.label}</span>
              <span className="ml-2 text-xs text-stone-500">by <b>{a.actor_nickname}</b></span>
              <span className="ml-2 text-xs text-stone-400">{new Date(a.created_at + "Z").toLocaleString("zh-CN")}</span>
            </div>
            {detail && Object.keys(detail).length > 0 && (
              <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-[#fffdf8] p-3 text-xs text-stone-500">{JSON.stringify(detail, null, 2)}</pre>
            )}
          </li>
        );
      })}
    </ol>
  );
}
