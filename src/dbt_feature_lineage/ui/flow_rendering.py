"""streamlit_flow-specific conversion helpers for the Model DAG page.

Kept separate from ui/rendering.py, which stays free of any streamlit/
streamlit_flow import by its own module contract (so it's testable
without a running app or the component's frontend build) -- this module
exists specifically to turn a services.model_dag_service.build_model_dag()
graph into StreamlitFlowNode/StreamlitFlowEdge objects for
pages/model_dag.py. Importing streamlit_flow here (rather than in
ui/rendering.py) is the same boundary v0.4's ui/state.py already draws
for plain `streamlit` imports.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode

# React Flow's own default styling is light and doesn't inherit
# Streamlit's theme -- custom components render in an isolated iframe and
# can't read the host app's CSS (confirmed: Streamlit's own docs list
# this as a hard limitation of custom components, not a bug) -- so the
# palette is applied explicitly based on st.get_option("theme.base"),
# rather than left to the component's defaults. Colors intentionally
# echo build_lineage_dot()'s node fill (#eef2f7) for visual consistency
# between the two graph pages (docs/v0.5-plan.md Bölüm 4/5).
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
