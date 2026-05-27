import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "./cn";

export type BadgeTone =
  | "neutral"
  | "info"
  | "warn"
  | "accent"
  | "accent-2"
  | "success"
  | "error";

export type BadgeSize = "xs" | "sm" | "md";

const SIZES: Record<BadgeSize, string> = {
  xs: "h-5 px-1.5 text-[11px] gap-1 rounded-xs",
  sm: "h-6 px-2 text-[12px] gap-1 rounded-xs",
  md: "h-7 px-2.5 text-[13px] gap-1.5 rounded-sm",
};

const TONES: Record<BadgeTone, string> = {
  neutral: "bg-surface-strong text-ink-muted border border-line",
  info: "bg-info-soft text-info border border-info/30",
  warn: "bg-warn-soft text-warn border border-warn/30",
  accent: "bg-accent-soft text-accent border border-accent/30",
  "accent-2": "bg-accent-2-soft text-accent-2 border border-accent-2/30",
  success: "bg-success-soft text-success border border-success/30",
  error: "bg-error-soft text-error border border-error/30",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  size?: BadgeSize;
  /** Animate (use for long-running states like "AI 助理处理中") */
  pulse?: boolean;
}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { tone = "neutral", size = "sm", pulse, className, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      className={cn(
        "inline-flex items-center font-medium whitespace-nowrap",
        SIZES[size],
        TONES[tone],
        pulse && "anim-pulse-accent",
        className,
      )}
      {...rest}
    />
  );
});

/** Convenience pill variant (rounded-full). */
export const Pill = forwardRef<HTMLSpanElement, BadgeProps>(function Pill({ className, ...rest }, ref) {
  return <Badge ref={ref} className={cn("!rounded-pill", className)} {...rest} />;
});
