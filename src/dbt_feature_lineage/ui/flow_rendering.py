"""streamlit_flow-specific conversion helpers for the Model DAG, Column
Lineage, and (v0.6) Query Flow pages.

Kept separate from ui/rendering.py, which stays free of any streamlit/
streamlit_flow import by its own module contract (so it's testable
without a running app or the component's frontend build) -- this module
exists specifically to turn a services graph into StreamlitFlowNode/
StreamlitFlowEdge objects for pages/model_dag.py and
pages/column_lineage.py. Importing streamlit_flow here (rather than in
ui/rendering.py) is the same boundary v0.4's ui/state.py already draws
for plain `streamlit` imports.

Two separate conversion functions, not one: build_model_dag_flow_elements()
consumes services.model_dag_service.build_model_dag()'s graph (plain
model-name string nodes), while build_column_lineage_flow_elements()
consumes a services.column_search.get_upstream_chain()/
get_downstream_chain() subgraph (domain.lineage.ColumnNode nodes,
ColumnEdge-shaped edge data) -- different domain type, different node
identity/content shape, genuinely two distinct conversions that only
happen to share a target format and a color palette.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode

from dbt_feature_lineage.domain.lineage import ColumnNode
from dbt_feature_lineage.domain.models import QueryFlowStep

# React Flow's own default styling is light and doesn't inherit
# Streamlit's theme -- custom components render in an isolated iframe and
# can't read the host app's CSS (confirmed: Streamlit's own docs list
# this as a hard limitation of custom components, not a bug) -- so the
# palette is applied explicitly based on st.get_option("theme.base"),
# rather than left to the component's defaults. Shared by both
# conversion functions below for visual consistency between the two
# graph pages (docs/v0.5-plan.md Bölüm 4/5).
_LIGHT_NODE_STYLE: dict[str, str] = {
    "backgroundColor": "#eef2f7",
    "color": "#1a2233",
    "border": "1px solid #b8c4d9",
    "borderRadius": "8px",
    "padding": "10px",
}
_DARK_NODE_STYLE: dict[str, str] = {
    "backgroundColor": "#2b2f3a",
    "color": "#e6e9ef",
    "border": "1px solid #47506b",
    "borderRadius": "8px",
    "padding": "10px",
}
_LIGHT_EDGE_STYLE: dict[str, str] = {"stroke": "#6b7a99"}
_DARK_EDGE_STYLE: dict[str, str] = {"stroke": "#8892b0"}


def build_model_dag_flow_elements(
    graph: nx.DiGraph, theme_base: str = "light"
) -> tuple[list[StreamlitFlowNode], list[StreamlitFlowEdge]]:
    """Convert a build_model_dag() graph into React Flow elements.

    `theme_base` should be `st.get_option("theme.base")` ("light"/"dark",
    possibly None) -- passed in rather than read here so this stays a
    pure function of its arguments, unit-testable without a Streamlit
    runtime. Node positions are left at (0, 0): pages/model_dag.py always
    renders with a `Layout` (LayeredLayout) that computes real positions
    via ELK, so the placeholder here is never actually seen.
    """

    node_style = _DARK_NODE_STYLE if theme_base == "dark" else _LIGHT_NODE_STYLE
    edge_style = _DARK_EDGE_STYLE if theme_base == "dark" else _LIGHT_EDGE_STYLE

    nodes = [
        StreamlitFlowNode(
            id=model_name,
            pos=(0, 0),
            data={"content": _node_content(model_name, attrs)},
            node_type="default",
            source_position="right",
            target_position="left",
            # StreamlitFlowNode defaults selectable=False -- without this,
            # clicking a node never sets new_state.selected_id and the
            # detail panel (pages/model_dag.py) never updates (verified
            # against a real browser, not just AppTest, during development).
            selectable=True,
            style=dict(node_style),
        )
        for model_name, attrs in graph.nodes(data=True)
    ]
    edges = [
        StreamlitFlowEdge(
            id=f"{source}->{target}",
            source=source,
            target=target,
            marker_end={"type": "arrowclosed"},
            style=dict(edge_style),
        )
        for source, target in graph.edges
    ]
    return nodes, edges


def _node_content(model_name: str, attrs: dict[str, Any]) -> str:
    """Markdown node label -- streamlit-flow-component renders node
    `data.content` through a markdown renderer (verified against the
    component's bundled frontend build), so "**bold**" and a two-space
    trailing line break both work here."""

    materialization = attrs.get("materialization") or "unknown"
    column_count = attrs.get("column_count", 0)
    column_label = "column" if column_count == 1 else "columns"
    return f"**{model_name}**  \n{materialization} · {column_count} {column_label}"


def build_column_lineage_flow_elements(
    subgraph: nx.DiGraph, theme_base: str = "light"
) -> tuple[list[StreamlitFlowNode], list[StreamlitFlowEdge]]:
    """Convert a get_upstream_chain()/get_downstream_chain() subgraph
    into React Flow elements for pages/column_lineage.py.

    Replaces build_lineage_dot()'s static graphviz DOT string (removed --
    this was its only caller). Edge labels carry `transformation_type`,
    same information build_lineage_dot() put in its DOT edge labels, just
    rendered by streamlit_flow's own edge-label support instead of DOT
    syntax. `theme_base` should be `st.get_option("theme.base")`, same
    contract as build_model_dag_flow_elements().
    """

    node_style = _DARK_NODE_STYLE if theme_base == "dark" else _LIGHT_NODE_STYLE
    edge_style = _DARK_EDGE_STYLE if theme_base == "dark" else _LIGHT_EDGE_STYLE

    nodes = [
        StreamlitFlowNode(
            id=_column_node_id(node),
            pos=(0, 0),
            data={"content": _column_node_content(node)},
            node_type="default",
            source_position="right",
            target_position="left",
            style=dict(node_style),
        )
        for node in subgraph.nodes
    ]
    edges = [
        StreamlitFlowEdge(
            id=f"{_column_node_id(source)}->{_column_node_id(target)}",
            source=_column_node_id(source),
            target=_column_node_id(target),
            label=str(data.get("transformation_type", "")),
            label_show_bg=True,
            marker_end={"type": "arrowclosed"},
            style=dict(edge_style),
        )
        for source, target, data in subgraph.edges(data=True)
    ]
    return nodes, edges


def _column_node_id(node: ColumnNode) -> str:
    return f"{node.model}.{node.column}"


def _column_node_content(node: ColumnNode) -> str:
    return f"**{node.column}**  \n{node.model} ({node.layer})"


def build_query_flow_elements(
    steps: list[QueryFlowStep], theme_base: str = "light"
) -> tuple[list[StreamlitFlowNode], list[StreamlitFlowEdge]]:
    """Convert a build_query_flow_steps() list into React Flow elements
    for the Query Flow tab (pages/model_explorer.py, v0.6).

    Third distinct conversion in this module: a flat QueryFlowStep list
    (already ordered source -> cte -> final_select -> output), not an
    nx.DiGraph -- edges come from each step's own `upstream_step_ids`
    rather than graph edges. Same shared palette/`theme_base` contract
    and `selectable=True` requirement as the other two conversions (see
    build_model_dag_flow_elements's docstring for why selectable matters
    for the click -> detail-panel behavior).
    """

    node_style = _DARK_NODE_STYLE if theme_base == "dark" else _LIGHT_NODE_STYLE
    edge_style = _DARK_EDGE_STYLE if theme_base == "dark" else _LIGHT_EDGE_STYLE

    nodes = [
        StreamlitFlowNode(
            id=step.step_id,
            pos=(0, 0),
            data={"content": _query_flow_node_content(step)},
            node_type="default",
            source_position="right",
            target_position="left",
            selectable=True,
            style=dict(node_style),
        )
        for step in steps
    ]
    edges = [
        StreamlitFlowEdge(
            id=f"{upstream_id}->{step.step_id}",
            source=upstream_id,
            target=step.step_id,
            marker_end={"type": "arrowclosed"},
            style=dict(edge_style),
        )
        for step in steps
        for upstream_id in step.upstream_step_ids
    ]
    return nodes, edges


def _query_flow_node_content(step: QueryFlowStep) -> str:
    badges: list[str] = []
    if step.join_types:
        join_count = len(step.join_types)
        badges.append(f"{join_count} join" if join_count == 1 else f"{join_count} joins")
    if step.has_where_clause:
        badges.append("filter")
    if step.group_by_columns:
        badges.append("group by")
    if step.window_functions:
        badges.append("window")
    badge_line = " · ".join(badges) if badges else step.step_type
    return f"**{step.name}**  \n{badge_line}"
