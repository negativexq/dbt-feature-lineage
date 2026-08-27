"""FastAPI backend for the dbt-feature-lineage web UI.

Replaces the Streamlit app (pages/, app.py) as the web frontend's server --
the CLI and the underlying services/domain layer are completely unchanged;
this is purely a new *consumer* of that same layer, exactly like the CLI
is (see CONTRIBUTING.md's architecture note: every interface reads the
same `services`/`domain` layer instead of duplicating analysis logic).

Routes are grouped to mirror the five pages the Next.js frontend renders:
projects (Select Project), models (Model Explorer), model-dag (Model DAG),
lineage (Column Lineage), features (Feature Explorer). Every project-path
argument is a query parameter (`path=`), never a URL path segment, since
local filesystem paths contain slashes that don't belong in a route.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dbt_feature_lineage.api.cache import (
    cached_build_model_dag,
    cached_build_project_lineage,
    cached_inspect_model,
    cached_load_project,
    cached_load_run_results,
    generate_artifacts_and_reload,
    manifest_mtime,
    project_scoped_to_group,
)
from dbt_feature_lineage.domain.lineage import ColumnNode
from dbt_feature_lineage.domain.models import DbtProject
from dbt_feature_lineage.loaders.git_loader import GitCloneError, clone_or_pull_repo
from dbt_feature_lineage.loaders.project_discovery import discover_dbt_projects
from dbt_feature_lineage.loaders.run_results_loader import run_results_mtime
from dbt_feature_lineage.parsers.query_flow_parser import build_query_flow_steps
from dbt_feature_lineage.services.column_search import (
    build_feature_index,
    build_search_index,
    get_downstream_chain,
    get_upstream_chain,
    summarize_downstream_impact,
)
from dbt_feature_lineage.services.health_service import compute_model_health
from dbt_feature_lineage.services.lineage_service import lineage_cache_key
from dbt_feature_lineage.services.model_dag_service import model_dag_cache_key
from dbt_feature_lineage.ui.rendering import (
    describe_artifact_status,
    detect_model_groups,
    filter_models_by_group,
    render_node_detail_panel,
    render_query_flow_step_panel,
)

app = FastAPI(title="dbt-feature-lineage API")

# Local-only tool: the frontend is a Next.js dev/prod server on a
# different port than this API, both running on localhost. No public
# deployment, so a permissive local CORS policy is fine here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve(path: str) -> Path:
    # Absolute, matching discover_dbt_projects()'s own output shape -- the
    # frontend round-trips a `path` value from one endpoint's response
    # into another endpoint's query param, and a relative-vs-absolute
    # mismatch there would be a real (if subtle) correctness bug, not
    # just a cosmetic one.
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Project path does not exist: {resolved}")
    return resolved


def _load_project(path: str) -> DbtProject:
    resolved = _resolve(path)
    try:
        return cached_load_project(str(resolved), manifest_mtime(resolved))
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _scoped_project(path: str, group: str | None) -> DbtProject:
    return project_scoped_to_group(_load_project(path), group)


# ---------------------------------------------------------------------------
# Select Project
# ---------------------------------------------------------------------------


@app.get("/api/discover")
def discover(root: str = "examples") -> list[dict[str, str]]:
    root_path = Path(root).expanduser()
    if not root_path.exists():
        raise HTTPException(status_code=404, detail=f"Root directory does not exist: {root_path}")
    return [
        {"name": p.name, "path": p.path, "relative_path": p.relative_path}
        for p in discover_dbt_projects(root_path)
    ]


@app.post("/api/project/clone")
def clone_project(url: str, ref: str | None = None) -> list[dict[str, str]]:
    """Clone (or update) a git repo into a local cache directory, then
    hand back the same shape GET /api/discover returns -- a cloned
    checkout is discovered within exactly the way a scanned local
    directory is, since a monorepo's dbt project can sit in a
    subdirectory rather than at the repo root, same as any other
    directory a user might point the local scan at.
    """

    try:
        dest = clone_or_pull_repo(url, ref or None)
    except GitCloneError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    projects = discover_dbt_projects(dest)
    if not projects:
        raise HTTPException(
            status_code=404,
            detail=f"Cloned {url!r} but found no dbt_project.yml anywhere in it.",
        )
    return [{"name": p.name, "path": p.path, "relative_path": p.relative_path} for p in projects]


class ProjectSummary(BaseModel):
    name: str
    path: str
    model_count: int
    model_groups: list[str]
    artifact_status: dict[str, Any] | None


@app.get("/api/project")
def get_project(path: str) -> ProjectSummary:
    project = _load_project(path)
    return ProjectSummary(
        name=project.name,
        path=str(_resolve(path)),
        model_count=len(project.models),
        model_groups=detect_model_groups(project.models),
        artifact_status=project.artifact_status.model_dump() if project.artifact_status else None,
    )


@app.post("/api/project/generate-artifacts")
def generate_artifacts(path: str) -> ProjectSummary:
    resolved = _resolve(path)
    project = generate_artifacts_and_reload(str(resolved))
    level, message = (
        describe_artifact_status(project.artifact_status)
        if project.artifact_status
        else ("info", "")
    )
    return ProjectSummary(
        name=project.name,
        path=str(resolved),
        model_count=len(project.models),
        model_groups=detect_model_groups(project.models),
        artifact_status={
            **(project.artifact_status.model_dump() if project.artifact_status else {}),
            "level": level,
            "display_message": message,
        },
    )


# ---------------------------------------------------------------------------
# Model Explorer
# ---------------------------------------------------------------------------


@app.get("/api/models")
def list_models(path: str, group: str | None = None) -> list[dict[str, Any]]:
    project = _load_project(path)
    models = filter_models_by_group(project.models, [group] if group else [])
    return [
        {"name": m.name, "layer": m.layer, "relative_path": m.relative_path}
        for m in models
    ]


@app.get("/api/models/{model_name}")
def get_model(model_name: str, path: str) -> dict[str, Any]:
    resolved = _resolve(path)
    analysis = cached_inspect_model(str(resolved), model_name)
    result = analysis.model_dump()

    # DbtModelAnalysis is SQL-structure only (CTEs, joins, output columns --
    # what analyze_model() actually computes from the raw SQL); the schema
    # metadata a "premium" overview wants (description/owner/tags/tests,
    # plus the materialization the manifest already resolved) lives on the
    # DbtModel in the already-loaded, already-cached project instead. Merge
    # it in here rather than growing DbtModelAnalysis itself, since that
    # would mean either duplicating this data into every query-flow/lineage
    # call too or threading a DbtProject into analyze_model() for no reason
    # -- this is the one endpoint that actually needs both shapes at once.
    project = cached_load_project(str(resolved), manifest_mtime(resolved))
    model = next((m for m in project.models if m.name == model_name), None)
    if model is not None:
        result["description"] = model.description
        result["owner"] = model.owner
        result["tags"] = model.tags
        result["test_count"] = model.test_count
        result["materialization"] = model.materialization

    return result


@app.get("/api/models/{model_name}/query-flow")
def get_query_flow(model_name: str, path: str) -> dict[str, Any]:
    resolved = _resolve(path)
    analysis = cached_inspect_model(str(resolved), model_name)
    steps = build_query_flow_steps(analysis.raw_sql, model_name=model_name)
    return {
        "steps": [step.model_dump() for step in steps],
        "panels": {step.step_id: render_query_flow_step_panel(step) for step in steps},
    }


# ---------------------------------------------------------------------------
# Model DAG
# ---------------------------------------------------------------------------


@app.get("/api/model-dag")
def get_model_dag(path: str, group: str | None = None) -> dict[str, Any]:
    resolved = _resolve(path)
    project = _load_project(path)
    dag_key = model_dag_cache_key(project)
    graph = cached_build_model_dag(str(resolved), manifest_mtime(resolved), dag_key, group)

    scoped_project = project_scoped_to_group(project, group)
    nodes = [
        {"id": name, "panel": render_node_detail_panel(scoped_project, name), **attrs}
        for name, attrs in graph.nodes(data=True)
    ]
    edges = [{"source": source, "target": target} for source, target in graph.edges]
    return {
        "nodes": nodes,
        "edges": edges,
        "warnings": graph.graph.get("model_dag_warnings", []),
    }


@app.get("/api/model-health")
def get_model_health(path: str, group: str | None = None) -> dict[str, Any]:
    """Per-model Healthy/Caution/Degraded/Unknown, derived from
    target/run_results.json -- see services/health_service.py. A
    separate route from GET /api/models rather than a field folded into
    it: this reads a second, independently-timestamped local file (a
    project can have a fresh manifest and a stale or absent
    run_results.json), and every consumer so far (Dashboard's aggregate
    breakdown, Model DAG's per-node badge) wants it as its own fetch
    rather than paying for it on every model-list call.
    """

    resolved = _resolve(path)
    project = _load_project(path)
    scoped_project = project_scoped_to_group(project, group)

    loaded = cached_load_run_results(str(resolved), run_results_mtime(resolved))
    run_results, generated_at = loaded if loaded is not None else (None, None)
    health = compute_model_health(scoped_project.models, run_results)

    return {
        "generated_at": generated_at,
        "models": [
            {
                "model": h.model,
                "status": h.status,
                "build_status": h.build_status,
                "failing_tests": h.failing_tests,
                "total_tests_run": h.total_tests_run,
            }
            for h in health
        ],
    }


# ---------------------------------------------------------------------------
# Column Lineage
# ---------------------------------------------------------------------------


def _node_key(node: ColumnNode) -> str:
    return f"{node.model}.{node.column}"


@app.get("/api/lineage/search")
def search_columns(path: str, q: str, group: str | None = None) -> list[dict[str, str]]:
    resolved = _resolve(path)
    project = _load_project(path)
    lineage_key = lineage_cache_key(project_scoped_to_group(project, group))
    graph = cached_build_project_lineage(
        str(resolved), manifest_mtime(resolved), lineage_key, group
    )
    index = build_search_index(graph)
    return [
        {"model": node.model, "column": node.column, "layer": node.layer, "key": _node_key(node)}
        for name, nodes in index.items()
        if q.lower() in name.lower()
        for node in nodes
    ]


@app.get("/api/lineage/chain")
def get_lineage_chain(
    path: str,
    model: str,
    column: str,
    layer: str,
    direction: Literal["upstream", "downstream"] = "upstream",
    impact: bool = False,
    group: str | None = None,
) -> dict[str, Any]:
    resolved = _resolve(path)
    project = _load_project(path)
    lineage_key = lineage_cache_key(project_scoped_to_group(project, group))
    graph = cached_build_project_lineage(
        str(resolved), manifest_mtime(resolved), lineage_key, group
    )

    try:
        target = ColumnNode(model=model, column=column, layer=layer)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid layer {layer!r}: {exc}") from exc
    if target not in graph:
        raise HTTPException(status_code=404, detail="Column not found in this project's lineage.")

    chain = (
        get_upstream_chain(graph, target)
        if direction == "upstream"
        else get_downstream_chain(graph, target)
    )
    subgraph = graph.subgraph(chain)

    payload: dict[str, Any] = {
        "target": target.model_dump(),
        "nodes": [
            {"key": _node_key(n), "model": n.model, "column": n.column, "layer": n.layer}
            for n in chain
        ],
        "edges": [
            {
                "source": _node_key(source),
                "target": _node_key(edge_target),
                "transformation_type": data.get("transformation_type", ""),
                "expression_sql": data.get("expression_sql", ""),
            }
            for source, edge_target, data in subgraph.edges(data=True)
        ],
        "warnings": graph.graph.get("lineage_warnings", []),
    }

    if impact and direction == "downstream":
        summary = summarize_downstream_impact(graph, target, chain, project.exposures)
        payload["impact_summary"] = {
            "affected_model_count": summary.affected_model_count,
            "affected_column_count": summary.affected_column_count,
            "direct": [{"model": m.model, "columns": m.columns} for m in summary.direct],
            "all_impacted": [
                {"model": m.model, "columns": m.columns} for m in summary.all_impacted
            ],
            "affected_exposures": [
                {
                    "name": e.name,
                    "exposure_type": e.exposure_type,
                    "owner": e.owner,
                    "url": e.url,
                    "via_models": e.via_models,
                }
                for e in summary.affected_exposures
            ],
        }

    return payload


# ---------------------------------------------------------------------------
# Feature Explorer
# ---------------------------------------------------------------------------


@app.get("/api/features")
def search_features(path: str, q: str, group: str | None = None) -> dict[str, Any]:
    scoped_project = _scoped_project(path, group)
    index = build_feature_index(scoped_project)

    matching_names = [name for name in index if q.lower() in name.lower()]
    exact_match = q.lower()
    matching_names.sort(key=lambda name: (name.lower() != exact_match, name))

    return {
        "matching_names": matching_names,
        "matches": {
            name: [
                {
                    "model": m.model,
                    "layer": m.layer,
                    "description": m.description,
                    "owner": m.owner,
                    "tags": m.tags,
                    "test_count": m.test_count,
                }
                for m in index[name]
            ]
            for name in matching_names
        },
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
