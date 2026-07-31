"""Filesystem scanning for dbt models and YAML files."""

from __future__ import annotations

from pathlib import Path

from dbt_feature_lineage.domain.models import DbtModel, Layer
from dbt_feature_lineage.parsers.dependency_parser import (
    parse_ref_dependencies,
    parse_source_dependencies,
)


def detect_model_layer(relative_path: str | Path) -> Layer:
    """Detect the logical layer for a model based on its path."""

    parts = Path(relative_path).parts
    if "staging" in parts:
        return "staging"
    if "intermediate" in parts:
        return "intermediate"
    if "marts" in parts:
        return "marts"
    return "unknown"


def discover_models(project_root: Path, model_paths: list[str]) -> list[DbtModel]:
    """Find SQL models under the configured model paths."""

    models: list[DbtModel] = []
    for model_path in model_paths:
        base_path = project_root / model_path
        if not base_path.exists():
            continue
        for sql_path in sorted(base_path.rglob("*.sql")):
            raw_sql = sql_path.read_text(encoding="utf-8")
            relative_path = sql_path.relative_to(project_root)
            models.append(
                DbtModel(
                    name=sql_path.stem,
                    file_path=str(sql_path),
                    relative_path=str(relative_path),
                    layer=detect_model_layer(relative_path),
                    raw_sql=raw_sql,
                    ref_dependencies=parse_ref_dependencies(raw_sql),
                    source_dependencies=parse_source_dependencies(raw_sql),
                )
            )
    return models


def discover_yaml_files(project_root: Path, model_paths: list[str]) -> list[Path]:
    """Find YAML files under the configured model paths."""

    yaml_files: list[Path] = []
    for model_path in model_paths:
        base_path = project_root / model_path
        if not base_path.exists():
            continue
        yaml_files.extend(sorted(base_path.rglob("*.yml")))
        yaml_files.extend(sorted(base_path.rglob("*.yaml")))
    deduped = sorted(set(yaml_files))
    return deduped
