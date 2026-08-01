"""Tests for services/lineage_service.py.

Covers: get_column_lineage() (single sqlglot lineage() call using a built
ProjectSchema), dialect resolution from manifest metadata.adapter_type,
Node -> ColumnNode/ColumnEdge conversion, the full project-wide
build_project_lineage() graph (including a real end-to-end raw-source-to-
mart chain), lineage_cache_key()'s content-sensitivity, and a guard against
circular ref() dependencies (docs/v0.3-plan.md Risk 5) -- verified via the
project's own ref_dependencies, not by provoking sqlglot internals.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pytest
from sqlglot.lineage import Node

from dbt_feature_lineage.domain.lineage import ColumnNode
from dbt_feature_lineage.domain.models import DbtDependency, DbtModel, DbtProject
from dbt_feature_lineage.loaders.manifest_loader import load_dbt_project_from_manifest
from dbt_feature_lineage.loaders.project_loader import load_dbt_project
from dbt_feature_lineage.services.lineage_service import (
    CircularDependencyError,
    build_project_lineage,
    get_column_lineage,
    lineage_cache_key,
    resolve_dialect,
)
from dbt_feature_lineage.services.schema_builder import build_project_schema

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_manifest_project(tmp_path: Path, fixture_name: str) -> DbtProject:
    # A dedicated subdir per fixture, since a single test may request more
    # than one of these fixtures and they'd otherwise share `tmp_path`.
    project_dir = tmp_path / Path(fixture_name).stem
    target_path = project_dir / "target"
    target_path.mkdir(parents=True)
    manifest_data = json.loads((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"))
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    return load_dbt_project_from_manifest(project_dir)


@pytest.fixture
def manifest_project(tmp_path: Path) -> DbtProject:
    return _load_manifest_project(tmp_path, "manifest.json")


@pytest.fixture
def chain_project(tmp_path: Path) -> DbtProject:
    return _load_manifest_project(tmp_path, "manifest_lineage_chain.json")


@pytest.fixture
def static_project(sample_project_path: Path) -> DbtProject:
    return load_dbt_project(sample_project_path)


# ---------------------------------------------------------------------------
# resolve_dialect(): adapter_type -> sqlglot dialect, with a fixed fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter_type,expected",
    [
        ("postgres", "postgres"),
        ("snowflake", "snowflake"),
        ("bigquery", "bigquery"),
        ("redshift", "redshift"),
        ("trino", "trino"),
    ],
)
def test_resolve_dialect_maps_known_adapters(adapter_type: str, expected: str) -> None:
    project = DbtProject(
        name="proj",
        project_path="/tmp/proj",
        dbt_project_file="/tmp/proj/dbt_project.yml",
        model_paths=["models"],
        source="manifest",
        metadata={"adapter_type": adapter_type},
    )

    assert resolve_dialect(project) == expected


def test_resolve_dialect_falls_back_to_postgres_for_unknown_adapter() -> None:
    project = DbtProject(
        name="proj",
        project_path="/tmp/proj",
        dbt_project_file="/tmp/proj/dbt_project.yml",
        model_paths=["models"],
        source="manifest",
        metadata={"adapter_type": "databricks"},
    )

    assert resolve_dialect(project) == "postgres"


def test_resolve_dialect_falls_back_to_postgres_in_static_mode(
    static_project: DbtProject,
) -> None:
    assert resolve_dialect(static_project) == "postgres"


def test_resolve_dialect_uses_real_manifest_adapter_type(manifest_project: DbtProject) -> None:
    assert manifest_project.metadata.get("adapter_type") == "postgres"
    assert resolve_dialect(manifest_project) == "postgres"


# ---------------------------------------------------------------------------
# get_column_lineage(): a single lineage() call using the built ProjectSchema
# ---------------------------------------------------------------------------


def test_get_column_lineage_returns_a_node_for_the_requested_column(
    manifest_project: DbtProject,
) -> None:
    project_schema = build_project_schema(manifest_project)

    node = get_column_lineage(project_schema, "stg_customers", "customer_id", "postgres")

    assert isinstance(node, Node)
    assert node.name == "customer_id"


def test_get_column_lineage_resolves_select_star_via_schema(
    manifest_project: DbtProject,
) -> None:
    # stg_customers.raw_sql is `select * from source_customers` (a CTE) --
    # without a schema this would dead-end at a Star node (docs/v0.3-plan.md
    # Bölüm 2); with one it must trace all the way to the raw source.
    project_schema = build_project_schema(manifest_project)

    node = get_column_lineage(project_schema, "stg_customers", "first_name", "postgres")

    leaves = [n for n in node.walk() if not n.downstream]
    assert any(leaf.expression.sql() for leaf in leaves)
    assert not any(leaf.name in ("*", "") for leaf in leaves)


# ---------------------------------------------------------------------------
# build_project_lineage(): the full project graph
# ---------------------------------------------------------------------------


def test_build_project_lineage_returns_a_plain_digraph(manifest_project: DbtProject) -> None:
    graph = build_project_lineage(manifest_project)

    assert type(graph) is nx.DiGraph


def test_build_project_lineage_nodes_are_hashable_column_nodes(
    manifest_project: DbtProject,
) -> None:
    graph = build_project_lineage(manifest_project)

    assert graph.number_of_nodes() > 0
    assert all(isinstance(node, ColumnNode) for node in graph.nodes)


def test_build_project_lineage_edges_carry_column_edge_fields(
    manifest_project: DbtProject,
) -> None:
    graph = build_project_lineage(manifest_project)

    assert graph.number_of_edges() > 0
    for _source, _target, data in graph.edges(data=True):
        assert "transformation_type" in data
        assert "expression_sql" in data


def test_build_project_lineage_records_warning_and_keeps_other_models(
    manifest_project: DbtProject,
) -> None:
    # A CTE selecting a column its own upstream CTE never actually
    # projected -- sqlglot's qualify() correctly rejects the *whole* query
    # for this (verified: it's a per-query check, not per-column, so every
    # output column of a broken model fails together). This is a real bug
    # class this engine caught in examples/sample_banking_dbt during
    # development. build_project_lineage() must skip just the broken
    # model, not abort the whole project, and must say so -- never silently.
    broken_model = DbtModel(
        name="broken_model",
        file_path="/tmp/broken_model.sql",
        relative_path="models/broken_model.sql",
        layer="unknown",
        raw_sql=(
            "with upstream as (select customer_id from raw_banking.customers) "
            "select upstream.customer_id, upstream.nonexistent_column as x "
            "from upstream"
        ),
        schema_name="analytics_staging",
        alias="broken_model",
    )
    project = manifest_project.model_copy(
        update={"models": [*manifest_project.models, broken_model]}
    )

    graph = build_project_lineage(project)

    assert graph.graph["lineage_warnings"]
    assert any("broken_model" in warning for warning in graph.graph["lineage_warnings"])
    # Every column of the broken model failed -- none of them silently
    # dropped into the graph as if they'd succeeded.
    assert not any(node.model == "broken_model" for node in graph.nodes)
    # The rest of the (valid) project still built successfully.
    assert any(node.model == "stg_customers" for node in graph.nodes)


def test_build_project_lineage_end_to_end_raw_source_to_mart(chain_project: DbtProject) -> None:
    # customer_id is a pure passthrough from the raw source all the way to
    # the mart -- a real, verified multi-hop chain (docs/v0.3-plan.md
    # Bölüm 2 point 3: sqlglot's `sources` mechanism handles this in one
    # lineage() call per column; this test checks our own graph assembly
    # correctly threads it together across three separate calls, one per
    # model, into a single connected DiGraph).
    graph = build_project_lineage(chain_project)

    source_node = ColumnNode(model="raw_banking.customers", column="customer_id", layer="unknown")
    mart_node = ColumnNode(model="mart_customer_overview", column="customer_id", layer="marts")

    assert source_node in graph.nodes
    assert mart_node in graph.nodes
    assert nx.has_path(graph, source_node, mart_node)


def test_build_project_lineage_intermediate_hops_are_present(chain_project: DbtProject) -> None:
    graph = build_project_lineage(chain_project)

    stg_node = ColumnNode(model="stg_customers", column="customer_id", layer="staging")
    int_node = ColumnNode(
        model="int_customer_activity", column="customer_id", layer="intermediate"
    )

    assert stg_node in graph.nodes
    assert int_node in graph.nodes


# ---------------------------------------------------------------------------
# Circular ref() guard (Risk 5) -- validated via ref_dependencies, not by
# provoking sqlglot's own expansion internals.
# ---------------------------------------------------------------------------


def _circular_project() -> DbtProject:
    model_a = DbtModel(
        name="model_a",
        file_path="/tmp/model_a.sql",
        relative_path="models/model_a.sql",
        layer="unknown",
        raw_sql="select x from model_b",
        ref_dependencies=[DbtDependency(dependency_type="ref", target_name="model_b")],
        schema_name="analytics",
        alias="model_a",
    )
    model_b = DbtModel(
        name="model_b",
        file_path="/tmp/model_b.sql",
        relative_path="models/model_b.sql",
        layer="unknown",
        raw_sql="select x from model_a",
        ref_dependencies=[DbtDependency(dependency_type="ref", target_name="model_a")],
        schema_name="analytics",
        alias="model_b",
    )
    return DbtProject(
        name="proj",
        project_path="/tmp/proj",
        dbt_project_file="/tmp/proj/dbt_project.yml",
        model_paths=["models"],
        models=[model_a, model_b],
        source="manifest",
    )


def test_build_project_lineage_raises_on_circular_ref_dependency() -> None:
    project = _circular_project()

    with pytest.raises(CircularDependencyError):
        build_project_lineage(project)


def test_acyclic_real_projects_do_not_raise(
    manifest_project: DbtProject, static_project: DbtProject, chain_project: DbtProject
) -> None:
    # Sanity check for the guard itself: none of the real fixture/example
    # projects (whose ref() graphs are genuinely acyclic) should trip it.
    build_project_lineage(manifest_project)
    build_project_lineage(static_project)
    build_project_lineage(chain_project)


# ---------------------------------------------------------------------------
# lineage_cache_key(): pure, content-sensitive
# ---------------------------------------------------------------------------


def test_lineage_cache_key_is_stable_for_the_same_project(manifest_project: DbtProject) -> None:
    assert lineage_cache_key(manifest_project) == lineage_cache_key(manifest_project)


def test_lineage_cache_key_changes_when_a_model_sql_changes(manifest_project: DbtProject) -> None:
    key_before = lineage_cache_key(manifest_project)

    changed_model = manifest_project.models[0].model_copy(
        update={"raw_sql": manifest_project.models[0].raw_sql + "\n-- changed"}
    )
    models = [changed_model, *manifest_project.models[1:]]
    changed_project = manifest_project.model_copy(update={"models": models})

    key_after = lineage_cache_key(changed_project)

    assert key_before != key_after


def test_lineage_cache_key_differs_between_distinct_projects(
    manifest_project: DbtProject, static_project: DbtProject
) -> None:
    assert lineage_cache_key(manifest_project) != lineage_cache_key(static_project)
