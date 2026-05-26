import { useState } from "react";
import { ArrowRight, UserRound } from "lucide-react";

export function NicknameDialog({ onSubmit }: { onSubmit: (nickname: string) => Promise<void> | void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    if (!value.trim()) return;
    setBusy(true); setErr(null);
    try {
      await onSubmit(value.trim());
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-950/35 px-4 backdrop-blur-sm">
      <div className="paper-surface w-full max-w-[420px] p-6 sm:p-8">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg border border-stone-300 bg-stone-950 text-[#fffdf8]">
            <UserRound className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-xl font-semibold text-stone-950">填一个昵称</h2>
            <p className="mt-1 text-sm text-stone-500">仅用于在内网识别你；后续可以改。</p>
          </div>
        </div>
        <input
          autoFocus
          className="field mt-5"
          value={value}
          placeholder="比如：阿吴 / 产品-小明"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        />
        {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
        <button
          className="button-primary mt-5 w-full"
          disabled={busy || !value.trim()}
          onClick={submit}
        >
          {busy ? "进入中..." : "进入"}
          {!busy && <ArrowRight className="h-4 w-4" aria-hidden="true" />}
        </button>
      </div>
    </div>
  );
}
