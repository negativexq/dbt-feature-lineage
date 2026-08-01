"""Tests for the manifest-vs-static artifact detection/fallback orchestrator.

Written ahead of the implementation: dbt_feature_lineage.loaders.artifact_detector
does not exist yet. No test here invokes a real `dbt` CLI — subprocess.run and
shutil.which are always monkeypatched.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dbt_feature_lineage.loaders import artifact_detector
from dbt_feature_lineage.loaders.artifact_detector import resolve_dbt_project

FIXTURE_MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "manifest.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def manifest_data() -> dict[str, Any]:
    return json.loads(FIXTURE_MANIFEST_PATH.read_text(encoding="utf-8"))


def _write_manifest(project_dir: Path, manifest_data: dict[str, Any]) -> None:
    target_path = project_dir / "target"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")


def _write_minimal_project(tmp_path: Path, with_profiles: bool = False) -> Path:
    project_dir = tmp_path / "fixture_project"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text(
        "name: fixture_project\nmodel-paths:\n  - models\n",
        encoding="utf-8",
    )
    if with_profiles:
        (project_dir / "profiles.yml").write_text(
            "fixture_project:\n  target: dev\n  outputs:\n    dev:\n      type: postgres\n",
            encoding="utf-8",
        )
    return project_dir


def _forbid_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess.run must not be called in this scenario")

    monkeypatch.setattr(artifact_detector.subprocess, "run", _fail)


def _isolate_home_profiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make the ~/.dbt/profiles.yml fallback check deterministic in tests."""

    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)
    monkeypatch.setattr(
        artifact_detector, "_home_profiles_path", lambda: tmp_path / "unused_home" / "profiles.yml"
    )


# ---------------------------------------------------------------------------
# 1. manifest.json already present -> manifest mode, no subprocess involved
# ---------------------------------------------------------------------------


def test_existing_manifest_is_used_directly(tmp_path: Path, manifest_data: dict[str, Any]) -> None:
    _write_manifest(tmp_path, manifest_data)

    project = resolve_dbt_project(tmp_path, generate_artifacts=False)

    assert project.source == "manifest"
    assert project.artifact_status is not None
    assert project.artifact_status.mode == "manifest"
    assert project.artifact_status.reason == "found"


def test_existing_manifest_takes_precedence_over_generate_artifacts_flag(
    tmp_path: Path, manifest_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_manifest(tmp_path, manifest_data)
    _forbid_subprocess_run(monkeypatch)

    project = resolve_dbt_project(tmp_path, generate_artifacts=True)

    assert project.source == "manifest"
    assert project.artifact_status.reason == "found"


def test_existing_but_malformed_manifest_falls_back_to_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    target_path = project_dir / "target"
    target_path.mkdir()
    (target_path / "manifest.json").write_text("{not valid json", encoding="utf-8")
    _forbid_subprocess_run(monkeypatch)

    project = resolve_dbt_project(project_dir, generate_artifacts=False)

    assert project.source == "static"
    assert project.artifact_status.mode == "static"
    assert project.artifact_status.reason == "manifest_parse_failed"


def test_existing_manifest_with_unsupported_schema_falls_back_to_static(
    tmp_path: Path, manifest_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    unsupported = copy.deepcopy(manifest_data)
    unsupported["metadata"]["dbt_schema_version"] = "https://schemas.getdbt.com/dbt/manifest/v3.json"
    _write_manifest(project_dir, unsupported)
    _forbid_subprocess_run(monkeypatch)

    project = resolve_dbt_project(project_dir, generate_artifacts=False)

    assert project.source == "static"
    assert project.artifact_status.reason == "unsupported_manifest_schema_version"


# ---------------------------------------------------------------------------
# 2. manifest.json absent, generate_artifacts=False -> static, no interactive
#    confirmation happens at this layer
# ---------------------------------------------------------------------------


def test_manifest_absent_and_generate_artifacts_false_falls_back_to_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    _forbid_subprocess_run(monkeypatch)

    project = resolve_dbt_project(project_dir, generate_artifacts=False)

    assert project.source == "static"
    assert project.artifact_status.mode == "static"
    assert project.artifact_status.reason == "not_generated"


def test_manifest_absent_default_generate_artifacts_is_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    _forbid_subprocess_run(monkeypatch)

    project = resolve_dbt_project(project_dir)

    assert project.artifact_status.reason == "not_generated"


def test_static_fallback_produces_a_working_project(sample_project_path: Path) -> None:
    # No target/manifest.json under examples/sample_banking_dbt, so this
    # exercises the real static loader end to end (no dbt parse attempted).
    project = resolve_dbt_project(sample_project_path, generate_artifacts=False)

    assert project.source == "static"
    assert project.name == "sample_banking_dbt"
    assert len(project.models) == 12


# ---------------------------------------------------------------------------
# 3. generate_artifacts=True: dbt CLI / profiles.yml pre-checks
# ---------------------------------------------------------------------------


def test_generate_artifacts_but_dbt_cli_missing_falls_back_to_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path, with_profiles=True)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: None)
    _forbid_subprocess_run(monkeypatch)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.source == "static"
    assert project.artifact_status.reason == "dbt_cli_unavailable"


def test_generate_artifacts_but_no_profiles_yml_falls_back_to_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path, with_profiles=False)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")
    _isolate_home_profiles(monkeypatch, tmp_path)
    _forbid_subprocess_run(monkeypatch)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.source == "static"
    assert project.artifact_status.reason == "no_profile"


def test_dbt_cli_check_runs_before_profile_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Neither dbt nor profiles.yml are available; dbt_cli_unavailable should
    # win since the plan says the CLI check happens first.
    project_dir = _write_minimal_project(tmp_path, with_profiles=False)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: None)
    _isolate_home_profiles(monkeypatch, tmp_path)
    _forbid_subprocess_run(monkeypatch)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.artifact_status.reason == "dbt_cli_unavailable"


# ---------------------------------------------------------------------------
# 3. generate_artifacts=True: dbt parse subprocess (always mocked)
# ---------------------------------------------------------------------------


def test_dbt_parse_is_invoked_without_shell_and_with_project_dir(
    tmp_path: Path, manifest_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path, with_profiles=True)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")

    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        _write_manifest(project_dir, manifest_data)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(artifact_detector.subprocess, "run", fake_run)

    resolve_dbt_project(project_dir, generate_artifacts=True)

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[0] == "dbt"
    assert "parse" in cmd
    assert str(project_dir) in cmd
    assert kwargs.get("shell", False) is not True


def test_dbt_parse_success_uses_manifest_mode(
    tmp_path: Path, manifest_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path, with_profiles=True)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")

    def fake_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_manifest(project_dir, manifest_data)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(artifact_detector.subprocess, "run", fake_run)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.source == "manifest"
    assert project.artifact_status.mode == "manifest"
    assert project.artifact_status.reason == "generated"
    assert {model.name for model in project.models} == {
        "stg_customers",
        "stg_accounts",
        "int_customer_activity",
    }


def test_dbt_parse_nonzero_exit_falls_back_to_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path, with_profiles=True)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")

    def fake_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="Compilation Error: model not found"
        )

    monkeypatch.setattr(artifact_detector.subprocess, "run", fake_run)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.source == "static"
    assert project.artifact_status.reason == "dbt_parse_failed"
    assert "Compilation Error" in project.artifact_status.message


def test_dbt_parse_timeout_falls_back_to_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path, with_profiles=True)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")

    def fake_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(artifact_detector.subprocess, "run", fake_run)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.source == "static"
    assert project.artifact_status.reason == "dbt_parse_failed"


def test_dbt_parse_success_without_manifest_file_falls_back_to_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # dbt exits 0 but, for whatever reason, target/manifest.json was not
    # written -- must not be treated as a manifest-mode success.
    project_dir = _write_minimal_project(tmp_path, with_profiles=True)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")

    def fake_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(artifact_detector.subprocess, "run", fake_run)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.source == "static"
    assert project.artifact_status.reason == "dbt_parse_failed"


def test_dbt_parse_success_with_unsupported_schema_falls_back_to_static(
    tmp_path: Path, manifest_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path, with_profiles=True)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")
    unsupported = copy.deepcopy(manifest_data)
    unsupported["metadata"]["dbt_schema_version"] = "https://schemas.getdbt.com/dbt/manifest/v3.json"

    def fake_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_manifest(project_dir, unsupported)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(artifact_detector.subprocess, "run", fake_run)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.source == "static"
    assert project.artifact_status.reason == "unsupported_manifest_schema_version"


def test_dbt_parse_success_with_malformed_manifest_falls_back_to_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path, with_profiles=True)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")

    def fake_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        target_path = project_dir / "target"
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "manifest.json").write_text("{not valid json", encoding="utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(artifact_detector.subprocess, "run", fake_run)

    project = resolve_dbt_project(project_dir, generate_artifacts=True)

    assert project.source == "static"
    assert project.artifact_status.reason == "manifest_parse_failed"
