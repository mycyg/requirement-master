import { useEffect, useState, useCallback, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "./cn";

export type ToastTone = "neutral" | "success" | "warn" | "error" | "info" | "accent";

export interface ToastItem {
  id: string;
  tone?: ToastTone;
  title: ReactNode;
  description?: ReactNode;
  action?: { label: string; onClick: () => void };
  /** ms; 0 means sticky */
  duration?: number;
}

const TONES: Record<ToastTone, string> = {
  neutral: "border-line",
  success: "border-success/40",
  warn: "border-warn/40",
  error: "border-error/40",
  info: "border-info/40",
  accent: "border-accent/40",
};

// Stack of mounted ToastHost push fns. Using a stack (not a single slot)
// so that two hosts mounted in sequence (e.g. shell + a feature route
// that accidentally re-renders ToastHost) don't disable each other when
// either one unmounts — we hand toasts to the most-recently-mounted one,
// and fall back to the previous when it goes away.
const pushStack: Array<(t: Omit<ToastItem, "id"> & { id?: string }) => string> = [];

/** Push a toast from anywhere in the app. ToastHost must be mounted. */
export function toast(item: Omit<ToastItem, "id"> & { id?: string }): string {
  const fn = pushStack[pushStack.length - 1];
  if (!fn) {
    console.warn("ToastHost not mounted; toast skipped:", item.title);
    return "";
  }
  return fn(item);
}

/** Mount once near the root. Renders the stack at bottom-right. */
export function ToastHost({ max = 4 }: { max?: number }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef(new Map<string, number>());

  const remove = useCallback((id: string) => {
    setItems((xs) => xs.filter((x) => x.id !== id));
    const handle = timers.current.get(id);
    if (handle) {
      window.clearTimeout(handle);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback((item: Omit<ToastItem, "id"> & { id?: string }) => {
    const id = item.id ?? Math.random().toString(36).slice(2);
    const full: ToastItem = { tone: "neutral", duration: 6000, ...item, id };
    setItems((xs) => {
      const next = [...xs, full];
      return next.length > max ? next.slice(next.length - max) : next;
    });
    if (full.duration && full.duration > 0) {
      const handle = window.setTimeout(() => remove(id), full.duration);
      timers.current.set(id, handle);
    }
    return id;
  }, [max, remove]);

  useEffect(() => {
    pushStack.push(push);
    return () => {
      const idx = pushStack.lastIndexOf(push);
      if (idx >= 0) pushStack.splice(idx, 1);
      // Also clear any pending timers — without this the timer callback
      // would call setItems on an unmounted host (React warning).
      for (const handle of timers.current.values()) window.clearTimeout(handle);
      timers.current.clear();
    };
  }, [push]);

  return createPortal(
    <div className="fixed z-50 bottom-4 right-4 flex flex-col gap-2 max-w-sm pointer-events-none">
      {items.map((t) => (
        <div
          key={t.id}
          className={cn(
            "pointer-events-auto glass-strong rounded-md px-4 py-3 border anim-slide-right",
            TONES[t.tone ?? "neutral"],
          )}
        >
          <div className="flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="text-body font-semibold text-ink">{t.title}</div>
              {t.description && <div className="mt-0.5 text-body-sm text-ink-muted">{t.description}</div>}
            </div>
            <button
              onClick={() => remove(t.id)}
              className="text-ink-faint hover:text-ink h-6 w-6 grid place-items-center rounded-xs hover:bg-accent-soft"
              aria-label="关闭"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          {t.action && (
            <div className="mt-2 flex justify-end">
              <button
                className="text-caption text-accent hover:underline"
                onClick={() => {
                  t.action!.onClick();
                  remove(t.id);
                }}
              >
                {t.action.label}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>,
    document.body,
  );
}
