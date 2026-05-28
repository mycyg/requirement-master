/**
 * Backend emits ISO-8601 timestamps via Python `datetime.utcnow().isoformat()`,
 * which is naive UTC — no `Z` suffix, no offset. Raw `new Date(naive)` in JS
 * interprets the value as LOCAL time, off by the user's timezone (e.g. CST users
 * see every timestamp 8h earlier than reality). Append `Z` so the parser treats
 * it as UTC, then JS's toLocaleString / getHours / etc. correctly convert.
 *
 * Idempotent on values that already carry `Z` or an explicit offset like `+08:00`.
 *
 * Returns `null` for missing/empty strings so callers can branch cleanly.
 */
export function parseServerDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  if (typeof value !== "string") return null;
  // Already has a timezone marker → trust it.
  const date = /Z$|[+-]\d\d:?\d\d$/.test(value)
    ? new Date(value)
    : new Date(value + "Z");
  // `new Date("not a date")` returns an Invalid Date object which is
  // TRUTHY but produces NaN for every getter and "Invalid Date" for
  // toString. Without this check, downstream `?? new Date(0)` fallbacks
  // never fire and the UI renders literal "NaN:NaN" or "Invalid Date".
  return Number.isNaN(date.getTime()) ? null : date;
}
