"""Presentation helpers for the local web interface."""

from __future__ import annotations

from collections import defaultdict

from dbt_feature_lineage.domain.models import (
    ArtifactStatus,
    DbtModel,
    DbtModelAnalysis,
    DbtOutputColumn,
    DbtProject,
)

_ARTIFACT_STATUS_MESSAGES: dict[str, str] = {
    "found": "Using compiled artifacts from target/manifest.json.",
    "generated": "Generated target/manifest.json via `dbt parse` and now using it.",
    "not_generated": "target/manifest.json not found — using the static SQL parser.",
    "dbt_cli_unavailable": "`dbt` CLI not found on PATH — using the static SQL parser.",
    "no_profile": "No profiles.yml found for this project — using the static SQL parser.",
    "dbt_parse_failed": "`dbt parse` failed — using the static SQL parser.",
    "unsupported_manifest_schema_version": (
        "manifest.json schema version is not supported — using the static SQL parser."
    ),
    "manifest_parse_failed": (
        "target/manifest.json could not be parsed — using the static SQL parser."
    ),
}


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


def detect_model_groups(models: list[DbtModel]) -> list[str]:
    """Sorted distinct model_group values across models, None excluded.

    Callers use this to decide whether a "Model Group" filter widget is
    worth showing at all -- a project with zero or one distinct group
    (examples/sample_banking_dbt's flat layout, or any project that
    hasn't adopted a domain-per-folder convention) has nothing to filter
    by, so the widget should stay hidden rather than offer a single
    always-selected, do-nothing option.
    """

    return sorted({model.model_group for model in models if model.model_group is not None})


def filter_models_by_group(models: list[DbtModel], selected_groups: list[str]) -> list[DbtModel]:
    """Filter models by model_group membership.

    Empty `selected_groups` means no filtering (show everything) -- same
    "empty selection defensively shows all, not nothing" contract
    pages/model_explorer.py's existing layer-filter multiselect already
    relies on. A model whose model_group is None (flat layout, or a
    project mixing grouped and ungrouped models) is excluded once a real
    filter is active, since it doesn't belong to any selected group.
    """

    if not selected_groups:
        return models
    return [model for model in models if model.model_group in selected_groups]


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


def describe_artifact_status(status: ArtifactStatus) -> tuple[str, str]:
    """Build a (level, message) pair for surfacing an ArtifactStatus in the UI.

    level is one of "success", "info", "warning" -- matching
    st.success/st.info/st.warning (or a CLI color) respectively.

    The rendered text is `_ARTIFACT_STATUS_MESSAGES[reason]`, with
    `status.message` appended only when present. By contract (see
    artifact_detector), `status.message` must be supplementary detail the
    fixed headline doesn't already cover (e.g. dbt's stderr, the offending
    schema version) -- never a restatement of the headline itself, or the
    two end up saying the same thing twice.
    """

    if status.mode == "manifest":
        level = "success"
    elif status.reason == "not_generated":
        level = "info"
    else:
        level = "warning"

    message = _ARTIFACT_STATUS_MESSAGES.get(
        status.reason, f"{status.mode} mode ({status.reason})."
    )
    if status.message:
        message = f"{message} {status.message}"
    return level, message


def render_node_detail_panel(project: DbtProject, model_name: str) -> dict[str, str]:
    """Build the Model DAG right-hand detail panel's content for one model.

    A plain function returning label -> value, not a Streamlit render call,
    so it can be unit tested independently of streamlit_flow -- AppTest
    can't simulate a node click (no real JS runtime executes, so a custom
    component's return value never changes -- see docs/v0.5-plan.md
    Bölüm 8, verified via a sandbox spike), so this is the only way the
    "click a node -> panel updates" logic gets tested at all. The caller
    (pages/model_dag.py) is responsible for turning this dict into
    `st.write`/`st.markdown` calls.

    Fields with nothing to show (owner/description/tags unset, static
    mode, or a dbt project that simply never documented this model) are
    left out of the returned dict entirely -- not a scope/coverage
    problem worth a schema_warnings-style warning, just this model having
    less metadata than another one.
    """

    model = next((m for m in project.models if m.name == model_name), None)
    if model is None:
        return {}

    panel: dict[str, str] = {"Model": model.name, "Layer": model.layer}
    if model.materialization:
        panel["Materialization"] = model.materialization
    if model.description:
        panel["Description"] = model.description
    if model.tags:
        panel["Tags"] = ", ".join(model.tags)
    if model.owner:
        panel["Owner"] = model.owner
    if model.test_count:
        panel["Tests"] = str(model.test_count)

    return panel


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
