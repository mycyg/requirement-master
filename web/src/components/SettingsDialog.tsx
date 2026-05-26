import { useEffect, useState } from "react";
import { useSettings } from "@/hooks/useSettings";

type VoicesResp = { ready: boolean; voices: string[]; default: string | null };

const VOICE_LABEL: Record<string, string> = {
  male: "男声 · male",
  yujie: "御姐 · yujie",
  xiaoguang: "小光 · xiaoguang",
};

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { settings, update } = useSettings();
  const [voices, setVoices] = useState<string[]>([]);
  const [voicesErr, setVoicesErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    fetch("/api/voice/voices", { credentials: "include" })
      .then((r) => r.json() as Promise<VoicesResp>)
      .then((d) => {
        if (d.ready) setVoices(d.voices);
        else setVoicesErr("TTS 服务不可用");
      })
      .catch((e) => setVoicesErr(String(e)));
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[460px] rounded-xl bg-white p-7 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-baseline justify-between">
          <h2 className="text-xl font-semibold">设置</h2>
          <button className="text-sm text-slate-400" onClick={onClose}>关闭</button>
        </div>

        <section className="mt-6 space-y-4">
          <label className="flex items-center justify-between">
            <div>
              <div className="font-medium">自动朗读 AI 消息</div>
              <p className="text-xs text-slate-500">AI 每次反问 / 总结时自动播放语音。</p>
            </div>
            <input
              type="checkbox"
              className="h-5 w-5 accent-slate-900"
              checked={settings.ttsAutoplay}
              onChange={(e) => update({ ttsAutoplay: e.target.checked })}
            />
          </label>

          <div>
            <div className="font-medium">TTS 音色</div>
            {voicesErr ? (
              <p className="mt-1 text-xs text-red-600">{voicesErr}</p>
            ) : (
              <div className="mt-2 space-y-1">
                {voices.length === 0 && <p className="text-xs text-slate-400">加载中…</p>}
                {voices.map((v) => (
                  <label key={v} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-slate-50">
                    <input
                      type="radio"
                      name="voice"
                      value={v}
                      checked={settings.ttsVoice === v}
                      onChange={() => update({ ttsVoice: v })}
                    />
                    <span className="text-sm">{VOICE_LABEL[v] ?? v}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
