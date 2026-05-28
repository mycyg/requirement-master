import { useEffect, useState } from "react";
import { Modal, Button, Stepper, Progress, toast } from "@yqgl/shared";
import { invoke, useEvent } from "@/lib/tauri";

const STEPS = [
  { key: "confirm", label: "确认范围" },
  { key: "upload", label: "打包并上传" },
  { key: "wait", label: "等 AI 写交付文档" },
];

export function DeliveryWizard({
  open,
  onClose,
  reqId,
  projectSlug,
  code,
}: {
  open: boolean;
  onClose: () => void;
  reqId: string;
  projectSlug: string;
  code: string;
}) {
  const [step, setStep] = useState(0);
  const [folder, setFolder] = useState("");
  const [progress, setProgress] = useState({ sent: 0, total: 1, phase: "idle" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setProgress({ sent: 0, total: 1, phase: "idle" });
    setBusy(false);
    invoke<{ sync_root: string }>("get_config").then((cfg) => {
      setFolder(`${cfg.sync_root}\\${projectSlug}\\${code}`);
    }).catch(() => {});
  }, [open, projectSlug, code]);

  useEvent<{ req_id: string; phase: string; sent: number; total: number }>("delivery-progress", (p) => {
    if (p.req_id !== reqId) return;
    setProgress({ sent: p.sent, total: p.total || 1, phase: p.phase });
    if (p.phase === "doc_pending") setStep(2);
  });

  useEvent<{ event: string; data: any }>("push-event", (p) => {
    if (step === 2 && p.event === "delivery.doc_ready" && p.data?.requirement_id === reqId) {
      toast({ title: "交付文档已生成", tone: "success", action: { label: "查看", onClick: onClose } });
      onClose();
    }
  });

  const start = async () => {
    setBusy(true);
    try {
      setStep(1);
      await invoke("start_delivery", { reqId, folder });
    } catch (e: any) {
      toast({ title: "上传失败", description: String(e), tone: "error" });
      setStep(0);
    } finally {
      setBusy(false);
    }
  };

  const pct = progress.total ? Math.round((progress.sent / progress.total) * 100) : 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="完成并交付"
      size="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>取消</Button>
          {step === 0 && (
            <Button variant="accent" loading={busy} onClick={start}>开始上传</Button>
          )}
          {step === 2 && (
            <Button variant="secondary" onClick={onClose}>留在窗口</Button>
          )}
        </>
      }
    >
      <Stepper steps={STEPS} current={step} />

      <div className="mt-5 space-y-3">
        {step === 0 && (
          <>
            <p className="text-body-sm text-ink-muted">
              将打包以下目录并上传作为本次交付。系统会自动排除 .git / node_modules / .venv / .vscode 等。
            </p>
            <input
              className="field"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
            />
          </>
        )}
        {step === 1 && (
          <>
            <div className="text-body-sm text-ink-muted">{progress.phase === "zip" ? "正在打包…" : "正在上传…"}</div>
            <Progress value={pct} showLabel />
            <div className="text-caption text-ink-faint">
              已发送 {(progress.sent / 1024 / 1024).toFixed(2)} MB / {(progress.total / 1024 / 1024).toFixed(2)} MB
            </div>
          </>
        )}
        {step === 2 && (
          <div className="text-center py-4">
            <div className="text-h4 text-ink mb-2">已提交</div>
            <div className="text-body-sm text-ink-muted">AI 助理正在写交付文档…</div>
            <div className="anim-pulse-accent inline-block mt-3 px-3 py-1 rounded-pill bg-accent-soft text-accent text-caption">
              等待中
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
