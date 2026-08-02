"""Loading dbt projects from compiled manifest.json artifacts."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from dbt_feature_lineage.domain.models import (
    DbtDependency,
    DbtModel,
    DbtProject,
    DbtSource,
    DbtSourceTable,
)
from dbt_feature_lineage.scanners.model_scanner import detect_model_layer

SUPPORTED_MANIFEST_SCHEMA_VERSIONS = frozenset({"v11", "v12"})

_SCHEMA_VERSION_PATTERN = re.compile(r"manifest/(v\d+)\.json")


class ManifestNotFoundError(FileNotFoundError):
    """Raised when target/manifest.json is missing."""


class ManifestParseError(ValueError):
    """Raised when manifest.json cannot be parsed as JSON."""


class UnsupportedManifestSchemaVersionError(ValueError):
    """Raised when the manifest's dbt_schema_version is outside the supported range."""


def load_dbt_project_from_manifest(
    project_path: str | Path,
    target_dir: str = "target",
) -> DbtProject:
    """Load a dbt project from a compiled manifest.json (and optional catalog.json)."""

    resolved_path = Path(project_path).expanduser().resolve()
    manifest_file = resolved_path / target_dir / "manifest.json"
    if not manifest_file.exists():
        raise ManifestNotFoundError(f"Manifest not found: {manifest_file}")

    try:
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestParseError(f"Failed to parse manifest JSON: {manifest_file}") from exc

    metadata = manifest_data.get("metadata", {})
    _validate_schema_version(metadata.get("dbt_schema_version", ""))

    models = _parse_models(manifest_data.get("nodes", {}), resolved_path)
    sources = _parse_sources(manifest_data.get("sources", {}))
    model_paths = _infer_model_paths(manifest_data.get("nodes", {}))

    return DbtProject(
        name=metadata.get("project_name", resolved_path.name),
        project_path=str(resolved_path),
        dbt_project_file=str(resolved_path / "dbt_project.yml"),
        model_paths=model_paths,
        models=models,
        sources=sources,
        metadata=metadata,
        source="manifest",
    )


def _validate_schema_version(dbt_schema_version: str) -> None:
    match = _SCHEMA_VERSION_PATTERN.search(dbt_schema_version)
    if not match or match.group(1) not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        raise UnsupportedManifestSchemaVersionError(
            f"Unsupported manifest schema version: {dbt_schema_version!r}. "
            f"Supported versions: {sorted(SUPPORTED_MANIFEST_SCHEMA_VERSIONS)}"
        )


def _parse_models(nodes: dict[str, Any], project_root: Path) -> list[DbtModel]:
    test_counts = _count_tests_by_model(nodes)

    models: list[DbtModel] = []
    for node in nodes.values():
        if node.get("resource_type") != "model":
            continue

        relative_path = node["original_file_path"]
        ref_dependencies, source_dependencies = _parse_dependencies(node)

        models.append(
            DbtModel(
                name=node["name"],
                file_path=str(project_root / relative_path),
                relative_path=relative_path,
                layer=detect_model_layer(relative_path),
                raw_sql=node.get("compiled_code") or node.get("raw_code") or "",
                ref_dependencies=ref_dependencies,
                source_dependencies=source_dependencies,
                unique_id=node.get("unique_id"),
                materialization=node.get("config", {}).get("materialized"),
                compiled=bool(node.get("compiled", False)),
                database=node.get("database"),
                schema_name=node.get("schema"),
                alias=node.get("alias"),
                description=node.get("description") or None,
                tags=node.get("tags") or [],
                owner=(node.get("meta") or {}).get("owner"),
                test_count=test_counts.get(node["name"], 0),
            )
        )
    return sorted(models, key=lambda model: model.name)


def _count_tests_by_model(nodes: dict[str, Any]) -> dict[str, int]:
    """Map model name -> number of dbt tests that depend on it.

    Unlike description/tags/meta (attributes of the model's own node),
    tests are separate top-level nodes (resource_type == "test") that
    reference their subject via depends_on.nodes -- there is no "tests"
    list directly on a model node to read.
    """

    counts: dict[str, int] = defaultdict(int)
    for node in nodes.values():
        if node.get("resource_type") != "test":
            continue
        for dependency_unique_id in node.get("depends_on", {}).get("nodes", []):
            parts = dependency_unique_id.split(".")
            if parts[0] == "model":
                counts[parts[-1]] += 1
    return counts


def _parse_dependencies(node: dict[str, Any]) -> tuple[list[DbtDependency], list[DbtDependency]]:
    ref_dependencies: list[DbtDependency] = []
    source_dependencies: list[DbtDependency] = []

    for dependency_unique_id in node.get("depends_on", {}).get("nodes", []):
        parts = dependency_unique_id.split(".")
        resource_type = parts[0]

        if resource_type == "model":
            ref_dependencies.append(DbtDependency(dependency_type="ref", target_name=parts[-1]))
        elif resource_type == "source":
            source_dependencies.append(
                DbtDependency(
                    dependency_type="source",
                    source_name=parts[-2],
                    target_name=parts[-1],
                )
            )

    return ref_dependencies, source_dependencies


def _parse_sources(source_nodes: dict[str, Any]) -> list[DbtSource]:
    tables_by_source: dict[str, list[DbtSourceTable]] = {}
    source_meta: dict[str, dict[str, Any]] = {}

    for node in source_nodes.values():
        source_name = node["source_name"]
        tables_by_source.setdefault(source_name, []).append(
            DbtSourceTable(
                name=node["name"],
                identifier=node.get("identifier"),
                description=node.get("description"),
                columns=sorted(node.get("columns", {}).keys()),
            )
        )
        source_meta.setdefault(
            source_name,
            {
                "database": node.get("database"),
                "schema": node.get("schema"),
                "description": node.get("source_description"),
            },
        )

    return [
        DbtSource(
            name=source_name,
            database=source_meta[source_name]["database"],
            schema=source_meta[source_name]["schema"],
            description=source_meta[source_name]["description"],
            tables=sorted(tables, key=lambda table: table.name),
        )
        for source_name, tables in sorted(tables_by_source.items())
    ]


def _infer_model_paths(nodes: dict[str, Any]) -> list[str]:
    bases: set[str] = set()
    for node in nodes.values():
        if node.get("resource_type") != "model":
            continue
        original_file_path = node["original_file_path"]
        path = node.get("path", "")
        if path and original_file_path.endswith(path):
            base = original_file_path[: -len(path)].rstrip("/")
            if base:
                bases.add(base)

    return sorted(bases) if bases else ["models"]
