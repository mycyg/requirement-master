import { useState } from "react";
import {
  Check,
  Download,
  FileText,
  FolderOpen,
  PackageOpen,
  Rocket,
  RotateCcw,
  Send,
  UserCog,
} from "lucide-react";
import { Button, Card, Modal, Textarea, toast } from "@yqgl/shared";
import type { Requirement } from "@yqgl/shared";
import { invoke } from "@/lib/tauri";
import { AssigneeSelector } from "@/components/AssigneeSelector";
import { FileAttachRail } from "@/components/FileAttachRail";

/**
 * 派活 Space 在 TaskDetail 里挂载的操作面板。根据 status 给出不同入口：
 *  - draft / clarifying / summary_ready: 编辑分派 + 投递
 *  - ready: 重新分派 + 撤回
 *  - claimed / doing: 改分派、催进度（只读状态显示）
 *  - delivered: ★ 验收 / 打回（核心动作）
 *  - revision_requested / accepted: 只读总结
 *
 * 验收 / 打回 的核心交互特意做得显眼 —— 顶部 hero 卡片 + accent 渐变背景 +
 * 一键打开本地交付目录，避免提交人忘了点。
 */
type Props = {
  req: Requirement;
  meId: string | null;
  onChange: () => void;
};

export function ActionRailDispatch({ req, meId, onChange }: Props) {
  const [submitOpen, setSubmitOpen] = useState(false);
  const [assigneesOpen, setAssigneesOpen] = useState(false);
  const [reviseOpen, setReviseOpen] = useState(false);
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const isSubmitter = !!meId && req.submitter_user_id === meId;
  if (!isSubmitter) return null;

  const submit = async () => {
    setBusy(true);
    try {
      await invoke("submit_requirement", { reqId: req.id });
      toast({ title: "已投递", description: "等接单人接走，会在「投递池」里看到。", tone: "success" });
      setSubmitOpen(false);
      onChange();
    } catch (e: any) {
      toast({ title: "投递失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const acceptIt = async (note: string) => {
    setBusy(true);
    try {
      await invoke("accept_requirement", { reqId: req.id, note: note || null });
      toast({ title: "验收通过", description: "需求已归档。", tone: "success" });
      setAcceptOpen(false);
      onChange();
    } catch (e: any) {
      toast({ title: "验收失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const reviseIt = async (reason: string) => {
    if (!reason.trim()) {
      toast({ title: "请写一下哪里需要返工", tone: "warn" });
      return;
    }
    setBusy(true);
    try {
      await invoke("request_revision", { reqId: req.id, reasonMd: reason.trim() });
      toast({ title: "已打回返工", description: "接单人会收到通知。", tone: "info" });
      setReviseOpen(false);
      onChange();
    } catch (e: any) {
      toast({ title: "打回失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const downloadDelivery = async () => {
    setBusy(true);
    try {
      await invoke("download_delivery", { reqId: req.id });
      toast({ title: "已发起下载", description: "查看本地交付目录可看到 zip 文件。", tone: "info" });
    } catch (e: any) {
      toast({ title: "下载失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  const openDeliveryFolder = async () => {
    try {
      const cfg = await invoke<{ sync_root: string }>("get_config");
      await invoke("open_folder", {
        path: `${cfg.sync_root}\\${req.project_slug}\\${req.code}\\deliveries`,
      });
    } catch (e: any) {
      toast({ title: "打不开本地目录", description: String(e), tone: "error" });
    }
  };

  // Hero banner — only when there's a delivery awaiting acceptance.
  const heroForDelivered = req.status === "delivered" && (
    <Card
      variant="glass-strong"
      padding="lg"
      className="mb-5 border border-accent/30"
      style={{
        background: "linear-gradient(135deg, rgba(255,110,142,0.12) 0%, rgba(107,91,255,0.08) 100%)",
      }}
    >
      <div className="flex items-start gap-4">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-accent text-white">
          <PackageOpen className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-h3 text-ink">交付来了，等你验收</h2>
          <p className="text-body-sm text-ink-muted mt-1">
            接单人已经把活做完了。先下载/打开本地交付目录看一眼，再决定通过或打回。
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="accent" leftIcon={<Check className="h-4 w-4" />} onClick={() => setAcceptOpen(true)}>
              通过
            </Button>
            <Button variant="secondary" leftIcon={<RotateCcw className="h-4 w-4" />} onClick={() => setReviseOpen(true)}>
              打回返工
            </Button>
            <Button variant="ghost" leftIcon={<Download className="h-4 w-4" />} loading={busy} onClick={downloadDelivery}>
              下载交付物
            </Button>
            <Button variant="ghost" leftIcon={<FolderOpen className="h-4 w-4" />} onClick={openDeliveryFolder}>
              打开本地目录
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );

  // Inline buttons row by status
  const actions = (() => {
    const isDraft = ["draft", "clarifying", "summary_ready"].includes(req.status);
    const isReady = req.status === "ready";
    const isWorking = ["claimed", "doing", "ai_processing", "delivery_doc_pending"].includes(req.status);
    return (
      <>
        {isDraft && (
          <Button variant="accent" leftIcon={<Rocket className="h-4 w-4" />} onClick={() => setSubmitOpen(true)}>
            投递
          </Button>
        )}
        {(isDraft || isReady || isWorking) && (
          <Button variant="secondary" leftIcon={<UserCog className="h-4 w-4" />} onClick={() => setAssigneesOpen(true)}>
            {isReady ? "重新分派" : "改分派"}
          </Button>
        )}
        {req.status === "revision_requested" && (
          <span className="text-body-sm text-ink-muted self-center">已打回，等接单人重做。</span>
        )}
        {req.status === "accepted" && (
          <span className="inline-flex items-center gap-1.5 text-body-sm text-success">
            <Check className="h-4 w-4" /> 已通过验收
          </span>
        )}
      </>
    );
  })();

  return (
    <>
      {heroForDelivered}

      <Card variant="glass-quiet" padding="md" className="mb-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 text-body-sm text-ink-muted">
            <FileText className="h-4 w-4" />
            <span>你是这个需求的发起人，这里是你能做的事</span>
          </div>
          <div className="flex gap-2 flex-wrap">{actions}</div>
        </div>
      </Card>

      {/* For draft-phase submitters, expose the file attach rail inline */}
      {["draft", "clarifying", "summary_ready"].includes(req.status) && (
        <Card variant="glass" padding="md" className="mb-5">
          <h3 className="text-h4 text-ink mb-3 flex items-center gap-2">
            <FileText className="h-4 w-4 text-ink-muted" />
            规格附件
          </h3>
          <FileAttachRail reqId={req.id} />
        </Card>
      )}

      {/* Modals */}
      <Modal open={submitOpen} onClose={() => setSubmitOpen(false)} title="确认投递？">
        <div className="space-y-3">
          <p className="text-body-sm text-ink-muted">
            投递后接单人会立刻收到通知。投递后你还能改截止 / 分派，但内容已经定型。
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setSubmitOpen(false)}>取消</Button>
            <Button variant="accent" loading={busy} leftIcon={<Send className="h-4 w-4" />} onClick={submit}>
              确认投递
            </Button>
          </div>
        </div>
      </Modal>

      <Modal open={assigneesOpen} onClose={() => setAssigneesOpen(false)} title="重新分派">
        <AssigneesEditor
          req={req}
          onCancel={() => setAssigneesOpen(false)}
          onDone={() => { setAssigneesOpen(false); onChange(); }}
        />
      </Modal>

      <Modal open={acceptOpen} onClose={() => setAcceptOpen(false)} title="验收通过">
        <AcceptForm onCancel={() => setAcceptOpen(false)} onSubmit={acceptIt} busy={busy} />
      </Modal>

      <Modal open={reviseOpen} onClose={() => setReviseOpen(false)} title="打回返工">
        <ReviseForm onCancel={() => setReviseOpen(false)} onSubmit={reviseIt} busy={busy} />
      </Modal>
    </>
  );
}

function AssigneesEditor({
  req,
  onCancel,
  onDone,
}: {
  req: Requirement;
  onCancel: () => void;
  onDone: () => void;
}) {
  const initLead = req.assignees?.find((a) => a.role === "lead")?.user_id ?? null;
  const initCollab = (req.assignees ?? [])
    .filter((a) => a.role !== "lead")
    .map((a) => a.user_id);
  const [leadUserId, setLead] = useState<string | null>(initLead);
  const [collabIds, setCollab] = useState<string[]>(initCollab);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await invoke("put_assignees", {
        reqId: req.id,
        leadUserId,
        collaboratorUserIds: collabIds,
      });
      toast({ title: "已更新分派", tone: "success" });
      onDone();
    } catch (e: any) {
      toast({ title: "更新失败", description: String(e), tone: "error" });
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-3">
      <AssigneeSelector
        leadUserId={leadUserId}
        collaboratorUserIds={collabIds}
        onChange={({ leadUserId: l, collaboratorUserIds: c }) => { setLead(l); setCollab(c); }}
      />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>取消</Button>
        <Button variant="accent" loading={busy} onClick={save}>保存</Button>
      </div>
    </div>
  );
}

function AcceptForm({
  onCancel,
  onSubmit,
  busy,
}: {
  onCancel: () => void;
  onSubmit: (note: string) => void | Promise<void>;
  busy: boolean;
}) {
  const [note, setNote] = useState("");
  return (
    <div className="space-y-3">
      <p className="text-body-sm text-ink-muted">
        通过后接单人会收到致谢通知，需求转为「已通过」状态。
      </p>
      <label className="block">
        <span className="text-eyebrow text-ink-muted block mb-1">致谢 / 备注（可选）</span>
        <Textarea
          autosize
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="比如：超出预期，文档写得很清楚"
        />
      </label>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>取消</Button>
        <Button variant="accent" loading={busy} leftIcon={<Check className="h-4 w-4" />} onClick={() => onSubmit(note)}>
          确认通过
        </Button>
      </div>
    </div>
  );
}

function ReviseForm({
  onCancel,
  onSubmit,
  busy,
}: {
  onCancel: () => void;
  onSubmit: (reason: string) => void | Promise<void>;
  busy: boolean;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="space-y-3">
      <p className="text-body-sm text-ink-muted">
        把需要返工的部分写清楚 — 接单人会基于你的描述继续调整。
      </p>
      <label className="block">
        <span className="text-eyebrow text-ink-muted block mb-1">需要返工的部分（必填）</span>
        <Textarea
          autosize
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={5}
          placeholder="比如：导出按钮位置不对，应该放在右上角；数据看板需要补全季度同比图表"
          autoFocus
        />
      </label>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>取消</Button>
        <Button
          variant="danger"
          loading={busy}
          leftIcon={<RotateCcw className="h-4 w-4" />}
          onClick={() => onSubmit(reason)}
          disabled={!reason.trim()}
        >
          打回返工
        </Button>
      </div>
    </div>
  );
}
