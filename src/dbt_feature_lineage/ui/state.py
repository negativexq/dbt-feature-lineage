"""Streamlit-cached project/lineage loaders shared across pages.

Kept separate from ui/rendering.py (which stays framework-agnostic --
no `streamlit` import) since this module exists specifically to hold
`st.cache_data`-wrapped functions that both pages/model_explorer.py and
pages/column_lineage.py need. Defining these independently in each page
file would create two separate caches for the same underlying data
(and, for cached_load_project specifically, two separate `dbt parse`
subprocess-triggering code paths).
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import streamlit as st

from dbt_feature_lineage.domain.models import DbtProject
from dbt_feature_lineage.loaders.artifact_detector import resolve_dbt_project
from dbt_feature_lineage.services.lineage_service import build_project_lineage
from dbt_feature_lineage.services.model_analysis_service import inspect_model
from dbt_feature_lineage.services.model_dag_service import build_model_dag
from dbt_feature_lineage.ui.rendering import filter_models_by_group

DEFAULT_PROJECT_PATH = "examples/sample_banking_dbt"


def manifest_mtime(resolved_path: Path) -> float:
    """Cache-busting key: the manifest's mtime, or 0.0 when it doesn't exist.

    Without this, st.cache_data would keep serving a stale "no manifest"
    result even after `dbt parse` (triggered by us or run manually by the
    user) writes target/manifest.json.
    """

    manifest_file = resolved_path / "target" / "manifest.json"
    return manifest_file.stat().st_mtime if manifest_file.exists() else 0.0


@st.cache_data(show_spinner=False)
def cached_load_project(project_path: str, manifest_cache_key: float) -> DbtProject:
    return resolve_dbt_project(project_path, generate_artifacts=False)


def generate_artifacts_and_reload(project_path: str) -> DbtProject:
    """Run `dbt parse` (uncached, so a retry after a fix is never stale)."""

    return resolve_dbt_project(project_path, generate_artifacts=True)


@st.cache_data(show_spinner=False)
def cached_inspect_model(project_path: str, model_name: str):
    return inspect_model(project_path, model_name)


def _project_scoped_to_group(project: DbtProject, selected_group: str | None) -> DbtProject:
    """Narrow `project.models` to one model_group before an expensive
    graph build, if a group is actually selected.

    Filtering here (before build_project_lineage()/build_model_dag())
    rather than after is deliberate: the group is chosen once, up front,
    on pages/select_project.py (not a live, frequently-changed widget the
    way v0.5's per-page multiselect was), so there's no repeated-rebuild
    cost to worry about, and skipping the subgraph-filtering step this
    replaced is both simpler and cheaper than building the full graph and
    throwing most of it away.
    """

    if selected_group is None:
        return project
    return project.model_copy(
        update={"models": filter_models_by_group(project.models, [selected_group])}
    )


@st.cache_data(show_spinner=False)
def cached_build_project_lineage(
    project_path: str,
    manifest_cache_key: float,
    lineage_key: tuple,
    selected_group: str | None,
) -> nx.DiGraph:
    """Same cache-busting pattern as cached_load_project: `lineage_key`
    (from services.lineage_service.lineage_cache_key()) is computed cheaply
    by the caller and passed in as a plain hashable argument, rather than
    caching on the DbtProject object itself (untested with Streamlit's own
    hashing, and cached_load_project never took that risk either).

    `selected_group` is a plain function argument specifically so
    st.cache_data's own argument-hashing keys the cache on it too --
    switching the shared model group (pages/select_project.py) must
    build (and cache) a genuinely different graph, not silently reuse a
    previous group's cached result just because lineage_key (computed
    from the *unfiltered* project) didn't change.

    Only called from pages/column_lineage.py -- st.navigation() pages are
    lazy (only the active page's script executes), so this expensive,
    whole-project graph build no longer runs on every rerun of every page
    the way it did when Column Lineage was just another st.tabs() tab
    (st.tabs bodies all execute unconditionally on every rerun).
    """

    project = cached_load_project(project_path, manifest_cache_key)
    project = _project_scoped_to_group(project, selected_group)
    return build_project_lineage(project)


@st.cache_data(show_spinner=False)
def cached_build_model_dag(
    project_path: str,
    manifest_cache_key: float,
    model_dag_key: tuple,
    selected_group: str | None,
) -> nx.DiGraph:
    """Same cache-busting pattern as cached_build_project_lineage:
    `model_dag_key` (from services.model_dag_service.model_dag_cache_key())
    is computed cheaply by the caller and passed in as a plain hashable
    argument, and `selected_group` is folded in the same way -- see that
    function's docstring for why it can't just ride along on
    manifest_cache_key/model_dag_key instead.

    Only called from pages/model_dag.py -- st.navigation() pages are lazy
    (only the active page's script executes), same reasoning as
    cached_build_project_lineage.
    """

    project = cached_load_project(project_path, manifest_cache_key)
    project = _project_scoped_to_group(project, selected_group)
    return build_model_dag(project)
