"""Tests for services/model_dag_service.py (v0.5).

Covers build_model_dag(): node/edge construction from DbtModel.ref_dependencies
(no new parsing -- see docs/v0.5-plan.md Bölüm 1), node attribute population
(materialization/description/tags/owner/test_count/column_count), the
deliberate reuse of schema_builder.build_project_schema() instead of
lineage_service.build_project_lineage() for column_count (cheap vs.
expensive -- Bölüm 1 gözlem 2), and the warn-and-exclude circular ref()
handling shared with lineage_service (Bölüm 7).
"""

from __future__ import annotations

import time
from pathlib import Path

import networkx as nx

from dbt_feature_lineage.domain.models import DbtDependency, DbtModel, DbtProject
from dbt_feature_lineage.loaders.project_loader import load_dbt_project
from dbt_feature_lineage.services.model_dag_service import build_model_dag


def _model(
    name: str,
    raw_sql: str,
    ref_targets: list[str] | None = None,
    **kwargs: object,
) -> DbtModel:
    return DbtModel(
        name=name,
        file_path=f"/tmp/{name}.sql",
        relative_path=f"models/{name}.sql",
        layer=kwargs.pop("layer", "unknown"),
        raw_sql=raw_sql,
        ref_dependencies=[
            DbtDependency(dependency_type="ref", target_name=target)
            for target in (ref_targets or [])
        ],
        schema_name="analytics",
        alias=name,
        **kwargs,
    )


def _project(models: list[DbtModel]) -> DbtProject:
    return DbtProject(
        name="proj",
        project_path="/tmp/proj",
        dbt_project_file="/tmp/proj/dbt_project.yml",
        model_paths=["models"],
        models=models,
        source="manifest",
    )


# ---------------------------------------------------------------------------
# Node/edge construction -- straight from DbtModel.ref_dependencies
# ---------------------------------------------------------------------------


def test_build_model_dag_creates_one_node_per_model() -> None:
    project = _project(
        [
            _model("stg_customers", "select id from raw.customers"),
            _model("mart_customers", "select id from stg_customers", ref_targets=["stg_customers"]),
        ]
    )

    graph = build_model_dag(project)

    assert set(graph.nodes) == {"stg_customers", "mart_customers"}


def test_build_model_dag_edge_direction_is_upstream_to_downstream() -> None:
    project = _project(
        [
            _model("stg_customers", "select id from raw.customers"),
            _model("mart_customers", "select id from stg_customers", ref_targets=["stg_customers"]),
        ]
    )

    graph = build_model_dag(project)

    assert ("stg_customers", "mart_customers") in graph.edges
    assert ("mart_customers", "stg_customers") not in graph.edges


def test_build_model_dag_nodes_are_plain_model_name_strings() -> None:
    # Not domain.lineage.ColumnNode -- this graph has no column granularity.
    project = _project([_model("stg_customers", "select id from raw.customers")])

    graph = build_model_dag(project)

    assert list(graph.nodes) == ["stg_customers"]
    assert all(isinstance(node, str) for node in graph.nodes)


def test_build_model_dag_ignores_ref_targets_outside_the_project() -> None:
    # A ref() to a model dbt itself would reject (target not in the
    # project) shouldn't produce a dangling edge to a node that was never
    # created.
    project = _project(
        [_model("mart_customers", "select 1", ref_targets=["nonexistent_model"])]
    )

    graph = build_model_dag(project)

    assert set(graph.nodes) == {"mart_customers"}
    assert graph.number_of_edges() == 0


# ---------------------------------------------------------------------------
# Node attributes
# ---------------------------------------------------------------------------


def test_build_model_dag_node_attributes_carry_model_metadata() -> None:
    project = _project(
        [
            _model(
                "mart_customers",
                "select id, name from stg_customers",
                layer="marts",
                materialization="table",
                description="Customer mart.",
                tags=["finance"],
                owner="finance-team",
                test_count=2,
            )
        ]
    )

    graph = build_model_dag(project)

    attrs = graph.nodes["mart_customers"]
    assert attrs["layer"] == "marts"
    assert attrs["materialization"] == "table"
    assert attrs["description"] == "Customer mart."
    assert attrs["tags"] == ["finance"]
    assert attrs["owner"] == "finance-team"
    assert attrs["test_count"] == 2


def test_build_model_dag_node_attributes_include_model_group() -> None:
    # Lets pages/model_dag.py filter the graph by domain (Model Group
    # sidebar filter) without going back to DbtProject.models -- the
    # attribute is already on the node, same as materialization/owner/etc.
    project = _project(
        [
            _model("stg_orders", "select 1", model_group="retail"),
            _model("stg_borrowers", "select 1", model_group="lending"),
        ]
    )

    graph = build_model_dag(project)

    assert graph.nodes["stg_orders"]["model_group"] == "retail"
    assert graph.nodes["stg_borrowers"]["model_group"] == "lending"


def test_build_model_dag_node_model_group_defaults_to_none_for_a_flat_layout() -> None:
    project = _project([_model("stg_customers", "select 1")])

    graph = build_model_dag(project)

    assert graph.nodes["stg_customers"]["model_group"] is None


def test_build_model_dag_column_count_reflects_output_columns() -> None:
    project = _project([_model("mart_customers", "select id, name, email from stg_customers")])

    graph = build_model_dag(project)

    assert graph.nodes["mart_customers"]["column_count"] == 3


def test_build_model_dag_metadata_defaults_match_static_mode(
    sample_project_path: Path,
) -> None:
    # Static mode never populates description/tags/owner/test_count (no
    # manifest to read them from) -- the node attributes must reflect that
    # (None/[]/None/0), not silently guess or omit the keys.
    project = load_dbt_project(sample_project_path)

    graph = build_model_dag(project)

    assert graph.number_of_nodes() > 0
    for _node, attrs in graph.nodes(data=True):
        assert attrs["description"] is None
        assert attrs["tags"] == []
        assert attrs["owner"] is None
        assert attrs["test_count"] == 0


# ---------------------------------------------------------------------------
# column_count uses build_project_schema(), not build_project_lineage()
# ---------------------------------------------------------------------------


def test_build_model_dag_is_fast_even_on_a_project_lineage_would_be_slow_on(
    sample_project_path: Path,
) -> None:
    # build_project_lineage() on this same 12-model project takes several
    # seconds (one sqlglot.lineage() call per output column per model --
    # docs/v0.4-plan.md Bölüm 6). build_model_dag() must not pay that cost:
    # it only needs build_project_schema() (one cheap parse pass per
    # model) for column_count. A generous ceiling, not a tight benchmark --
    # this exists to catch an accidental reintroduction of
    # build_project_lineage(), not to enforce a performance SLA.
    project = load_dbt_project(sample_project_path)

    start = time.monotonic()
    build_model_dag(project)
    elapsed = time.monotonic() - start

    assert elapsed < 3.0


# ---------------------------------------------------------------------------
# Circular ref() handling -- shared with lineage_service, warn-and-exclude
# ---------------------------------------------------------------------------


def _circular_project(extra_models: list[DbtModel] | None = None) -> DbtProject:
    model_a = _model("model_a", "select x from model_b", ref_targets=["model_b"])
    model_b = _model("model_b", "select x from model_a", ref_targets=["model_a"])
    return _project([model_a, model_b, *(extra_models or [])])


def test_build_model_dag_is_acyclic_even_with_a_ref_cycle() -> None:
    project = _circular_project()

    graph = build_model_dag(project)

    assert nx.is_directed_acyclic_graph(graph)


def test_build_model_dag_excludes_cyclic_models_and_reports_a_warning() -> None:
    project = _circular_project()

    graph = build_model_dag(project)

    assert set(graph.nodes) == set()
    assert graph.graph["model_dag_warnings"]
    assert any(
        "model_a" in warning and "model_b" in warning
        for warning in graph.graph["model_dag_warnings"]
    )


def test_build_model_dag_keeps_a_third_model_that_only_refs_into_the_cycle() -> None:
    model_c = _model("model_c", "select x from model_a", ref_targets=["model_a"])
    project = _circular_project(extra_models=[model_c])

    graph = build_model_dag(project)

    assert nx.is_directed_acyclic_graph(graph)
    assert "model_c" in graph.nodes
    assert "model_a" not in graph.nodes
    # model_a is excluded, so model_c's would-be edge from it must not exist.
    assert graph.number_of_edges() == 0


def test_build_model_dag_does_not_raise_on_circular_ref_dependency() -> None:
    project = _circular_project()

    graph = build_model_dag(project)

    assert isinstance(graph, nx.DiGraph)


def test_acyclic_real_project_has_no_warnings(sample_project_path: Path) -> None:
    project = load_dbt_project(sample_project_path)

    graph = build_model_dag(project)

    assert graph.graph["model_dag_warnings"] == []
