"""Tests for the Streamlit app's manifest-vs-static artifact UI flow.

No test here invokes a real `dbt` CLI -- dbt_feature_lineage.loaders.artifact_detector's
shutil/subprocess entry points are always monkeypatched.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from dbt_feature_lineage.loaders import artifact_detector


def _run_app() -> AppTest:
    at = AppTest.from_file("app.py")
    at.run()
    assert not at.exception
    return at


def _generate_button(at: AppTest):
    return next(b for b in at.button if b.label == "Generate artifacts (dbt parse)")


def _write_minimal_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "fixture_project"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text(
        "name: fixture_project\nmodel-paths:\n  - models\n", encoding="utf-8"
    )
    return project_dir


def test_default_project_has_no_manifest_and_shows_generate_button() -> None:
    # examples/sample_banking_dbt has no target/manifest.json checked in.
    at = _run_app()

    assert any("Loaded project: sample_banking_dbt" in success.value for success in at.success)
    assert any(button.label == "Generate artifacts (dbt parse)" for button in at.button)
    assert any("not found" in info.value.lower() for info in at.info)
    assert not at.warning


def test_generate_button_dbt_cli_unavailable_shows_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: None)

    at = _run_app()
    _generate_button(at).click().run()

    assert not at.exception
    assert any(
        "dbt" in warning.value.lower() and "not found" in warning.value.lower()
        for warning in at.warning
    )
    # Still on the static path -- the button should remain available for a retry.
    assert any(button.label == "Generate artifacts (dbt parse)" for button in at.button)


def test_generate_button_no_profile_shows_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")
    monkeypatch.setattr(artifact_detector, "_dbt_profile_available", lambda _project_dir: False)

    at = _run_app()
    at.text_input[0].set_value(str(project_dir)).run()
    _generate_button(at).click().run()

    assert not at.exception
    assert any("no profiles.yml" in warning.value.lower() for warning in at.warning)


def test_generate_button_success_shows_manifest_success_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    staging_dir = project_dir / "models" / "staging"
    staging_dir.mkdir(parents=True)
    (staging_dir / "stg_widgets.sql").write_text("select 1 as widget_id\n", encoding="utf-8")
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")
    monkeypatch.setattr(artifact_detector, "_dbt_profile_available", lambda _project_dir: True)

    manifest_payload = {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
            "project_name": "fixture_project",
        },
        "nodes": {
            "model.fixture_project.stg_widgets": {
                "resource_type": "model",
                "unique_id": "model.fixture_project.stg_widgets",
                "name": "stg_widgets",
                "path": "staging/stg_widgets.sql",
                "original_file_path": "models/staging/stg_widgets.sql",
                "config": {"materialized": "view"},
                "raw_code": "select 1 as widget_id",
                "compiled_code": "select 1 as widget_id",
                "compiled": True,
                "depends_on": {"macros": [], "nodes": []},
            }
        },
        "sources": {},
    }

    def fake_run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        target_path = project_dir / "target"
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "manifest.json").write_text(json.dumps(manifest_payload), encoding="utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(artifact_detector.subprocess, "run", fake_run)

    at = _run_app()
    at.text_input[0].set_value(str(project_dir)).run()
    _generate_button(at).click().run()

    # The generation itself triggers a rerun once the manifest is on disk,
    # so this final state reflects a fresh "found" load rather than the
    # one-shot "generated" status -- both are manifest-mode successes.
    assert not at.exception
    assert any("manifest.json" in success.value.lower() for success in at.success)
    assert not at.warning
    # Manifest mode -- no more "Generate artifacts" button needed.
    assert not any(button.label == "Generate artifacts (dbt parse)" for button in at.button)
