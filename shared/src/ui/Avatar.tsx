import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "./cn";

export type AvatarSize = "xs" | "sm" | "md" | "lg";

const SIZES: Record<AvatarSize, string> = {
  xs: "h-6 w-6 text-[10px]",
  sm: "h-7 w-7 text-[11px]",
  md: "h-9 w-9 text-[13px]",
  lg: "h-12 w-12 text-[16px]",
};

// 6 deterministic gradient pairs picked by nickname hash. All blend with Aurora Glass palette.
const GRADIENTS = [
  "from-[#6B5BFF] to-[#FF6E8E]",
  "from-[#4F89F1] to-[#8B7BFF]",
  "from-[#2E9F6E] to-[#4F89F1]",
  "from-[#E2A03F] to-[#FF6E8E]",
  "from-[#FF6E8E] to-[#8B7BFF]",
  "from-[#6B5BFF] to-[#4F89F1]",
];

function pick(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h << 5) - h + name.charCodeAt(i);
  return Math.abs(h) % GRADIENTS.length;
}

function initial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  // For Chinese names take first char; for ASCII take first 1-2 chars.
  const code = trimmed.charCodeAt(0);
  if (code > 0xff) return trimmed.slice(0, 1);
  return trimmed.slice(0, 2).toUpperCase();
}

export interface AvatarProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  nickname: string;
  size?: AvatarSize;
  src?: string | null;
  online?: boolean;
}

export const Avatar = forwardRef<HTMLDivElement, AvatarProps>(function Avatar(
  { nickname, size = "md", src, online, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        "relative inline-flex items-center justify-center rounded-pill font-semibold text-white shadow-e1 select-none",
        SIZES[size],
        !src && `bg-gradient-to-br ${GRADIENTS[pick(nickname)]}`,
        className,
      )}
      title={nickname}
      {...rest}
    >
      {src ? (
        <img src={src} alt={nickname} className="h-full w-full rounded-pill object-cover" />
      ) : (
        <span>{initial(nickname)}</span>
      )}
      {online !== undefined && (
        <span
          className={cn(
            "absolute -bottom-0 -right-0 h-2.5 w-2.5 rounded-pill border-2 border-canvas",
            online ? "bg-success" : "bg-ink-faint",
          )}
        />
      )}
    </div>
  );
});

/** Stacked avatar group — shows up to `max` avatars, rest as +N pill. */
export interface AvatarGroupProps {
  users: { nickname: string; online?: boolean }[];
  max?: number;
  size?: AvatarSize;
  className?: string;
}

export function AvatarGroup({ users, max = 4, size = "sm", className }: AvatarGroupProps) {
  const shown = users.slice(0, max);
  const rest = users.length - shown.length;
  return (
    <div className={cn("inline-flex items-center -space-x-1.5", className)}>
      {shown.map((u, i) => (
        <Avatar key={i} nickname={u.nickname} online={u.online} size={size} className="ring-2 ring-canvas" />
      ))}
      {rest > 0 && (
        <span className={cn(
          "ring-2 ring-canvas inline-flex items-center justify-center rounded-pill bg-surface-strong text-ink-soft font-semibold",
          SIZES[size],
        )}>
          +{rest}
        </span>
      )}
    </div>
  );
}
