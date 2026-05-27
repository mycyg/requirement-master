/** Minimal classnames helper — accept strings / falsy / arrays / records, return joined string. */
export type ClassValue =
  | string
  | number
  | boolean
  | undefined
  | null
  | ClassValue[]
  | { [k: string]: any };

export function cn(...values: ClassValue[]): string {
  const out: string[] = [];
  const walk = (v: ClassValue) => {
    if (!v) return;
    if (typeof v === "string" || typeof v === "number") {
      out.push(String(v));
    } else if (Array.isArray(v)) {
      v.forEach(walk);
    } else if (typeof v === "object") {
      for (const k of Object.keys(v)) if (v[k]) out.push(k);
    }
  };
  values.forEach(walk);
  return out.join(" ");
}
