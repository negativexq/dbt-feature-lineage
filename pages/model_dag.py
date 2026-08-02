"""Model DAG page: project-wide model-level dependency graph (v0.5).

Independent of Model Explorer's model selection and Column Lineage's
column search -- its own "dbt project path" input, same pattern
v0.4 established for Column Lineage (docs/v0.4-plan.md multi-page
follow-up). Renders via streamlit-flow-component (React Flow) instead
of build_lineage_dot()'s static graphviz DOT string, for zoom/pan/
minimap/click-to-inspect -- see docs/v0.5-plan.md Bölüm 4.
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
from dbt_feature_lineage.ui.state import (
    DEFAULT_PROJECT_PATH,
    cached_build_model_dag,
    cached_load_project,
    manifest_mtime,
)

st.title("Model DAG")
st.caption("Searches the whole project's model-level dependencies, not just a single model.")

project_path = st.text_input(
    "dbt project path", value=DEFAULT_PROJECT_PATH, key="model_dag_project_path"
)
resolved_path = Path(project_path).expanduser()

if not resolved_path.exists():
    st.error(f"Project path does not exist: {resolved_path}")
    st.stop()

try:
    project = cached_load_project(str(resolved_path), manifest_mtime(resolved_path))
except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
    st.error(str(exc))
    st.stop()

with st.spinner("Building model DAG..."):
    dag_key = model_dag_cache_key(project)
    graph = cached_build_model_dag(str(resolved_path), manifest_mtime(resolved_path), dag_key)

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
# whenever the underlying graph changes, or a previous project's stale
# nodes/edges would linger. dag_key already changes whenever anything
# build_model_dag() reads (SQL, ref()s, or metadata) does, so comparing
# against the last key used to build model_dag_state is enough.
if (
    "model_dag_state" not in st.session_state
    or st.session_state.get("model_dag_state_key") != dag_key
):
    theme_base = st.get_option("theme.base") or "light"
    nodes, edges = build_model_dag_flow_elements(graph, theme_base)
    st.session_state.model_dag_state = StreamlitFlowState(nodes, edges)
    st.session_state.model_dag_state_key = dag_key

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
