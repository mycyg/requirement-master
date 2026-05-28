import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "./cn";

/** Native-styled checkbox / radio with glass accent. */
export interface CheckRadioProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
  description?: ReactNode;
}

const BOX_BASE =
  "shrink-0 grid place-items-center border border-line bg-surface-strong rounded-sm transition " +
  "checked:border-accent checked:bg-accent " +
  "focus-visible:ring-2 focus-visible:ring-accent/35 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas " +
  "disabled:opacity-60";

export const Checkbox = forwardRef<HTMLInputElement, CheckRadioProps>(function Checkbox(
  { label, description, className, ...rest },
  ref,
) {
  return (
    <label className={cn("flex items-start gap-2 cursor-pointer", className)}>
      <input
        ref={ref}
        type="checkbox"
        className={cn(BOX_BASE, "h-4 w-4 appearance-none mt-[3px] relative",
          "after:content-[''] after:absolute after:left-[3px] after:top-[0px] after:w-[6px] after:h-[10px]",
          "after:border-r-2 after:border-b-2 after:border-white after:rotate-45 after:opacity-0 checked:after:opacity-100")}
        {...rest}
      />
      {(label || description) && (
        <span>
          {label && <span className="text-body text-ink">{label}</span>}
          {description && <span className="block text-caption text-ink-muted">{description}</span>}
        </span>
      )}
    </label>
  );
});

export const Radio = forwardRef<HTMLInputElement, CheckRadioProps>(function Radio(
  { label, description, className, ...rest },
  ref,
) {
  return (
    <label className={cn("flex items-start gap-2 cursor-pointer", className)}>
      <input
        ref={ref}
        type="radio"
        className={cn(BOX_BASE, "h-4 w-4 rounded-full appearance-none mt-[3px] relative",
          "after:content-[''] after:absolute after:left-1/2 after:top-1/2 after:-translate-x-1/2 after:-translate-y-1/2",
          "after:w-1.5 after:h-1.5 after:rounded-full after:bg-white after:opacity-0 checked:after:opacity-100")}
        {...rest}
      />
      {(label || description) && (
        <span>
          {label && <span className="text-body text-ink">{label}</span>}
          {description && <span className="block text-caption text-ink-muted">{description}</span>}
        </span>
      )}
    </label>
  );
});

/** Toggle switch — controlled or uncontrolled. */
export interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
}

export const Switch = forwardRef<HTMLInputElement, SwitchProps>(function Switch(
  { label, className, ...rest },
  ref,
) {
  return (
    <label className={cn("inline-flex items-center gap-2 cursor-pointer select-none", className)}>
      <span className="relative inline-flex h-5 w-9 items-center">
        <input
          ref={ref}
          type="checkbox"
          className="peer sr-only"
          {...rest}
        />
        <span
          className={cn(
            "absolute inset-0 rounded-full bg-line-strong transition",
            "peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent/35",
          )}
        />
        <span
          className={cn(
            "absolute left-0.5 top-1/2 -translate-y-1/2 h-4 w-4 rounded-full bg-white shadow-e1 transition",
            "peer-checked:translate-x-4",
          )}
        />
      </span>
      {label && <span className="text-body text-ink">{label}</span>}
    </label>
  );
});
