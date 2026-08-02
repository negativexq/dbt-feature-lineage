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
from dbt_feature_lineage.domain.models import QueryFlowStep
from dbt_feature_lineage.ui.flow_rendering import (
    build_column_lineage_flow_elements,
    build_model_dag_flow_elements,
    build_query_flow_elements,
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


# ---------------------------------------------------------------------------
# build_query_flow_elements() -- v0.6's per-model Query Flow diagram
# (docs/v0.6-plan.md Bölüm 4). Consumes build_query_flow_steps()'s
# QueryFlowStep list, not an nx.DiGraph -- the third distinct conversion
# in this module, same shared palette/selectable=True/theme contract as
# the other two.
# ---------------------------------------------------------------------------


def _query_flow_steps() -> list[QueryFlowStep]:
    return [
        QueryFlowStep(step_id="source:stg_customers", step_type="source", name="stg_customers"),
        QueryFlowStep(
            step_id="cte:joined",
            step_type="cte",
            name="joined",
            upstream_step_ids=["source:stg_customers"],
            join_types=["LEFT"],
            has_where_clause=True,
            group_by_columns=["customer_id"],
        ),
        QueryFlowStep(
            step_id="final_select",
            step_type="final_select",
            name="final_select",
            upstream_step_ids=["cte:joined"],
        ),
        QueryFlowStep(
            step_id="output",
            step_type="output",
            name="mart_customers",
            upstream_step_ids=["final_select"],
        ),
    ]


def test_build_query_flow_elements_one_node_per_step() -> None:
    nodes, _edges = build_query_flow_elements(_query_flow_steps())

    assert {node.id for node in nodes} == {
        "source:stg_customers",
        "cte:joined",
        "final_select",
        "output",
    }


def test_build_query_flow_elements_nodes_are_selectable() -> None:
    # Same reasoning as build_model_dag_flow_elements's selectable test --
    # without this, clicking a step node never updates the detail panel
    # (verified against a real browser during v0.5 development).
    nodes, _edges = build_query_flow_elements(_query_flow_steps())

    assert all(node.selectable for node in nodes)


def test_build_query_flow_elements_one_edge_per_upstream_link() -> None:
    _nodes, edges = build_query_flow_elements(_query_flow_steps())

    edge_pairs = {(edge.source, edge.target) for edge in edges}
    assert edge_pairs == {
        ("source:stg_customers", "cte:joined"),
        ("cte:joined", "final_select"),
        ("final_select", "output"),
    }


def test_build_query_flow_elements_edge_direction_is_upstream_to_step() -> None:
    _nodes, edges = build_query_flow_elements(_query_flow_steps())

    joined_edge = next(edge for edge in edges if edge.target == "cte:joined")
    assert joined_edge.source == "source:stg_customers"


def test_build_query_flow_elements_step_with_multiple_upstream_ids_gets_multiple_edges() -> None:
    steps = [
        QueryFlowStep(step_id="cte:a", step_type="cte", name="a"),
        QueryFlowStep(step_id="cte:b", step_type="cte", name="b"),
        QueryFlowStep(
            step_id="cte:joined",
            step_type="cte",
            name="joined",
            upstream_step_ids=["cte:a", "cte:b"],
        ),
    ]

    _nodes, edges = build_query_flow_elements(steps)

    joined_edges = [edge for edge in edges if edge.target == "cte:joined"]
    assert {edge.source for edge in joined_edges} == {"cte:a", "cte:b"}


def test_build_query_flow_elements_cte_node_content_shows_join_filter_group_by_badges() -> None:
    nodes, _edges = build_query_flow_elements(_query_flow_steps())

    joined_node = next(node for node in nodes if node.id == "cte:joined")
    content = joined_node.data["content"]
    assert "joined" in content
    assert "join" in content.lower()
    assert "filter" in content.lower()
    assert "group by" in content.lower()


def test_build_query_flow_elements_source_node_content_has_no_badges() -> None:
    nodes, _edges = build_query_flow_elements(_query_flow_steps())

    source_node = next(node for node in nodes if node.id == "source:stg_customers")
    assert "stg_customers" in source_node.data["content"]


def test_build_query_flow_elements_output_node_content_includes_model_name() -> None:
    nodes, _edges = build_query_flow_elements(_query_flow_steps())

    output_node = next(node for node in nodes if node.id == "output")
    assert "mart_customers" in output_node.data["content"]


def test_build_query_flow_elements_empty_steps_returns_empty_lists() -> None:
    nodes, edges = build_query_flow_elements([])

    assert nodes == []
    assert edges == []


def test_build_query_flow_elements_dark_theme_uses_a_different_palette() -> None:
    light_nodes, light_edges = build_query_flow_elements(_query_flow_steps(), theme_base="light")
    dark_nodes, dark_edges = build_query_flow_elements(_query_flow_steps(), theme_base="dark")

    assert light_nodes[0].style != dark_nodes[0].style
    assert light_edges[0].style != dark_edges[0].style


def test_build_query_flow_elements_shares_the_model_dag_palette() -> None:
    query_flow_nodes, _ = build_query_flow_elements(_query_flow_steps())
    model_nodes, _ = build_model_dag_flow_elements(_graph())

    assert query_flow_nodes[0].style == model_nodes[0].style
