import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "./cn";

/** Sunken panel (no glass). Use inside Card to group sub-sections. */
export const Panel = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function Panel(
  { className, ...rest },
  ref,
) {
  return <div ref={ref} className={cn("glass-sunken p-4", className)} {...rest} />;
});
