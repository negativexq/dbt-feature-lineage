/**
 * Thin fetch wrapper for the FastAPI backend (src/dbt_feature_lineage/api/app.py).
 * One function per route, matching the backend's own route grouping
 * (discover/project, models, model-dag, lineage, features) -- no
 * client-side business logic here, every response is already the shape
 * the backend's services/domain layer produced.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `Request to ${path} failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export interface DiscoveredProject {
  name: string;
  path: string;
  relative_path: string;
}

export interface ArtifactStatus {
  mode: "manifest" | "static";
  reason: string;
  message: string;
  dbt_version: string | null;
  level?: string;
  display_message?: string;
}

export interface ProjectSummary {
  name: string;
  path: string;
  model_count: number;
  model_groups: string[];
  artifact_status: ArtifactStatus | null;
}

export interface ModelSummary {
  name: string;
  layer: string;
  relative_path: string;
}

export interface DbtOutputColumn {
  output_name: string;
  original_sql_expression: string;
  transformation_type: string;
  referenced_input_columns: string[];
}

export interface ModelAnalysis {
  model_name: string;
  file_path: string;
  relative_path: string;
  layer: string;
  raw_sql: string;
  ref_dependencies: { dependency_type: string; target_name: string; source_name: string | null }[];
  source_dependencies: { dependency_type: string; target_name: string; source_name: string | null }[];
  cte_names: string[];
  join_count: number;
  join_types: string[];
  has_where_clause: boolean;
  group_by_columns: string[];
  aggregate_functions: string[];
  window_functions: string[];
  output_columns: DbtOutputColumn[];
  parsing_warnings: string[];
  description: string | null;
  owner: string | null;
  tags: string[];
  test_count: number;
  materialization: string | null;
}

export interface QueryFlowStep {
  step_id: string;
  step_type: "source" | "cte" | "final_select" | "output";
  name: string;
  upstream_step_ids: string[];
  join_types: string[];
  has_where_clause: boolean;
  group_by_columns: string[];
  aggregate_functions: string[];
  window_functions: string[];
  output_columns: DbtOutputColumn[];
}

export interface QueryFlowResponse {
  steps: QueryFlowStep[];
  panels: Record<string, Record<string, string>>;
}

export interface ModelDagNode {
  id: string;
  layer: string;
  materialization: string | null;
  column_count: number;
  panel: Record<string, string>;
  [key: string]: unknown;
}

export interface ModelDagResponse {
  nodes: ModelDagNode[];
  edges: { source: string; target: string }[];
  warnings: string[];
}

export interface ColumnMatch {
  model: string;
  column: string;
  layer: string;
  key: string;
}

export interface ExposureImpact {
  name: string;
  exposure_type: string | null;
  owner: string | null;
  url: string | null;
  via_models: string[];
}

export interface LineageChainResponse {
  target: { model: string; column: string; layer: string };
  nodes: ColumnMatch[];
  edges: { source: string; target: string; transformation_type: string; expression_sql: string }[];
  warnings: string[];
  impact_summary?: {
    affected_model_count: number;
    affected_column_count: number;
    direct: { model: string; columns: string[] }[];
    all_impacted: { model: string; columns: string[] }[];
    affected_exposures: ExposureImpact[];
  };
}

export type HealthStatus = "healthy" | "caution" | "degraded" | "unknown";

export interface ModelHealth {
  model: string;
  status: HealthStatus;
  build_status: string | null;
  failing_tests: number;
  total_tests_run: number;
}

export interface ModelHealthResponse {
  generated_at: string | null;
  models: ModelHealth[];
}

export interface FeatureMatch {
  model: string;
  layer: string;
  description: string | null;
  owner: string | null;
  tags: string[];
  test_count: number;
}

export interface FeatureSearchResponse {
  matching_names: string[];
  matches: Record<string, FeatureMatch[]>;
}

export const api = {
  discover: (root: string) =>
    apiFetch<DiscoveredProject[]>(`/api/discover?root=${encodeURIComponent(root)}`),
  cloneProject: (url: string, ref?: string) =>
    apiFetch<DiscoveredProject[]>(
      `/api/project/clone?url=${encodeURIComponent(url)}${ref ? `&ref=${encodeURIComponent(ref)}` : ""}`,
      { method: "POST" }
    ),
  getProject: (path: string) => apiFetch<ProjectSummary>(`/api/project?path=${encodeURIComponent(path)}`),
  generateArtifacts: (path: string) =>
    apiFetch<ProjectSummary>(`/api/project/generate-artifacts?path=${encodeURIComponent(path)}`, {
      method: "POST",
    }),
  listModels: (path: string, group?: string | null) =>
    apiFetch<ModelSummary[]>(
      `/api/models?path=${encodeURIComponent(path)}${group ? `&group=${encodeURIComponent(group)}` : ""}`
    ),
  getModel: (path: string, name: string) =>
    apiFetch<ModelAnalysis>(`/api/models/${encodeURIComponent(name)}?path=${encodeURIComponent(path)}`),
  getQueryFlow: (path: string, name: string) =>
    apiFetch<QueryFlowResponse>(
      `/api/models/${encodeURIComponent(name)}/query-flow?path=${encodeURIComponent(path)}`
    ),
  getModelDag: (path: string, group?: string | null) =>
    apiFetch<ModelDagResponse>(
      `/api/model-dag?path=${encodeURIComponent(path)}${group ? `&group=${encodeURIComponent(group)}` : ""}`
    ),
  getModelHealth: (path: string, group?: string | null) =>
    apiFetch<ModelHealthResponse>(
      `/api/model-health?path=${encodeURIComponent(path)}${group ? `&group=${encodeURIComponent(group)}` : ""}`
    ),
  searchColumns: (path: string, q: string, group?: string | null) =>
    apiFetch<ColumnMatch[]>(
      `/api/lineage/search?path=${encodeURIComponent(path)}&q=${encodeURIComponent(q)}${
        group ? `&group=${encodeURIComponent(group)}` : ""
      }`
    ),
  getLineageChain: (params: {
    path: string;
    model: string;
    column: string;
    layer: string;
    direction: "upstream" | "downstream";
    impact?: boolean;
    group?: string | null;
  }) => {
    const search = new URLSearchParams({
      path: params.path,
      model: params.model,
      column: params.column,
      layer: params.layer,
      direction: params.direction,
      impact: String(params.impact ?? false),
    });
    if (params.group) search.set("group", params.group);
    return apiFetch<LineageChainResponse>(`/api/lineage/chain?${search.toString()}`);
  },
  searchFeatures: (path: string, q: string, group?: string | null) =>
    apiFetch<FeatureSearchResponse>(
      `/api/features?path=${encodeURIComponent(path)}&q=${encodeURIComponent(q)}${
        group ? `&group=${encodeURIComponent(group)}` : ""
      }`
    ),
};
