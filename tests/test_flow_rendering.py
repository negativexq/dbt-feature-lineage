"""Tests for ui/flow_rendering.py -- build_model_dag_flow_elements().

A pure conversion function (services.model_dag_service.build_model_dag()'s
nx.DiGraph -> StreamlitFlowNode/StreamlitFlowEdge lists), so it's tested
directly rather than through pages/model_dag.py's AppTest coverage --
same "test the data going into the component, not the component itself"
strategy as test_app.py's Model DAG page tests (docs/v0.5-plan.md Bölüm 8).
"""

from __future__ import annotations

import networkx as nx

from dbt_feature_lineage.ui.flow_rendering import build_model_dag_flow_elements


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
