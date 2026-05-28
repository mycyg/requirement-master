import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { acquireBodyScrollLock, releaseBodyScrollLock } from "./bodyScrollLock";
import { cn } from "./cn";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  side?: "right" | "left";
  width?: string; // tailwind width class, e.g. "w-[420px]"
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}

export function Drawer({
  open,
  onClose,
  side = "right",
  width = "w-[420px]",
  title,
  children,
  footer,
  className,
}: DrawerProps) {
  useEffect(() => {
    if (!open) return;
    acquireBodyScrollLock();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      releaseBodyScrollLock();
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-ink/30 backdrop-blur-1 anim-fade-up" onClick={onClose} aria-hidden="true" />
      <aside
        role="dialog"
        aria-modal="true"
        className={cn(
          "absolute top-0 bottom-0 glass-strong flex flex-col anim-slide-right",
          side === "right" ? "right-0" : "left-0",
          width,
          className,
        )}
      >
        {title && (
          <header className="px-5 py-4 border-b border-line">
            <h2 className="text-h4 text-ink">{title}</h2>
          </header>
        )}
        <div className="flex-1 overflow-auto px-5 py-4 text-body text-ink-soft">{children}</div>
        {footer && (
          <footer className="px-5 py-4 border-t border-line flex items-center justify-end gap-2">
            {footer}
          </footer>
        )}
      </aside>
    </div>,
    document.body,
  );
}
