import { cn } from "./cn";

export interface ProgressProps {
  value: number; // 0-100
  size?: "sm" | "md" | "lg";
  tone?: "accent" | "success" | "warn" | "error" | "info";
  showLabel?: boolean;
  className?: string;
}

const HEIGHTS = { sm: "h-1.5", md: "h-2", lg: "h-3" };
const TONES = {
  accent: "bg-accent",
  success: "bg-success",
  warn: "bg-warn",
  error: "bg-error",
  info: "bg-info",
};

export function Progress({ value, size = "md", tone = "accent", showLabel, className }: ProgressProps) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className={cn("relative w-full overflow-hidden rounded-pill bg-line", HEIGHTS[size])}>
        <div
          className={cn("absolute inset-y-0 left-0 rounded-pill transition-all duration-base ease-out-soft", TONES[tone])}
          style={{ width: `${v}%` }}
        />
      </div>
      {showLabel && <span className="text-caption text-ink-muted w-9 text-right">{Math.round(v)}%</span>}
    </div>
  );
}

export interface CircularProgressProps {
  value: number;
  size?: number;
  stroke?: number;
  tone?: ProgressProps["tone"];
  className?: string;
  label?: string;
}

export function CircularProgress({ value, size = 48, stroke = 4, tone = "accent", className, label }: CircularProgressProps) {
  const v = Math.max(0, Math.min(100, value));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - v / 100);
  const colors = {
    accent: "var(--accent)",
    success: "var(--success)",
    warn: "var(--warn)",
    error: "var(--error)",
    info: "var(--info)",
  };
  return (
    <div className={cn("inline-flex items-center justify-center", className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--line)" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={colors[tone]}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={c}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-base ease-out-soft"
        />
      </svg>
      <span className="absolute text-caption text-ink-soft font-semibold">{label ?? `${Math.round(v)}%`}</span>
    </div>
  );
}
