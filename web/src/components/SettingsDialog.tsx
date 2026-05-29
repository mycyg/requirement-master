import { useEffect, useState } from "react";
import { HelpCircle, Settings, UserRound, Volume2, X } from "lucide-react";
import { api } from "@/lib/api";
import { useSettings } from "@/hooks/useSettings";

type VoicesResp = { ready: boolean; voices: string[]; default: string | null; error?: string };

const VOICE_LABEL: Record<string, string> = {
  male: "男声 · male",
  yujie: "御姐 · yujie",
  xiaoguang: "小光 · xiaoguang",
};

export function SettingsDialog({
  open,
  onClose,
  onShowWelcome,
}: {
  open: boolean;
  onClose: () => void;
  /** Re-open the first-run welcome tour. Settings closes itself first. */
  onShowWelcome?: () => void;
}) {
  const { settings, update } = useSettings();
  const [voices, setVoices] = useState<string[]>([]);
  const [voicesErr, setVoicesErr] = useState<string | null>(null);
  const [voicesLoaded, setVoicesLoaded] = useState(false);
  const [availabilityStatus, setAvailabilityStatus] = useState<"free" | "busy" | "custom">("free");
  const [availabilityText, setAvailabilityText] = useState("");
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setVoicesErr(null);
    setVoices([]);
    setVoicesLoaded(false);
    let alive = true;
    (async () => {
      try {
        const r = await fetch("/api/voice/voices", { credentials: "include" });
        const text = await r.text();
        if (!alive) return;
        if (!r.ok) {
          setVoicesErr("无法读取 TTS 音色，服务可能没启动。");
          return;
        }
        if (!text.trim()) {
          setVoicesErr("无法读取 TTS 音色，接口返回为空。");
          return;
        }
        let d: VoicesResp;
        try {
          d = JSON.parse(text) as VoicesResp;
        } catch {
          setVoicesErr("无法读取 TTS 音色，接口返回格式异常。");
          return;
        }
        if (d.ready) setVoices(Array.isArray(d.voices) ? d.voices : []);
        else setVoicesErr("无法读取 TTS 音色，服务可能没启动。");
      } catch {
        if (alive) setVoicesErr("无法读取 TTS 音色，服务可能没启动。");
      } finally {
        // Mark the fetch settled so the UI can distinguish "still loading"
        // from "loaded but the server returned an empty voice list" — the
        // latter previously showed a permanent "加载中…".
        if (alive) setVoicesLoaded(true);
      }
    })();
    return () => { alive = false; };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-950/35 px-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="paper-surface max-h-[90vh] w-full max-w-[460px] overflow-auto p-6 sm:p-7 scrollbar-thin-warm"
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
          <div className="paper-panel p-4">
            <div className="flex items-center gap-2 font-semibold text-stone-900">
              <UserRound className="h-4 w-4 text-stone-500" aria-hidden="true" />
              接单状态
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2">
              {[
                ["free", "空闲"],
                ["busy", "忙碌"],
                ["custom", "其他"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  className={`button min-h-9 px-2 py-1 text-xs ${availabilityStatus === value ? "border-stone-950 bg-stone-950 text-[#fffdf8]" : "border-stone-300 bg-[#fffdf8] text-stone-700"}`}
                  onClick={() => setAvailabilityStatus(value as "free" | "busy" | "custom")}
                >
                  {label}
                </button>
              ))}
            </div>
            <input
              className="field mt-3"
              placeholder={availabilityStatus === "custom" ? "比如：开会中，但可以接急活" : "可选备注"}
              value={availabilityText}
              onChange={(e) => setAvailabilityText(e.target.value)}
            />
            <button
              className="button-secondary mt-3 min-h-9 px-3 py-1.5 text-xs"
              disabled={statusBusy}
              onClick={async () => {
                if (statusBusy) return;
                setStatusBusy(true);
                setStatusMsg(null);
                try {
                  await api.updateMyStatus({ availability_status: availabilityStatus, availability_text: availabilityText || null });
                  setStatusMsg("状态已更新");
                } catch (e: any) {
                  setStatusMsg(String(e));
                } finally {
                  setStatusBusy(false);
                }
              }}
            >
              {statusBusy ? "保存中..." : "保存接单状态"}
            </button>
            {statusMsg && <p className="mt-2 text-xs text-stone-500">{statusMsg}</p>}
          </div>

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

          {onShowWelcome && (
            <button
              type="button"
              onClick={onShowWelcome}
              className="paper-panel flex w-full items-center justify-between gap-4 p-4 text-left transition hover:bg-stone-50"
            >
              <div>
                <div className="flex items-center gap-2 font-semibold text-stone-900">
                  <HelpCircle className="h-4 w-4 text-stone-500" aria-hidden="true" />
                  再看一遍新手引导
                </div>
                <p className="mt-1 text-xs text-stone-500">忘了某个概念怎么用？随时回头看一遍。</p>
              </div>
              <span className="text-xs text-stone-400">打开 →</span>
            </button>
          )}

          <div className="paper-panel p-4">
            <div className="flex items-center gap-2 font-semibold text-stone-900">
              <Volume2 className="h-4 w-4 text-stone-500" aria-hidden="true" />
              TTS 音色
            </div>
            {voicesErr ? (
              <p className="mt-2 text-xs text-red-700">{voicesErr}</p>
            ) : (
              <div className="mt-2 space-y-1">
                {voices.length === 0 && (
                  <p className="text-xs text-stone-400">{voicesLoaded ? "暂无可用音色" : "加载中…"}</p>
                )}
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
