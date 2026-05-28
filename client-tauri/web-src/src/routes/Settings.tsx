import { useEffect, useState } from "react";
import { Button, Card, Input, Switch, toast, useTheme, type ThemeMode } from "@yqgl/shared";
import { invoke } from "@/lib/tauri";
import { AdminPanel } from "@/components/AdminPanel";

type Cfg = any;

export function Settings() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [busy, setBusy] = useState(false);
  const { mode, setMode } = useTheme();

  useEffect(() => {
    invoke<Cfg>("get_config").then(setCfg).catch(() => {});
  }, []);

  if (!cfg) {
    return <div className="flex-1 p-6">加载中…</div>;
  }

  const save = async (patch: Record<string, any>) => {
    setBusy(true);
    try {
      const next = await invoke<Cfg>("set_config", { patch });
      setCfg(next);
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
              {(["off", "download", "two_way"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => save({ drive_sync_mode: m, drive_sync_enabled: m !== "off" })}
                  className={`h-9 px-3 rounded-sm text-body-sm border transition ${
                    cfg.drive_sync_mode === m ? "bg-accent text-white border-accent" : "border-line text-ink-soft hover:border-accent/40"
                  }`}
                >
                  {m === "off" ? "关" : m === "download" ? "仅下载" : "双向"}
                </button>
              ))}
            </div>
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
            onBlur={(e) => Number(e.target.value) !== cfg.server_port && save({ server_port: Number(e.target.value), server_url: "" })}
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
