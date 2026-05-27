import { type ReactNode } from "react";
import { cn } from "./cn";

export interface Step {
  key: string;
  label: ReactNode;
  description?: ReactNode;
}

export interface StepperProps {
  steps: Step[];
  /** Index of the currently active step (0-based). */
  current: number;
  /** Optional: clicking a step jumps to it (only if allowed). */
  onJump?: (idx: number) => void;
  className?: string;
}

export function Stepper({ steps, current, onJump, className }: StepperProps) {
  return (
    <ol className={cn("flex items-start gap-2 w-full", className)}>
      {steps.map((s, idx) => {
        const done = idx < current;
        const active = idx === current;
        const clickable = !!onJump && idx <= current;
        return (
          <li key={s.key} className="flex-1 min-w-0">
            <button
              type="button"
              disabled={!clickable}
              onClick={() => onJump?.(idx)}
              className={cn(
                "w-full text-left group",
                clickable ? "cursor-pointer" : "cursor-default",
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "h-6 w-6 grid place-items-center rounded-pill text-caption font-semibold shrink-0 transition",
                    done && "bg-accent text-white",
                    active && "bg-accent text-white anim-pulse-accent",
                    !done && !active && "bg-surface-strong text-ink-muted border border-line",
                  )}
                >
                  {done ? "✓" : idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div
                    className={cn(
                      "text-body-sm font-medium truncate",
                      active ? "text-ink" : done ? "text-ink-soft" : "text-ink-muted",
                    )}
                  >
                    {s.label}
                  </div>
                  {s.description && (
                    <div className="text-caption text-ink-faint truncate">{s.description}</div>
                  )}
                </div>
              </div>
              {idx < steps.length - 1 && (
                <div
                  className={cn(
                    "ml-3 mt-2 h-px",
                    done ? "bg-accent" : "bg-line",
                  )}
                />
              )}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
