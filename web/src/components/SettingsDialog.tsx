import { useEffect, useState } from "react";
import { Settings, Volume2, X } from "lucide-react";
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
    setVoicesErr(null);
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-950/35 px-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="paper-surface w-full max-w-[460px] p-6 sm:p-7"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 text-stone-500" aria-hidden="true" />
            <h2 className="text-xl font-semibold text-stone-950">设置</h2>
          </div>
          <button className="button-ghost min-h-9 w-9 px-0" aria-label="关闭设置" onClick={onClose}>
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <section className="mt-6 space-y-4">
          <label className="paper-panel flex cursor-pointer items-center justify-between gap-4 p-4">
            <div>
              <div className="font-semibold text-stone-900">自动朗读 AI 消息</div>
              <p className="text-xs text-stone-500">AI 每次反问 / 总结时自动播放语音。</p>
            </div>
            <input
              type="checkbox"
              className="h-5 w-5 accent-stone-950"
              checked={settings.ttsAutoplay}
              onChange={(e) => update({ ttsAutoplay: e.target.checked })}
            />
          </label>

          <div className="paper-panel p-4">
            <div className="flex items-center gap-2 font-semibold text-stone-900">
              <Volume2 className="h-4 w-4 text-stone-500" aria-hidden="true" />
              TTS 音色
            </div>
            {voicesErr ? (
              <p className="mt-2 text-xs text-red-700">{voicesErr}</p>
            ) : (
              <div className="mt-2 space-y-1">
                {voices.length === 0 && <p className="text-xs text-stone-400">加载中...</p>}
                {voices.map((v) => (
                  <label key={v} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 hover:bg-stone-900/5">
                    <input
                      type="radio"
                      name="voice"
                      value={v}
                      checked={settings.ttsVoice === v}
                      onChange={() => update({ ttsVoice: v })}
                    />
                    <span className="text-sm text-stone-700">{VOICE_LABEL[v] ?? v}</span>
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
