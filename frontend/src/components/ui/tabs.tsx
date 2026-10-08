import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface TabItem {
  id: string;
  label: string;
  /** Rendered only while the tab is selected, so heavy panels cost nothing until opened. */
  content: ReactNode;
  /** Short status text announced and shown after the label (for example a count). */
  badge?: string | number | undefined;
}

/** Accessible tabs: roving tabindex, arrow/Home/End keys, role=tab/tabpanel wiring. */
export function Tabs({ items, label, initialId }: { items: TabItem[]; label: string; initialId?: string }) {
  const base = useId();
  const [selected, setSelected] = useState(initialId ?? items[0]?.id);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const move = (index: number) => {
    const next = items[(index + items.length) % items.length];
    if (!next) return;
    setSelected(next.id);
    refs.current[next.id]?.focus();
  };

  const onKeyDown = (e: KeyboardEvent, index: number) => {
    if (e.key === "ArrowRight") move(index + 1);
    else if (e.key === "ArrowLeft") move(index - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(items.length - 1);
    else return;
    e.preventDefault();
  };

  const active = items.find((i) => i.id === selected) ?? items[0];
  return (
    <div>
      <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b">
        {items.map((item, i) => {
          const isActive = item.id === active?.id;
          return (
            <button
              key={item.id}
              ref={(el) => { refs.current[item.id] = el; }}
              role="tab"
              type="button"
              id={`${base}-tab-${item.id}`}
              aria-selected={isActive}
              aria-controls={`${base}-panel-${item.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => setSelected(item.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={cn(
                "-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium hover:bg-muted",
                isActive ? "border-primary text-foreground" : "border-transparent text-muted-foreground",
              )}
            >
              {item.label}
              {item.badge !== undefined && (
                <span className="rounded-full bg-secondary px-1.5 text-xs text-secondary-foreground">{item.badge}</span>
              )}
            </button>
          );
        })}
      </div>
      {active && (
        <div
          role="tabpanel"
          id={`${base}-panel-${active.id}`}
          aria-labelledby={`${base}-tab-${active.id}`}
          tabIndex={0}
          className="pt-5"
        >
          {active.content}
        </div>
      )}
    </div>
  );
}
