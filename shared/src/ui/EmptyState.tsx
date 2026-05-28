import { type ReactNode } from "react";
import { cn } from "./cn";

export interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "glass-sunken p-8 text-center flex flex-col items-center gap-3 anim-fade-up",
        className,
      )}
    >
      {icon && <div className="text-ink-faint">{icon}</div>}
      <div className="text-h4 text-ink">{title}</div>
      {description && <div className="text-body-sm text-ink-muted max-w-md">{description}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
