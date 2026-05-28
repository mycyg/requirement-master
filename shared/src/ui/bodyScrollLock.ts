/**
 * Shared ref-counted body-scroll lock used by both Modal and Drawer.
 *
 * Why this exists: a naïve per-overlay implementation that captures
 * `prev = document.body.style.overflow` and restores it on close leaks
 * `overflow: hidden` permanently when two overlays open in sequence —
 * the second one captures `"hidden"` as its `prev` value (set by the
 * first), then on close restores body to `"hidden"` forever.
 *
 * We count outstanding locks and only flip body.style.overflow at the
 * boundaries (0 → 1 acquire, N → 0 release).
 */
let count = 0;
let prevOverflow: string | null = null;

export function acquireBodyScrollLock(): void {
  if (typeof document === "undefined") return;
  if (count === 0) {
    prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  count += 1;
}

export function releaseBodyScrollLock(): void {
  if (typeof document === "undefined") return;
  count = Math.max(0, count - 1);
  if (count === 0) {
    document.body.style.overflow = prevOverflow ?? "";
    prevOverflow = null;
  }
}
