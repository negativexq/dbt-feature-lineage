"""Streamlit application entry point -- multi-page navigation.

Select Project (project/model-group picker, shared via session_state) is
the default/first page. Model Explorer (single-model deep dive), Model
DAG (project-wide model-level graph), and Column Lineage (project-wide
column search) all read that shared selection instead of each having its
own "dbt project path" input -- see pages/select_project.py's module
docstring for the reasoning. Each page's expensive graph-building call
still only runs when a user actually visits that page (st.navigation()
pages are lazy).
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="dbt Feature Lineage", layout="wide")

pages = st.navigation(
    [
        st.Page("pages/select_project.py", title="Select Project", default=True),
        st.Page("pages/model_explorer.py", title="Model Explorer"),
        st.Page("pages/model_dag.py", title="Model DAG"),
        st.Page("pages/column_lineage.py", title="Column Lineage"),
    ]
)
pages.run()
