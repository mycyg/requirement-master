import { type HTMLAttributes } from "react";
import { cn } from "./cn";

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** Tailwind height utility like "h-4". Defaults to "h-4". */
  height?: string;
  /** Tailwind width utility like "w-32" or arbitrary class. Defaults to "w-full". */
  width?: string;
  rounded?: "sm" | "md" | "lg" | "pill";
}

const R = { sm: "rounded-sm", md: "rounded-md", lg: "rounded-lg", pill: "rounded-pill" };

export function Skeleton({ height = "h-4", width = "w-full", rounded = "sm", className, ...rest }: SkeletonProps) {
  return <div className={cn("shimmer", height, width, R[rounded], className)} {...rest} />;
}

/** Useful preset: a 3-line text skeleton with last line shorter. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height="h-3.5"
          width={i === lines - 1 ? "w-2/3" : "w-full"}
        />
      ))}
    </div>
  );
}
