"use client";

/**
 * "Recently viewed" -- the one piece of state a command palette like
 * this one is missing without it: on an empty query it can only ever
 * suggest pages, never "the three things you were just looking at",
 * which is the whole point of a jump box in a tool with dozens of
 * models. localStorage-backed, same pattern as useProject.ts's shared
 * project state -- this is a single-user local tool, no server session
 * to keep it in.
 */

const KEY = "dfl.recent";
const MAX_ENTRIES = 8;

export interface RecentView {
  label: string;
  hint: string;
  href: string;
  viewedAt: number;
}

export function recordRecentView(entry: Omit<RecentView, "viewedAt">) {
  if (typeof window === "undefined") return;
  try {
    const existing = getRecentViews().filter((e) => e.href !== entry.href);
    const next = [{ ...entry, viewedAt: Date.now() }, ...existing].slice(0, MAX_ENTRIES);
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // localStorage can throw (private browsing, quota) -- recent-view
    // tracking is a convenience, never worth breaking the page over.
  }
}

export function getRecentViews(): RecentView[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
