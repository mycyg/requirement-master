import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "./cn";

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "prefix"> {
  prefixSlot?: ReactNode;
  suffixSlot?: ReactNode;
  error?: string | null;
  containerClassName?: string;
}

const SHELL =
  "flex items-center gap-2 w-full bg-surface-strong border border-line rounded-sm px-3 h-10 text-body text-ink " +
  "transition focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20 " +
  "[&:has(input:disabled)]:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { prefixSlot, suffixSlot, error, containerClassName, className, ...rest },
  ref,
) {
  return (
    <div className="w-full">
      <div className={cn(SHELL, error && "border-error focus-within:border-error focus-within:ring-error/25", containerClassName)}>
        {prefixSlot && <span className="shrink-0 text-ink-muted">{prefixSlot}</span>}
        <input
          ref={ref}
          className={cn(
            "flex-1 bg-transparent outline-none placeholder:text-ink-faint disabled:cursor-not-allowed",
            className,
          )}
          {...rest}
        />
        {suffixSlot && <span className="shrink-0 text-ink-muted">{suffixSlot}</span>}
      </div>
      {error && <p className="mt-1 text-caption text-error">{error}</p>}
    </div>
  );
});
