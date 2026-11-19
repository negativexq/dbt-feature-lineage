"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, ModelDagResponse } from "@/lib/api";
import { useProjectSummary, useSharedProject } from "@/lib/useProject";
import { Card, EmptyState, ErrorBanner, PageHeader, StatusPill } from "@/components/ui";
import { FlowGraph, FlowEdgeSpec, FlowNodeSpec, layerColor } from "@/components/FlowGraph";

/** The model plus every ancestor and descendant -- dbt's `+model+`. */
function lineageOf(start: string, edges: { source: string; target: string }[]): Set<string> {
  const ids = new Set<string>([start]);
  for (const [from, to] of [
    ["source", "target"],
    ["target", "source"],
  ] as const) {
    const stack = [start];
    while (stack.length) {
      const current = stack.pop()!;
      for (const e of edges) {
        if (e[from] === current && !ids.has(e[to])) {
          ids.add(e[to]);
          stack.push(e[to]);
        }
      }
    }
  }
  return ids;
}

export default function ModelDagPage() {
  const { path, group, ready } = useSharedProject();
  const { name: projectName, mode, dbtVersion } = useProjectSummary(path);
  const [dag, setDag] = useState<ModelDagResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState(false);
  const [finder, setFinder] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !path) return;
    setError(null);
    api
      .getModelDag(path, group)
      .then((d) => {
        setDag(d);
        setSelected(null);
      })
      .catch((err) => setError(err.message));
  }, [ready, path, group]);

  // Focus mode = dbt's `+model+` selector: the selected model plus every
  // ancestor and descendant, laid out on their own so a large project's
  // DAG becomes readable around one model.
  const focusIds = useMemo(
    () => (dag && selected && focus ? lineageOf(selected, dag.edges) : null),
    [dag, selected, focus]
  );

  const finderMatches = useMemo(() => {
    const q = finder.trim().toLowerCase();
    if (!dag || !q) return [];
    return dag.nodes.filter((n) => n.id.toLowerCase().includes(q)).slice(0, 8);
  }, [dag, finder]);

  if (!ready) return null;
  if (!path) {
    return (
      <EmptyState
        title="No project selected yet"
        body="Head to Select Project to point at a dbt project first."
      />
    );
  }

  const visibleNodes = dag?.nodes.filter((n) => !focusIds || focusIds.has(n.id)) ?? [];
  const nodes: FlowNodeSpec[] =
    visibleNodes.map((n) => ({
      id: n.id,
      label: n.id,
      sublabel: `${n.materialization ?? "unknown"} · ${n.column_count} cols`,
      color: layerColor(n.layer),
    }));
  const edges: FlowEdgeSpec[] =
    dag?.edges
      .filter((e) => !focusIds || (focusIds.has(e.source) && focusIds.has(e.target)))
      .map((e) => ({ id: `${e.source}->${e.target}`, source: e.source, target: e.target })) ?? [];
  const selectedPanel = dag?.nodes.find((n) => n.id === selected)?.panel;
  const legend = Array.from(new Set(dag?.nodes.map((n) => n.layer) ?? [])).map((l) => ({
    label: l,
    color: layerColor(l),
  }));

  return (
    <div>
      <PageHeader
        eyebrow="model-dag --project-wide"
        title="Model DAG"
        caption="The whole project's model-level ref()/source() dependency graph."
        right={<StatusPill projectName={projectName ?? path.split("/").pop() ?? path} group={group} mode={mode} dbtVersion={dbtVersion} />}
      />
      {error && <ErrorBanner message={error} />}
      {dag?.warnings.length ? (
        <div className="mb-4 rounded-md border border-amber-900/50 bg-amber-950/20 px-3 py-2 font-mono text-sm text-amber-300">
          {dag.warnings.length} warning(s): {dag.warnings.join(" · ")}
        </div>
      ) : null}

      {!dag ? (
        <p className="font-mono text-sm text-text-lo">loading…</p>
      ) : (
        <div className="flex gap-4">
          <div className="min-w-0 flex-1">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <div className="relative">
                <input
                  value={finder}
                  onChange={(e) => setFinder(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && finderMatches[0]) {
                      setSelected(finderMatches[0].id);
                      setFinder("");
                    }
                    if (e.key === "Escape") setFinder("");
                  }}
                  placeholder="find model…"
                  aria-label="Find a model in the DAG"
                  className="w-64 rounded-md border border-line bg-ink-900 px-3 py-1.5 font-mono text-sm text-text-hi outline-none placeholder:text-text-lo focus:border-accent"
                />
                {finderMatches.length > 0 && (
                  <ul className="absolute left-0 top-full z-20 mt-1 w-64 overflow-hidden rounded-md border border-line bg-ink-900 shadow-lg">
                    {finderMatches.map((n) => (
                      <li key={n.id}>
                        <button
                          onClick={() => {
                            setSelected(n.id);
                            setFinder("");
                          }}
                          className="flex w-full items-center gap-2 px-3 py-1.5 text-left font-mono text-sm text-text-hi hover:bg-ink-950"
                        >
                          <span className="h-1.5 w-1.5 rounded-full" style={{ background: layerColor(n.layer) }} />
                          {n.id}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <label
                className={`flex items-center gap-2 font-mono text-sm ${selected ? "text-text-hi" : "text-text-lo"}`}
                title={selected ? undefined : "Select a model first"}
              >
                <input
                  type="checkbox"
                  checked={focus}
                  disabled={!selected}
                  onChange={(e) => setFocus(e.target.checked)}
                  className="accent-[var(--accent)]"
                />
                focus on +{selected ?? "model"}+
              </label>
              <span className="ml-auto font-mono text-xs text-text-lo">
                {nodes.length} of {dag.nodes.length} models
              </span>
            </div>
            <FlowGraph
              key={focusIds ? `focus-${selected}` : "all"}
              nodes={nodes}
              edges={edges}
              height={560}
              onNodeClick={(id) => {
                setSelected(id || null);
                if (!id) setFocus(false);
              }}
              selectedId={selected}
              legend={legend}
            />
          </div>
          <Card className="w-64 shrink-0">
            <p className="eyebrow mb-2">details</p>
            {selectedPanel ? (
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  {Object.entries(selectedPanel).map(([k, v]) => (
                    <div key={k}>
                      <p className="font-mono text-sm text-text-lo">{k}</p>
                      <p className="text-sm text-text-hi">{v}</p>
                    </div>
                  ))}
                </div>
                {selected && (
                  <Link
                    href={`/models?model=${encodeURIComponent(selected)}`}
                    className="mt-1 inline-flex items-center gap-1 font-mono text-sm text-accent transition-colors hover:text-text-hi"
                  >
                    open in model explorer →
                  </Link>
                )}
              </div>
            ) : (
              <p className="text-sm text-text-lo">Click a node to see its details here.</p>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
