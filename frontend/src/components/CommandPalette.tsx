"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ColumnMatch, ModelSummary } from "@/lib/api";
import { useSharedProject } from "@/lib/useProject";
import { layerColor } from "@/components/ui";
import { getRecentViews } from "@/lib/useRecentlyViewed";

const PAGES = [
  { href: "/", label: "select-project", hint: "switch project" },
  { href: "/dashboard", label: "dashboard", hint: "project overview" },
  { href: "/models", label: "model-explorer", hint: "inspect a model" },
  { href: "/model-dag", label: "model-dag", hint: "project-wide graph" },
  { href: "/lineage", label: "column-lineage", hint: "trace a column" },
  { href: "/features", label: "feature-explorer", hint: "compare a column" },
];

type Item =
  | { kind: "page"; key: string; label: string; hint: string; href: string }
  | { kind: "model"; key: string; label: string; hint: string; href: string }
  | { kind: "column"; key: string; label: string; hint: string; href: string }
  | { kind: "recent"; key: string; label: string; hint: string; href: string };

/**
 * Global ⌘K / Ctrl+K jump box. The app already treats every view as a
 * real URL (?model=, ?column=, ?q=) rather than client-only state --
 * this is just a fast, keyboard-driven way to compose those URLs
 * instead of clicking through model list -> tab -> row every time.
 * Mounted once in AppShell so it works from any page.
 */
export function CommandPalette() {
  const router = useRouter();
  const { path, group, ready } = useSharedProject();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [columns, setColumns] = useState<ColumnMatch[]>([]);
  const [recent, setRecent] = useState<ReturnType<typeof getRecentViews>>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setColumns([]);
    setActiveIndex(0);
  }, []);

  // ⌘K / Ctrl+K opens from anywhere; Escape closes.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    // Lets the header's visible "⌘K" hint trigger the same open path as
    // the shortcut, for anyone who reaches for a mouse instead.
    const onOpenEvent = () => setOpen(true);
    window.addEventListener("open-command-palette", onOpenEvent);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("open-command-palette", onOpenEvent);
    };
  }, []);

  useEffect(() => {
    if (open) {
      // Focus needs a tick -- the input isn't in the DOM yet on the same
      // render the keydown handler flips `open`.
      requestAnimationFrame(() => inputRef.current?.focus());
      // Read fresh each open rather than once on mount -- a model/column
      // viewed since the palette was last opened should show up without
      // a full page reload.
      setRecent(getRecentViews());
    }
  }, [open]);

  // Model list is cheap and small -- load it once per project on open,
  // filter client-side as the user types.
  useEffect(() => {
    if (!open || !ready || !path) return;
    api.listModels(path, group).then(setModels).catch(() => setModels([]));
  }, [open, ready, path, group]);

  useEffect(() => {
    if (!open || !ready || !path || !query) {
      setColumns([]);
      return;
    }
    const handle = setTimeout(() => {
      api.searchColumns(path, query, group).then(setColumns).catch(() => setColumns([]));
    }, 150);
    return () => clearTimeout(handle);
  }, [open, ready, path, group, query]);

  const items = useMemo<Item[]>(() => {
    const q = query.trim().toLowerCase();
    const pageItems: Item[] = PAGES.filter((p) => !q || p.label.includes(q) || p.hint.toLowerCase().includes(q)).map(
      (p) => ({ kind: "page", key: `page:${p.href}`, label: p.label, hint: p.hint, href: p.href })
    );
    const modelItems: Item[] = (q ? models.filter((m) => m.name.toLowerCase().includes(q)) : []).slice(0, 6).map((m) => ({
      kind: "model",
      key: `model:${m.name}`,
      label: m.name,
      hint: `${m.layer} model`,
      href: `/models?model=${encodeURIComponent(m.name)}`,
    }));
    const columnItems: Item[] = columns.slice(0, 8).map((c) => ({
      kind: "column",
      key: `column:${c.key}`,
      label: `${c.model}.${c.column}`,
      hint: `trace in ${c.layer}`,
      href: `/lineage?model=${encodeURIComponent(c.model)}&column=${encodeURIComponent(c.column)}&layer=${encodeURIComponent(
        c.layer
      )}`,
    }));
    const recentItems: Item[] = recent.map((r) => ({
      kind: "recent",
      key: `recent:${r.href}`,
      label: r.label,
      hint: r.hint,
      href: r.href,
    }));
    return q ? [...modelItems, ...columnItems, ...pageItems] : [...recentItems, ...pageItems];
  }, [query, models, columns, recent]);

  useEffect(() => setActiveIndex(0), [items.length, query]);

  const activate = useCallback(
    (item: Item | undefined) => {
      if (!item) return;
      router.push(item.href);
      close();
    },
    [router, close]
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink-950/70 pt-[14vh] backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-lg border border-line bg-ink-900 shadow-[0_24px_64px_-16px_rgba(0,0,0,0.7)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-line px-4 py-3.5">
          <span className="font-mono text-sm text-accent">$</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActiveIndex((i) => Math.min(i + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveIndex((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                activate(items[activeIndex]);
              }
            }}
            placeholder={path ? "jump to a model, a column, or a page…" : "select a project first…"}
            className="w-full bg-transparent font-mono text-sm text-text-hi outline-none placeholder:text-text-lo"
          />
          <kbd className="shrink-0 rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-text-lo">esc</kbd>
        </div>

        <div className="max-h-80 overflow-auto py-1.5">
          {items.length === 0 && (
            <p className="px-4 py-6 text-center font-mono text-sm text-text-lo">
              {query ? `No matches for "${query}"` : "No pages match."}
            </p>
          )}
          {items.map((item, i) => (
            <div key={item.key}>
              {item.kind === "recent" && i === 0 && (
                <p className="px-4 pb-1 pt-2 font-mono text-[10px] uppercase tracking-wide text-text-lo">recent</p>
              )}
              {item.kind === "page" && items[i - 1]?.kind !== "page" && (
                <p className="px-4 pb-1 pt-3 font-mono text-[10px] uppercase tracking-wide text-text-lo">pages</p>
              )}
              <button
                onClick={() => activate(item)}
                onMouseEnter={() => setActiveIndex(i)}
                className={`flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors ${
                  i === activeIndex ? "bg-accent-dim" : ""
                }`}
              >
              <span className="flex min-w-0 items-center gap-2.5">
                {(item.kind === "model" || item.kind === "column") && (
                  <span
                    className="h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{
                      background:
                        item.kind === "model"
                          ? layerColor(models.find((m) => `model:${m.name}` === item.key)?.layer)
                          : layerColor(columns.find((c) => `column:${c.key}` === item.key)?.layer),
                    }}
                  />
                )}
                {item.kind === "recent" && <span className="shrink-0 text-xs text-text-lo">&#8635;</span>}
                <span className="truncate font-mono text-sm text-text-hi">{item.label}</span>
              </span>
              <span className="shrink-0 font-mono text-xs text-text-lo">{item.hint}</span>
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
