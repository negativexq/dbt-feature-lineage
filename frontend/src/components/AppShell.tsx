"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CommandPalette } from "@/components/CommandPalette";

const NAV_ITEMS = [
  { href: "/", label: "select-project" },
  { href: "/dashboard", label: "dashboard" },
  { href: "/models", label: "model-explorer" },
  { href: "/model-dag", label: "model-dag" },
  { href: "/lineage", label: "column-lineage" },
  { href: "/features", label: "feature-explorer" },
];

/**
 * Deliberately NOT a boxed left sidebar with pill-highlighted links --
 * that's the exact shape Streamlit's own default nav takes, and this
 * project is specifically trying to read as a distinct, engineered tool
 * rather than "a themed Streamlit app." Instead: a terminal/editor
 * tab-bar metaphor across the top -- a command prompt, a row of open
 * "files" (pages) as underline tabs, no rounded pill backgrounds.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-ink-900/60 backdrop-blur">
        <div className="flex items-center justify-between gap-2 px-8 pb-4 pt-4">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-accent">&gt;</span>
            <span className="font-mono text-sm tracking-wide text-text-lo">
              dbt-feature-lineage
            </span>
          </div>
          <button
            onClick={() => window.dispatchEvent(new Event("open-command-palette"))}
            className="flex items-center gap-2 rounded-md border border-line px-2.5 py-1.5 font-mono text-xs text-text-lo transition-colors hover:border-accent hover:text-text-hi"
          >
            jump to…
            <kbd className="rounded border border-line px-1.5 py-0.5 text-[10px]">⌘K</kbd>
          </button>
        </div>
        <nav className="flex gap-2 border-t border-line/60 px-6 pt-4">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`border-b-2 px-3.5 pb-3 font-mono text-[15px] transition-colors ${
                  active
                    ? "border-accent text-text-hi"
                    : "border-transparent text-text-lo hover:text-text-hi"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-8 py-10">{children}</main>
      <CommandPalette />
    </div>
  );
}
