"use client";

import { Check, ChevronDown, Search, X } from "lucide-react";
import * as React from "react";
import { fieldClass } from "@/components/ui/input";
import { FilterTemplate } from "@/lib/api";
import { cn } from "@/lib/utils";

function label(t: FilterTemplate): string {
  return `${t.name}${t.aggregation?.enabled ? " (with parse & aggregate)" : ""}`;
}

function matches(t: FilterTemplate, q: string): boolean {
  const hay = `${t.name} ${t.customer ?? ""}`.toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => hay.includes(word));
}

/** Searchable replacement for the native saved-search <select>, which is
 *  unusable past a dozen entries: type to filter by name or customer,
 *  arrows + Enter to pick, Escape to close. Same value contract as the
 *  select it replaces (template id, or "" for none). */
export function TemplatePicker({
  templates,
  value,
  onPick,
}: {
  templates: FilterTemplate[];
  value: number | "";
  onPick: (id: number | "") => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const searchRef = React.useRef<HTMLInputElement>(null);

  const selected = templates.find((t) => t.id === value) ?? null;
  const filtered = React.useMemo(
    () => (query.trim() ? templates.filter((t) => matches(t, query)) : templates),
    [templates, query]
  );

  function close(restoreFocus: boolean) {
    setOpen(false);
    setQuery("");
    setActive(0);
    if (restoreFocus) buttonRef.current?.focus();
  }

  function pick(id: number | "") {
    onPick(id);
    close(true);
  }

  React.useEffect(() => {
    if (open) searchRef.current?.focus();
  }, [open ]);

  React.useEffect(() => {
    setActive(0);
  }, [query]);

  if (templates.length === 0) {
    return (
      <button type="button" className={cn(fieldClass, "flex cursor-not-allowed opacity-60")} disabled>
        <span className="truncate">No saved searches yet</span>
      </button>
    );
  }

  return (
    <div className="relative">
      <div className="flex gap-1.5">
        <button
          ref={buttonRef}
          type="button"
          className={cn(fieldClass, "flex flex-1 items-center justify-between gap-2 text-left")}
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => (open ? close(false) : setOpen(true))}
        >
          <span className="truncate">{selected ? label(selected) : "Choose a saved search…"}</span>
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
        {selected && (
          <button
            type="button"
            className="border border-border px-2 text-muted-foreground hover:text-foreground"
            aria-label="Clear saved search"
            title="Clear"
            onClick={() => onPick("")}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {open && (
        <>
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            className="fixed inset-0 z-40 cursor-default bg-transparent"
            onClick={() => close(false)}
          />
          <div className="absolute inset-x-0 top-full z-50 mt-1 border border-border bg-background shadow-lg">
            <div className="flex items-center gap-2 border-b border-border px-2">
              <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setActive((a) => Math.min(a + 1, filtered.length - 1));
                  } else if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setActive((a) => Math.max(a - 1, 0));
                  } else if (e.key === "Enter") {
                    e.preventDefault();
                    if (filtered[active]) pick(filtered[active].id);
                  } else if (e.key === "Escape") {
                    close(true);
                  }
                }}
                placeholder="Type to filter…"
                aria-label="Filter saved searches"
                className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
            </div>
            <ul role="listbox" aria-label="Saved searches" className="max-h-64 overflow-auto py-1">
              {filtered.length === 0 && (
                <li className="px-3 py-2 text-xs text-muted-foreground">
                  No saved searches match{query.trim() ? ` “${query.trim()}”` : ""}.
                </li>
              )}
              {filtered.map((t, i) => (
                <li
                  key={t.id}
                  role="option"
                  aria-selected={t.id === value}
                  onClick={() => pick(t.id)}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm",
                    i === active ? "bg-muted text-foreground" : "text-muted-foreground"
                  )}
                  title={t.customer ? `Customer: ${t.customer}` : undefined}
                >
                  {t.id === value ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-success" />
                  ) : (
                    <span className="w-3.5 shrink-0" />
                  )}
                  <span className="truncate">
                    {t.name}
                    {t.aggregation?.enabled && (
                      <span className="opacity-60"> (with parse & aggregate)</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
            <p className="border-t border-border px-3 py-1 font-mono text-[11px] text-muted-foreground">
              {filtered.length} of {templates.length}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
