"""Select Project page: shared project/model-group selection (v0.6).

First/default page in the nav -- Model Explorer, Model DAG, and Column
Lineage no longer each have their own "dbt project path" input and (for
the latter two) their own group filter widget; they all read
`st.session_state["shared_project_path"]`/`["shared_model_group"]`,
written here once via "Continue".

This design is only safe because of what a throwaway sandbox spike
confirmed first (not assumed): st.session_state survives both
st.switch_page() and ordinary sidebar navigation clicks within the same
browser session/tab -- the earlier per-page multiselect design predated
that confirmation and defensively avoided sharing state at all. The one
real limitation the same spike found: a full browser refresh (F5) resets
session_state unconditionally, in either design -- unavoidable, not
specific to this one, so each of the other three pages must still cope
with "no project selected yet" as a normal, expected state.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from dbt_feature_lineage.loaders.project_discovery import discover_dbt_projects
from dbt_feature_lineage.ui import detect_model_groups
from dbt_feature_lineage.ui.state import cached_load_project, manifest_mtime

st.title("Select Project")
st.caption(
    "Pick a dbt project and, optionally, a model group -- shared with "
    "Model Explorer, Model DAG, and Column Lineage."
)

root_input = st.text_input("Root directory to scan", value="examples", key="select_project_root")
root_path = Path(root_input).expanduser()

if not root_path.exists():
    st.error(f"Root directory does not exist: {root_path}")
    st.stop()

discovered = discover_dbt_projects(root_path)

if not discovered:
    st.warning(f"No dbt projects (dbt_project.yml) found under {root_path}.")
    st.stop()

project_options = {f"{p.name} ({p.relative_path})": p.path for p in discovered}
selected_label = st.selectbox(
    "Project", options=sorted(project_options), key="select_project_project"
)
selected_path = project_options[selected_label]
resolved_path = Path(selected_path)

try:
    project = cached_load_project(str(resolved_path), manifest_mtime(resolved_path))
except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
    st.error(str(exc))
    st.stop()

st.success(f"Loaded project: {project.name} ({len(project.models)} models)")

available_groups = detect_model_groups(project.models)
if available_groups:
    group_options = ["All", *available_groups]
    selected_group_label = st.selectbox(
        "Model group", options=group_options, key="select_project_group"
    )
    selected_group = None if selected_group_label == "All" else selected_group_label
else:
    selected_group = None

if st.button("Continue", key="select_project_continue"):
    st.session_state["shared_project_path"] = selected_path
    st.session_state["shared_model_group"] = selected_group
    st.switch_page("pages/model_explorer.py")
