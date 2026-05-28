import { useEffect, type ReactNode } from "react";

/**
 * Wraps children in a CSS view-transition when the browser supports it.
 * Useful as the outermost element under <Route> or in App.tsx.
 *
 * Browsers without the API just render children (no extra animation).
 */
export interface RouteTransitionProps {
  /** A key that changes when navigating — typically `useLocation().pathname`. */
  routeKey: string;
  children: ReactNode;
}

export function RouteTransition({ routeKey, children }: RouteTransitionProps) {
  useEffect(() => {
    const doc: any = document;
    if (typeof doc.startViewTransition === "function") {
      try {
        doc.startViewTransition(() => Promise.resolve());
      } catch {
        /* ignore — older Safari throws */
      }
    }
  }, [routeKey]);

  return <div className="anim-fade-up">{children}</div>;
}
