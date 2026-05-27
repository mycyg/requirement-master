import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Check, FolderOpen, ServerCog, Sparkles, UserRound, XCircle } from "lucide-react";
import { Button, Card, Input, Stepper, toast } from "@yqgl/shared";
import { invoke } from "@/lib/tauri";

const STEPS = [
  { key: "server", label: "服务地址" },
  { key: "me", label: "我是谁" },
  { key: "fs", label: "文件放哪" },
  { key: "done", label: "完成" },
];

export function Onboarding() {
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [ip, setIp] = useState("192.168.0.224");
  const [port, setPort] = useState("8080");
  const [serverOk, setServerOk] = useState<boolean | null>(null);
  const [nickname, setNickname] = useState("");
  const [syncRoot, setSyncRoot] = useState("D:\\工作需求");
  const [driveMode, setDriveMode] = useState<"off" | "download" | "two_way">("download");
  const [busy, setBusy] = useState(false);

  const testServer = async () => {
    setBusy(true);
    try {
      await invoke("set_config", { patch: { server_ip: ip, server_port: Number(port) } });
      const r = await invoke<{ ok: boolean; status: number }>("test_server");
      setServerOk(r.ok);
      if (r.ok) toast({ title: `已连接 ${ip}:${port}`, tone: "success" });
      else toast({ title: `连接失败 (HTTP ${r.status})`, tone: "error" });
    } catch (e: any) {
      setServerOk(false);
      toast({ title: "连接失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const identifyAndRegister = async () => {
    setBusy(true);
    try {
      const id = await invoke<{ id: string; nickname: string }>("identify", { nickname: nickname.trim() });
      await invoke("set_config", { patch: { nickname: id.nickname } });
      await invoke("register_device", { deviceName: window.navigator.platform });
      toast({ title: `欢迎，${id.nickname}`, tone: "success" });
      setStep(2);
    } catch (e: any) {
      toast({ title: "登录失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const finalize = async () => {
    setBusy(true);
    try {
      await invoke("set_config", { patch: {
        sync_root: syncRoot,
        drive_sync_root: `${syncRoot}\\项目网盘`,
        drive_sync_mode: driveMode,
        drive_sync_enabled: driveMode !== "off",
      }});
      setStep(3);
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen grid place-items-center p-6 pt-12">
      <Card variant="glass-strong" padding="lg" className="w-full max-w-2xl">
        <div className="text-center mb-6">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-pill bg-gradient-to-br from-[#6B5BFF] to-[#FF6E8E] text-white shadow-e2 mb-3">
            <Sparkles className="h-6 w-6" />
          </div>
          <h1 className="text-h1 text-ink">欢迎来到需求管理大师</h1>
          <p className="text-body-sm text-ink-muted mt-1">4 步把客户端连上服务器，开始接单。</p>
        </div>

        <Stepper steps={STEPS} current={step} />

        <div className="mt-6 min-h-[280px]">
          {step === 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-ink"><ServerCog className="h-4 w-4" /> 服务地址</div>
              <div className="grid grid-cols-[1fr_140px] gap-2">
                <Input prefixSlot="IP" value={ip} onChange={(e) => setIp(e.target.value)} />
                <Input prefixSlot=":" value={port} onChange={(e) => setPort(e.target.value)} />
              </div>
              <Button onClick={testServer} loading={busy} variant="secondary">测试连接</Button>
              {serverOk === true && (
                <div className="text-success text-body-sm inline-flex items-center gap-1.5">
                  <Check className="h-4 w-4" /> 服务器可达
                </div>
              )}
              {serverOk === false && (
                <div className="text-error text-body-sm inline-flex items-center gap-1.5">
                  <XCircle className="h-4 w-4" /> 连不上，检查 IP/端口/防火墙
                </div>
              )}
              <div className="pt-3 flex justify-end">
                <Button disabled={!serverOk} onClick={() => setStep(1)}>下一步</Button>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-ink"><UserRound className="h-4 w-4" /> 我是谁</div>
              <Input placeholder="昵称（用作团队识别）" value={nickname} onChange={(e) => setNickname(e.target.value)} />
              <div className="text-caption text-ink-faint">
                第一次使用会创建账号；如果团队里已经有这个昵称，会直接登录到那个账号。
              </div>
              <div className="pt-3 flex justify-between">
                <Button variant="secondary" onClick={() => setStep(0)}>上一步</Button>
                <Button disabled={!nickname.trim()} loading={busy} onClick={identifyAndRegister}>下一步</Button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-ink"><FolderOpen className="h-4 w-4" /> 文件放哪</div>
              <label className="block">
                <span className="text-caption text-ink-muted">本地工作目录</span>
                <Input value={syncRoot} onChange={(e) => setSyncRoot(e.target.value)} />
              </label>
              <div>
                <span className="text-caption text-ink-muted">项目网盘同步</span>
                <div className="flex gap-2 mt-1">
                  {(["off", "download", "two_way"] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setDriveMode(m)}
                      className={`h-9 px-3 rounded-sm text-body-sm border transition ${
                        driveMode === m ? "bg-accent text-white border-accent" : "border-line text-ink-soft hover:border-accent/40"
                      }`}
                    >
                      {m === "off" ? "关" : m === "download" ? "仅下载" : "双向同步"}
                    </button>
                  ))}
                </div>
              </div>
              <div className="pt-3 flex justify-between">
                <Button variant="secondary" onClick={() => setStep(1)}>上一步</Button>
                <Button loading={busy} onClick={finalize}>下一步</Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3 text-center py-4">
              <CheckCircle2 className="mx-auto h-12 w-12 text-success" />
              <h2 className="text-h3 text-ink">全部就绪</h2>
              <ul className="inline-block text-left text-body-sm text-ink-soft space-y-1">
                <li className="flex items-center gap-2"><Check className="h-4 w-4 text-success" /> 已连接 {ip}:{port}</li>
                <li className="flex items-center gap-2"><Check className="h-4 w-4 text-success" /> 已注册设备</li>
                <li className="flex items-center gap-2"><Check className="h-4 w-4 text-success" /> 工作目录：{syncRoot}</li>
                <li className="flex items-center gap-2"><Check className="h-4 w-4 text-success" /> 网盘同步：{driveMode === "off" ? "关" : driveMode === "download" ? "仅下载" : "双向"}</li>
              </ul>
              <div className="pt-4">
                <Button variant="accent" onClick={() => nav("/")}>打开主窗口 →</Button>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
