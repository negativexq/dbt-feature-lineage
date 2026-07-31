"""CLI for dbt_feature_lineage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dbt_feature_lineage.domain.models import DbtModelAnalysis, DbtProject
from dbt_feature_lineage.loaders.project_loader import load_dbt_project
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

    if models_only:
        return {
            "project": project.name,
            "models": [model.model_dump(mode="json") for model in project.models],
        }
    if sources_only:
        return {
            "project": project.name,
            "sources": [
                source.model_dump(mode="json", by_alias=True) for source in project.sources
            ],
        }
    return project.model_dump(mode="json", by_alias=True)


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
) -> None:
    """Analyze a local dbt project."""

    resolved_path = Path(project_path).expanduser().resolve()
    project = load_dbt_project(resolved_path)

    if json_output:
        payload = _build_output_payload(project, models_only=models_only, sources_only=sources_only)
        typer.echo(json.dumps(payload, indent=2))
        return

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
