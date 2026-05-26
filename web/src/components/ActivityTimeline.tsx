import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Activity } from "@/lib/types";

const ACTION_ZH: Record<string, string> = {
  created: "📝 创建需求",
  clarified: "✅ AI 完成澄清",
  submitted: "📤 投递",
  claimed: "🙋 接单",
  status_changed: "🔄 状态变更",
  commented: "💬 评论",
  file_added: "📎 上传附件",
  synced: "💾 客户端已同步",
  ai_started: "🤖 AI 开始处理",
  ai_delivered: "🤖 AI 交付",
  ai_failed: "❌ AI 翻车",
  accepted: "✅ 验收",
  revision_requested: "↺ 申请返工",
};

export function ActivityTimeline({ reqId }: { reqId: string }) {
  const [items, setItems] = useState<Activity[] | null>(null);

  useEffect(() => {
    api.listActivity(reqId).then(setItems);
  }, [reqId]);

  if (!items) return <div className="text-slate-500">加载中…</div>;
  if (items.length === 0) return <div className="text-slate-500">无活动记录</div>;

  return (
    <ol className="relative space-y-4 border-l-2 border-slate-200 pl-5">
      {items.map((a) => {
        let detail: any = null;
        try { detail = a.detail_json ? JSON.parse(a.detail_json) : null; } catch { /* ignore */ }
        return (
          <li key={a.id} className="relative">
            <span className="absolute -left-[27px] top-1 inline-block h-3 w-3 rounded-full bg-slate-300 ring-4 ring-white" />
            <div className="text-sm">
              <span className="font-medium">{ACTION_ZH[a.action] ?? a.action}</span>
              <span className="ml-2 text-xs text-slate-500">by <b>{a.actor_nickname}</b></span>
              <span className="ml-2 text-xs text-slate-400">{new Date(a.created_at + "Z").toLocaleString("zh-CN")}</span>
            </div>
            {detail && Object.keys(detail).length > 0 && (
              <pre className="mt-1 whitespace-pre-wrap text-xs text-slate-500">{JSON.stringify(detail, null, 2)}</pre>
            )}
          </li>
        );
      })}
    </ol>
  );
}
