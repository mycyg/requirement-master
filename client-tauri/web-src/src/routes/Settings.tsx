import { useEffect, useState } from "react";
import { HelpCircle } from "lucide-react";
import { Button, Card, Input, Switch, toast, useFirstRun, useTheme, type ThemeMode } from "@yqgl/shared";
import { invoke, resetClientTokenCache } from "@/lib/tauri";
import { AdminPanel } from "@/components/AdminPanel";

type Cfg = any;

export function Settings() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { mode, setMode } = useTheme();
  const { reset: resetTour } = useFirstRun();

  useEffect(() => {
    invoke<Cfg>("get_config")
      .then(setCfg)
      .catch((e) => setLoadErr(String(e)));
  }, []);

  if (loadErr) {
    return (
      <div className="flex-1 p-6">
        <h1 className="text-h2 text-ink mb-3">设置</h1>
        <div className="glass p-4 text-error">设置加载失败：{loadErr}</div>
      </div>
    );
  }
  if (!cfg) {
    return <div className="flex-1 p-6">加载中…</div>;
  }

  const save = async (patch: Record<string, any>) => {
    setBusy(true);
    try {
      const next = await invoke<Cfg>("set_config", { patch });
      setCfg(next);
      // If the user changed server endpoint, invalidate the cached base
      // URL in clientFetch — otherwise every direct-API page keeps
      // calling the OLD address until the app restarts.
      if (patch.server_ip != null || patch.server_port != null || patch.server_url != null
          || patch.server_scheme != null || patch.client_token != null) {
        resetClientTokenCache();
      }
      toast({ title: "已保存", tone: "success" });
    } catch (e: any) {
      toast({ title: "保存失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  return (
    <div className="flex-1 p-6 overflow-auto space-y-5 max-w-3xl">
      <h1 className="text-h2 text-ink">设置</h1>

      <Card>
        <h2 className="text-h4 text-ink mb-3">个人</h2>
        <label className="block">
          <span className="text-caption text-ink-muted">昵称</span>
          <Input
            defaultValue={cfg.nickname}
            onBlur={(e) => e.target.value !== cfg.nickname && save({ nickname: e.target.value })}
          />
        </label>
      </Card>

      <Card>
        <h2 className="text-h4 text-ink mb-3">接单状态</h2>
        <div className="flex gap-2">
          {(["free", "busy", "custom"] as const).map((s) => (
            <button
              key={s}
              onClick={() => save({ availability_status: s })}
              className={`h-9 px-3 rounded-sm text-body-sm border transition ${
                cfg.availability_status === s ? "bg-accent text-white border-accent" : "border-line text-ink-soft hover:border-accent/40"
              }`}
            >
              {s === "free" ? "空闲" : s === "busy" ? "忙碌" : "自定义"}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="text-h4 text-ink mb-3">外观</h2>
        <div className="flex gap-2">
          {(["auto", "light", "dark"] as ThemeMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`h-9 px-3 rounded-sm text-body-sm border transition ${
                mode === m ? "bg-accent text-white border-accent" : "border-line text-ink-soft hover:border-accent/40"
              }`}
            >
              {m === "auto" ? "跟随系统" : m === "light" ? "亮色" : "暗色"}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="text-h4 text-ink mb-3">同步</h2>
        <div className="space-y-3">
          <label className="block">
            <span className="text-caption text-ink-muted">需求工作目录</span>
            <Input
              defaultValue={cfg.sync_root}
              onBlur={(e) => e.target.value !== cfg.sync_root && save({ sync_root: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="text-caption text-ink-muted">项目网盘目录</span>
            <Input
              defaultValue={cfg.drive_sync_root}
              onBlur={(e) => e.target.value !== cfg.drive_sync_root && save({ drive_sync_root: e.target.value })}
            />
          </label>
          <div>
            <span className="text-caption text-ink-muted">网盘同步模式</span>
            <div className="flex gap-2 mt-1">
              {(["off", "download"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => save({ drive_sync_mode: m, drive_sync_enabled: m !== "off" })}
                  className={`h-9 px-3 rounded-sm text-body-sm border transition ${
                    cfg.drive_sync_mode === m ? "bg-accent text-white border-accent" : "border-line text-ink-soft hover:border-accent/40"
                  }`}
                >
                  {m === "off" ? "关" : "仅下载"}
                </button>
              ))}
            </div>
            <p className="mt-2 text-caption text-ink-muted">双向同步还在保险箱里打磨，当前版本先提供安全的单向下载。</p>
          </div>
          <Switch
            defaultChecked={cfg.drive_sync_paused}
            onChange={(e) => save({ drive_sync_paused: e.currentTarget.checked })}
            label="暂时停止同步"
          />
        </div>
      </Card>

      <Card>
        <h2 className="text-h4 text-ink mb-3">服务器</h2>
        <div className="grid grid-cols-[1fr_140px] gap-2">
          <Input
            defaultValue={cfg.server_ip}
            onBlur={(e) => e.target.value !== cfg.server_ip && save({ server_ip: e.target.value, server_url: "" })}
            prefixSlot="IP"
          />
          <Input
            defaultValue={String(cfg.server_port)}
            onBlur={(e) => {
              // Guard against NaN / out-of-range port — `Number("")` is 0,
              // `Number("abc")` is NaN. Either would write a garbage value
              // into config.json (serde NaN → null) and silently kill the
              // app's backend connection.
              const n = Number(e.target.value);
              if (!Number.isFinite(n) || n < 1 || n > 65535) {
                toast({ title: "端口必须是 1-65535 的整数", tone: "error" });
                e.target.value = String(cfg.server_port);
                return;
              }
              if (n !== cfg.server_port) save({ server_port: n, server_url: "" });
            }}
            prefixSlot=":"
          />
        </div>
        <div className="mt-2 text-caption text-ink-faint">
          当前：{cfg.server_url || `${cfg.server_scheme}://${cfg.server_ip}:${cfg.server_port}`}
        </div>
        <div className="mt-3">
          <Button
            variant="secondary"
            size="sm"
            loading={busy}
            onClick={async () => {
              try {
                const r = await invoke<{ ok: boolean; status: number }>("test_server");
                toast({ title: r.ok ? "连得通" : "连不上", tone: r.ok ? "success" : "error" });
              } catch (e: any) {
                toast({ title: "失败", description: String(e), tone: "error" });
              }
            }}
          >
            测试连接
          </Button>
        </div>
      </Card>

      <Card>
        <h2 className="text-h4 text-ink mb-3">帮助</h2>
        <Button
          variant="secondary"
          leftIcon={<HelpCircle className="h-4 w-4" />}
          onClick={() => {
            resetTour();
            // The App-level WelcomeTour is gated on `!tourSeen`, so
            // clearing the flag causes it to re-open on the next render.
            // Tell the user explicitly in case they're not on the Hub.
            toast({ title: "已重新打开引导，回主页就能看到", tone: "info" });
          }}
        >
          再看一遍新手引导
        </Button>
        <p className="mt-2 text-caption text-ink-faint">
          忘了某个概念怎么用？随时回头看一眼。
        </p>
      </Card>

      <Card>
        <h2 className="text-h4 text-ink mb-3">关于</h2>
        <div className="text-body-sm text-ink-soft space-y-1">
          <div>版本：0.2.0 · Aurora Glass</div>
          <div>配置文件：%APPDATA%\\yqgl\\config.json</div>
        </div>
      </Card>

      {/* AdminPanel returns null for non-admins, so this is invisible to most. */}
      <AdminPanel />
    </div>
  );
}
