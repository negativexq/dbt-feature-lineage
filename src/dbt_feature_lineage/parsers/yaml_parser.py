"""YAML parsing helpers for dbt projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from dbt_feature_lineage.domain.models import DbtSource, DbtSourceTable


def parse_yaml_file(yaml_path: Path) -> dict[str, Any]:
    """Read a YAML file into a dictionary."""

    content = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise ValueError(f"YAML file must contain a mapping: {yaml_path}")
    return content


def parse_project_metadata(dbt_project_file: Path) -> dict[str, Any]:
    """Parse dbt_project.yml metadata."""

    return parse_yaml_file(dbt_project_file)


def parse_source_definitions(yaml_files: list[Path]) -> list[DbtSource]:
    """Parse dbt source definitions from YAML files."""

    sources: list[DbtSource] = []
    for yaml_file in yaml_files:
        parsed = parse_yaml_file(yaml_file)
        for source_entry in parsed.get("sources", []):
            tables = [
                DbtSourceTable(
                    name=table_entry["name"],
                    identifier=table_entry.get("identifier"),
                    description=table_entry.get("description"),
                    columns=[column.get("name", "") for column in table_entry.get("columns", [])],
                )
                for table_entry in source_entry.get("tables", [])
            ]
            sources.append(
                DbtSource(
                    name=source_entry["name"],
                    database=source_entry.get("database"),
                    schema=source_entry.get("schema"),
                    description=source_entry.get("description"),
                    tables=tables,
                )
            )
    return sources

