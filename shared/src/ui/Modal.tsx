import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { acquireBodyScrollLock, releaseBodyScrollLock } from "./bodyScrollLock";
import { cn } from "./cn";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  description?: ReactNode;
  /** Width preset. Use a Tailwind class for finer control. */
  size?: "sm" | "md" | "lg" | "xl";
  /** Click on backdrop to close. Default true. */
  dismissOnBackdrop?: boolean;
  className?: string;
  children: ReactNode;
  footer?: ReactNode;
}

const SIZES = {
  sm: "max-w-md",
  md: "max-w-xl",
  lg: "max-w-3xl",
  xl: "max-w-5xl",
};

export function Modal({
  open,
  onClose,
  title,
  description,
  size = "md",
  dismissOnBackdrop = true,
  className,
  children,
  footer,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // Lock body scroll while open (ref-counted across Modal+Drawer stack).
  useEffect(() => {
    if (!open) return;
    acquireBodyScrollLock();
    return () => {
      releaseBodyScrollLock();
    };
  }, [open]);

  // ESC to close + focus trap (minimal: keep focus inside) + focus
  // restoration so keyboard users land back on whatever opened the modal.
  useEffect(() => {
    if (!open) return;
    // Remember what was focused so we can restore on close. Without this,
    // a keyboard user closing a modal lands on `<body>` and has to tab
    // through the entire page to get back to the trigger button.
    const prevFocus = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && dialogRef.current) {
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
          'a, button, input, textarea, select, [tabindex]:not([tabindex="-1"])',
        );
        const list = Array.from(focusables).filter((el) => !el.hasAttribute("disabled"));
        if (list.length === 0) return;
        const first = list[0];
        const last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          last.focus();
          e.preventDefault();
        } else if (!e.shiftKey && document.activeElement === last) {
          first.focus();
          e.preventDefault();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    queueMicrotask(() => dialogRef.current?.focus());
    return () => {
      window.removeEventListener("keydown", onKey);
      // Restore focus to the element that had it before the modal opened,
      // if it's still in the DOM.
      if (prevFocus && document.body.contains(prevFocus)) {
        try { prevFocus.focus(); } catch { /* ignore */ }
      }
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4 anim-fade-up"
      onMouseDown={(e) => {
        if (dismissOnBackdrop && e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="absolute inset-0 bg-ink/40 backdrop-blur-2"
        aria-hidden="true"
        onMouseDown={() => dismissOnBackdrop && onClose()}
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={cn(
          "relative w-full glass-strong p-6 anim-scale-in outline-none",
          SIZES[size],
          className,
        )}
      >
        {(title || description) && (
          <header className="mb-4">
            {title && <h2 className="text-h3 text-ink">{title}</h2>}
            {description && <p className="mt-1 text-body-sm text-ink-muted">{description}</p>}
          </header>
        )}
        <div className="text-body text-ink-soft">{children}</div>
        {footer && (
          <footer className="mt-5 pt-4 border-t border-line flex items-center justify-end gap-2">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}
