"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, FeatureSearchResponse } from "@/lib/api";
import { useProjectSummary, useSharedProject } from "@/lib/useProject";
import {
  Card,
  EmptyState,
  ErrorBanner,
  LayerBadge,
  MetricCard,
  PageHeader,
  PromptField,
  StatusPill,
} from "@/components/ui";

export default function FeatureExplorerPage() {
  return (
    <Suspense fallback={null}>
      <FeatureExplorerPageInner />
    </Suspense>
  );
}

function FeatureExplorerPageInner() {
  const { path, group, ready } = useSharedProject();
  const { name: projectName, mode } = useProjectSummary(path);
  // A deep link from Model Explorer's Columns tab ("compare this
  // column") lands here as ?q=name.
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [result, setResult] = useState<FeatureSearchResponse | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !path || !query) {
      setResult(null);
      return;
    }
    setError(null);
    api
      .searchFeatures(path, query, group)
      .then((r) => {
        setResult(r);
        setSelectedName(r.matching_names[0] ?? "");
      })
      .catch((err) => setError(err.message));
  }, [ready, path, group, query]);

  if (!ready) return null;
  if (!path) {
    return (
      <EmptyState
        title="No project selected yet"
        body="Head to Select Project to point at a dbt project first."
      />
    );
  }

  const matches = result?.matches[selectedName] ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="feature-explorer --compare"
        title="Feature explorer"
        caption="Search a column name and compare every model that produces it, side by side."
        right={<StatusPill projectName={projectName ?? path.split("/").pop() ?? path} group={group} mode={mode} />}
      />
      {error && <ErrorBanner message={error} />}

      <div className="mb-4">
        <PromptField prompt="find">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="column name…"
            className="w-full bg-transparent font-mono text-sm text-text-hi outline-none placeholder:text-text-lo"
          />
        </PromptField>
      </div>

      {query && result?.matching_names.length === 0 && (
        <EmptyState title={`No columns matching "${query}"`} />
      )}

      {result && result.matching_names.length > 1 && (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {result.matching_names.map((name) => (
            <button
              key={name}
              onClick={() => setSelectedName(name)}
              className={`rounded-full border px-3 py-1 font-mono text-sm transition-colors ${
                name === selectedName
                  ? "border-accent bg-accent-dim text-text-hi"
                  : "border-line text-text-lo hover:text-text-hi"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {matches.length > 0 && (
        <>
          <div className="mb-4 grid grid-cols-4 gap-3">
            <MetricCard label="Models" value={matches.length} />
            <MetricCard
              label="Documented"
              value={`${matches.filter((m) => m.description).length}/${matches.length}`}
            />
            <MetricCard label="Owned" value={`${matches.filter((m) => m.owner).length}/${matches.length}`} />
            <MetricCard
              label="Tested"
              value={`${matches.filter((m) => m.test_count > 0).length}/${matches.length}`}
            />
          </div>

          <div className="overflow-hidden rounded-lg border border-line">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line bg-ink-900 font-mono text-text-lo">
                  <th className="px-3 py-2 font-normal">layer</th>
                  <th className="px-3 py-2 font-normal">model</th>
                  <th className="px-3 py-2 font-normal">description</th>
                  <th className="px-3 py-2 font-normal">owner</th>
                  <th className="px-3 py-2 font-normal">tags</th>
                  <th className="px-3 py-2 font-normal text-right">tests</th>
                  <th className="px-3 py-2 font-normal text-right">lineage</th>
                </tr>
              </thead>
              <tbody>
                {matches.map((m) => (
                  <tr key={m.model} className="border-b border-line/60">
                    <td className="px-3 py-2">
                      <LayerBadge layer={m.layer} />
                    </td>
                    <td className="px-3 py-2 font-mono">
                      <Link
                        href={`/models?model=${encodeURIComponent(m.model)}`}
                        className="text-text-hi underline decoration-line underline-offset-2 transition-colors hover:text-accent hover:decoration-accent"
                      >
                        {m.model}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-text-lo">{m.description || <span className="text-line">—</span>}</td>
                    <td className="px-3 py-2 text-text-lo">{m.owner || <span className="text-line">—</span>}</td>
                    <td className="px-3 py-2">
                      {m.tags.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {m.tags.map((tag) => (
                            <span
                              key={tag}
                              className="rounded-full border border-line px-2 py-0.5 font-mono text-[10px] text-text-lo"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-line">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex items-center justify-end gap-1.5 font-mono text-text-hi">
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ background: m.test_count > 0 ? "var(--accent)" : "var(--line)" }}
                        />
                        {m.test_count}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Link
                        href={`/lineage?model=${encodeURIComponent(m.model)}&column=${encodeURIComponent(
                          selectedName
                        )}&layer=${encodeURIComponent(m.layer)}`}
                        className="font-mono text-xs text-text-lo transition-colors hover:text-accent"
                        title={`Trace ${m.model}.${selectedName} in Column Lineage`}
                      >
                        trace →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!query && <Card className="text-sm text-text-lo">Type a column name to search across the project.</Card>}
    </div>
  );
}
