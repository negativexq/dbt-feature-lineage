"""Column Lineage page: project-wide column search + upstream/downstream lineage graph.

Independent of Model Explorer's model selection -- this searches the
whole project by column name, not a single selected model. Reads the
project path and model group from shared session_state (set once on
pages/select_project.py) rather than its own "dbt project path" input
and group filter -- see pages/select_project.py's module docstring for
why that's safe to rely on.

A separate page (rather than a tab on Model Explorer, which is how v0.4
first shipped this) specifically so that build_project_lineage() -- the
expensive part, one sqlglot.lineage() call per model output column --
only runs when a user actually opens this page. st.tabs() bodies all
execute on every rerun regardless of which tab is visible; st.navigation()
pages don't (verified: only the active page's script executes).

Renders via streamlit-flow-component (React Flow) rather than v0.4's
static build_lineage_dot()/st.graphviz_chart -- same component and
layout/session_state/theming pattern pages/model_dag.py established
(v0.5), for visual consistency between the two graph pages and the
zoom/pan/minimap interactivity a static DOT string couldn't offer.

When a model group is selected, it narrows the lineage graph itself (via
cached_build_project_lineage's selected_group -- built from a
group-filtered project, not the full one), not just the search results:
a column whose real upstream/downstream crosses into a different group
will show that neighbor as an unresolved leaf instead of a fully-traced
node, the same graceful degradation lineage_service already applies to
any other reference it can't resolve. This is a deliberate behavior
change from v0.5's per-page multiselect design, where filtering only
ever narrowed search results and never touched the trace itself -- here
the group is a one-time, upfront choice (pages/select_project.py), so
"give me retail's lineage" is taken at face value rather than hedged.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit_flow import streamlit_flow
from streamlit_flow.layouts import LayeredLayout
from streamlit_flow.state import StreamlitFlowState

from dbt_feature_lineage.services.column_search import (
    build_search_index,
    get_downstream_chain,
    get_upstream_chain,
)
from dbt_feature_lineage.services.lineage_service import lineage_cache_key
from dbt_feature_lineage.ui.flow_rendering import build_column_lineage_flow_elements
from dbt_feature_lineage.ui.state import (
    cached_build_project_lineage,
    cached_load_project,
    manifest_mtime,
)

st.title("Column Lineage")
st.caption("Searches the whole project, not just a single model.")

if "shared_project_path" not in st.session_state:
    st.info("No project selected yet.")
    st.page_link("pages/select_project.py", label="Select a project", icon="🗂️")
    st.stop()

project_path = st.session_state["shared_project_path"]
selected_group = st.session_state.get("shared_model_group")
resolved_path = Path(project_path).expanduser()

if not resolved_path.exists():
    st.error(f"Project path does not exist: {resolved_path}")
    st.page_link("pages/select_project.py", label="Select a project", icon="🗂️")
    st.stop()

try:
    project = cached_load_project(str(resolved_path), manifest_mtime(resolved_path))
except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
    st.error(str(exc))
    st.stop()

header_col, change_col = st.columns([4, 1])
with header_col:
    st.caption(f"Current project: **{project.name}** (group: {selected_group or 'All'})")
with change_col:
    st.page_link("pages/select_project.py", label="Change", icon="🔄")

with st.spinner("Building project-wide lineage graph..."):
    lineage_key = lineage_cache_key(project)
    lineage_graph = cached_build_project_lineage(
        str(resolved_path), manifest_mtime(resolved_path), lineage_key, selected_group
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
        chain_subgraph = lineage_graph.subgraph(chain)

        # Same session_state pattern as pages/model_dag.py: the
        # component's own pan/zoom state must survive reruns, but has to
        # be rebuilt whenever the selected column/direction/project/group
        # changes, or a previous selection's stale nodes/edges would
        # linger in the canvas. lineage_key alone doesn't capture a group
        # change (it's computed from the *unfiltered* project), so
        # selected_group is folded in explicitly, same reasoning as
        # pages/model_dag.py's flow_key.
        flow_key = (
            lineage_key,
            selected_group,
            target.model,
            target.column,
            target.layer,
            is_upstream,
        )
        if (
            "column_lineage_state" not in st.session_state
            or st.session_state.get("column_lineage_state_key") != flow_key
        ):
            theme_base = st.get_option("theme.base") or "light"
            nodes, edges = build_column_lineage_flow_elements(chain_subgraph, theme_base)
            st.session_state.column_lineage_state = StreamlitFlowState(nodes, edges)
            st.session_state.column_lineage_state_key = flow_key

        large_view = len(chain) > 12 and st.checkbox("Show larger view", key="lineage_large_view")
        new_state = streamlit_flow(
            "column_lineage",
            st.session_state.column_lineage_state,
            layout=LayeredLayout(direction="right"),
            fit_view=True,
            show_controls=True,
            show_minimap=True,
            height=800 if large_view else 450,
        )
        st.session_state.column_lineage_state = new_state
