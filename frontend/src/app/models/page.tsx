"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, ModelAnalysis, ModelSummary, QueryFlowStep } from "@/lib/api";
import { useProjectSummary, useSharedProject } from "@/lib/useProject";
import {
  Card,
  EmptyState,
  ErrorBanner,
  LayerBadge,
  MetricCard,
  PageHeader,
  StatusPill,
} from "@/components/ui";
import { FlowGraph, FlowEdgeSpec, FlowNodeSpec, layerColor } from "@/components/FlowGraph";
import { SqlCode } from "@/components/SqlCode";
import { recordRecentView } from "@/lib/useRecentlyViewed";

const TABS = ["overview", "query-flow", "columns", "raw-sql"] as const;
type Tab = (typeof TABS)[number];

function stepColor(stepType: string): string {
  if (stepType === "output" || stepType === "final_select") return "var(--layer-marts)";
  if (stepType === "cte") return "var(--layer-intermediate)";
  return "var(--layer-unknown)";
}

function stepBadges(step: QueryFlowStep): string {
  const badges: string[] = [];
  if (step.join_types.length) badges.push(`${step.join_types.length} join`);
  if (step.has_where_clause) badges.push("filter");
  if (step.group_by_columns.length) badges.push("group by");
  if (step.window_functions.length) badges.push("window");
  return badges.length ? badges.join(" · ") : step.step_type;
}

export default function ModelExplorerPage() {
  return (
    <Suspense fallback={null}>
      <ModelExplorerPageInner />
    </Suspense>
  );
}

function ModelExplorerPageInner() {
  const { path, group, ready } = useSharedProject();
  const { name: projectName, mode } = useProjectSummary(path);
  // A deep link from Feature Explorer ("compare" -> "go inspect this
  // model") lands here as ?model=name -- read once on mount so the
  // model list's own default-first-model logic doesn't clobber it.
  const searchParams = useSearchParams();
  const deepLinkedModel = searchParams.get("model");
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(deepLinkedModel);
  const [search, setSearch] = useState("");
  const [analysis, setAnalysis] = useState<ModelAnalysis | null>(null);
  const [queryFlow, setQueryFlow] = useState<{ steps: QueryFlowStep[]; panels: Record<string, Record<string, string>> } | null>(null);
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !path) return;
    api
      .listModels(path, group)
      .then((list) => {
        setModels(list);
        setSelected((prev) => prev ?? list[0]?.name ?? null);
      })
      .catch((err) => setError(err.message));
  }, [ready, path, group]);

  // A ref-dependency/columns-tab link within this same page (e.g. "open
  // stg_loan_applications" from another model's overview) only changes
  // the ?model= query param -- Next.js doesn't remount this component
  // for a same-route navigation, so `selected`'s initial useState value
  // never sees the update on its own. Without this, clicking such a
  // link visibly does nothing.
  useEffect(() => {
    if (deepLinkedModel) setSelected(deepLinkedModel);
  }, [deepLinkedModel]);

  useEffect(() => {
    if (!path || !selected) return;
    setError(null);
    api
      .getModel(path, selected)
      .then((a) => {
        setAnalysis(a);
        recordRecentView({
          label: a.model_name,
          hint: `${a.layer} model`,
          href: `/models?model=${encodeURIComponent(a.model_name)}`,
        });
      })
      .catch((err) => setError(err.message));
    api
      .getQueryFlow(path, selected)
      .then((qf) => {
        setQueryFlow(qf);
        setSelectedStep(null);
      })
      .catch((err) => setError(err.message));
  }, [path, selected]);

  const filteredModels = useMemo(
    () => models.filter((m) => m.name.toLowerCase().includes(search.toLowerCase())),
    [models, search]
  );

  if (!ready) return null;
  if (!path) {
    return (
      <EmptyState
        title="No project selected yet"
        body="Head to Select Project to point at a dbt project first."
      />
    );
  }

  const flowNodes: FlowNodeSpec[] =
    queryFlow?.steps.map((s) => ({
      id: s.step_id,
      label: s.name,
      sublabel: stepBadges(s),
      color: stepColor(s.step_type),
    })) ?? [];
  const flowEdges: FlowEdgeSpec[] =
    queryFlow?.steps.flatMap((s) =>
      s.upstream_step_ids.map((up) => ({ id: `${up}->${s.step_id}`, source: up, target: s.step_id }))
    ) ?? [];
  const queryFlowLegend = [
    { label: "source", color: "var(--layer-unknown)" },
    { label: "cte", color: "var(--layer-intermediate)" },
    { label: "output", color: "var(--layer-marts)" },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="model-explorer --inspect"
        title="Model explorer"
        right={<StatusPill projectName={projectName ?? path.split("/").pop() ?? path} group={group} mode={mode} />}
      />
      {error && <ErrorBanner message={error} />}

      <div className="flex gap-6">
        <aside className="w-64 shrink-0">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="filter models…"
            className="mb-3 w-full rounded-md border border-line bg-ink-900 px-3 py-2 font-mono text-sm text-text-hi outline-none placeholder:text-text-lo focus:border-accent"
          />
          <div className="flex flex-col gap-0.5">
            {filteredModels.map((m) => (
              <button
                key={m.name}
                onClick={() => setSelected(m.name)}
                className={`flex items-center justify-between rounded-md px-2.5 py-1.5 text-left font-mono text-sm transition-colors ${
                  m.name === selected ? "bg-accent-dim text-text-hi" : "text-text-lo hover:text-text-hi"
                }`}
              >
                <span className="truncate">{m.name}</span>
                <span
                  className="ml-2 h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ background: layerColor(m.layer) }}
                />
              </button>
            ))}
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          {!analysis ? (
            <p className="font-mono text-sm text-text-lo">loading…</p>
          ) : (
            <>
              <div className="mb-5">
                <div className="flex flex-wrap items-center gap-3">
                  <h2 className="font-mono text-lg text-text-hi">{analysis.model_name}</h2>
                  <LayerBadge layer={analysis.layer} />
                  {analysis.materialization && (
                    <span className="rounded-full border border-line px-2 py-0.5 font-mono text-xs text-text-lo">
                      {analysis.materialization}
                    </span>
                  )}
                  {analysis.owner && (
                    <span className="font-mono text-xs text-text-lo">
                      owned by <span className="text-text-hi">{analysis.owner}</span>
                    </span>
                  )}
                </div>
                {analysis.description && <p className="mt-2 max-w-2xl text-sm text-text-lo">{analysis.description}</p>}
                {analysis.tags.length > 0 && (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {analysis.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full border border-line px-2 py-0.5 font-mono text-[10px] text-text-lo"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div className="mb-6 flex gap-1 border-b border-line">
                {TABS.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTab(t)}
                    className={`border-b-2 px-3 pb-2.5 font-mono text-sm transition-colors ${
                      tab === t ? "border-accent text-text-hi" : "border-transparent text-text-lo hover:text-text-hi"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>

              {tab === "overview" && (
                <div className="flex flex-col gap-5">
                  <div className="grid grid-cols-5 gap-3">
                    <MetricCard label="CTEs" value={analysis.cte_names.length} />
                    <MetricCard label="Joins" value={analysis.join_count} />
                    <MetricCard label="Output cols" value={analysis.output_columns.length} />
                    <MetricCard label="Sources" value={analysis.source_dependencies.length} />
                    <MetricCard label="Tests" value={analysis.test_count} />
                  </div>

                  {analysis.parsing_warnings.length > 0 && (
                    <div className="rounded-md border border-amber-900/50 bg-amber-950/20 px-4 py-3 font-mono text-sm text-amber-300">
                      {analysis.parsing_warnings.length} warning(s): {analysis.parsing_warnings.join(" · ")}
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-4">
                    <Card>
                      <p className="eyebrow mb-3">upstream ref models</p>
                      {analysis.ref_dependencies.length > 0 ? (
                        <div className="flex flex-col gap-1.5">
                          {analysis.ref_dependencies.map((d) => (
                            <Link
                              key={d.target_name}
                              href={`/models?model=${encodeURIComponent(d.target_name)}`}
                              className="font-mono text-sm text-text-hi underline decoration-line underline-offset-2 transition-colors hover:text-accent hover:decoration-accent"
                            >
                              {d.target_name}
                            </Link>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-text-lo">This model reads no other models — it&apos;s a root.</p>
                      )}
                    </Card>
                    <Card>
                      <p className="eyebrow mb-3">source tables</p>
                      {analysis.source_dependencies.length > 0 ? (
                        <div className="flex flex-col gap-1.5">
                          {analysis.source_dependencies.map((d) => (
                            <p key={d.target_name} className="font-mono text-sm text-text-hi">
                              {d.source_name ? `${d.source_name}.` : ""}
                              {d.target_name}
                            </p>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-text-lo">No raw source() dependencies.</p>
                      )}
                    </Card>
                  </div>

                  <Card>
                    <p className="font-mono text-sm text-text-lo">file</p>
                    <p className="font-mono text-sm text-text-hi">{analysis.file_path}</p>
                  </Card>
                </div>
              )}

              {tab === "query-flow" && queryFlow && (
                <div className="flex gap-4">
                  <div className="flex-1">
                    <FlowGraph
                      nodes={flowNodes}
                      edges={flowEdges}
                      onNodeClick={setSelectedStep}
                      selectedId={selectedStep}
                      legend={queryFlowLegend}
                    />
                  </div>
                  <Card className="w-64 shrink-0">
                    <p className="eyebrow mb-2">details</p>
                    {selectedStep && queryFlow.panels[selectedStep] ? (
                      <div className="flex flex-col gap-1.5">
                        {Object.entries(queryFlow.panels[selectedStep]).map(([k, v]) => (
                          <div key={k}>
                            <p className="font-mono text-sm text-text-lo">{k}</p>
                            <p className="text-sm text-text-hi">{v}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-text-lo">Click a node to see its details here.</p>
                    )}
                  </Card>
                </div>
              )}

              {tab === "columns" && (
                <div className="overflow-hidden rounded-lg border border-line">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-line bg-ink-900 font-mono text-text-lo">
                        <th className="px-3 py-2 font-normal">output</th>
                        <th className="px-3 py-2 font-normal">type</th>
                        <th className="px-3 py-2 font-normal">expression</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.output_columns.map((c) => (
                        <tr key={c.output_name} className="border-b border-line/60">
                          <td className="px-3 py-2 font-mono">
                            <Link
                              href={`/features?q=${encodeURIComponent(c.output_name)}`}
                              className="text-text-hi underline decoration-line underline-offset-2 transition-colors hover:text-accent hover:decoration-accent"
                              title="Compare this column across every model that produces it"
                            >
                              {c.output_name}
                            </Link>
                          </td>
                          <td className="px-3 py-2 text-text-lo">{c.transformation_type}</td>
                          <td className="max-w-md truncate px-3 py-2 font-mono text-text-lo">
                            {c.original_sql_expression}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {tab === "raw-sql" && <SqlCode sql={analysis.raw_sql} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
