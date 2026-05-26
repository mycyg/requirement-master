import { useState } from "react";

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
      <div className="w-[420px] rounded-xl bg-white p-8 shadow-2xl">
        <h2 className="text-xl font-semibold">填一个昵称</h2>
        <p className="mt-2 text-sm text-slate-500">仅用于在内网识别你；后续可以改。</p>
        <input
          autoFocus
          className="mt-5 w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-slate-900"
          value={value}
          placeholder="比如：阿吴 / 产品-小明"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        />
        {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
        <button
          className="mt-5 w-full rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
          disabled={busy || !value.trim()}
          onClick={submit}
        >
          {busy ? "进入中…" : "进入"}
        </button>
      </div>
    </div>
  );
}
