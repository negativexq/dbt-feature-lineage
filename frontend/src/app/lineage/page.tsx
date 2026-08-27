"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, ColumnMatch, LineageChainResponse } from "@/lib/api";
import { useProjectSummary, useSharedProject } from "@/lib/useProject";
import { Card, EmptyState, ErrorBanner, MetricCard, PageHeader, PromptField, StatusPill } from "@/components/ui";
import { FlowGraph, FlowEdgeSpec, FlowNodeSpec, layerColor } from "@/components/FlowGraph";
import { SqlCode } from "@/components/SqlCode";
import { recordRecentView } from "@/lib/useRecentlyViewed";

/**
 * Combines the upstream and downstream chain into one graph instead of
 * a direction toggle that only ever shows half the picture -- the
 * target column sits in the middle, its raw sources flow in from the
 * left, everything it feeds flows out to the right. "Where did this
 * come from, and what does it affect" answered in one view, since
 * both chains were already two cheap, independent queries against the
 * same already-built lineage graph (no new backend cost, just not
 * throwing half the answer away).
 */
export default function ColumnLineagePage() {
  return (
    <Suspense fallback={null}>
      <ColumnLineagePageInner />
    </Suspense>
  );
}

function ColumnLineagePageInner() {
  const { path, group, ready } = useSharedProject();
  const { name: projectName, mode } = useProjectSummary(path);
  // Two deep-link shapes land here: a general ?q=name from Model
  // Explorer/Feature Explorer's page-level search (falls into the same
  // search+disambiguate flow a manual search would), or an exact
  // ?model=&column=&layer= from Feature Explorer's per-row "trace" link,
  // which already knows precisely which column identity to jump to and
  // skips the search round-trip entirely.
  const searchParams = useSearchParams();
  const deepLinkModel = searchParams.get("model");
  const deepLinkColumn = searchParams.get("column");
  const deepLinkLayer = searchParams.get("layer");
  const hasExactDeepLink = Boolean(deepLinkModel && deepLinkColumn && deepLinkLayer);

  const [query, setQuery] = useState(deepLinkColumn ?? searchParams.get("q") ?? "");
  const [matches, setMatches] = useState<ColumnMatch[]>(
    hasExactDeepLink
      ? [
          {
            model: deepLinkModel!,
            column: deepLinkColumn!,
            layer: deepLinkLayer!,
            key: `${deepLinkModel}.${deepLinkColumn}`,
          },
        ]
      : []
  );
  const [selectedKey, setSelectedKey] = useState<string>(
    hasExactDeepLink ? `${deepLinkModel}.${deepLinkColumn}` : ""
  );
  const [upstream, setUpstream] = useState<LineageChainResponse | null>(null);
  const [downstream, setDownstream] = useState<LineageChainResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pathHighlight, setPathHighlight] = useState<string | null>(null);

  useEffect(() => {
    // The exact deep-link case already has its one match seeded above --
    // searching again would just be a slower way to arrive at the same
    // place (and could reorder/duplicate it if the search API's own
    // sort differs).
    if (hasExactDeepLink) return;
    if (!ready || !path || !query) {
      setMatches([]);
      return;
    }
    api
      .searchColumns(path, query, group)
      .then((m) => {
        setMatches(m);
        setSelectedKey(m[0]?.key ?? "");
      })
      .catch((err) => setError(err.message));
  }, [ready, path, group, query, hasExactDeepLink]);

  const target = useMemo(() => matches.find((m) => m.key === selectedKey) ?? null, [matches, selectedKey]);

  useEffect(() => {
    if (!path || !target) {
      setUpstream(null);
      setDownstream(null);
      return;
    }
    setError(null);
    setPathHighlight(null);
    recordRecentView({
      label: `${target.model}.${target.column}`,
      hint: `trace in ${target.layer}`,
      href: `/lineage?model=${encodeURIComponent(target.model)}&column=${encodeURIComponent(
        target.column
      )}&layer=${encodeURIComponent(target.layer)}`,
    });
    const base = { path, model: target.model, column: target.column, layer: target.layer, group };
    Promise.all([
      api.getLineageChain({ ...base, direction: "upstream" }),
      api.getLineageChain({ ...base, direction: "downstream", impact: true }),
    ])
      .then(([up, down]) => {
        setUpstream(up);
        setDownstream(down);
      })
      .catch((err) => setError(err.message));
  }, [path, target, group]);

  if (!ready) return null;
  if (!path) {
    return (
      <EmptyState
        title="No project selected yet"
        body="Head to Select Project to point at a dbt project first."
      />
    );
  }

  const targetKey = target ? `${target.model}.${target.column}` : null;

  // Merge: upstream chain + downstream chain, de-duplicating the shared
  // target node (chain[0] in both responses).
  const nodeMap = new Map<string, FlowNodeSpec>();
  for (const n of [...(upstream?.nodes ?? []), ...(downstream?.nodes ?? [])]) {
    nodeMap.set(n.key, { id: n.key, label: n.column, sublabel: n.model, color: layerColor(n.layer) });
  }
  const nodes = Array.from(nodeMap.values());
  const rawEdges = [...(upstream?.edges ?? []), ...(downstream?.edges ?? [])];
  const edges: FlowEdgeSpec[] = rawEdges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    // "unknown" is a real, meaningful classification in the
    // Transformations panel (it's the parser's honest "couldn't
    // classify this expression" answer) -- but as a floating label on
    // every other edge in the graph it reads as broken, not honest. So
    // it's shown there, just not repeated as visual noise on the graph.
    label: e.transformation_type === "unknown" ? undefined : e.transformation_type,
  }));
  const labelByKey = new Map(nodes.map((n) => [n.id, n.label]));
  const modelByKey = new Map(nodes.map((n) => [n.id, n.sublabel]));
  const legend = Array.from(new Set([...(upstream?.nodes ?? []), ...(downstream?.nodes ?? [])].map((n) => n.layer))).map(
    (l) => ({ label: l, color: layerColor(l) })
  );

  const hasUpstream = (upstream?.nodes.length ?? 0) > 1;
  const hasDownstream = (downstream?.nodes.length ?? 0) > 1;
  const impact = downstream?.impact_summary;

  return (
    <div>
      <PageHeader
        eyebrow="column-lineage --trace"
        title="Column lineage"
        caption="Search a column and see its full path at once — raw sources on the left, everything it feeds on the right."
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

      {matches.length > 1 && (
        <div className="mb-4">
          <PromptField prompt="pick">
            <select
              value={selectedKey}
              onChange={(e) => setSelectedKey(e.target.value)}
              className="w-full bg-transparent font-mono text-sm text-text-hi outline-none"
            >
              {matches.map((m) => (
                <option key={m.key} value={m.key} className="bg-ink-900">
                  {m.model}.{m.column} ({m.layer})
                </option>
              ))}
            </select>
          </PromptField>
        </div>
      )}

      {query && matches.length === 0 && <EmptyState title={`No columns matching "${query}"`} />}

      {target && (
        <>
          {!hasUpstream && !hasDownstream ? (
            <EmptyState
              title="This column stands alone"
              body="No traceable upstream sources and nothing in this project consumes it."
            />
          ) : (
            <div className="flex gap-4">
              <div className="flex-1">
                <FlowGraph
                  nodes={nodes}
                  edges={edges}
                  height={440}
                  selectedId={pathHighlight ?? targetKey}
                  onNodeClick={setPathHighlight}
                  legend={legend}
                />
              </div>
              <Card className="w-80 shrink-0 overflow-auto" style={{ maxHeight: 440 }}>
                <p className="eyebrow mb-3">transformations</p>
                <div className="flex flex-col gap-4">
                  {rawEdges.map((e) => {
                    const sourceKey = e.source;
                    const targetKeyStr = e.target;
                    return (
                      <div key={`${sourceKey}->${targetKeyStr}`} className="border-l-2 border-line pl-3">
                        <p className="break-words font-mono text-xs text-text-lo">
                          <span className="text-text-hi">{modelByKey.get(sourceKey)}</span>.
                          {labelByKey.get(sourceKey)}
                        </p>
                        <p className="my-0.5 text-accent">↓</p>
                        <p className="break-words font-mono text-xs text-text-lo">
                          <span className="text-text-hi">{modelByKey.get(targetKeyStr)}</span>.
                          {labelByKey.get(targetKeyStr)}
                        </p>
                        {e.transformation_type !== "unknown" && (
                          <span className="mt-1 inline-block rounded-full border border-line px-2 py-0.5 font-mono text-[10px] text-text-lo">
                            {e.transformation_type}
                          </span>
                        )}
                        {e.expression_sql ? (
                          <SqlCode sql={e.expression_sql} className="mt-1.5 !p-2 !text-[11px]" />
                        ) : (
                          <p className="mt-1.5 rounded-md bg-ink-950 p-2 font-mono text-[11px] text-text-lo">—</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </Card>
            </div>
          )}

          {impact && impact.affected_model_count > 0 && (
            <div className="mt-6">
              <p className="eyebrow mb-3">downstream impact</p>
              <div className="mb-4 grid grid-cols-2 gap-3">
                <MetricCard label="Affected models" value={impact.affected_model_count} />
                <MetricCard label="Affected columns" value={impact.affected_column_count} />
              </div>

              {impact.affected_exposures.length > 0 && (
                <div className="mb-4 rounded-lg border border-amber-900/50 bg-amber-950/20 p-4">
                  <p className="mb-2.5 flex items-center gap-2 font-mono text-xs text-amber-300">
                    <span>&#9650;</span>
                    {impact.affected_exposures.length} exposure(s) affected — a dashboard or downstream consumer
                    reads this
                  </p>
                  <div className="flex flex-col gap-2">
                    {impact.affected_exposures.map((e) => (
                      <div key={e.name} className="flex items-center justify-between gap-3">
                        <div>
                          <p className="font-mono text-sm text-text-hi">
                            {e.name}
                            {e.exposure_type && (
                              <span className="ml-2 text-xs text-text-lo">({e.exposure_type})</span>
                            )}
                          </p>
                          <p className="text-xs text-text-lo">
                            via {e.via_models.join(", ")}
                            {e.owner && <> · owned by {e.owner}</>}
                          </p>
                        </div>
                        {e.url && (
                          <a
                            href={e.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="shrink-0 font-mono text-xs text-amber-300 underline decoration-amber-800 underline-offset-2 hover:text-amber-200"
                          >
                            open →
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="overflow-hidden rounded-lg border border-line">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-line bg-ink-900 font-mono text-text-lo">
                      <th className="px-3 py-2 font-normal">model</th>
                      <th className="px-3 py-2 font-normal">columns</th>
                    </tr>
                  </thead>
                  <tbody>
                    {impact.all_impacted.map((row) => (
                      <tr key={row.model} className="border-b border-line/60">
                        <td className="px-3 py-2 font-mono text-text-hi">{row.model}</td>
                        <td className="px-3 py-2 text-text-lo">{row.columns.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {!query && <Card className="text-sm text-text-lo">Type a column name to search across the project.</Card>}
    </div>
  );
}
