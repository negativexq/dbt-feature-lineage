"""Streamlit application entry point -- multi-page navigation.

Model Explorer (single-model deep dive) and Column Lineage (project-wide
search) are separate pages so that Column Lineage's expensive
build_project_lineage() call only runs when a user actually visits that
page. See pages/column_lineage.py's module docstring for why this split
replaced the earlier single-page, st.tabs()-based layout.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="dbt Feature Lineage", layout="wide")

pages = st.navigation(
    [
        st.Page("pages/model_explorer.py", title="Model Explorer", default=True),
        st.Page("pages/column_lineage.py", title="Column Lineage"),
    ]
)
pages.run()
