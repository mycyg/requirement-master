import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "./cn";

export type CardVariant = "glass" | "glass-strong" | "glass-quiet" | "glass-sunken";
export type CardPadding = "none" | "sm" | "md" | "lg";

const PAD: Record<CardPadding, string> = {
  none: "p-0",
  sm: "p-3",
  md: "p-5",
  lg: "p-6",
};

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
  padding?: CardPadding;
  interactive?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { variant = "glass", padding = "md", interactive, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        variant,
        PAD[padding],
        interactive &&
          "transition cursor-pointer hover:-translate-y-0.5 hover:shadow-e3 hover:border-accent/30",
        className,
      )}
      {...rest}
    />
  );
});

export const CardHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function CardHeader({ className, ...rest }, ref) {
    return <div ref={ref} className={cn("mb-3 flex items-center justify-between gap-3", className)} {...rest} />;
  },
);

export const CardTitle = forwardRef<HTMLHeadingElement, HTMLAttributes<HTMLHeadingElement>>(
  function CardTitle({ className, ...rest }, ref) {
    return <h3 ref={ref} className={cn("text-h4 text-ink", className)} {...rest} />;
  },
);

export const CardBody = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function CardBody({ className, ...rest }, ref) {
    return <div ref={ref} className={cn("text-body text-ink-soft", className)} {...rest} />;
  },
);

export const CardFooter = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function CardFooter({ className, ...rest }, ref) {
    return (
      <div
        ref={ref}
        className={cn("mt-4 pt-3 flex items-center justify-end gap-2 border-t border-line", className)}
        {...rest}
      />
    );
  },
);
