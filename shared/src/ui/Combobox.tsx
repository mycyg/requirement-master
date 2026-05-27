import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "./cn";

export interface ComboboxOption<T = string> {
  value: T;
  label: ReactNode;
  description?: ReactNode;
  /** Plain text the search query matches against. Defaults to String(label). */
  searchText?: string;
}

export interface ComboboxProps<T = string> {
  value: T | null;
  onChange: (v: T | null) => void;
  options: ComboboxOption<T>[];
  placeholder?: string;
  /** Allow clearing the selection. */
  clearable?: boolean;
  /** When true, the search input is always visible (vs only inside the dropdown). */
  searchInline?: boolean;
  className?: string;
  /** Render the trigger button content from the selected option. */
  renderValue?: (opt: ComboboxOption<T> | null) => ReactNode;
  emptyText?: ReactNode;
}

export function Combobox<T = string>({
  value,
  onChange,
  options,
  placeholder = "选择…",
  clearable,
  searchInline,
  className,
  renderValue,
  emptyText = "没有匹配项",
}: ComboboxProps<T>) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    queueMicrotask(() => inputRef.current?.focus());
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = options.find((o) => o.value === value) ?? null;
  const q = query.trim().toLowerCase();
  const filtered = q
    ? options.filter((o) =>
        (o.searchText ?? String(typeof o.label === "string" ? o.label : "")).toLowerCase().includes(q),
      )
    : options;

  return (
    <div ref={root} className={cn("relative inline-flex w-full", className)}>
      <button
        type="button"
        onClick={() => setOpen((x) => !x)}
        className={cn(
          "w-full h-10 px-3 rounded-sm bg-surface-strong border border-line text-body text-ink",
          "flex items-center justify-between gap-2 transition outline-none",
          "focus:border-accent focus:ring-2 focus:ring-accent/20",
        )}
      >
        <span className={cn("truncate", !selected && "text-ink-faint")}>
          {renderValue ? renderValue(selected) : selected?.label ?? placeholder}
        </span>
        <svg className="h-3.5 w-3.5 text-ink-muted shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {searchInline && open && (
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索…"
          className="absolute inset-x-0 -bottom-12 h-10 px-3 rounded-sm bg-surface-strong border border-line outline-none"
        />
      )}

      {open && (
        <div className="absolute z-40 top-full mt-1 left-0 right-0 glass-strong rounded-md p-1 anim-scale-in max-h-72 overflow-auto">
          {!searchInline && (
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索…"
              className="w-full h-9 px-3 mb-1 rounded-xs bg-transparent border border-line outline-none placeholder:text-ink-faint focus:border-accent"
            />
          )}
          {clearable && value !== null && (
            <button
              onClick={() => {
                onChange(null);
                setOpen(false);
                setQuery("");
              }}
              className="w-full text-left px-3 h-8 rounded-xs text-body-sm text-ink-muted hover:bg-accent-soft"
            >
              清除选择
            </button>
          )}
          {filtered.length === 0 && (
            <div className="px-3 py-4 text-caption text-ink-faint text-center">{emptyText}</div>
          )}
          {filtered.map((o, i) => {
            const active = o.value === value;
            return (
              <button
                key={i}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                  setQuery("");
                }}
                className={cn(
                  "w-full text-left px-3 h-8 rounded-xs text-body-sm flex items-center gap-2 transition",
                  active ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft hover:text-ink",
                )}
              >
                <span className="flex-1 min-w-0 truncate">{o.label}</span>
                {o.description && <span className="text-caption text-ink-faint shrink-0">{o.description}</span>}
                {active && (
                  <svg className="h-3.5 w-3.5 text-accent shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
