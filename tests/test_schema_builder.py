"""Tests for services/schema_builder.py.

Covers manifest-mode (schema-qualified, 2-level nested) and static-mode
(flat) schema/sources construction, plus the schema_warnings paths that
flag models/sources the builder couldn't place -- per docs/v0.3-plan.md
Bölüm 3 and Risk 1, an incomplete schema must be reported explicitly,
never silently dropped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dbt_feature_lineage.domain.models import DbtModel, DbtProject, DbtSource, DbtSourceTable
from dbt_feature_lineage.loaders.manifest_loader import load_dbt_project_from_manifest
from dbt_feature_lineage.loaders.project_loader import load_dbt_project
from dbt_feature_lineage.services.schema_builder import build_project_schema

FIXTURE_MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "manifest.json"


@pytest.fixture
def manifest_data() -> dict[str, Any]:
    return json.loads(FIXTURE_MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def manifest_project(tmp_path: Path, manifest_data: dict[str, Any]) -> DbtProject:
    target_path = tmp_path / "target"
    target_path.mkdir()
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    return load_dbt_project_from_manifest(tmp_path)


@pytest.fixture
def static_project(sample_project_path: Path) -> DbtProject:
    return load_dbt_project(sample_project_path)


def _raw_sql_for(project: DbtProject, model_name: str) -> str:
    return next(model.raw_sql for model in project.models if model.name == model_name)


# ---------------------------------------------------------------------------
# Manifest mode: 2-level nesting keyed by schema -> alias/table
# ---------------------------------------------------------------------------


def test_manifest_mode_schema_is_nested_by_schema_name(manifest_project: DbtProject) -> None:
    project_schema = build_project_schema(manifest_project)

    assert set(project_schema.schema["analytics_staging"]) == {"stg_customers", "stg_accounts"}
    assert set(project_schema.schema["analytics_intermediate"]) == {"int_customer_activity"}


def test_manifest_mode_schema_columns_come_from_output_columns(
    manifest_project: DbtProject,
) -> None:
    project_schema = build_project_schema(manifest_project)

    stg_customers_columns = project_schema.schema["analytics_staging"]["stg_customers"]
    assert "customer_id" in stg_customers_columns
    assert "first_name" in stg_customers_columns
    # Column type is a placeholder -- sqlglot.lineage() only needs names.
    assert stg_customers_columns["customer_id"] == "unknown"


def test_manifest_mode_physical_to_model_resolves_schema_and_alias(
    manifest_project: DbtProject,
) -> None:
    project_schema = build_project_schema(manifest_project)

    assert (
        project_schema.physical_to_model[("analytics_staging", "stg_customers")]
        == "stg_customers"
    )
    assert (
        project_schema.physical_to_model[("analytics_intermediate", "int_customer_activity")]
        == "int_customer_activity"
    )


def test_manifest_mode_sources_dict_covers_bare_qualified_and_database_qualified_keys(
    manifest_project: DbtProject,
) -> None:
    project_schema = build_project_schema(manifest_project)
    raw_sql = _raw_sql_for(manifest_project, "stg_customers")

    assert project_schema.sources["stg_customers"] == raw_sql
    assert project_schema.sources["analytics_staging.stg_customers"] == raw_sql
    assert project_schema.sources["banking_dev.analytics_staging.stg_customers"] == raw_sql


def test_manifest_mode_dbt_sources_are_nested_under_their_schema(
    manifest_project: DbtProject,
) -> None:
    project_schema = build_project_schema(manifest_project)

    assert set(project_schema.schema["raw_banking"]) == {"customers", "accounts"}
    assert "customer_id" in project_schema.schema["raw_banking"]["customers"]


def test_manifest_mode_dbt_sources_are_terminal_in_physical_to_model(
    manifest_project: DbtProject,
) -> None:
    project_schema = build_project_schema(manifest_project)

    # A None value marks a known, resolved *source* (terminal) as opposed to
    # an unresolved/orphan leaf, which simply wouldn't be a key at all.
    assert project_schema.physical_to_model[("raw_banking", "customers")] is None
    assert project_schema.physical_to_model[("raw_banking", "accounts")] is None


def test_manifest_project_with_valid_models_has_no_schema_warnings(
    manifest_project: DbtProject,
) -> None:
    project_schema = build_project_schema(manifest_project)

    assert project_schema.schema_warnings == []


# ---------------------------------------------------------------------------
# Static mode: flat nesting keyed by bare model/source-placeholder name
# ---------------------------------------------------------------------------


def test_static_mode_schema_is_flat_by_model_name(static_project: DbtProject) -> None:
    project_schema = build_project_schema(static_project)

    assert "customer_id" in project_schema.schema["stg_customers"]
    assert "account_count" in project_schema.schema["int_customer_activity"]
    # No schema-qualified nesting in static mode.
    assert "analytics_staging" not in project_schema.schema


def test_static_mode_source_placeholder_matches_sql_parser_convention(
    static_project: DbtProject,
) -> None:
    # sql_parser.preprocess_dbt_sql() replaces {{ source('core_banking', 'customers') }}
    # with the flat placeholder "core_banking__customers" -- the schema builder's
    # key for that source table must match it exactly or SELECT * against it
    # (via a source-derived CTE) would resolve incorrectly.
    project_schema = build_project_schema(static_project)

    assert "core_banking__customers" in project_schema.schema
    assert project_schema.physical_to_model[(None, "core_banking__customers")] is None


def test_static_mode_sources_dict_is_keyed_by_bare_model_name_only(
    static_project: DbtProject,
) -> None:
    project_schema = build_project_schema(static_project)
    raw_sql = _raw_sql_for(static_project, "stg_customers")

    assert project_schema.sources["stg_customers"] == raw_sql
    # No schema-qualified duplicate keys -- static mode has no schema/alias info.
    assert "analytics_staging.stg_customers" not in project_schema.sources


def test_static_mode_physical_to_model_resolves_flat_model_names(
    static_project: DbtProject,
) -> None:
    project_schema = build_project_schema(static_project)

    assert project_schema.physical_to_model[(None, "stg_customers")] == "stg_customers"


def test_static_project_with_valid_models_has_no_schema_warnings(
    static_project: DbtProject,
) -> None:
    project_schema = build_project_schema(static_project)

    assert project_schema.schema_warnings == []


# ---------------------------------------------------------------------------
# schema_warnings: models/sources the builder can't place, reported not dropped
# ---------------------------------------------------------------------------


def test_schema_warning_when_model_sql_does_not_parse(manifest_project: DbtProject) -> None:
    broken_model = manifest_project.models[0].model_copy(
        update={"raw_sql": "this is not valid sql at all ;;;"}
    )
    project = manifest_project.model_copy(update={"models": [broken_model]})

    project_schema = build_project_schema(project)

    assert project_schema.schema_warnings
    assert any(broken_model.name in warning for warning in project_schema.schema_warnings)
    # The model is still registered in `sources` (for substitution purposes)
    # even though its own columns couldn't be determined.
    assert project_schema.sources[broken_model.name] == broken_model.raw_sql


def test_schema_warning_when_manifest_model_missing_schema_or_alias() -> None:
    orphan_model = DbtModel(
        name="orphan_model",
        file_path="/tmp/orphan_model.sql",
        relative_path="models/orphan_model.sql",
        layer="unknown",
        raw_sql="select 1 as x",
    )
    project = DbtProject(
        name="proj",
        project_path="/tmp/proj",
        dbt_project_file="/tmp/proj/dbt_project.yml",
        model_paths=["models"],
        models=[orphan_model],
        source="manifest",
    )

    project_schema = build_project_schema(project)

    assert project_schema.schema == {}
    assert any("orphan_model" in warning for warning in project_schema.schema_warnings)
    # Still kept in `sources` for substitution, and resolvable by bare name.
    assert project_schema.sources["orphan_model"] == "select 1 as x"
    assert project_schema.physical_to_model[(None, "orphan_model")] == "orphan_model"


def test_schema_warning_when_manifest_source_missing_schema() -> None:
    source = DbtSource(
        name="core_banking",
        tables=[DbtSourceTable(name="customers", columns=["customer_id"])],
    )
    project = DbtProject(
        name="proj",
        project_path="/tmp/proj",
        dbt_project_file="/tmp/proj/dbt_project.yml",
        model_paths=["models"],
        models=[],
        sources=[source],
        source="manifest",
    )

    project_schema = build_project_schema(project)

    assert project_schema.schema == {}
    assert any(
        "core_banking" in warning and "customers" in warning
        for warning in project_schema.schema_warnings
    )
