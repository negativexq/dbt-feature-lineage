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
from dbt_feature_lineage.domain.models import DbtModel, DbtProject
from dbt_feature_lineage.loaders.manifest_loader import load_dbt_project_from_manifest
from dbt_feature_lineage.loaders.project_loader import load_dbt_project
from dbt_feature_lineage.services.column_search import (
    build_feature_index,
    build_search_index,
    get_downstream_chain,
    get_upstream_chain,
    summarize_downstream_impact,
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


# ---------------------------------------------------------------------------
# build_feature_index() -- v0.7's Feature Explorer data source. Built on
# build_project_schema().columns_by_model, NOT build_search_index()'s
# lineage graph (docs/v0.7-plan.md Bölüm 1: measured ~300x cheaper, and
# Feature Explorer never needs a lineage edge, only "which model produces
# this column name and what's that model's own metadata").
# ---------------------------------------------------------------------------


def _model(
    name: str,
    raw_sql: str,
    layer: str = "marts",
    **kwargs: object,
) -> DbtModel:
    return DbtModel(
        name=name,
        file_path=f"/tmp/{name}.sql",
        relative_path=f"models/{name}.sql",
        layer=layer,
        raw_sql=raw_sql,
        **kwargs,
    )


def _project(models: list[DbtModel], source: str = "manifest") -> DbtProject:
    return DbtProject(
        name="proj",
        project_path="/tmp/proj",
        dbt_project_file="/tmp/proj/dbt_project.yml",
        model_paths=["models"],
        models=models,
        source=source,
    )


def test_build_feature_index_zero_matches_for_an_unknown_column() -> None:
    project = _project([_model("mart_a", "select customer_id from stg_a")])

    index = build_feature_index(project)

    assert index.get("does_not_exist_anywhere", []) == []


def test_build_feature_index_single_match_carries_that_models_own_metadata() -> None:
    project = _project(
        [
            _model(
                "mart_with_metadata",
                "select customer_id from stg_customers",
                description="Customer-level feature mart.",
                tags=["finance", "daily"],
                owner="finance-team",
                test_count=2,
            )
        ]
    )

    matches = build_feature_index(project)["customer_id"]

    assert len(matches) == 1
    match = matches[0]
    assert match.model == "mart_with_metadata"
    assert match.column == "customer_id"
    assert match.layer == "marts"
    assert match.description == "Customer-level feature mart."
    assert match.tags == ["finance", "daily"]
    assert match.owner == "finance-team"
    assert match.test_count == 2


def test_build_feature_index_multiple_matches_each_keep_their_own_models_metadata() -> None:
    # The same column name produced by two different models with
    # different (or absent) metadata -- the whole point of Feature
    # Explorer's comparison view (docs/v0.7-plan.md Hedef).
    project = _project(
        [
            _model(
                "mart_with_metadata",
                "select customer_id from stg_customers",
                layer="marts",
                description="Documented mart.",
                owner="finance-team",
            ),
            _model(
                "stg_customers",
                "select customer_id from raw.customers",
                layer="staging",
            ),
        ]
    )

    matches = build_feature_index(project)["customer_id"]

    assert len(matches) == 2
    by_model = {m.model: m for m in matches}
    assert by_model["mart_with_metadata"].description == "Documented mart."
    assert by_model["mart_with_metadata"].owner == "finance-team"
    assert by_model["stg_customers"].description is None
    assert by_model["stg_customers"].owner is None


def test_build_feature_index_sorts_matches_by_model_name() -> None:
    project = _project(
        [
            _model("mart_zeta", "select customer_id from stg_a"),
            _model("mart_alpha", "select customer_id from stg_b"),
        ]
    )

    matches = build_feature_index(project)["customer_id"]

    assert [m.model for m in matches] == ["mart_alpha", "mart_zeta"]


def test_build_feature_index_static_mode_metadata_is_empty_not_missing() -> None:
    # Static mode never populates description/tags/owner/test_count (no
    # manifest to read them from, same as render_node_detail_panel's
    # "static mode" contract) -- the FeatureMatch must still exist, with
    # those fields at their defaults, not omitted or raising.
    project = _project(
        [_model("mart_a", "select customer_id from stg_a")], source="static"
    )

    match = build_feature_index(project)["customer_id"][0]

    assert match.description is None
    assert match.tags == []
    assert match.owner is None
    assert match.test_count == 0


def test_build_feature_index_on_sample_banking_dbt_customer_id_appears_in_every_model(
    sample_project_path: Path,
) -> None:
    # Real fixture, measured during planning (docs/v0.7-plan.md Bölüm 1):
    # all 12 models in this project produce customer_id.
    project = load_dbt_project(sample_project_path)

    matches = build_feature_index(project)["customer_id"]

    assert len(matches) == 12
    assert {m.model for m in matches} == {model.name for model in project.models}
    # This fixture ships with no manifest -- static mode, so every match's
    # metadata is empty, not fabricated.
    assert all(m.description is None and m.owner is None for m in matches)


def test_build_feature_index_on_sample_banking_dbt_unique_column_has_one_match(
    sample_project_path: Path,
) -> None:
    project = load_dbt_project(sample_project_path)

    matches = build_feature_index(project)["lifetime_transaction_count"]

    assert len(matches) == 1
    assert matches[0].model == "int_customer_activity"


# ---------------------------------------------------------------------------
# summarize_downstream_impact() -- v0.8's Downstream Impact Analysis. Built
# directly on get_downstream_chain()'s existing output (chain + graph),
# not a new lineage computation -- docs/v0.8-plan.md Bölüm 1/4.
# ---------------------------------------------------------------------------


def _impact_model(summary, model_name: str):
    return next(m for m in summary.all_impacted if m.model == model_name)


_EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="module")
def sample_banking_lineage_graph() -> nx.DiGraph:
    # Module-scoped (can't depend on the function-scoped sample_project_path
    # fixture, so this recomputes the same path conftest.py does): building
    # this 12-model project's lineage graph is genuinely expensive (~12.8s,
    # measured during v0.7/v0.8 planning) -- every test below shares this
    # one build instead of paying that cost per test.
    project = load_dbt_project(_EXAMPLES_DIR / "sample_banking_dbt")
    return build_project_lineage(project)


@pytest.fixture(scope="module")
def multi_domain_lineage_graph() -> nx.DiGraph:
    project = load_dbt_project(_EXAMPLES_DIR / "multi_domain_dbt")
    return build_project_lineage(project)


def test_summarize_downstream_impact_no_downstream_is_all_zero(
    sample_banking_lineage_graph: nx.DiGraph,
) -> None:
    # A genuine leaf in this fixture's lineage graph (out_degree == 0,
    # verified against the real graph) -- nothing consumes it.
    target = ColumnNode(model="int_customer_activity", column="customer_id", layer="intermediate")
    chain = get_downstream_chain(sample_banking_lineage_graph, target)

    summary = summarize_downstream_impact(sample_banking_lineage_graph, target, chain)

    assert summary.affected_model_count == 0
    assert summary.affected_column_count == 0
    assert summary.direct == []
    assert summary.all_impacted == []


def test_summarize_downstream_impact_excludes_the_target_itself(
    sample_banking_lineage_graph: nx.DiGraph,
) -> None:
    target = ColumnNode(
        model="core_banking__transactions", column="transaction_timestamp", layer="unknown"
    )
    chain = get_downstream_chain(sample_banking_lineage_graph, target)

    summary = summarize_downstream_impact(sample_banking_lineage_graph, target, chain)

    assert all(m.model != "core_banking__transactions" for m in summary.all_impacted)
    # chain includes the target itself (get_downstream_chain's own
    # contract) -- the summary's column count must not count it.
    assert summary.affected_column_count == len(chain) - 1


def test_summarize_downstream_impact_dedupes_a_model_appearing_many_times(
    sample_banking_lineage_graph: nx.DiGraph,
) -> None:
    # Real fixture, measured during planning (docs/v0.8-plan.md Bölüm 1):
    # mart_customer_features appears 19 times in this chain (19 of its
    # own columns), but that's ONE model, not 19.
    target = ColumnNode(
        model="core_banking__transactions", column="transaction_timestamp", layer="unknown"
    )
    chain = get_downstream_chain(sample_banking_lineage_graph, target)

    summary = summarize_downstream_impact(sample_banking_lineage_graph, target, chain)

    assert summary.affected_model_count == 8
    assert summary.affected_column_count == 66
    mart_customer_features = _impact_model(summary, "mart_customer_features")
    assert len(mart_customer_features.columns) == 19


def test_summarize_downstream_impact_sorts_all_impacted_by_descending_column_count(
    sample_banking_lineage_graph: nx.DiGraph,
) -> None:
    target = ColumnNode(
        model="core_banking__transactions", column="transaction_timestamp", layer="unknown"
    )
    chain = get_downstream_chain(sample_banking_lineage_graph, target)

    summary = summarize_downstream_impact(sample_banking_lineage_graph, target, chain)

    assert [m.model for m in summary.all_impacted] == [
        "mart_customer_features",
        "mart_feature_store_export",
        "int_customer_spend_metrics",
        "int_customer_daily_balance",
        "int_customer_activity",
        "mart_customer_360",
        "mart_risk_features",
        "stg_transactions",
    ]


def test_summarize_downstream_impact_ties_are_broken_alphabetically(
    sample_banking_lineage_graph: nx.DiGraph,
) -> None:
    # mart_customer_360 and mart_risk_features are BOTH at 4 columns in
    # this chain -- descending-count sort alone doesn't define their
    # relative order, so the tiebreaker must be deterministic.
    target = ColumnNode(
        model="core_banking__transactions", column="transaction_timestamp", layer="unknown"
    )
    chain = get_downstream_chain(sample_banking_lineage_graph, target)

    summary = summarize_downstream_impact(sample_banking_lineage_graph, target, chain)

    tied = [m.model for m in summary.all_impacted if len(m.columns) == 4]
    assert tied == ["mart_customer_360", "mart_risk_features"]


def test_summarize_downstream_impact_direct_can_span_multiple_models(
    sample_banking_lineage_graph: nx.DiGraph,
) -> None:
    # stg_transactions.amount has 7 immediate successors across 3
    # different models (docs/v0.8-plan.md Bölüm 1/2) -- real branching,
    # not a straight line, and "direct" isn't limited to one model.
    target = ColumnNode(model="stg_transactions", column="amount", layer="staging")
    chain = get_downstream_chain(sample_banking_lineage_graph, target)

    summary = summarize_downstream_impact(sample_banking_lineage_graph, target, chain)

    assert {m.model for m in summary.direct} == {
        "stg_transactions",
        "int_customer_daily_balance",
        "int_customer_spend_metrics",
    }
    direct_stg = next(m for m in summary.direct if m.model == "stg_transactions")
    assert set(direct_stg.columns) == {
        "credit_amount",
        "debit_amount",
        "incoming_transfer_amount",
        "outgoing_transfer_amount",
        "spend_amount",
    }
    assert summary.affected_model_count == 7
    assert summary.affected_column_count == 53


def test_summarize_downstream_impact_direct_is_a_subset_of_all_impacted(
    sample_banking_lineage_graph: nx.DiGraph,
) -> None:
    target = ColumnNode(model="stg_transactions", column="amount", layer="staging")
    chain = get_downstream_chain(sample_banking_lineage_graph, target)

    summary = summarize_downstream_impact(sample_banking_lineage_graph, target, chain)

    all_impacted_columns = {
        (m.model, column) for m in summary.all_impacted for column in m.columns
    }
    direct_columns = {(m.model, column) for m in summary.direct for column in m.columns}
    assert direct_columns <= all_impacted_columns


def test_summarize_downstream_impact_on_multi_domain_dbt(
    multi_domain_lineage_graph: nx.DiGraph,
) -> None:
    target = ColumnNode(
        model="lending_raw__loan_applications", column="requested_amount", layer="unknown"
    )
    chain = get_downstream_chain(multi_domain_lineage_graph, target)

    summary = summarize_downstream_impact(multi_domain_lineage_graph, target, chain)

    assert summary.affected_model_count == 5
    assert summary.affected_column_count == 7
    assert summary.all_impacted[0].model == "mart_default_risk"
    assert len(summary.all_impacted[0].columns) == 3
