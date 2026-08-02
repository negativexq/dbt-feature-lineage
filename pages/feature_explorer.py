"""Feature Explorer page: project-wide column-name search + per-model
metadata comparison (v0.7).

Independent of Model Explorer's model selection and Column Lineage's
lineage tracing -- this answers "which models produce a column named
X, and how does each one's own description/owner/tags/tests compare?",
never following a lineage edge. Reads the project path and model group
from shared session_state (set once on pages/select_project.py), same
pattern as the other three pages.

Renders as plain st.text_input/selectbox/dataframe, not a
streamlit-flow-component graph: the data here isn't a graph (two models
producing the same column name aren't "connected" by that fact), and a
side-by-side metadata comparison is what a dataframe is naturally good
at (docs/v0.7-plan.md Bölüm 3). This also means -- unlike Model DAG/
Column Lineage/Query Flow -- there's no click-to-inspect interaction
that AppTest can't simulate; this whole page is testable end-to-end.

Built on services.column_search.build_feature_index(), which is itself
built on services.schema_builder.build_project_schema() rather than a
lineage graph -- measured ~300x cheaper on real fixtures (docs/v0.7-plan.md
Bölüm 1), so no st.cache_data wrapper is added here either (same
reasoning as pages/model_explorer.py's Query Flow tab, v0.6).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from dbt_feature_lineage.services.column_search import build_feature_index
from dbt_feature_lineage.ui import filter_models_by_group
from dbt_feature_lineage.ui.state import cached_load_project, manifest_mtime

st.title("Feature Explorer")
st.caption("Search a column name across the whole project and compare each model's own metadata.")

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

if project.source == "static":
    st.warning(
        "This project is in static mode -- description, owner, tags, and test counts "
        "are only populated when a manifest is present (see the 'Generate artifacts' "
        "button on Model Explorer)."
    )

# Group filtering happens once, up front, on Select Project -- same
# convention as pages/model_explorer.py's sidebar: a group-scoped project
# is built before build_feature_index() runs, not filtered post-hoc, so a
# selected group's index never shows a column name that only exists
# outside it.
scoped_models = filter_models_by_group(project.models, [selected_group] if selected_group else [])
scoped_project = project.model_copy(update={"models": scoped_models})
feature_index = build_feature_index(scoped_project)

search_term = st.text_input("Search for a column", value="", key="feature_explorer_search")

if not search_term:
    st.info("Type a column name to search across every model in the project.")
    st.stop()

matching_names = [name for name in feature_index if search_term.lower() in name.lower()]

if not matching_names:
    st.info(f"No columns matching '{search_term}'.")
    st.stop()

# Exact match first, then alphabetical -- a substring search for "id"
# would otherwise bury the column literally named "id" among every
# other *_id column (docs/v0.7-plan.md Bölüm 5/Riskler).
exact_match = search_term.lower()
matching_names.sort(key=lambda name: (name.lower() != exact_match, name))

selected_column_name = st.selectbox(
    "Select a column", options=matching_names, key="feature_explorer_column_select"
)

matches = feature_index[selected_column_name]
rows = [
    {
        "Layer": match.layer,
        "Model": match.model,
        "Description": match.description or "",
        "Owner": match.owner or "",
        "Tags": ", ".join(match.tags),
        "Tests": match.test_count,
    }
    for match in matches
]
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
