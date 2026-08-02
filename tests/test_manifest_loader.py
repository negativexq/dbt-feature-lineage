"""Tests for the manifest.json-based project loader (v0.2 artifact engine).

Written ahead of the implementation: dbt_feature_lineage.loaders.manifest_loader
does not exist yet. These tests pin down its intended public contract, as
documented in docs/v0.2-plan.md (section 8).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dbt_feature_lineage.domain.models import DbtDependency
from dbt_feature_lineage.loaders.manifest_loader import (
    SUPPORTED_MANIFEST_SCHEMA_VERSIONS,
    ManifestNotFoundError,
    ManifestParseError,
    UnsupportedManifestSchemaVersionError,
    load_dbt_project_from_manifest,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "manifest.json"
METADATA_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "manifest_model_metadata.json"
)


@pytest.fixture
def manifest_data() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def metadata_manifest_data() -> dict[str, Any]:
    return json.loads(METADATA_FIXTURE_PATH.read_text(encoding="utf-8"))


def _write_manifest(
    project_dir: Path, manifest_data: dict[str, Any], target_dir: str = "target"
) -> Path:
    target_path = project_dir / target_dir
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    return project_dir


def _model(project, name: str):
    for model in project.models:
        if model.name == name:
            return model
    raise AssertionError(f"model not found in loaded project: {name}")


# ---------------------------------------------------------------------------
# Missing / malformed manifest handling
# ---------------------------------------------------------------------------


def test_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestNotFoundError):
        load_dbt_project_from_manifest(tmp_path)


def test_missing_manifest_is_a_file_not_found_error(tmp_path: Path) -> None:
    # ManifestNotFoundError should be catchable as a plain FileNotFoundError
    # by callers that don't care about the artifact-engine-specific type.
    with pytest.raises(FileNotFoundError):
        load_dbt_project_from_manifest(tmp_path)


def test_malformed_manifest_json_raises(tmp_path: Path) -> None:
    target_path = tmp_path / "target"
    target_path.mkdir()
    (target_path / "manifest.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ManifestParseError):
        load_dbt_project_from_manifest(tmp_path)


def test_custom_target_dir_is_respected(tmp_path: Path, manifest_data: dict[str, Any]) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data, target_dir="custom_target")

    project = load_dbt_project_from_manifest(project_dir, target_dir="custom_target")

    assert project.name == "sample_banking_dbt"


# ---------------------------------------------------------------------------
# Schema version gate
# ---------------------------------------------------------------------------


def test_supported_schema_versions_is_a_fixed_nonempty_range() -> None:
    assert isinstance(SUPPORTED_MANIFEST_SCHEMA_VERSIONS, frozenset)
    assert SUPPORTED_MANIFEST_SCHEMA_VERSIONS
    assert "v12" in SUPPORTED_MANIFEST_SCHEMA_VERSIONS


def test_unsupported_schema_version_raises(tmp_path: Path, manifest_data: dict[str, Any]) -> None:
    manifest_data["metadata"]["dbt_schema_version"] = (
        "https://schemas.getdbt.com/dbt/manifest/v3.json"
    )
    project_dir = _write_manifest(tmp_path, manifest_data)

    with pytest.raises(UnsupportedManifestSchemaVersionError):
        load_dbt_project_from_manifest(project_dir)


def test_unparseable_schema_version_string_raises(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    manifest_data["metadata"]["dbt_schema_version"] = "not-a-schema-url"
    project_dir = _write_manifest(tmp_path, manifest_data)

    with pytest.raises(UnsupportedManifestSchemaVersionError):
        load_dbt_project_from_manifest(project_dir)


# ---------------------------------------------------------------------------
# Successful load: project + model mapping
# ---------------------------------------------------------------------------


def test_load_valid_manifest_sets_project_metadata(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)

    project = load_dbt_project_from_manifest(project_dir)

    assert project.name == "sample_banking_dbt"
    assert project.source == "manifest"
    assert project.artifact_status is None


def test_load_valid_manifest_maps_all_model_nodes(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)

    project = load_dbt_project_from_manifest(project_dir)

    assert {model.name for model in project.models} == {
        "stg_customers",
        "stg_accounts",
        "int_customer_activity",
    }


def test_model_layer_is_detected_from_relative_path(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    assert _model(project, "stg_customers").layer == "staging"
    assert _model(project, "int_customer_activity").layer == "intermediate"


def test_model_relative_and_file_paths_are_project_rooted(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    model = _model(project, "stg_customers")
    assert model.relative_path == "models/staging/stg_customers.sql"
    assert model.file_path.endswith("models/staging/stg_customers.sql")


def test_manifest_only_fields_are_populated(tmp_path: Path, manifest_data: dict[str, Any]) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    stg_customers = _model(project, "stg_customers")
    assert stg_customers.unique_id == "model.sample_banking_dbt.stg_customers"
    assert stg_customers.materialization == "view"
    assert stg_customers.compiled is True

    int_customer_activity = _model(project, "int_customer_activity")
    assert int_customer_activity.materialization == "table"


def test_manifest_only_fields_include_physical_relation_identity(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    stg_customers = _model(project, "stg_customers")
    assert stg_customers.database == "banking_dev"
    assert stg_customers.schema_name == "analytics_staging"
    assert stg_customers.alias == "stg_customers"

    int_customer_activity = _model(project, "int_customer_activity")
    assert int_customer_activity.database == "banking_dev"
    assert int_customer_activity.schema_name == "analytics_intermediate"
    assert int_customer_activity.alias == "int_customer_activity"


def test_physical_relation_fields_default_to_none_when_absent(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    node = manifest_data["nodes"]["model.sample_banking_dbt.stg_accounts"]
    del node["database"]
    del node["schema"]
    del node["alias"]
    project_dir = _write_manifest(tmp_path, manifest_data)

    project = load_dbt_project_from_manifest(project_dir)

    stg_accounts = _model(project, "stg_accounts")
    assert stg_accounts.database is None
    assert stg_accounts.schema_name is None
    assert stg_accounts.alias is None


# ---------------------------------------------------------------------------
# raw_sql: compiled_code preferred, raw_code as fallback
# ---------------------------------------------------------------------------


def test_raw_sql_prefers_compiled_code_when_present(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    stg_customers = _model(project, "stg_customers")
    assert "raw_banking.customers" in stg_customers.raw_sql
    assert "source(" not in stg_customers.raw_sql


def test_raw_sql_falls_back_to_raw_code_when_compiled_code_missing(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    # stg_accounts has compiled_code=None in the fixture (as `dbt parse`,
    # unlike `dbt compile`/`run`, does not always populate compiled_code).
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    stg_accounts = _model(project, "stg_accounts")
    assert "{{ source('core_banking', 'accounts') }}" in stg_accounts.raw_sql
    assert stg_accounts.compiled is False


# ---------------------------------------------------------------------------
# Dependency mapping from depends_on.nodes
# ---------------------------------------------------------------------------


def test_source_dependency_is_derived_from_depends_on_nodes(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    stg_customers = _model(project, "stg_customers")
    assert stg_customers.ref_dependencies == []
    assert stg_customers.source_dependencies == [
        DbtDependency(dependency_type="source", source_name="core_banking", target_name="customers")
    ]


def test_ref_dependency_is_derived_from_depends_on_nodes(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    int_customer_activity = _model(project, "int_customer_activity")
    ref_targets = {dep.target_name for dep in int_customer_activity.ref_dependencies}
    assert ref_targets == {"stg_customers", "stg_accounts"}
    assert all(dep.dependency_type == "ref" for dep in int_customer_activity.ref_dependencies)
    assert int_customer_activity.source_dependencies == []


# ---------------------------------------------------------------------------
# Source table mapping from manifest["sources"]
# ---------------------------------------------------------------------------


def test_sources_are_grouped_by_source_name(tmp_path: Path, manifest_data: dict[str, Any]) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    assert len(project.sources) == 1
    source = project.sources[0]
    assert source.name == "core_banking"
    assert {table.name for table in source.tables} == {"customers", "accounts"}


def test_source_table_columns_are_populated(tmp_path: Path, manifest_data: dict[str, Any]) -> None:
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    source = project.sources[0]
    customers_table = next(table for table in source.tables if table.name == "customers")
    assert set(customers_table.columns) == {"customer_id", "first_name"}


# ---------------------------------------------------------------------------
# Model metadata: description/tags/owner/test_count (v0.5)
# ---------------------------------------------------------------------------


def test_description_and_tags_are_read_from_the_model_node(
    tmp_path: Path, metadata_manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, metadata_manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    model = _model(project, "mart_with_metadata")
    assert model.description == "Customer-level feature mart used by the finance team."
    assert model.tags == ["finance", "daily"]


def test_owner_is_read_from_meta_owner(
    tmp_path: Path, metadata_manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, metadata_manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    model = _model(project, "mart_with_metadata")
    assert model.owner == "finance-team"


def test_test_count_is_derived_from_separate_test_nodes(
    tmp_path: Path, metadata_manifest_data: dict[str, Any]
) -> None:
    # The manifest has no "tests" list directly on the model node -- two
    # separate resource_type="test" nodes each depend_on it via
    # depends_on.nodes, and test_count must be reverse-mapped from those.
    project_dir = _write_manifest(tmp_path, metadata_manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    model = _model(project, "mart_with_metadata")
    assert model.test_count == 2


def test_model_with_no_tests_has_zero_test_count(
    tmp_path: Path, metadata_manifest_data: dict[str, Any]
) -> None:
    project_dir = _write_manifest(tmp_path, metadata_manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    model = _model(project, "mart_without_metadata")
    assert model.test_count == 0


def test_empty_description_meta_and_tags_default_to_none_or_empty(
    tmp_path: Path, metadata_manifest_data: dict[str, Any]
) -> None:
    # mart_without_metadata has description="" and meta={} in the fixture
    # (a dbt project that never documented this model) -- an empty string
    # should normalize to None, not be kept as a falsy-but-present string.
    project_dir = _write_manifest(tmp_path, metadata_manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    model = _model(project, "mart_without_metadata")
    assert model.description is None
    assert model.tags == []
    assert model.owner is None


def test_metadata_fields_default_to_none_or_empty_when_entirely_absent(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    # The main manifest.json fixture's model nodes have description=None,
    # tags=[], meta=None (never set at all, vs. metadata_manifest_data's
    # "set but empty" case above) and no test nodes -- a real-world
    # manifest from a project that doesn't use any of this dbt metadata.
    project_dir = _write_manifest(tmp_path, manifest_data)
    project = load_dbt_project_from_manifest(project_dir)

    stg_customers = _model(project, "stg_customers")
    assert stg_customers.description is None
    assert stg_customers.tags == []
    assert stg_customers.owner is None
    assert stg_customers.test_count == 0
