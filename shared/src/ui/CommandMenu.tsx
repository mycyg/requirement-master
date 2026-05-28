import { useEffect, useState, type ReactNode } from "react";
import { Modal } from "./Modal";
import { cn } from "./cn";

export interface CommandItem {
  id: string;
  label: ReactNode;
  description?: ReactNode;
  /** Plain text searched against the query. */
  searchText?: string;
  group?: string;
  onSelect: () => void;
  icon?: ReactNode;
  /** Keyboard shortcut hint, e.g. "⌘K". */
  hint?: string;
}

export interface CommandMenuProps {
  open: boolean;
  onClose: () => void;
  items: CommandItem[];
  placeholder?: string;
}

/**
 * Lightweight ⌘K palette. Use `useCommandMenu()` for the toggle hotkey.
 * For a fuller-featured version, swap to `cmdk` later.
 */
export function CommandMenu({ open, onClose, items, placeholder = "搜索命令、需求、项目…" }: CommandMenuProps) {
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (open) {
      setQ("");
      setIdx(0);
    }
  }, [open]);

  const query = q.trim().toLowerCase();
  const filtered = query
    ? items.filter((it) =>
        (it.searchText ?? String(typeof it.label === "string" ? it.label : "")).toLowerCase().includes(query),
      )
    : items;

  // Group by `group` while preserving insertion order
  const groups = new Map<string, CommandItem[]>();
  filtered.forEach((it) => {
    const g = it.group ?? "";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(it);
  });

  // Flattened list for keyboard nav
  const flat = filtered;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        setIdx((i) => Math.min(flat.length - 1, i + 1));
        e.preventDefault();
      } else if (e.key === "ArrowUp") {
        setIdx((i) => Math.max(0, i - 1));
        e.preventDefault();
      } else if (e.key === "Enter") {
        const it = flat[idx];
        if (it) {
          it.onSelect();
          onClose();
        }
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, flat, idx, onClose]);

  return (
    <Modal open={open} onClose={onClose} size="lg" className="!p-0">
      <div className="border-b border-line">
        <input
          autoFocus
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setIdx(0);
          }}
          placeholder={placeholder}
          className="w-full h-12 px-4 bg-transparent outline-none text-body text-ink placeholder:text-ink-faint"
        />
      </div>
      <div className="max-h-96 overflow-auto py-1">
        {flat.length === 0 ? (
          <div className="py-12 text-center text-body-sm text-ink-faint">什么也没找到。</div>
        ) : (
          Array.from(groups.entries()).map(([groupName, list]) => (
            <div key={groupName} className="mb-1">
              {groupName && (
                <div className="px-4 pt-2 pb-1 text-caption text-ink-faint uppercase tracking-wider">{groupName}</div>
              )}
              {list.map((it) => {
                const i = flat.indexOf(it);
                const active = i === idx;
                return (
                  <button
                    key={it.id}
                    onMouseEnter={() => setIdx(i)}
                    onClick={() => {
                      it.onSelect();
                      onClose();
                    }}
                    className={cn(
                      "w-full text-left px-4 h-10 flex items-center gap-3 text-body-sm transition",
                      active ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-accent-soft hover:text-ink",
                    )}
                  >
                    {it.icon && <span className="text-ink-muted shrink-0">{it.icon}</span>}
                    <span className="flex-1 min-w-0 truncate">{it.label}</span>
                    {it.description && (
                      <span className="text-caption text-ink-faint shrink-0">{it.description}</span>
                    )}
                    {it.hint && (
                      <kbd className="text-caption text-ink-faint border border-line rounded-xs px-1.5 py-0.5">{it.hint}</kbd>
                    )}
                  </button>
                );
              })}
            </div>
          ))
        )}
      </div>
    </Modal>
  );
}

/** Helper hook: ⌘K / Ctrl+K toggles open. */
export function useCommandMenu() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setOpen((x) => !x);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return { open, setOpen, close: () => setOpen(false) };
}
