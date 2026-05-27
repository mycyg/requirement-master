import { forwardRef, type SelectHTMLAttributes } from "react";
import { cn } from "./cn";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  error?: string | null;
}

const SHELL =
  "w-full appearance-none bg-surface-strong border border-line rounded-sm px-3 pr-9 h-10 text-body text-ink " +
  "outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60 " +
  "bg-no-repeat bg-[right_0.6rem_center] bg-[length:14px_14px]";

// Inline chevron SVG as data-URI so we don't need an external icon.
const CHEVRON =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236e6e80' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>\")";

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { error, className, style, ...rest },
  ref,
) {
  return (
    <div className="w-full">
      <select
        ref={ref}
        className={cn(SHELL, error && "border-error focus:border-error focus:ring-error/25", className)}
        style={{ backgroundImage: CHEVRON, ...style }}
        {...rest}
      />
      {error && <p className="mt-1 text-caption text-error">{error}</p>}
    </div>
  );
});
