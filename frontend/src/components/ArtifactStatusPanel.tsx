"use client";

import { useState } from "react";
import type { ArtifactStatus, DbtIssue } from "@/lib/api";

/**
 * Where this project's lineage comes from (manifest vs raw-SQL parsing),
 * which dbt wrote the manifest, and -- when a `dbt parse` run complained --
 * what dbt said, as a list of file:line issues instead of a wall of
 * terminal output. dbt 2.0 exits non-zero for config it merely *ignores*
 * (a top-level `meta:` and so on) while still writing a usable manifest,
 * so "manifest mode, with errors" is a real, common state worth showing
 * precisely.
 */
export function ArtifactStatusPanel({
  status,
  generating,
  onGenerate,
}: {
  status: ArtifactStatus | null;
  generating: boolean;
  onGenerate: () => void;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const mode = status?.mode ?? "static";
  const degraded = mode === "static" || status?.level === "warning";
  const issues = status?.issues ?? [];
  const headline =
    status?.headline ?? status?.display_message ?? "No manifest found — parsing raw SQL only.";
  // dbt 1.x (or a crash) gives unstructured output: show it raw.
  const rawOutput = issues.length === 0 && status?.message ? status.message : null;

  return (
    <div
      className={`rounded-md border ${
        degraded ? "border-amber-900/50 bg-amber-950/20" : "border-line bg-ink-900"
      }`}
    >
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <p className="font-mono text-xs text-text-lo">
            <span className={degraded ? "text-amber-400" : "text-accent"}>
              {mode === "manifest" ? "●" : "○"}
            </span>{" "}
            {mode} mode
            {status?.dbt_version && <span> · written by dbt {status.dbt_version}</span>}
          </p>
          <p className="mt-0.5 text-sm text-text-hi">{headline}</p>
        </div>
        <button
          onClick={onGenerate}
          disabled={generating}
          className="shrink-0 rounded-md border border-line px-3.5 py-2 font-mono text-xs text-text-hi transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
        >
          {generating ? "running dbt parse…" : mode === "manifest" ? "re-parse" : "generate artifacts →"}
        </button>
      </div>

      {issues.length > 0 && <IssueList issues={issues} />}

      {rawOutput && (
        <div className="border-t border-amber-900/40 px-4 py-2.5">
          <button
            onClick={() => setShowRaw((v) => !v)}
            className="font-mono text-xs text-amber-300 hover:text-text-hi"
            aria-expanded={showRaw}
          >
            {showRaw ? "▾ hide dbt output" : "▸ show dbt output"}
          </button>
          {showRaw && (
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-lo">
              {rawOutput}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function IssueList({ issues }: { issues: DbtIssue[] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? issues : issues.slice(0, 4);
  const byKind = issues.reduce<Record<string, number>>((acc, i) => {
    acc[i.kind] = (acc[i.kind] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="border-t border-amber-900/40 px-4 py-3">
      <p className="mb-2 font-mono text-xs text-amber-300">
        dbt reported {issues.length} issue{issues.length === 1 ? "" : "s"} —{" "}
        {Object.entries(byKind)
          .map(([kind, n]) => `${n}× ${kind}`)
          .join(", ")}
      </p>
      <ul className="flex flex-col gap-1.5">
        {visible.map((issue, i) => (
          <li key={`${issue.file}:${issue.line}:${i}`} className="text-xs leading-relaxed">
            <span className="font-mono text-text-lo">
              {issue.file ?? "project"}
              {issue.line ? `:${issue.line}` : ""}
            </span>{" "}
            <span className="text-text-hi">{issue.message}</span>{" "}
            <span className="font-mono text-text-lo">({issue.code})</span>
          </li>
        ))}
      </ul>
      {issues.length > 4 && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 font-mono text-xs text-amber-300 hover:text-text-hi"
        >
          {expanded ? "show fewer" : `show all ${issues.length}`}
        </button>
      )}
    </div>
  );
}
