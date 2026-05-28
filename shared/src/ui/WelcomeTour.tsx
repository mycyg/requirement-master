import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { Modal } from "./Modal";
import { Button } from "./Button";
import { cn } from "./cn";

/**
 * 首次使用引导 / Welcome tour.
 *
 * Reusable between web and tauri client. Caller passes the slide deck so
 * each surface can highlight what's relevant (e.g. desktop adds 文件同步
 * + 系统通知, web skips them). Caller also owns the open/close state —
 * see `useFirstRun` for the typical pairing.
 */
export interface WelcomeSlide {
  /** Short noun-phrase shown in the progress label, e.g. "派活 vs 接活". */
  key: string;
  /** Icon shown above the heading. Use a lucide-react icon component. */
  icon: ReactNode;
  /** Headline, 4-12 chars. */
  title: string;
  /** Body paragraph(s). Plain text or JSX. */
  body: ReactNode;
  /** Optional accent tint for the icon chip — defaults to accent purple. */
  tint?: "accent" | "dispatch" | "success" | "info";
  /** Optional secondary footer note (e.g. shortcut hint). */
  footnote?: ReactNode;
}

export interface WelcomeTourProps {
  open: boolean;
  onClose: () => void;
  slides: WelcomeSlide[];
  /** Fired when user reaches the last slide and clicks "完成" or "开始用".
   *  Different from onClose in that it signals "user actually finished the
   *  tour", not "user dismissed it"; callers can persist a separate flag. */
  onFinish?: () => void;
  /** Optional title shown across all slides (defaults to "欢迎使用 需求管理大师"). */
  appName?: string;
}

const TINT_CLASSES: Record<NonNullable<WelcomeSlide["tint"]>, string> = {
  accent: "bg-gradient-to-br from-[#6B5BFF] to-[#9d8bff] text-white",
  dispatch: "bg-gradient-to-br from-[#FF6E8E] to-[#ffa8b9] text-white",
  success: "bg-gradient-to-br from-emerald-500 to-emerald-300 text-white",
  info: "bg-gradient-to-br from-sky-500 to-sky-300 text-white",
};

export function WelcomeTour({
  open,
  onClose,
  slides,
  onFinish,
  appName = "欢迎使用 需求管理大师",
}: WelcomeTourProps) {
  const [idx, setIdx] = useState(0);

  // Reset to first slide whenever the tour is re-opened so a user who
  // re-triggers it from Settings doesn't land mid-deck.
  useEffect(() => {
    if (open) setIdx(0);
  }, [open]);

  const total = slides.length;
  const safeIdx = total === 0 ? 0 : Math.min(idx, total - 1);
  const slide = slides[safeIdx];
  const isLast = safeIdx >= total - 1;

  const next = useCallback(() => {
    if (isLast) {
      onFinish?.();
      onClose();
    } else {
      setIdx((i) => i + 1);
    }
  }, [isLast, onClose, onFinish]);

  const prev = useCallback(() => {
    setIdx((i) => Math.max(0, i - 1));
  }, []);

  // Arrow key nav while open
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, next, prev]);

  const footer = useMemo(
    () => (
      <div className="flex w-full items-center justify-between gap-3">
        <button
          type="button"
          onClick={onClose}
          className="text-caption text-ink-faint hover:text-ink underline-offset-4 hover:underline"
        >
          跳过引导
        </button>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<ArrowLeft className="h-4 w-4" />}
            onClick={prev}
            disabled={safeIdx === 0}
          >
            上一步
          </Button>
          <Button
            variant="accent"
            size="sm"
            rightIcon={isLast ? <Check className="h-4 w-4" /> : <ArrowRight className="h-4 w-4" />}
            onClick={next}
          >
            {isLast ? "开始用" : "下一步"}
          </Button>
        </div>
      </div>
    ),
    [isLast, next, onClose, prev, safeIdx],
  );

  if (!slide) return null;

  return (
    <Modal open={open} onClose={onClose} size="md" footer={footer}>
      <div className="flex flex-col items-center text-center">
        <span
          className={cn(
            "grid h-14 w-14 place-items-center rounded-pill shadow-e2 mb-4",
            TINT_CLASSES[slide.tint ?? "accent"],
          )}
        >
          {slide.icon}
        </span>
        <p className="text-eyebrow text-ink-faint">{appName}</p>
        <h2 className="mt-1 text-h2 text-ink">{slide.title}</h2>
        <div className="mt-3 text-body text-ink-soft leading-relaxed max-w-prose">
          {slide.body}
        </div>
        {slide.footnote && (
          <div className="mt-4 text-caption text-ink-muted">{slide.footnote}</div>
        )}

        {/* Progress dots */}
        <div className="mt-6 flex items-center gap-1.5" role="tablist" aria-label="进度">
          {slides.map((s, i) => (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-label={`第 ${i + 1} 步：${s.key}`}
              aria-selected={i === safeIdx}
              onClick={() => setIdx(i)}
              className={cn(
                "h-1.5 rounded-pill transition-all",
                i === safeIdx ? "w-6 bg-accent" : "w-1.5 bg-ink-faint/30 hover:bg-ink-faint/60",
              )}
            />
          ))}
        </div>
        <p className="mt-2 text-caption text-ink-faint">
          {safeIdx + 1} / {total}
        </p>
      </div>
    </Modal>
  );
}

/**
 * Default slide deck used by both surfaces. Pass `variant: "client"` for
 * the desktop client (adds the 文件同步 + 托盘通知 slides) or `"web"` for
 * the browser entry (skips them; users in Mac/Linux land on the web entry).
 */
export function defaultWelcomeSlides(
  variant: "client" | "web",
  icons: {
    Sparkles: ReactNode;
    SwitchHorizontal: ReactNode;
    Bot: ReactNode;
    Bell: ReactNode;
    Folder: ReactNode;
    Command: ReactNode;
  },
): WelcomeSlide[] {
  const common: WelcomeSlide[] = [
    {
      key: "welcome",
      icon: icons.Sparkles,
      title: "把需求接力跑顺",
      tint: "accent",
      body: (
        <>
          把需求写出来 → AI 助理帮你打磨清楚 → 投递给团队接单 →
          做完自动通知你验收。<br />
          全程不用追问「做完没」、不用群里 @ 谁。
        </>
      ),
    },
    {
      key: "dual-space",
      icon: icons.SwitchHorizontal,
      title: "派活 与 接活",
      tint: "dispatch",
      body: (
        <>
          同一份数据，两种滤镜：<b>派活</b> 看「我发出去的活怎么样了」；
          <b>接活</b> 看「我手头有什么活」。
        </>
      ),
      footnote: (
        <>
          快捷键 <kbd className="rounded-xs border border-line px-1.5 py-0.5 text-[10px]">Ctrl+1</kbd>
          /<kbd className="rounded-xs border border-line px-1.5 py-0.5 text-[10px]">Ctrl+2</kbd>
          {variant === "client" ? " 切换" : " 切换（仅桌面客户端）"}
        </>
      ),
    },
    {
      key: "clarify",
      icon: icons.Bot,
      title: "AI 帮你澄清需求",
      tint: "info",
      body: (
        <>
          写一句原始描述就够了。AI 会跟你聊几轮，问清楚目标、受众、
          交付形式，再自动生成结构化摘要 + 标题。<br />
          你确认 DDL，一键投递。
        </>
      ),
    },
  ];

  const desktopOnly: WelcomeSlide[] = [
    {
      key: "files",
      icon: icons.Folder,
      title: "文件自动同步",
      tint: "success",
      body: (
        <>
          需求附件会自动同步到 <code>D:\工作需求\&#123;项目&#125;\&#123;编号&#125;\</code>。
          打开 spec 文件夹监听后，往里丢文件就会自动上传到这条需求。
        </>
      ),
      footnote: <>设置 → 同步 可以改本地工作目录</>,
    },
    {
      key: "notif",
      icon: icons.Bell,
      title: "通知直达系统托盘",
      tint: "accent",
      body: (
        <>
          被指派、需求更新、AI 写完交付文档 → Win11 右下角弹窗 + 托盘红点。
          窗口最小化也不会错过。
        </>
      ),
    },
  ];

  const webOnly: WelcomeSlide[] = [
    {
      key: "notif",
      icon: icons.Bell,
      title: "通知与待办",
      tint: "accent",
      body: (
        <>
          顶部「通知」实时收到指派、交付、验收等动态；
          桌面用户还会收到 Win11 系统托盘弹窗 — 在浏览器顶部横幅
          可以下载 Windows 桌面客户端。
        </>
      ),
    },
  ];

  const trailing: WelcomeSlide[] = [
    {
      key: "command",
      icon: icons.Command,
      title: "⌘K 直达任何地方",
      tint: "info",
      body: (
        <>
          按 <kbd className="rounded-xs border border-line px-1.5 py-0.5 text-[10px]">Ctrl+K</kbd> /
          <kbd className="rounded-xs border border-line px-1.5 py-0.5 text-[10px]">⌘K</kbd>
          打开命令面板，搜需求 / 跳页面 / 改设置都一气呵成。
        </>
      ),
      footnote: <>命令面板里还能「再看一遍引导」</>,
    },
  ];

  return variant === "client"
    ? [...common, ...desktopOnly, ...trailing]
    : [...common, ...webOnly, ...trailing];
}
