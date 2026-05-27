import { forwardRef, useEffect, useRef, type TextareaHTMLAttributes } from "react";
import { cn } from "./cn";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  autosize?: boolean;
  error?: string | null;
}

const SHELL =
  "w-full bg-surface-strong border border-line rounded-sm px-3 py-2 text-body text-ink leading-relaxed " +
  "outline-none transition placeholder:text-ink-faint focus:border-accent focus:ring-2 focus:ring-accent/20 " +
  "disabled:opacity-60";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { autosize, error, className, value, defaultValue, onChange, rows = 3, ...rest },
  ref,
) {
  const inner = useRef<HTMLTextAreaElement | null>(null);
  const setRef = (el: HTMLTextAreaElement | null) => {
    inner.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) (ref as { current: HTMLTextAreaElement | null }).current = el;
  };

  useEffect(() => {
    if (!autosize) return;
    const el = inner.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }, [autosize, value, defaultValue]);

  return (
    <div className="w-full">
      <textarea
        ref={setRef}
        rows={rows}
        value={value}
        defaultValue={defaultValue}
        onChange={(e) => {
          if (autosize && inner.current) {
            inner.current.style.height = "auto";
            inner.current.style.height = inner.current.scrollHeight + "px";
          }
          onChange?.(e);
        }}
        className={cn(SHELL, autosize ? "resize-none overflow-hidden" : "resize-y", error && "border-error focus:border-error focus:ring-error/25", className)}
        {...rest}
      />
      {error && <p className="mt-1 text-caption text-error">{error}</p>}
    </div>
  );
});
