import { useId, useRef, useState, type ReactNode } from "react";
import { cn } from "./cn";

export interface TooltipProps {
  label: ReactNode;
  placement?: "top" | "bottom" | "left" | "right";
  delay?: number;
  className?: string;
  children: ReactNode;
}

/**
 * Lightweight tooltip — keyboard focus and hover both trigger.
 * Uses CSS positioning around the child wrapper, no portal.
 */
export function Tooltip({ label, placement = "top", delay = 250, className, children }: TooltipProps) {
  const id = useId();
  const timer = useRef<number | null>(null);
  const [open, setOpen] = useState(false);

  const show = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), delay);
  };
  const hide = () => {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen(false);
  };

  const pos: Record<typeof placement, string> = {
    top: "bottom-[calc(100%+6px)] left-1/2 -translate-x-1/2",
    bottom: "top-[calc(100%+6px)] left-1/2 -translate-x-1/2",
    left: "right-[calc(100%+6px)] top-1/2 -translate-y-1/2",
    right: "left-[calc(100%+6px)] top-1/2 -translate-y-1/2",
  };

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      <span aria-describedby={open ? id : undefined}>{children}</span>
      {open && (
        <span
          id={id}
          role="tooltip"
          className={cn(
            "absolute z-50 whitespace-nowrap px-2 py-1 text-caption text-canvas bg-ink rounded-xs shadow-e3 anim-fade-up pointer-events-none",
            pos[placement],
            className,
          )}
        >
          {label}
        </span>
      )}
    </span>
  );
}
