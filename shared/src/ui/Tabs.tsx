import { createContext, useContext, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "./cn";

type TabsCtx = {
  value: string;
  onChange: (v: string) => void;
  variant: "underline" | "pill" | "glass";
};

const TabsContext = createContext<TabsCtx | null>(null);

export interface TabsProps {
  value: string;
  onChange: (v: string) => void;
  variant?: "underline" | "pill" | "glass";
  className?: string;
  children: ReactNode;
}

export function Tabs({ value, onChange, variant = "underline", className, children }: TabsProps) {
  return (
    <TabsContext.Provider value={{ value, onChange, variant }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("TabsList must be inside <Tabs>");
  const variantCls =
    ctx.variant === "underline"
      ? "flex gap-1 border-b border-line"
      : ctx.variant === "pill"
      ? "inline-flex gap-1 rounded-pill bg-surface-quiet p-1"
      : "inline-flex gap-1 glass-quiet rounded-md p-1";
  return <div role="tablist" className={cn(variantCls, className)} {...rest} />;
}

export interface TabProps extends HTMLAttributes<HTMLButtonElement> {
  value: string;
  disabled?: boolean;
}

export function Tab({ value, disabled, className, children, ...rest }: TabProps) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("Tab must be inside <Tabs>");
  const active = ctx.value === value;
  const base =
    ctx.variant === "underline"
      ? cn(
          "inline-flex h-10 items-center gap-2 px-3 text-body-sm font-medium transition border-b-2 -mb-px",
          active
            ? "border-accent text-ink"
            : "border-transparent text-ink-muted hover:text-ink hover:border-line-strong",
        )
      : cn(
          "inline-flex h-8 items-center gap-1.5 rounded-pill px-3 text-body-sm font-medium transition",
          active
            ? "bg-surface-strong text-ink shadow-e1"
            : "text-ink-muted hover:text-ink",
        );
  return (
    <button
      role="tab"
      aria-selected={active}
      disabled={disabled}
      onClick={() => !disabled && ctx.onChange(value)}
      className={cn(base, disabled && "opacity-50 cursor-not-allowed", className)}
      {...rest}
    >
      {children}
    </button>
  );
}

export interface TabsPanelProps extends HTMLAttributes<HTMLDivElement> {
  value: string;
}

export function TabsPanel({ value, className, ...rest }: TabsPanelProps) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("TabsPanel must be inside <Tabs>");
  if (ctx.value !== value) return null;
  return <div role="tabpanel" className={cn("anim-fade-up", className)} {...rest} />;
}
