import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "./cn";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "accent"
  | "danger"
  | "link"
  | "icon";

export type ButtonSize = "xs" | "sm" | "md" | "lg";

const BASE =
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition outline-none " +
  "disabled:pointer-events-none disabled:opacity-50 " +
  "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas";

const SIZES: Record<ButtonSize, string> = {
  xs: "h-7 px-2.5 text-[12px] rounded-sm gap-1.5",
  sm: "h-8 px-3 text-[13px] rounded-sm",
  md: "h-10 px-4 text-[14px] rounded-sm",
  lg: "h-11 px-5 text-[15px] rounded-md",
};

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-ink text-canvas border border-ink shadow-e1 hover:-translate-y-0.5 hover:bg-ink-soft active:translate-y-0",
  accent:
    "bg-accent text-white border border-accent shadow-e1 hover:bg-accent-hover hover:-translate-y-0.5 active:translate-y-0",
  secondary:
    "bg-surface text-ink border border-line hover:border-line-strong hover:bg-surface-strong backdrop-blur-2",
  ghost:
    "bg-transparent text-ink-soft border border-transparent hover:bg-accent-soft hover:text-ink",
  danger:
    "bg-error text-white border border-error hover:bg-error/90 active:translate-y-0",
  link:
    "bg-transparent text-accent border border-transparent px-0 h-auto underline-offset-4 hover:underline",
  icon:
    "bg-transparent text-ink-soft border border-transparent hover:bg-accent-soft hover:text-ink p-0",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  asChild?: never;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, leftIcon, rightIcon, disabled, className, children, ...rest },
  ref,
) {
  // Icon variant: render as a square button
  const iconOnly = variant === "icon";
  const sizeClass = iconOnly
    ? { xs: "h-7 w-7", sm: "h-8 w-8", md: "h-10 w-10", lg: "h-11 w-11" }[size] + " rounded-sm"
    : SIZES[size];

  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(BASE, sizeClass, VARIANTS[variant], className)}
      {...rest}
    >
      {loading ? <Spinner /> : leftIcon}
      {children}
      {rightIcon}
    </button>
  );
});

function Spinner() {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      className="animate-spin"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
