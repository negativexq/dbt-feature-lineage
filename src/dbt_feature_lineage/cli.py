"""CLI for dbt_feature_lineage."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from dbt_feature_lineage.domain.models import ArtifactStatus, DbtModelAnalysis, DbtProject
from dbt_feature_lineage.loaders.artifact_detector import resolve_dbt_project
from dbt_feature_lineage.services.model_analysis_service import inspect_model

app = typer.Typer(no_args_is_help=True)
console = Console()


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


def main() -> None:
    """CLI entrypoint."""

    app()


if __name__ == "__main__":
    main()
