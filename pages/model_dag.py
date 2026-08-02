"""Model DAG page: project-wide model-level dependency graph (v0.5).

Independent of Model Explorer's model selection and Column Lineage's
column search. Reads the project path and model group from shared
session_state (set once on pages/select_project.py) rather than its own
"dbt project path" input -- see pages/select_project.py's module
docstring for why that's safe to rely on (session_state survives both
st.switch_page() and ordinary sidebar navigation within one browser
session; a full refresh resets it regardless of this design).

Renders via streamlit-flow-component (React Flow) instead of v0.4's
static graphviz DOT string, for zoom/pan/minimap/click-to-inspect -- see
docs/v0.5-plan.md Bölüm 4.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit_flow import streamlit_flow
from streamlit_flow.layouts import LayeredLayout
from streamlit_flow.state import StreamlitFlowState

from dbt_feature_lineage.services.model_dag_service import model_dag_cache_key
from dbt_feature_lineage.ui import render_node_detail_panel
from dbt_feature_lineage.ui.flow_rendering import build_model_dag_flow_elements
from dbt_feature_lineage.ui.state import cached_build_model_dag, cached_load_project, manifest_mtime

st.title("Model DAG")
st.caption("Searches the whole project's model-level dependencies, not just a single model.")

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

with st.spinner("Building model DAG..."):
    dag_key = model_dag_cache_key(project)
    graph = cached_build_model_dag(
        str(resolved_path), manifest_mtime(resolved_path), dag_key, selected_group
    )

model_dag_warnings = graph.graph.get("model_dag_warnings", [])
if model_dag_warnings:
    with st.expander(f"{len(model_dag_warnings)} warning(s)"):
        for warning in model_dag_warnings:
            st.warning(warning)

if graph.number_of_nodes() == 0:
    st.info("No models to show (empty project, or every model was excluded -- see warnings above).")
    st.stop()

# The component's own pan/zoom/selection state lives in session_state so
# it survives reruns (e.g. clicking a node) -- but it must be rebuilt
# whenever the underlying graph OR the group selection changes, or a
# previous project's (or a previous group's) stale nodes/edges would
# linger. dag_key changes whenever anything build_model_dag() reads (SQL,
# ref()s, or metadata) does; selected_group is folded in too since
# cached_build_model_dag() is keyed on it but dag_key alone isn't (it's
# computed from the *unfiltered* project).
flow_key = (dag_key, selected_group)
if (
    "model_dag_state" not in st.session_state
    or st.session_state.get("model_dag_state_key") != flow_key
):
    theme_base = st.get_option("theme.base") or "light"
    nodes, edges = build_model_dag_flow_elements(graph, theme_base)
    st.session_state.model_dag_state = StreamlitFlowState(nodes, edges)
    st.session_state.model_dag_state_key = flow_key

graph_col, panel_col = st.columns([3, 1])

with graph_col:
    new_state = streamlit_flow(
        "model_dag",
        st.session_state.model_dag_state,
        layout=LayeredLayout(direction="right"),
        fit_view=True,
        show_controls=True,
        show_minimap=True,
        get_node_on_click=True,
    )
    st.session_state.model_dag_state = new_state

with panel_col:
    st.subheader("Details")
    if new_state.selected_id:
        panel = render_node_detail_panel(project, new_state.selected_id)
        for label, value in panel.items():
            st.write(f"**{label}:** {value}")
    else:
        st.caption("Click a node to see its details here.")
