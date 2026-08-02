"""Model Explorer page: single-model deep dive (Overview/Query Flow/Columns/Raw SQL)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from dbt_feature_lineage.ui import (
    build_model_flow_lines,
    describe_artifact_status,
    filter_models,
    filter_models_by_group,
    filter_output_columns,
    group_models_by_layer,
    summarize_model_analysis,
)
from dbt_feature_lineage.ui.state import (
    cached_inspect_model,
    cached_load_project,
    generate_artifacts_and_reload,
    manifest_mtime,
)

LAYER_ORDER = ["staging", "intermediate", "marts", "unknown"]


def _truncate_expression(expression: str, max_length: int = 120) -> str:
    if len(expression) <= max_length:
        return expression
    return expression[: max_length - 3] + "..."


st.title("dbt Feature Lineage")
st.caption("Local dbt project discovery and model inspection")

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

if project.artifact_status is not None and project.artifact_status.mode == "static":
    if st.button("Generate artifacts (dbt parse)"):
        with st.spinner("Running `dbt parse`..."):
            project = generate_artifacts_and_reload(str(resolved_path))
        cached_load_project.clear()
        if project.artifact_status is not None and project.artifact_status.mode == "manifest":
            # Rerun so the button (drawn above, before we knew the
            # outcome) disappears now that a manifest is in use.
            st.rerun()

if project.artifact_status is not None:
    level, message = describe_artifact_status(project.artifact_status)
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.info(message)

st.success(f"Loaded project: {project.name}")

with st.sidebar:
    st.header("Models")
    search_term = st.text_input("Search models", value="")

    # Group filtering happens once, up front, on Select Project -- this
    # page only ever sees the already-narrowed model list. (Distinct from
    # v0.5, where each of the three pages had its own live group
    # multiselect; see docs/... shared-state redesign notes.)
    project_models = filter_models_by_group(
        project.models, [selected_group] if selected_group else []
    )

    available_layers = [
        layer for layer in LAYER_ORDER if any(model.layer == layer for model in project_models)
    ]
    selected_layers = st.multiselect(
        "Filter layers",
        options=available_layers,
        default=available_layers,
    )

    filtered_models = filter_models(project_models, search_term)
    if selected_layers:
        filtered_models = [model for model in filtered_models if model.layer in selected_layers]

    grouped_models = group_models_by_layer(filtered_models)
    model_options: list[tuple[str, str]] = []
    for layer in LAYER_ORDER:
        for model in grouped_models.get(layer, []):
            model_options.append((f"{layer} / {model.name}", model.name))

    if not model_options:
        st.warning("No models match the current filters.")
        st.stop()

    selected_label = st.radio(
        "Select a model",
        options=[label for label, _ in model_options],
        index=0,
        key="model_explorer_model_picker",
    )
    selected_model_name = dict(model_options)[selected_label]

analysis = cached_inspect_model(str(resolved_path), selected_model_name)
metrics = summarize_model_analysis(analysis)

overview_tab, flow_tab, columns_tab, raw_sql_tab = st.tabs(
    ["Overview", "Query Flow", "Columns", "Raw SQL"]
)

with overview_tab:
    left_col, right_col = st.columns(2)
    with left_col:
        st.subheader(analysis.model_name)
        st.write(f"**File path:** `{analysis.file_path}`")
        st.write(f"**Layer:** `{analysis.layer}`")
        st.write(
            "**Upstream ref models:** "
            + (", ".join(dep.target_name for dep in analysis.ref_dependencies) or "None")
        )
        st.write(
            "**Source dependencies:** "
            + (
                ", ".join(
                    f"{dep.source_name}.{dep.target_name}"
                    for dep in analysis.source_dependencies
                )
                or "None"
            )
        )
    with right_col:
        st.metric("CTEs", metrics["cte_count"])
        st.metric("Joins", metrics["join_count"])
        st.metric("Output columns", metrics["output_column_count"])
        st.metric("Source dependencies", metrics["source_dependency_count"])

    if analysis.parsing_warnings:
        st.warning("\n".join(analysis.parsing_warnings))

with flow_tab:
    st.subheader("Logical query flow")
    st.code("\n".join(build_model_flow_lines(analysis)), language="text")

    st.subheader("CTE details")
    for cte_name in analysis.cte_names:
        with st.expander(cte_name):
            st.write(f"CTE name: `{cte_name}`")
            aliases = {
                alias: relation
                for alias, relation in analysis.table_aliases.items()
                if relation == cte_name or alias == cte_name
            }
            if aliases:
                st.write(f"Known aliases: {aliases}")

    if analysis.join_types:
        st.subheader("Join summary")
        st.write(", ".join(analysis.join_types))

with columns_tab:
    st.subheader("Output columns")
    available_types = sorted({column.transformation_type for column in analysis.output_columns})
    column_search = st.text_input("Search output columns", value="")
    selected_types = st.multiselect(
        "Filter transformation types",
        options=available_types,
        default=available_types,
    )
    filtered_columns = filter_output_columns(
        analysis.output_columns,
        column_search,
        selected_types,
    )

    rows = [
        {
            "Output column": column.output_name,
            "Expression": _truncate_expression(column.original_sql_expression),
            "Transformation type": column.transformation_type,
            "Referenced input columns": ", ".join(column.referenced_input_columns),
        }
        for column in filtered_columns
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    column_names = [column.output_name for column in filtered_columns]
    if column_names:
        selected_column_name = st.selectbox("Select a column", options=column_names)
        selected_column = next(
            column for column in filtered_columns if column.output_name == selected_column_name
        )
        st.markdown(f"**Output column:** `{selected_column.output_name}`")
        st.markdown(f"**Transformation type:** `{selected_column.transformation_type}`")
        st.markdown("**Expression:**")
        st.code(selected_column.original_sql_expression, language="sql")
        st.markdown("**Referenced input columns:**")
        if selected_column.referenced_input_columns:
            st.write(selected_column.referenced_input_columns)
        else:
            st.write("None detected")

with raw_sql_tab:
    st.subheader("Original SQL")
    st.code(analysis.raw_sql, language="sql")
    with st.expander("Preprocessed SQL used by sqlglot"):
        from dbt_feature_lineage.parsers.sql_parser import parse_sql_with_fallback

        parsed = parse_sql_with_fallback(analysis.raw_sql)
        st.code(parsed.preprocessed_sql, language="sql")
