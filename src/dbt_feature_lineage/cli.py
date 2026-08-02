"""CLI for dbt_feature_lineage."""

from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any

import networkx as nx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from dbt_feature_lineage.domain.lineage import ColumnNode
from dbt_feature_lineage.domain.models import ArtifactStatus, DbtModelAnalysis, DbtProject
from dbt_feature_lineage.loaders.artifact_detector import resolve_dbt_project
from dbt_feature_lineage.services.column_search import (
    DownstreamImpactSummary,
    build_search_index,
    get_downstream_chain,
    get_upstream_chain,
    summarize_downstream_impact,
)
from dbt_feature_lineage.services.lineage_service import build_project_lineage
from dbt_feature_lineage.services.model_analysis_service import inspect_model

app = typer.Typer(no_args_is_help=True)
console = Console()


class LineageDirection(str, Enum):
    """Which way to walk the lineage graph from the resolved target column."""

    upstream = "upstream"
    downstream = "downstream"


@app.callback()
def main_callback() -> None:
    """dbt_feature_lineage CLI."""


def _build_output_payload(
    project: DbtProject,
    models_only: bool,
    sources_only: bool,
) -> dict[str, Any]:
    if models_only and sources_only:
        raise typer.BadParameter("Use only one of --models-only or --sources-only.")

    artifact_status = (
        project.artifact_status.model_dump(mode="json") if project.artifact_status else None
    )

    if models_only:
        return {
            "project": project.name,
            "artifact_status": artifact_status,
            "models": [model.model_dump(mode="json") for model in project.models],
        }
    if sources_only:
        return {
            "project": project.name,
            "artifact_status": artifact_status,
            "sources": [
                source.model_dump(mode="json", by_alias=True) for source in project.sources
            ],
        }
    return project.model_dump(mode="json", by_alias=True)


def _is_interactive() -> bool:
    """Whether stdin is an interactive terminal (isolated for testability)."""

    return sys.stdin.isatty()


def _resolve_generate_artifacts(project_path: Path, generate_artifacts: bool | None) -> bool:
    """Decide whether `dbt parse` should be attempted.

    An explicit --generate-artifacts/--no-generate-artifacts flag always wins.
    Otherwise: if a manifest already exists there's nothing to decide, and in
    non-interactive contexts (CI, pipes) we never prompt -- we just fall back
    to the static parser silently-from-the-user's-perspective-but-not-really,
    since resolve_dbt_project still reports the fallback via ArtifactStatus.
    """

    if generate_artifacts is not None:
        return generate_artifacts

    manifest_file = project_path / "target" / "manifest.json"
    if manifest_file.exists() or not _is_interactive():
        return False

    return Confirm.ask(
        "target/manifest.json not found. Generate dbt artifacts via `dbt parse`?",
        default=False,
    )


def _render_artifact_status(status: ArtifactStatus | None) -> None:
    if status is None:
        return

    style = "green" if status.mode == "manifest" else "yellow"
    console.print(f"[{style}]artifact source: {status.mode} (reason: {status.reason})[/{style}]")
    if status.message:
        console.print(f"[{style}]{status.message}[/{style}]")
    console.print()


def _render_summary(project: DbtProject, models_only: bool, sources_only: bool) -> None:
    if models_only and sources_only:
        raise typer.BadParameter("Use only one of --models-only or --sources-only.")

    source_count = sum(len(source.tables) for source in project.sources)

    if not sources_only:
        console.print(f"Project: {project.name}")
        console.print(f"Models: {len(project.models)}")
        if not models_only:
            console.print(f"Sources: {source_count}")
            console.print(f"YAML files: {len(project.yaml_files)}")
        console.print()
        console.print("Models:")
        for model in project.models:
            console.print(f"- {model.name}")

    if not models_only:
        console.print()
        console.print("Sources:")
        for source in project.sources:
            for table in source.tables:
                console.print(f"- {source.name}.{table.name}")

        console.print()
        table = Table(title="Project metadata")
        table.add_column("Key")
        table.add_column("Value")
        table.add_row("Project path", project.project_path)
        table.add_row("dbt_project.yml", project.dbt_project_file)
        table.add_row("Model paths", ", ".join(project.model_paths))
        console.print(table)


def _render_model_inspection(analysis: DbtModelAnalysis) -> None:
    console.print(f"Model: {analysis.model_name}")
    console.print(f"File path: {analysis.file_path}")
    console.print(f"Layer: {analysis.layer}")
    console.print(f"ref dependencies: {[dep.target_name for dep in analysis.ref_dependencies]}")
    console.print(
        "source dependencies: "
        f"{[f'{dep.source_name}.{dep.target_name}' for dep in analysis.source_dependencies]}"
    )
    console.print(f"CTEs: {analysis.cte_names}")
    console.print(f"Table aliases: {analysis.table_aliases}")
    console.print(f"Join count: {analysis.join_count}")
    console.print(f"Join types: {analysis.join_types}")
    console.print(f"WHERE clause present: {analysis.has_where_clause}")
    console.print(f"GROUP BY columns: {analysis.group_by_columns}")
    console.print(f"Aggregate functions: {analysis.aggregate_functions}")
    console.print(f"Window functions: {analysis.window_functions}")

    output_table = Table(title="Output columns")
    output_table.add_column("Output")
    output_table.add_column("Type")
    output_table.add_column("Expression")
    output_table.add_column("Referenced columns")
    for output_column in analysis.output_columns:
        output_table.add_row(
            output_column.output_name,
            output_column.transformation_type,
            output_column.original_sql_expression,
            ", ".join(output_column.referenced_input_columns),
        )
    console.print(output_table)

    if analysis.parsing_warnings:
        console.print(Panel("\n".join(analysis.parsing_warnings), title="Parsing warnings"))

    console.print(Panel(analysis.raw_sql, title="Raw SQL"))


def _resolve_ambiguous_match(
    matches: list[ColumnNode], model_name: str | None, column_name: str
) -> ColumnNode:
    """Narrow a column-name search down to a single ColumnNode, or exit.

    An explicit --model always wins. Otherwise: a single match needs no
    disambiguation; multiple matches are resolved interactively only when
    the terminal is interactive (matching _resolve_generate_artifacts'
    non-interactive-never-prompts rule) -- non-interactive callers (CI,
    scripts) get the candidate list on stdout and a non-zero exit instead
    of hanging on a prompt.
    """

    if model_name is not None:
        matches = [match for match in matches if match.model == model_name]

    if not matches:
        target_description = f"'{column_name}'" + (
            f" in model '{model_name}'" if model_name else ""
        )
        console.print(f"[red]No matches for column {target_description}.[/red]")
        raise typer.Exit(code=1)

    if len(matches) == 1:
        return matches[0]

    if _is_interactive():
        selected_model = Prompt.ask(
            f"Multiple models produce a column named '{column_name}'. Which model?",
            choices=[match.model for match in matches],
        )
        return next(match for match in matches if match.model == selected_model)

    console.print(
        f"[yellow]Column '{column_name}' is ambiguous across {len(matches)} models:[/yellow]"
    )
    for match in matches:
        console.print(f"  - {match.model} ({match.layer})")
    console.print("Pass --model to disambiguate.")
    raise typer.Exit(code=1)


def _render_lineage_warnings(warnings: list[str]) -> None:
    if not warnings:
        return

    console.print(
        Panel(
            "\n".join(warnings),
            title=f"{len(warnings)} model(s) excluded from lineage",
        )
    )


def _render_lineage_chain(
    target: ColumnNode,
    chain: list[ColumnNode],
    subgraph: nx.DiGraph,
    direction: LineageDirection,
) -> None:
    console.print(f"Column: {target.column}")
    console.print(f"Model: {target.model} (layer: {target.layer})")
    console.print()

    if len(chain) == 1:
        if direction is LineageDirection.upstream:
            console.print(
                "[yellow]No upstream lineage found "
                "(this is a raw source or has no traceable inputs).[/yellow]"
            )
        else:
            console.print(
                "[yellow]No downstream lineage found "
                "(nothing in this project consumes this column).[/yellow]"
            )
        return

    # Edge list, not a single "a -> b -> c" arrow chain: a column fed by
    # more than one upstream input (e.g. coalesce()/joins), or feeding more
    # than one downstream output, has a genuinely branching DAG, not one
    # linear path (docs/v0.4-plan.md Bölüm 3). Printed as plain lines rather
    # than a Table: model.column identifiers (schema-qualified in manifest
    # mode) are long enough that a column-width-constrained Table truncates
    # them with "…" on anything but a wide terminal.
    console.print(f"{direction.value.capitalize()} lineage:")
    for source, edge_target, data in subgraph.edges(data=True):
        console.print(
            f"  {source.model}.{source.column} -> {edge_target.model}.{edge_target.column} "
            f"[{data['transformation_type']}]"
        )
        console.print(f"    {data['expression_sql']}")


def _build_lineage_payload(
    target: ColumnNode,
    chain: list[ColumnNode],
    subgraph: nx.DiGraph,
    lineage_warnings: list[str],
    direction: LineageDirection,
) -> dict[str, Any]:
    return {
        "column": target.column,
        "model": target.model,
        "layer": target.layer,
        "direction": direction.value,
        "chain": [node.model_dump(mode="json") for node in chain],
        "edges": [
            {
                "source": source.model_dump(mode="json"),
                "target": edge_target.model_dump(mode="json"),
                "transformation_type": data["transformation_type"],
                "expression_sql": data["expression_sql"],
            }
            for source, edge_target, data in subgraph.edges(data=True)
        ],
        "lineage_warnings": lineage_warnings,
    }


def _impact_summary_payload(summary: DownstreamImpactSummary) -> dict[str, Any]:
    return {
        "affected_model_count": summary.affected_model_count,
        "affected_column_count": summary.affected_column_count,
        "direct": [{"model": impact.model, "columns": impact.columns} for impact in summary.direct],
        "all_impacted": [
            {"model": impact.model, "columns": impact.columns} for impact in summary.all_impacted
        ],
    }


def _render_downstream_impact_summary(summary: DownstreamImpactSummary) -> None:
    # Printed below _render_lineage_chain()'s own output, never instead
    # of it (docs/v0.8-plan.md Bölüm 3/6) -- --impact only ADDS a section.
    console.print()
    console.print("Downstream impact:")

    if summary.affected_model_count == 0:
        console.print("  No downstream impact (nothing in this project consumes this column).")
        return

    console.print(
        f"  {summary.affected_model_count} model(s), "
        f"{summary.affected_column_count} column(s) affected."
    )

    console.print()
    console.print("  Directly affected:")
    for impact in summary.direct:
        console.print(f"    {impact.model}: {', '.join(impact.columns)}")

    console.print()
    console.print("  All affected (direct + transitive):")
    for impact in summary.all_impacted:
        console.print(f"    {impact.model}: {', '.join(impact.columns)}")


@app.command()
def analyze(
    project_path: str = typer.Argument(..., help="Path to a local dbt project."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    models_only: bool = typer.Option(False, "--models-only", help="Show models only."),
    sources_only: bool = typer.Option(False, "--sources-only", help="Show sources only."),
    generate_artifacts: bool | None = typer.Option(
        None,
        "--generate-artifacts/--no-generate-artifacts",
        help=(
            "Run `dbt parse` to generate target/manifest.json when it's missing. "
            "If left unset and the terminal is interactive, you'll be asked."
        ),
    ),
) -> None:
    """Analyze a local dbt project."""

    resolved_path = Path(project_path).expanduser().resolve()
    should_generate = _resolve_generate_artifacts(resolved_path, generate_artifacts)
    project = resolve_dbt_project(resolved_path, generate_artifacts=should_generate)

    if json_output:
        payload = _build_output_payload(project, models_only=models_only, sources_only=sources_only)
        typer.echo(json.dumps(payload, indent=2))
        return

    _render_artifact_status(project.artifact_status)
    _render_summary(project, models_only=models_only, sources_only=sources_only)


@app.command()
def inspect(
    project_path: str = typer.Argument(..., help="Path to a local dbt project."),
    model_name: str = typer.Argument(..., help="dbt model name to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Inspect a single dbt model."""

    resolved_path = Path(project_path).expanduser().resolve()
    analysis = inspect_model(resolved_path, model_name)

    if json_output:
        typer.echo(json.dumps(analysis.model_dump(mode="json"), indent=2))
        return

    _render_model_inspection(analysis)


@app.command()
def lineage(
    project_path: str = typer.Argument(..., help="Path to a local dbt project."),
    column_name: str = typer.Argument(..., help="Column name to trace."),
    model_name: str | None = typer.Option(
        None, "--model", help="Disambiguate when multiple models produce this column."
    ),
    direction: LineageDirection = typer.Option(
        LineageDirection.upstream,
        "--direction",
        help="Trace upstream to raw sources, or downstream to consumers.",
    ),
    impact: bool = typer.Option(
        False,
        "--impact",
        help=(
            "Add a model-grouped downstream impact summary "
            "(only valid with --direction downstream)."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Trace a column's lineage to its raw source(s) or downstream consumers."""

    if impact and direction is not LineageDirection.downstream:
        console.print(
            "[red]--impact is only valid with --direction downstream "
            "(a column's own upstream sources aren't an \"impact\").[/red]"
        )
        raise typer.Exit(code=1)

    resolved_path = Path(project_path).expanduser().resolve()
    project = resolve_dbt_project(resolved_path, generate_artifacts=False)
    graph = build_project_lineage(project)
    lineage_warnings: list[str] = graph.graph.get("lineage_warnings", [])

    matches = build_search_index(graph).get(column_name, [])
    target = _resolve_ambiguous_match(matches, model_name, column_name)
    get_chain = (
        get_upstream_chain if direction is LineageDirection.upstream else get_downstream_chain
    )
    chain = get_chain(graph, target)
    subgraph = graph.subgraph(chain)

    if json_output:
        payload = _build_lineage_payload(target, chain, subgraph, lineage_warnings, direction)
        if impact:
            payload["impact_summary"] = _impact_summary_payload(
                summarize_downstream_impact(graph, target, chain)
            )
        typer.echo(json.dumps(payload, indent=2))
        return

    _render_lineage_warnings(lineage_warnings)
    _render_lineage_chain(target, chain, subgraph, direction)
    if impact:
        _render_downstream_impact_summary(summarize_downstream_impact(graph, target, chain))


def main() -> None:
    """CLI entrypoint."""

    app()


if __name__ == "__main__":
    main()
