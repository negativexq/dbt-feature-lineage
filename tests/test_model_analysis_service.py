"""Tests for inspect_model's manifest-vs-static integration.

inspect_model() now goes through resolve_dbt_project() instead of calling
the static loader directly, so a model inspected from a project that has
target/manifest.json gets dbt's own compiled SQL rather than the raw Jinja
source. No test here invokes a real `dbt` CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dbt_feature_lineage.loaders.artifact_detector import resolve_dbt_project
from dbt_feature_lineage.services.model_analysis_service import inspect_model

FIXTURE_MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "manifest.json"


@pytest.fixture
def manifest_data() -> dict[str, Any]:
    return json.loads(FIXTURE_MANIFEST_PATH.read_text(encoding="utf-8"))


def _write_manifest(project_dir: Path, manifest_data: dict[str, Any]) -> None:
    target_path = project_dir / "target"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Static mode (no manifest.json) is unaffected
# ---------------------------------------------------------------------------


def test_inspect_model_static_mode_unaffected(sample_project_path: Path) -> None:
    # No target/manifest.json under examples/sample_banking_dbt.
    analysis = inspect_model(sample_project_path, "stg_customers")

    assert analysis.model_name == "stg_customers"
    assert analysis.layer == "staging"


def test_inspect_model_missing_model_raises(sample_project_path: Path) -> None:
    with pytest.raises(ValueError, match="Model not found"):
        inspect_model(sample_project_path, "does_not_exist")


# ---------------------------------------------------------------------------
# Manifest mode: raw_sql prefers compiled_code, falls back to raw_code
# ---------------------------------------------------------------------------


def test_inspect_model_prefers_manifest_compiled_code(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    _write_manifest(tmp_path, manifest_data)

    analysis = inspect_model(tmp_path, "stg_customers")

    assert "banking_dev.raw_banking.customers" in analysis.raw_sql
    assert "source(" not in analysis.raw_sql


def test_inspect_model_manifest_mode_falls_back_to_raw_code_when_uncompiled(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    # stg_accounts has compiled_code=None in the fixture (as `dbt parse`
    # doesn't always populate it, unlike `dbt compile`/`run`/`build`).
    _write_manifest(tmp_path, manifest_data)

    analysis = inspect_model(tmp_path, "stg_accounts")

    assert "{{ source('core_banking', 'accounts') }}" in analysis.raw_sql


def test_manifest_mode_model_compiled_flag_reflects_manifest(
    tmp_path: Path, manifest_data: dict[str, Any]
) -> None:
    _write_manifest(tmp_path, manifest_data)

    project = resolve_dbt_project(tmp_path, generate_artifacts=False)

    stg_customers = next(model for model in project.models if model.name == "stg_customers")
    stg_accounts = next(model for model in project.models if model.name == "stg_accounts")

    assert stg_customers.compiled is True
    assert stg_accounts.compiled is False
