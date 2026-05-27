import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "./cn";

export interface DropdownMenuProps {
  trigger: ReactNode;
  children: ReactNode;
  /** Alignment relative to trigger. */
  align?: "start" | "end";
  className?: string;
}

/** Lightweight popover menu, no portal needed for most cases. */
export function DropdownMenu({ trigger, children, align = "start", className }: DropdownMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={cn("relative inline-block", className)}>
      <span onClick={() => setOpen((x) => !x)}>{trigger}</span>
      {open && (
        <div
          role="menu"
          className={cn(
            "absolute z-40 mt-1 min-w-[180px] glass-strong rounded-md p-1 anim-scale-in",
            align === "end" ? "right-0" : "left-0",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

export interface DropdownItemProps {
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
  /** Visual hint for destructive items. */
  destructive?: boolean;
}

export function DropdownItem({ onClick, disabled, className, children, destructive }: DropdownItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "w-full text-left px-3 h-8 rounded-xs text-body-sm flex items-center gap-2 transition",
        "hover:bg-accent-soft hover:text-ink",
        destructive ? "text-error hover:bg-error-soft" : "text-ink-soft",
        disabled && "opacity-50 pointer-events-none",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function DropdownDivider() {
  return <div className="my-1 h-px bg-line" />;
}

export function DropdownLabel({ children }: { children: ReactNode }) {
  return <div className="px-3 py-1 text-caption text-ink-faint uppercase tracking-wider">{children}</div>;
}
