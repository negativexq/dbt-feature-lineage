"""High-level dbt project loading."""

from __future__ import annotations

from pathlib import Path

from dbt_feature_lineage.domain.models import DbtProject
from dbt_feature_lineage.parsers.yaml_parser import parse_project_metadata, parse_source_definitions
from dbt_feature_lineage.scanners.model_scanner import discover_models, discover_yaml_files


def load_dbt_project(project_path: str | Path) -> DbtProject:
    """Load a local dbt project from disk."""

    resolved_path = Path(project_path).expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Project path does not exist: {resolved_path}")
    if not resolved_path.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {resolved_path}")

    dbt_project_file = resolved_path / "dbt_project.yml"
    if not dbt_project_file.exists():
        raise FileNotFoundError(f"Missing dbt_project.yml in: {resolved_path}")

    project_metadata = parse_project_metadata(dbt_project_file)
    model_paths = project_metadata.get("model-paths", ["models"])

    models = discover_models(resolved_path, model_paths)
    yaml_files = discover_yaml_files(resolved_path, model_paths)
    sources = parse_source_definitions(yaml_files)

    return DbtProject(
        name=project_metadata.get("name", resolved_path.name),
        project_path=str(resolved_path),
        dbt_project_file=str(dbt_project_file),
        model_paths=model_paths,
        yaml_files=[str(path.relative_to(resolved_path)) for path in yaml_files],
        models=models,
        sources=sources,
        metadata=project_metadata,
    )

