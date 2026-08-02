"""Streamlit application entry point -- multi-page navigation.

Model Explorer (single-model deep dive), Model DAG (project-wide
model-level graph), and Column Lineage (project-wide column search) are
separate pages so that each page's expensive graph-building call only
runs when a user actually visits that page. See pages/column_lineage.py's
and pages/model_dag.py's module docstrings for why.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="dbt Feature Lineage", layout="wide")

pages = st.navigation(
    [
        st.Page("pages/model_explorer.py", title="Model Explorer", default=True),
        st.Page("pages/model_dag.py", title="Model DAG"),
        st.Page("pages/column_lineage.py", title="Column Lineage"),
    ]
)
pages.run()
