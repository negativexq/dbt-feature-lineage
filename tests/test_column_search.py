"""Tests for services/column_search.py.

Covers build_search_index() (0 / 1 / >1 match cases) and get_upstream_chain()
(linear and branching ancestor DAGs), built on top of the *real*
build_project_lineage() output for the v0.3 manifest fixtures -- every
ColumnNode asserted here was independently verified in a sandbox run
against the actual graph, not guessed from the SQL text.

A model now resolves to the *same* (model_name, layer) identity whether
it's reached as the root of its own trace or as an ancestor while tracing
a different, downstream model -- lineage_service._convert_node used to
resolve a Node's owning model straight from Node.source_name (a raw
ProjectSchema.sources key, e.g. "analytics_intermediate.int_customer_activity")
without mapping it back to the clean model name, so the same model could
appear twice in the graph under two different identities. Fixed via
ProjectSchema.sources_key_to_model.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pytest

from dbt_feature_lineage.domain.lineage import ColumnNode
from dbt_feature_lineage.domain.models import DbtProject
from dbt_feature_lineage.loaders.manifest_loader import load_dbt_project_from_manifest
from dbt_feature_lineage.services.column_search import (
    build_search_index,
    get_downstream_chain,
    get_upstream_chain,
)
from dbt_feature_lineage.services.lineage_service import build_project_lineage

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
def manifest_graph(tmp_path: Path) -> nx.DiGraph:
    project = _load_manifest_project(tmp_path, "manifest.json")
    return build_project_lineage(project)


@pytest.fixture
def chain_graph(tmp_path: Path) -> nx.DiGraph:
    project = _load_manifest_project(tmp_path, "manifest_lineage_chain.json")
    return build_project_lineage(project)


@pytest.fixture
def branching_graph(tmp_path: Path) -> nx.DiGraph:
    project = _load_manifest_project(tmp_path, "manifest_lineage_branching.json")
    return build_project_lineage(project)


# ---------------------------------------------------------------------------
# build_search_index(): 0 / 1 / >1 match
# ---------------------------------------------------------------------------


def test_search_index_zero_matches_for_an_unknown_column(manifest_graph: nx.DiGraph) -> None:
    index = build_search_index(manifest_graph)

    assert index.get("does_not_exist_anywhere", []) == []


def test_search_index_single_match_for_a_column_unique_to_one_model(
    manifest_graph: nx.DiGraph,
) -> None:
    # "last_name" only ever appears in stg_customers's own SELECT list --
    # no other model in this fixture references it.
    index = build_search_index(manifest_graph)

    matches = index["last_name"]

    assert matches == [ColumnNode(model="stg_customers", column="last_name", layer="staging")]


def test_search_index_reports_multiple_matches_for_an_ambiguous_column_name(
    chain_graph: nx.DiGraph,
) -> None:
    # "customer_id" is a pure passthrough through every model in the chain
    # fixture, so it legitimately shows up under several distinct
    # (model, layer) identities -- this is the "which one did you mean?"
    # case CLI/UI need to resolve (docs/v0.4-plan.md Bölüm 4/Riskler #2).
    index = build_search_index(chain_graph)

    matches = index["customer_id"]

    assert len(matches) > 1
    assert set(matches) == {
        ColumnNode(model="raw_banking.customers", column="customer_id", layer="unknown"),
        ColumnNode(model="stg_customers", column="customer_id", layer="staging"),
        ColumnNode(model="int_customer_activity", column="customer_id", layer="intermediate"),
        ColumnNode(model="mart_customer_overview", column="customer_id", layer="marts"),
    }


def test_search_index_every_entry_has_the_matching_column_name(
    chain_graph: nx.DiGraph,
) -> None:
    index = build_search_index(chain_graph)

    for column_name, nodes in index.items():
        assert all(node.column == column_name for node in nodes)


def test_search_index_covers_every_graph_node(chain_graph: nx.DiGraph) -> None:
    index = build_search_index(chain_graph)

    indexed_nodes = {node for nodes in index.values() for node in nodes}

    assert indexed_nodes == set(chain_graph.nodes)


# ---------------------------------------------------------------------------
# get_upstream_chain(): linear ancestor chain
# ---------------------------------------------------------------------------


def test_get_upstream_chain_linear_from_raw_source_to_mart(chain_graph: nx.DiGraph) -> None:
    target = ColumnNode(model="mart_customer_overview", column="customer_id", layer="marts")

    chain = get_upstream_chain(chain_graph, target)

    # A strict linear chain has exactly one valid topological order.
    assert chain == [
        ColumnNode(model="raw_banking.customers", column="customer_id", layer="unknown"),
        ColumnNode(model="int_customer_activity", column="customer_id", layer="intermediate"),
        ColumnNode(model="mart_customer_overview", column="customer_id", layer="marts"),
    ]


def test_get_upstream_chain_ends_with_the_requested_target(chain_graph: nx.DiGraph) -> None:
    target = ColumnNode(model="mart_customer_overview", column="first_name", layer="marts")

    chain = get_upstream_chain(chain_graph, target)

    assert chain[-1] == target
    assert len(chain) >= 2


def test_get_upstream_chain_for_a_terminal_raw_source_is_just_itself(
    chain_graph: nx.DiGraph,
) -> None:
    # A raw source column has no ancestors of its own -- the chain is a
    # single-element list, not an error.
    target = ColumnNode(model="raw_banking.customers", column="customer_id", layer="unknown")

    chain = get_upstream_chain(chain_graph, target)

    assert chain == [target]


# ---------------------------------------------------------------------------
# get_upstream_chain(): branching ancestor DAG (coalesce/join of two sources)
# ---------------------------------------------------------------------------


def test_get_upstream_chain_branching_includes_both_parallel_ancestors(
    branching_graph: nx.DiGraph,
) -> None:
    # mart_customer_merged.customer_id = coalesce(a.customer_id, b.customer_id)
    # from two independently-sourced staging models -- a genuine
    # multi-parent DAG, not a single arrow chain (docs/v0.3-plan.md Bölüm 3).
    target = ColumnNode(model="mart_customer_merged", column="customer_id", layer="marts")

    chain = get_upstream_chain(branching_graph, target)

    assert chain[-1] == target
    assert len(chain) == 3
    assert set(chain[:-1]) == {
        ColumnNode(model="raw_banking.customers", column="customer_id", layer="unknown"),
        ColumnNode(model="raw_banking.legacy_customers", column="customer_id", layer="unknown"),
    }


def test_get_upstream_chain_branching_ancestors_precede_the_target(
    branching_graph: nx.DiGraph,
) -> None:
    target = ColumnNode(model="mart_customer_merged", column="customer_id", layer="marts")

    chain = get_upstream_chain(branching_graph, target)
    target_index = chain.index(target)

    # Topological order: every ancestor must come before the target, even
    # though the two ancestors have no path between each other.
    assert target_index == len(chain) - 1


def test_get_upstream_chain_branching_subgraph_edges_carry_edge_data(
    branching_graph: nx.DiGraph,
) -> None:
    target = ColumnNode(model="mart_customer_merged", column="customer_id", layer="marts")
    chain = get_upstream_chain(branching_graph, target)

    subgraph = branching_graph.subgraph(chain)

    assert subgraph.number_of_edges() == 2
    for _source, _target, data in subgraph.edges(data=True):
        assert "transformation_type" in data
        assert "expression_sql" in data


# ---------------------------------------------------------------------------
# get_downstream_chain(): symmetric to get_upstream_chain, opposite direction
#
# Note: in both fixtures the raw source column feeds its staging model
# *and* separately feeds (via the intermediate/mart layer) the rest of the
# chain -- i.e. staging is a dead-end branch, not a hop the rest of the
# chain passes through (verified against the actual built graph, not
# assumed). So a raw source's downstream set is itself branching, same as
# an ambiguous column's upstream set is (docs/v0.4-plan.md Bölüm 3) -- the
# two functions are symmetric in behavior, not in the shape of every fixture
# graph traversal.
# ---------------------------------------------------------------------------


def test_get_downstream_chain_linear_from_intermediate_to_mart(chain_graph: nx.DiGraph) -> None:
    target = ColumnNode(model="int_customer_activity", column="customer_id", layer="intermediate")

    chain = get_downstream_chain(chain_graph, target)

    # A strict linear chain has exactly one valid topological order, and
    # unlike get_upstream_chain the target -- the root here -- comes first.
    assert chain == [
        ColumnNode(model="int_customer_activity", column="customer_id", layer="intermediate"),
        ColumnNode(model="mart_customer_overview", column="customer_id", layer="marts"),
    ]


def test_get_downstream_chain_starts_with_the_requested_target(chain_graph: nx.DiGraph) -> None:
    target = ColumnNode(model="int_customer_activity", column="first_name", layer="intermediate")

    chain = get_downstream_chain(chain_graph, target)

    assert chain[0] == target
    assert len(chain) >= 2


def test_get_downstream_chain_for_a_terminal_staging_column_is_just_itself(
    chain_graph: nx.DiGraph,
) -> None:
    # stg_customers is a dead-end branch in this fixture -- nothing
    # downstream consumes it -- so the chain is a single-element list, not
    # an error.
    target = ColumnNode(model="stg_customers", column="customer_id", layer="staging")

    chain = get_downstream_chain(chain_graph, target)

    assert chain == [target]


def test_get_downstream_chain_branching_includes_both_parallel_descendants(
    branching_graph: nx.DiGraph,
) -> None:
    # raw_banking.customers.customer_id feeds both mart_customer_merged
    # (via coalesce(a.customer_id, b.customer_id)) and stg_customers
    # independently -- a genuine multi-child DAG from this root, not a
    # single downstream path.
    target = ColumnNode(model="raw_banking.customers", column="customer_id", layer="unknown")

    chain = get_downstream_chain(branching_graph, target)

    assert chain[0] == target
    assert set(chain[1:]) == {
        ColumnNode(model="stg_customers", column="customer_id", layer="staging"),
        ColumnNode(model="mart_customer_merged", column="customer_id", layer="marts"),
    }


def test_get_downstream_chain_descendants_follow_the_target(chain_graph: nx.DiGraph) -> None:
    target = ColumnNode(model="raw_banking.customers", column="customer_id", layer="unknown")

    chain = get_downstream_chain(chain_graph, target)
    target_index = chain.index(target)

    # Topological order: the target -- the root of this subgraph -- must
    # come before every one of its descendants.
    assert target_index == 0


def test_get_downstream_chain_subgraph_edges_carry_edge_data(chain_graph: nx.DiGraph) -> None:
    # raw_banking.customers.customer_id fans out to stg_customers (1 edge)
    # and to int_customer_activity -> mart_customer_overview (2 edges) --
    # 3 edges total across mixed-depth branches.
    target = ColumnNode(model="raw_banking.customers", column="customer_id", layer="unknown")
    chain = get_downstream_chain(chain_graph, target)

    subgraph = chain_graph.subgraph(chain)

    assert subgraph.number_of_edges() == 3
    for _source, _target, data in subgraph.edges(data=True):
        assert "transformation_type" in data
        assert "expression_sql" in data


def test_get_downstream_chain_from_an_ancestor_reaches_back_to_the_original_target(
    chain_graph: nx.DiGraph,
) -> None:
    # Every node get_upstream_chain(leaf) returns is, by construction, an
    # ancestor of leaf -- so walking downstream from any of them must land
    # back on leaf. This holds even though the fixture graph isn't a simple
    # line (see module note above), unlike an exact chain-reversal equality
    # would.
    leaf = ColumnNode(model="mart_customer_overview", column="customer_id", layer="marts")
    upstream = get_upstream_chain(chain_graph, leaf)

    for ancestor in upstream:
        assert leaf in get_downstream_chain(chain_graph, ancestor)
