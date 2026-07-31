"""Streamlit application for local dbt model exploration."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from dbt_feature_lineage.loaders.project_loader import load_dbt_project
from dbt_feature_lineage.services.model_analysis_service import inspect_model
from dbt_feature_lineage.ui import (
    build_model_flow_lines,
    filter_models,
    filter_output_columns,
    group_models_by_layer,
    summarize_model_analysis,
)

DEFAULT_PROJECT_PATH = "examples/sample_banking_dbt"
LAYER_ORDER = ["staging", "intermediate", "marts", "unknown"]


@st.cache_data(show_spinner=False)
def cached_load_project(project_path: str):
    return load_dbt_project(project_path)


@st.cache_data(show_spinner=False)
def cached_inspect_model(project_path: str, model_name: str):
    return inspect_model(project_path, model_name)


def main() -> None:
    st.set_page_config(page_title="dbt Feature Lineage", layout="wide")
    st.title("dbt Feature Lineage")
    st.caption("Local dbt project discovery and model inspection")

    project_path = st.text_input("dbt project path", value=DEFAULT_PROJECT_PATH)
    resolved_path = Path(project_path).expanduser()

    if not resolved_path.exists():
        st.error(f"Project path does not exist: {resolved_path}")
        return

    try:
        project = cached_load_project(str(resolved_path))
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        st.error(str(exc))
        return

    st.success(f"Loaded project: {project.name}")

    with st.sidebar:
        st.header("Models")
        search_term = st.text_input("Search models", value="")
        available_layers = [
            layer
            for layer in LAYER_ORDER
            if any(model.layer == layer for model in project.models)
        ]
        selected_layers = st.multiselect(
            "Filter layers",
            options=available_layers,
            default=available_layers,
        )

        filtered_models = filter_models(project.models, search_term)
        if selected_layers:
            filtered_models = [model for model in filtered_models if model.layer in selected_layers]

        grouped_models = group_models_by_layer(filtered_models)
        model_options: list[tuple[str, str]] = []
        for layer in LAYER_ORDER:
            for model in grouped_models.get(layer, []):
                model_options.append((f"{layer} / {model.name}", model.name))

        if not model_options:
            st.warning("No models match the current filters.")
            return

        selected_label = st.radio(
            "Select a model",
            options=[label for label, _ in model_options],
            index=0,
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


def _truncate_expression(expression: str, max_length: int = 120) -> str:
    if len(expression) <= max_length:
        return expression
    return expression[: max_length - 3] + "..."


if __name__ == "__main__":
    main()
