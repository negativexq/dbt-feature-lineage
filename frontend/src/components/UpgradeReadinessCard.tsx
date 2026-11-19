"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ReadinessFinding, ReadinessSeverity, UpgradeReadinessResponse } from "@/lib/api";
import { Card } from "@/components/ui";

const SEVERITY_ORDER: ReadinessSeverity[] = ["blocker", "error", "info"];
const SEVERITY_COLOR: Record<ReadinessSeverity, string> = {
  blocker: "var(--status-degraded)",
  error: "var(--status-caution)",
  info: "var(--layer-staging)",
};
const SEVERITY_HINT: Record<ReadinessSeverity, string> = {
  blocker: "dbt 2.0 can't parse the project",
  error: "dbt 2.0 ignores or rejects it",
  info: "works, but worth changing",
};

/**
 * "What breaks if we move to dbt 2.0?" -- answered from the project's own
 * YAML (services/upgrade_readiness.py), so it works on a project that is
 * still on dbt 1.x, which is exactly when the question gets asked.
 */
export function UpgradeReadinessCard({ path }: { path: string }) {
  const [data, setData] = useState<UpgradeReadinessResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<ReadinessSeverity | null>(null);

  useEffect(() => {
    api
      .getUpgradeReadiness(path)
      .then((d) => {
        setData(d);
        setFailed(false);
        // Open the most severe non-empty group by default.
        setOpen(SEVERITY_ORDER.find((s) => d.summary[s] > 0 && s !== "info") ?? null);
      })
      .catch(() => setFailed(true));
  }, [path]);

  const byFile = useMemo(() => {
    const groups = new Map<string, ReadinessFinding[]>();
    for (const f of data?.findings ?? []) {
      if (f.severity !== open) continue;
      groups.set(f.file, [...(groups.get(f.file) ?? []), f]);
    }
    return Array.from(groups.entries());
  }, [data, open]);

  if (failed) return null;

  const mustFix = data ? data.summary.blocker + data.summary.error : 0;

  return (
    <Card>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <p className="eyebrow">dbt 2.0 readiness</p>
        <code className="font-mono text-xs text-text-lo">dbt-feature-lineage check-upgrade .</code>
      </div>
      {!data ? (
        <p className="font-mono text-sm text-text-lo">scanning YAML…</p>
      ) : (
        <>
          <p className="mb-4 text-sm text-text-lo">
            {mustFix === 0
              ? "Nothing in this project's YAML breaks under dbt 2.0's stricter spec."
              : `${mustFix} change${mustFix === 1 ? "" : "s"} needed before dbt 2.0 parses this project the way 1.x does. Found by scanning YAML — no dbt install needed.`}
          </p>
          <div className="grid grid-cols-3 gap-3">
            {SEVERITY_ORDER.map((severity) => {
              const count = data.summary[severity];
              const active = open === severity;
              return (
                <button
                  key={severity}
                  onClick={() => setOpen((s) => (s === severity ? null : severity))}
                  disabled={count === 0}
                  aria-pressed={active}
                  className={`rounded-md border px-3.5 py-2.5 text-left transition-colors disabled:cursor-default disabled:opacity-50 ${
                    active ? "border-accent bg-ink-950" : "border-line hover:border-text-lo"
                  }`}
                >
                  <div className="flex items-center gap-2 font-mono text-xl text-text-hi">
                    <span className="h-2 w-2 rounded-full" style={{ background: SEVERITY_COLOR[severity] }} />
                    {count}
                    <span className="text-xs text-text-lo">{severity}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-text-lo">{SEVERITY_HINT[severity]}</p>
                </button>
              );
            })}
          </div>

          {open && byFile.length > 0 && (
            <div className="mt-5 flex flex-col gap-4 border-t border-line pt-4">
              {byFile.map(([file, findings]) => (
                <div key={file}>
                  <p className="mb-1.5 font-mono text-xs text-text-lo">{file}</p>
                  <ul className="flex flex-col gap-2">
                    {findings.map((f, i) => (
                      <li key={`${f.line}-${i}`} className="grid grid-cols-[3.5rem_1fr] gap-x-2 text-sm">
                        <span className="pt-px text-right font-mono text-xs text-text-lo">
                          {f.line ? `:${f.line}` : ""}
                        </span>
                        <div>
                          <p className="text-text-hi">
                            <InlineCode text={f.message} />
                          </p>
                          <p className="text-xs text-text-lo">
                            → <InlineCode text={f.fix} />
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/** Render `backticked` spans of a finding's text as inline code. */
function InlineCode({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`)/g).map((part, i) =>
        part.startsWith("`") && part.endsWith("`") ? (
          <code key={i} className="rounded bg-ink-950 px-1 py-px font-mono text-[0.9em] text-accent">
            {part.slice(1, -1)}
          </code>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}
