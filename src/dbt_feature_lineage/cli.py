"""CLI for dbt_feature_lineage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from dbt_feature_lineage.domain.models import DbtProject
from dbt_feature_lineage.loaders.project_loader import load_dbt_project

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


def main() -> None:
    """CLI entrypoint."""

    app()


if __name__ == "__main__":
    main()
