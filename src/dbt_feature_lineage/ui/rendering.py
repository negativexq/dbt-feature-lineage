"""Presentation helpers for the local web interface."""

from __future__ import annotations

from collections import defaultdict

from dbt_feature_lineage.domain.models import DbtModel, DbtModelAnalysis, DbtOutputColumn


def group_models_by_layer(models: list[DbtModel]) -> dict[str, list[DbtModel]]:
    """Group models by logical layer."""

    grouped: dict[str, list[DbtModel]] = defaultdict(list)
    for model in sorted(models, key=lambda item: item.name):
        grouped[model.layer].append(model)
    return dict(grouped)


def filter_models(models: list[DbtModel], search_term: str) -> list[DbtModel]:
    """Filter models by name or relative path."""

    normalized_search = search_term.strip().lower()
    if not normalized_search:
        return models

    return [
        model
        for model in models
        if normalized_search in model.name.lower()
        or normalized_search in model.relative_path.lower()
    ]


def filter_output_columns(
    output_columns: list[DbtOutputColumn],
    search_term: str,
    transformation_types: list[str],
) -> list[DbtOutputColumn]:
    """Filter output columns by text and transformation type."""

    normalized_search = search_term.strip().lower()
    selected_types = set(transformation_types)
    filtered = output_columns

    if normalized_search:
        filtered = [
            column
            for column in filtered
            if normalized_search in column.output_name.lower()
            or normalized_search in column.original_sql_expression.lower()
            or any(normalized_search in ref.lower() for ref in column.referenced_input_columns)
        ]

    if selected_types:
        filtered = [
            column for column in filtered if column.transformation_type in selected_types
        ]

    return filtered


def summarize_model_analysis(analysis: DbtModelAnalysis) -> dict[str, int]:
    """Build compact model summary metrics for display."""

    return {
        "cte_count": len(analysis.cte_names),
        "join_count": analysis.join_count,
        "output_column_count": len(analysis.output_columns),
        "ref_dependency_count": len(analysis.ref_dependencies),
        "source_dependency_count": len(analysis.source_dependencies),
    }


def build_model_flow_lines(analysis: DbtModelAnalysis) -> list[str]:
    """Build a readable vertical query-flow summary."""

    lines: list[str] = []

    if analysis.source_dependencies:
        for dependency in analysis.source_dependencies:
            lines.append(f"source: {dependency.source_name}.{dependency.target_name}")

    if analysis.ref_dependencies:
        for dependency in analysis.ref_dependencies:
            lines.append(f"upstream model: {dependency.target_name}")

    for cte_name in analysis.cte_names:
        lines.append(f"cte: {cte_name}")

    if analysis.join_count:
        lines.append(
            "joins: "
            + ", ".join(analysis.join_types)
        )

    if analysis.has_where_clause:
        lines.append("filters: where clause present")

    if analysis.group_by_columns:
        lines.append(f"aggregations: group by {', '.join(analysis.group_by_columns)}")

    if analysis.window_functions:
        lines.append("window functions: present")

    lines.append("final select")
    lines.append(f"output model: {analysis.model_name}")

    return lines
