"""Column Lineage page: project-wide column search + upstream/downstream lineage graph.

Independent of Model Explorer's model selection -- this searches the
whole project by column name, not a single selected model.

A separate page (rather than a tab on Model Explorer, which is how v0.4
first shipped this) specifically so that build_project_lineage() -- the
expensive part, one sqlglot.lineage() call per model output column --
only runs when a user actually opens this page. st.tabs() bodies all
execute on every rerun regardless of which tab is visible; st.navigation()
pages don't (verified: only the active page's script executes).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from dbt_feature_lineage.services.column_search import (
    build_search_index,
    get_downstream_chain,
    get_upstream_chain,
)
from dbt_feature_lineage.services.lineage_service import lineage_cache_key
from dbt_feature_lineage.ui import build_lineage_dot
from dbt_feature_lineage.ui.state import (
    DEFAULT_PROJECT_PATH,
    cached_build_project_lineage,
    cached_load_project,
    manifest_mtime,
)

st.title("Column Lineage")
st.caption("Searches the whole project, not just a single model.")

project_path = st.text_input("dbt project path", value=DEFAULT_PROJECT_PATH)
resolved_path = Path(project_path).expanduser()

if not resolved_path.exists():
    st.error(f"Project path does not exist: {resolved_path}")
    st.stop()

try:
    project = cached_load_project(str(resolved_path), manifest_mtime(resolved_path))
except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
    st.error(str(exc))
    st.stop()

with st.spinner("Building project-wide lineage graph..."):
    lineage_graph = cached_build_project_lineage(
        str(resolved_path),
        manifest_mtime(resolved_path),
        lineage_cache_key(project),
    )

lineage_warnings = lineage_graph.graph.get("lineage_warnings", [])
if lineage_warnings:
    with st.expander(f"{len(lineage_warnings)} model(s) excluded from lineage"):
        for warning in lineage_warnings:
            st.warning(warning)

search_term = st.text_input("Search for a column", value="", key="lineage_search")
direction_label = st.radio(
    "Direction",
    options=["Upstream (to raw sources)", "Downstream (to consumers)"],
    horizontal=True,
    key="lineage_direction",
)
search_index = build_search_index(lineage_graph)
matches = [
    node
    for name, nodes in search_index.items()
    if search_term and search_term.lower() in name.lower()
    for node in nodes
]

if search_term and not matches:
    st.info(f"No columns matching '{search_term}'.")
elif matches:
    label_to_node = {f"{node.model}.{node.column} ({node.layer})": node for node in matches}
    selected_label = st.selectbox(
        "Select a match", options=sorted(label_to_node), key="lineage_match"
    )
    target = label_to_node[selected_label]
    is_upstream = direction_label.startswith("Upstream")
    chain = (
        get_upstream_chain(lineage_graph, target)
        if is_upstream
        else get_downstream_chain(lineage_graph, target)
    )

    if len(chain) == 1:
        message = (
            "No upstream lineage found for this column (raw source or no traceable inputs)."
            if is_upstream
            else "No downstream lineage found for this column (nothing consumes it)."
        )
        st.info(message)
    else:
        large_view = len(chain) > 12 and st.checkbox("Show larger view", key="lineage_large_view")
        chain_subgraph = lineage_graph.subgraph(chain)
        st.graphviz_chart(
            build_lineage_dot(chain_subgraph),
            width="stretch",
            height=800 if large_view else 450,
        )
