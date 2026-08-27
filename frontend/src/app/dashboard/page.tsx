"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, ModelDagResponse, ModelHealth, HealthStatus } from "@/lib/api";
import { useProjectSummary, useSharedProject } from "@/lib/useProject";
import {
  Card,
  EmptyState,
  ErrorBanner,
  MetricCard,
  PageHeader,
  PrimaryButton,
  StatusPill,
  layerColor,
  healthColor,
} from "@/components/ui";
import type { ModelDagNode } from "@/lib/api";

type CoverageKind = "documented" | "owned" | "tested";
const COVERAGE_PANEL_KEY: Record<CoverageKind, string> = {
  documented: "Description",
  owned: "Owner",
  tested: "Tests",
};

const HEALTH_ORDER: HealthStatus[] = ["degraded", "caution", "healthy", "unknown"];
const HEALTH_LABEL: Record<HealthStatus, string> = {
  degraded: "degraded",
  caution: "caution",
  healthy: "healthy",
  unknown: "no run data",
};

const LAYER_ORDER = ["staging", "intermediate", "marts", "unknown"];
const LAYER_LABEL: Record<string, string> = {
  staging: "staging",
  intermediate: "intermediate",
  marts: "marts",
  unknown: "unclassified",
};

/**
 * Everything here is derived from data the app already fetches for
 * Model DAG (api.getModelDag) -- no new backend endpoint, no N+1 calls
 * across every model. The DAG's per-node detail `panel` already carries
 * "Description"/"Owner"/"Tests" as optional keys (rendering.py's own
 * "no blank rows" contract), which is an honest enough signal to build
 * coverage percentages from without inventing a second source of truth.
 */
function Bar({
  label,
  count,
  total,
  color,
  onClick,
  active,
  dimmed,
}: {
  label: string;
  count: number;
  total: number;
  color: string;
  onClick?: () => void;
  active?: boolean;
  dimmed?: boolean;
}) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  const Wrapper = onClick ? "button" : "div";
  return (
    <Wrapper
      onClick={onClick}
      className={onClick ? `w-full text-left transition-opacity ${dimmed ? "opacity-50" : ""}` : undefined}
    >
      <div className="mb-1 flex items-center justify-between font-mono text-xs">
        <span className={`flex items-center gap-1.5 ${active ? "text-accent" : "text-text-hi"}`}>
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
          {label}
        </span>
        <span className="text-text-lo">
          {count} &middot; {pct}%
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink-950">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
    </Wrapper>
  );
}

export default function DashboardPage() {
  const { path, group, ready } = useSharedProject();
  const { name: projectName, mode } = useProjectSummary(path);
  const [dag, setDag] = useState<ModelDagResponse | null>(null);
  const [health, setHealth] = useState<ModelHealth[] | null>(null);
  const [healthGeneratedAt, setHealthGeneratedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeCoverage, setActiveCoverage] = useState<CoverageKind | null>(null);
  const [activeHealth, setActiveHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    if (!ready || !path) return;
    setError(null);
    api.getModelDag(path, group).then(setDag).catch((err) => setError(err.message));
    api
      .getModelHealth(path, group)
      .then((r) => {
        setHealth(r.models);
        setHealthGeneratedAt(r.generated_at);
      })
      .catch((err) => setError(err.message));
  }, [ready, path, group]);

  const stats = useMemo(() => {
    if (!dag) return null;
    const nodes = dag.nodes;
    const total = nodes.length;
    const totalColumns = nodes.reduce((sum, n) => sum + (n.column_count ?? 0), 0);

    const byLayer = new Map<string, number>();
    const byMaterialization = new Map<string, number>();
    const missing: Record<CoverageKind, ModelDagNode[]> = { documented: [], owned: [], tested: [] };
    for (const n of nodes) {
      byLayer.set(n.layer, (byLayer.get(n.layer) ?? 0) + 1);
      const mat = n.materialization ?? "unknown";
      byMaterialization.set(mat, (byMaterialization.get(mat) ?? 0) + 1);
      (Object.keys(COVERAGE_PANEL_KEY) as CoverageKind[]).forEach((kind) => {
        if (!n.panel[COVERAGE_PANEL_KEY[kind]]) missing[kind].push(n);
      });
    }
    const documented = total - missing.documented.length;
    const owned = total - missing.owned.length;
    const tested = total - missing.tested.length;

    const outgoing = new Set(dag.edges.map((e) => e.source));
    // A marts-layer model with nothing downstream is the expected,
    // terminal shape of a DAG -- only staging/intermediate models with
    // no consumer are a real "is this still used?" signal.
    const unused = nodes.filter((n) => n.layer !== "marts" && !outgoing.has(n.id));

    return { total, totalColumns, byLayer, byMaterialization, documented, owned, tested, missing, unused };
  }, [dag]);

  const healthStats = useMemo(() => {
    if (!health) return null;
    const byStatus: Record<HealthStatus, ModelHealth[]> = {
      healthy: [],
      caution: [],
      degraded: [],
      unknown: [],
    };
    for (const h of health) byStatus[h.status].push(h);
    return { total: health.length, byStatus };
  }, [health]);

  if (!ready) return null;
  if (!path) {
    return (
      <EmptyState
        title="No project selected yet"
        body="Head to Select Project to point at a dbt project first."
      />
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="dashboard --overview"
        title="Dashboard"
        caption="The project at a glance — scale, structure, and documentation coverage."
        right={<StatusPill projectName={projectName ?? path.split("/").pop() ?? path} group={group} mode={mode} />}
      />
      {error && <ErrorBanner message={error} />}

      {mode === "static" && (
        <div className="mb-6 flex items-center justify-between gap-3 rounded-md border border-amber-900/50 bg-amber-950/20 px-4 py-3">
          <p className="text-sm text-text-hi">
            Running on raw SQL parsing only — owner, tests, and docs coverage below will read low until a manifest exists.
          </p>
          <Link href="/">
            <PrimaryButton className="shrink-0 !px-4 !py-2 text-sm">Generate artifacts →</PrimaryButton>
          </Link>
        </div>
      )}

      {!stats ? (
        <p className="font-mono text-sm text-text-lo">loading…</p>
      ) : (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-4 gap-3">
            <MetricCard label="Models" value={stats.total} />
            <MetricCard label="Columns" value={stats.totalColumns} />
            <MetricCard label="Dependencies" value={dag?.edges.length ?? 0} />
            <MetricCard label="Unused models" value={stats.unused.length} />
          </div>

          {healthStats && (
            <Card>
              <p className="eyebrow mb-1">model health</p>
              {healthStats.byStatus.unknown.length === healthStats.total ? (
                <p className="text-sm text-text-lo">
                  No <span className="font-mono">dbt build</span>/<span className="font-mono">test</span> run recorded yet —
                  run one to see pass/fail health here.
                </p>
              ) : (
                <>
                  <p className="mb-4 text-sm text-text-lo">
                    From the last <span className="font-mono">dbt build</span>/<span className="font-mono">test</span> run
                    {healthGeneratedAt && ` (${new Date(healthGeneratedAt).toLocaleString()})`}. Click a status to
                    see which models.
                  </p>
                  <div className="grid grid-cols-4 gap-6">
                    {HEALTH_ORDER.map((status) => (
                      <Bar
                        key={status}
                        label={HEALTH_LABEL[status]}
                        count={healthStats.byStatus[status].length}
                        total={healthStats.total}
                        color={healthColor(status)}
                        active={activeHealth === status}
                        dimmed={activeHealth !== null && activeHealth !== status}
                        onClick={() => setActiveHealth((s) => (s === status ? null : status))}
                      />
                    ))}
                  </div>
                  {activeHealth && (
                    <div className="mt-5 border-t border-line pt-4">
                      {healthStats.byStatus[activeHealth].length === 0 ? (
                        <p className="text-sm text-text-lo">No models in this state.</p>
                      ) : (
                        <div className="flex flex-col gap-1.5">
                          {healthStats.byStatus[activeHealth].map((h) => (
                            <Link
                              key={h.model}
                              href={`/models?model=${encodeURIComponent(h.model)}`}
                              className="flex items-center justify-between rounded-md px-2.5 py-1.5 font-mono text-sm text-text-hi transition-colors hover:bg-ink-950"
                            >
                              <span className="flex items-center gap-2">
                                <span
                                  className="h-1.5 w-1.5 rounded-full"
                                  style={{ background: healthColor(h.status) }}
                                />
                                {h.model}
                              </span>
                              {h.failing_tests > 0 && (
                                <span className="text-xs text-text-lo">
                                  {h.failing_tests}/{h.total_tests_run} tests failing
                                </span>
                              )}
                            </Link>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </Card>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Card>
              <p className="eyebrow mb-4">models by layer</p>
              <div className="flex flex-col gap-3">
                {LAYER_ORDER.filter((l) => stats.byLayer.has(l)).map((l) => (
                  <Bar
                    key={l}
                    label={LAYER_LABEL[l]}
                    count={stats.byLayer.get(l) ?? 0}
                    total={stats.total}
                    color={layerColor(l)}
                  />
                ))}
              </div>
            </Card>
            <Card>
              <p className="eyebrow mb-4">models by materialization</p>
              <div className="flex flex-col gap-3">
                {Array.from(stats.byMaterialization.entries())
                  .sort((a, b) => b[1] - a[1])
                  .map(([mat, count]) => (
                    <Bar key={mat} label={mat} count={count} total={stats.total} color="var(--layer-intermediate)" />
                  ))}
              </div>
            </Card>
          </div>

          <Card>
            <p className="eyebrow mb-1">documentation coverage</p>
            <p className="mb-4 text-sm text-text-lo">Click a metric to see which models are missing it.</p>
            <div className="grid grid-cols-3 gap-6">
              <Bar
                label="documented"
                count={stats.documented}
                total={stats.total}
                color="var(--accent)"
                active={activeCoverage === "documented"}
                dimmed={activeCoverage !== null && activeCoverage !== "documented"}
                onClick={() => setActiveCoverage((c) => (c === "documented" ? null : "documented"))}
              />
              <Bar
                label="owned"
                count={stats.owned}
                total={stats.total}
                color="var(--accent)"
                active={activeCoverage === "owned"}
                dimmed={activeCoverage !== null && activeCoverage !== "owned"}
                onClick={() => setActiveCoverage((c) => (c === "owned" ? null : "owned"))}
              />
              <Bar
                label="tested"
                count={stats.tested}
                total={stats.total}
                color="var(--accent)"
                active={activeCoverage === "tested"}
                dimmed={activeCoverage !== null && activeCoverage !== "tested"}
                onClick={() => setActiveCoverage((c) => (c === "tested" ? null : "tested"))}
              />
            </div>

            {activeCoverage && (
              <div className="mt-5 border-t border-line pt-4">
                <p className="mb-3 font-mono text-xs text-text-lo">
                  {stats.missing[activeCoverage].length} model(s) missing {COVERAGE_PANEL_KEY[activeCoverage].toLowerCase()}
                </p>
                {stats.missing[activeCoverage].length === 0 ? (
                  <p className="text-sm text-text-lo">Every model has this covered.</p>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    {stats.missing[activeCoverage].map((n) => (
                      <Link
                        key={n.id}
                        href={`/models?model=${encodeURIComponent(n.id)}`}
                        className="flex items-center justify-between rounded-md px-2.5 py-1.5 font-mono text-sm text-text-hi transition-colors hover:bg-ink-950"
                      >
                        <span className="flex items-center gap-2">
                          <span className="h-1.5 w-1.5 rounded-full" style={{ background: layerColor(n.layer) }} />
                          {n.id}
                        </span>
                        <span className="text-xs text-text-lo">{n.layer}</span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>

          {dag && dag.warnings.length > 0 && (
            <div className="rounded-md border border-amber-900/50 bg-amber-950/20 px-4 py-3 font-mono text-sm text-amber-300">
              {dag.warnings.length} warning(s): {dag.warnings.join(" · ")}
            </div>
          )}

          {stats.unused.length > 0 && (
            <Card>
              <p className="eyebrow mb-1">unused models</p>
              <p className="mb-4 text-sm text-text-lo">
                Staging or intermediate models nothing in this project ref()s downstream — worth a second look before the
                next cleanup pass.
              </p>
              <div className="flex flex-col gap-1.5">
                {stats.unused.map((n) => (
                  <Link
                    key={n.id}
                    href={`/models?model=${encodeURIComponent(n.id)}`}
                    className="flex items-center justify-between rounded-md px-2.5 py-1.5 font-mono text-sm text-text-hi transition-colors hover:bg-ink-950"
                  >
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: layerColor(n.layer) }} />
                      {n.id}
                    </span>
                    <span className="text-xs text-text-lo">{n.layer}</span>
                  </Link>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
