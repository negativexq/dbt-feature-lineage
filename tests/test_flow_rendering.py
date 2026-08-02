"""Tests for ui/flow_rendering.py: build_model_dag_flow_elements() and
build_column_lineage_flow_elements().

Both are pure conversion functions (an nx.DiGraph -> StreamlitFlowNode/
StreamlitFlowEdge lists), so they're tested directly rather than through
their pages' AppTest coverage -- same "test the data going into the
component, not the component itself" strategy as test_app.py's Model
DAG/Column Lineage page tests (docs/v0.5-plan.md Bölüm 8).
"""

from __future__ import annotations

import networkx as nx

from dbt_feature_lineage.domain.lineage import ColumnNode
from dbt_feature_lineage.ui.flow_rendering import (
    build_column_lineage_flow_elements,
    build_model_dag_flow_elements,
)


def _graph() -> nx.DiGraph:
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_node(
        "stg_customers",
        layer="staging",
        materialization="view",
        description=None,
        tags=[],
        test_count=0,
        owner=None,
        column_count=4,
    )
    graph.add_node(
        "mart_customers",
        layer="marts",
        materialization="table",
        description="Customer mart.",
        tags=["finance"],
        test_count=1,
        owner="finance-team",
        column_count=1,
    )
    graph.add_edge("stg_customers", "mart_customers")
    return graph


def test_build_model_dag_flow_elements_one_node_per_graph_node() -> None:
    nodes, _edges = build_model_dag_flow_elements(_graph())

    assert {node.id for node in nodes} == {"stg_customers", "mart_customers"}


def test_build_model_dag_flow_elements_nodes_are_selectable() -> None:
    # StreamlitFlowNode defaults selectable=False -- without explicitly
    # overriding it, clicking a node in a real browser never sets
    # new_state.selected_id and pages/model_dag.py's detail panel never
    # updates (a real bug caught by manual browser verification, not by
    # AppTest -- AppTest can't simulate the click at all, see
    # docs/v0.5-plan.md Bölüm 8, so this is the only automated check
    # for it).
    nodes, _edges = build_model_dag_flow_elements(_graph())

    assert all(node.selectable for node in nodes)


def test_build_model_dag_flow_elements_one_edge_per_graph_edge() -> None:
    _nodes, edges = build_model_dag_flow_elements(_graph())

    assert len(edges) == 1
    assert edges[0].source == "stg_customers"
    assert edges[0].target == "mart_customers"


def test_build_model_dag_flow_elements_node_content_includes_name_materialization_and_columns() -> (
    None
):
    nodes, _edges = build_model_dag_flow_elements(_graph())

    mart_node = next(node for node in nodes if node.id == "mart_customers")
    content = mart_node.data["content"]
    assert "mart_customers" in content
    assert "table" in content
    assert "1 column" in content  # singular, not "1 columns"


def test_build_model_dag_flow_elements_pluralizes_column_count() -> None:
    nodes, _edges = build_model_dag_flow_elements(_graph())

    stg_node = next(node for node in nodes if node.id == "stg_customers")
    assert "4 columns" in stg_node.data["content"]


def test_build_model_dag_flow_elements_missing_materialization_shows_unknown() -> None:
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_node("orphan_model", layer="unknown", materialization=None, column_count=0)

    nodes, _edges = build_model_dag_flow_elements(graph)

    assert "unknown" in nodes[0].data["content"]


def test_build_model_dag_flow_elements_empty_graph_returns_empty_lists() -> None:
    nodes, edges = build_model_dag_flow_elements(nx.DiGraph())

    assert nodes == []
    assert edges == []


def test_build_model_dag_flow_elements_dark_theme_uses_a_different_palette() -> None:
    light_nodes, light_edges = build_model_dag_flow_elements(_graph(), theme_base="light")
    dark_nodes, dark_edges = build_model_dag_flow_elements(_graph(), theme_base="dark")

    assert light_nodes[0].style != dark_nodes[0].style
    assert light_edges[0].style != dark_edges[0].style


def test_build_model_dag_flow_elements_unrecognized_theme_falls_back_to_light() -> None:
    default_nodes, _ = build_model_dag_flow_elements(_graph())
    light_nodes, _ = build_model_dag_flow_elements(_graph(), theme_base="light")

    assert default_nodes[0].style == light_nodes[0].style


# ---------------------------------------------------------------------------
# build_column_lineage_flow_elements() -- replaces build_lineage_dot()
# (removed, its only caller). Separate conversion from
# build_model_dag_flow_elements(): domain.lineage.ColumnNode nodes and
# ColumnEdge-shaped edge data, not a plain model-name string graph.
# ---------------------------------------------------------------------------


def _column_lineage_graph() -> nx.DiGraph:
    source = ColumnNode(model="stg_customers", column="customer_id", layer="staging")
    target = ColumnNode(model="mart_customer_overview", column="customer_id", layer="marts")
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_edge(source, target, transformation_type="direct", expression_sql="a.customer_id")
    return graph


def test_build_column_lineage_flow_elements_one_node_per_column_node() -> None:
    nodes, _edges = build_column_lineage_flow_elements(_column_lineage_graph())

    assert {node.id for node in nodes} == {
        "stg_customers.customer_id",
        "mart_customer_overview.customer_id",
    }


def test_build_column_lineage_flow_elements_one_edge_per_column_edge() -> None:
    _nodes, edges = build_column_lineage_flow_elements(_column_lineage_graph())

    assert len(edges) == 1
    assert edges[0].source == "stg_customers.customer_id"
    assert edges[0].target == "mart_customer_overview.customer_id"


def test_build_column_lineage_flow_elements_edge_label_carries_transformation_type() -> None:
    _nodes, edges = build_column_lineage_flow_elements(_column_lineage_graph())

    assert edges[0].label == "direct"


def test_build_column_lineage_flow_elements_node_content_includes_column_model_and_layer() -> (
    None
):
    nodes, _edges = build_column_lineage_flow_elements(_column_lineage_graph())

    target_node = next(node for node in nodes if node.id == "mart_customer_overview.customer_id")
    content = target_node.data["content"]
    assert "customer_id" in content
    assert "mart_customer_overview" in content
    assert "marts" in content


def test_build_column_lineage_flow_elements_missing_transformation_type_is_blank_label() -> None:
    source = ColumnNode(model="a", column="x", layer="unknown")
    target = ColumnNode(model="b", column="x", layer="unknown")
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_edge(source, target)  # no transformation_type/expression_sql edge data

    _nodes, edges = build_column_lineage_flow_elements(graph)

    assert edges[0].label == ""


def test_build_column_lineage_flow_elements_empty_graph_returns_empty_lists() -> None:
    nodes, edges = build_column_lineage_flow_elements(nx.DiGraph())

    assert nodes == []
    assert edges == []


def test_build_column_lineage_flow_elements_dark_theme_uses_a_different_palette() -> None:
    light_nodes, light_edges = build_column_lineage_flow_elements(
        _column_lineage_graph(), theme_base="light"
    )
    dark_nodes, dark_edges = build_column_lineage_flow_elements(
        _column_lineage_graph(), theme_base="dark"
    )

    assert light_nodes[0].style != dark_nodes[0].style
    assert light_edges[0].style != dark_edges[0].style


def test_build_column_lineage_flow_elements_shares_the_model_dag_palette() -> None:
    # Not the same conversion function, but a deliberately shared palette
    # for visual consistency between the two graph pages.
    column_nodes, _ = build_column_lineage_flow_elements(_column_lineage_graph())
    model_nodes, _ = build_model_dag_flow_elements(_graph())

    assert column_nodes[0].style == model_nodes[0].style
