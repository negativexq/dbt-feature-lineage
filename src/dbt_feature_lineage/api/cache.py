"""Process-local caching for the FastAPI backend -- the `functools.lru_cache`
equivalent of ui/state.py's `st.cache_data`-wrapped functions.

Same cache-busting contract as ui/state.py: every project-derived cache key
includes `manifest_mtime(resolved_path)` so a `dbt parse` (ours or the
user's own) invalidates stale "no manifest" results, and expensive graph
builds (`build_project_lineage`, `build_model_dag`) are scoped by the
project's own content-fingerprint cache key plus `selected_group`, exactly
as ui/state.py's docstrings explain in more detail. Kept as its own module
(not reused from ui/state.py) since that module imports `streamlit` --
importing it here would pull a Streamlit dependency into the API process
for no reason, the same boundary ui/flow_rendering.py already draws
between streamlit-free and streamlit-importing modules.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import networkx as nx

from dbt_feature_lineage.domain.models import DbtModelAnalysis, DbtProject
from dbt_feature_lineage.loaders.artifact_detector import resolve_dbt_project
from dbt_feature_lineage.loaders.run_results_loader import RunResultEntry, load_run_results
from dbt_feature_lineage.services.lineage_service import build_project_lineage
from dbt_feature_lineage.services.model_analysis_service import inspect_model
from dbt_feature_lineage.services.model_dag_service import build_model_dag
from dbt_feature_lineage.ui.rendering import filter_models_by_group


def manifest_mtime(resolved_path: Path) -> float:
    manifest_file = resolved_path / "target" / "manifest.json"
    return manifest_file.stat().st_mtime if manifest_file.exists() else 0.0


@lru_cache(maxsize=32)
def cached_load_run_results(
    project_path: str, run_results_cache_key: float
) -> tuple[dict[str, RunResultEntry], str | None] | None:
    """Cached the same way as cached_load_project -- keyed on the
    file's own mtime (run_results_mtime()) rather than a manual
    invalidation call, so a `dbt build`/`test` run outside this process
    (the whole point of the file: it records what a real run did) is
    picked up on the next request without anyone having to remember to
    clear a cache for it."""

    return load_run_results(project_path)


@lru_cache(maxsize=32)
def cached_load_project(project_path: str, manifest_cache_key: float) -> DbtProject:
    return resolve_dbt_project(project_path, generate_artifacts=False)


def generate_artifacts_and_reload(project_path: str) -> DbtProject:
    """Run `dbt parse` (uncached, so a retry after a fix is never stale)."""

    project = resolve_dbt_project(project_path, generate_artifacts=True)
    cached_load_project.cache_clear()
    return project


@lru_cache(maxsize=128)
def cached_inspect_model(project_path: str, model_name: str) -> DbtModelAnalysis:
    return inspect_model(project_path, model_name)


def project_scoped_to_group(project: DbtProject, selected_group: str | None) -> DbtProject:
    if selected_group is None:
        return project
    return project.model_copy(
        update={"models": filter_models_by_group(project.models, [selected_group])}
    )


@lru_cache(maxsize=32)
def cached_build_project_lineage(
    project_path: str,
    manifest_cache_key: float,
    lineage_key: tuple,
    selected_group: str | None,
) -> nx.DiGraph:
    project = cached_load_project(project_path, manifest_cache_key)
    project = project_scoped_to_group(project, selected_group)
    return build_project_lineage(project)


@lru_cache(maxsize=32)
def cached_build_model_dag(
    project_path: str,
    manifest_cache_key: float,
    model_dag_key: tuple,
    selected_group: str | None,
) -> nx.DiGraph:
    project = cached_load_project(project_path, manifest_cache_key)
    project = project_scoped_to_group(project, selected_group)
    return build_model_dag(project)
