import { Badge } from "./Badge";
import { STATUS_VOCAB, type StatusKey } from "../design/status-vocab";

export interface StatusBadgeProps {
  status: string | null | undefined;
  size?: "xs" | "sm" | "md";
  className?: string;
}

export function StatusBadge({ status, size = "sm", className }: StatusBadgeProps) {
  if (!status) return null;
  const entry = STATUS_VOCAB[status as StatusKey];
  if (!entry) {
    return (
      <Badge tone="neutral" size={size} className={className}>
        {status}
      </Badge>
    );
  }
  return (
    <Badge tone={entry.tone} size={size} pulse={entry.pulse} className={className}>
      {entry.label}
    </Badge>
  );
}
