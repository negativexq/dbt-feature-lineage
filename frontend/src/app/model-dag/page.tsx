"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ModelDagResponse } from "@/lib/api";
import { useProjectSummary, useSharedProject } from "@/lib/useProject";
import { Card, EmptyState, ErrorBanner, PageHeader, StatusPill } from "@/components/ui";
import { FlowGraph, FlowEdgeSpec, FlowNodeSpec, layerColor } from "@/components/FlowGraph";

export default function ModelDagPage() {
  const { path, group, ready } = useSharedProject();
  const { name: projectName, mode } = useProjectSummary(path);
  const [dag, setDag] = useState<ModelDagResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
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

  if (!ready) return null;
  if (!path) {
    return (
      <EmptyState
        title="No project selected yet"
        body="Head to Select Project to point at a dbt project first."
      />
    );
  }

  const nodes: FlowNodeSpec[] =
    dag?.nodes.map((n) => ({
      id: n.id,
      label: n.id,
      sublabel: `${n.materialization ?? "unknown"} · ${n.column_count} cols`,
      color: layerColor(n.layer),
    })) ?? [];
  const edges: FlowEdgeSpec[] =
    dag?.edges.map((e) => ({ id: `${e.source}->${e.target}`, source: e.source, target: e.target })) ?? [];
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
        right={<StatusPill projectName={projectName ?? path.split("/").pop() ?? path} group={group} mode={mode} />}
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
          <div className="flex-1">
            <FlowGraph
              nodes={nodes}
              edges={edges}
              height={560}
              onNodeClick={setSelected}
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
