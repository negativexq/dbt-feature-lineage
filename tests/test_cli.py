import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import dbt_feature_lineage.cli as cli_module
from dbt_feature_lineage.cli import app
from dbt_feature_lineage.loaders import artifact_detector

runner = CliRunner()


def test_json_serialization(sample_project_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(sample_project_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["name"] == "sample_banking_dbt"
    assert len(payload["models"]) == 12
    assert payload["sources"][0]["name"] == "core_banking"


def test_models_only_output(sample_project_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(sample_project_path), "--json", "--models-only"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["project"] == "sample_banking_dbt"
    assert len(payload["models"]) == 12
    assert "sources" not in payload


def test_sources_only_output(sample_project_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(sample_project_path), "--json", "--sources-only"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["project"] == "sample_banking_dbt"
    assert len(payload["sources"]) == 1
    assert "models" not in payload


def test_inspect_command_json(sample_project_path: Path) -> None:
    result = runner.invoke(
        app,
        ["inspect", str(sample_project_path), "mart_customer_features", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["model_name"] == "mart_customer_features"
    assert len(payload["cte_names"]) >= 8
    assert payload["join_count"] >= 4
    assert any(column["output_name"] == "risk_segment" for column in payload["output_columns"])


def _write_minimal_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "fixture_project"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text(
        "name: fixture_project\nmodel-paths:\n  - models\n", encoding="utf-8"
    )
    return project_dir


# ---------------------------------------------------------------------------
# --generate-artifacts / --no-generate-artifacts / interactive prompt
# ---------------------------------------------------------------------------


def test_json_output_includes_artifact_status(sample_project_path: Path) -> None:
    # sample_project_path has no target/manifest.json, and CliRunner's stdin
    # is not a tty, so this must fall back to static without prompting.
    result = runner.invoke(app, ["analyze", str(sample_project_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["source"] == "static"
    assert payload["artifact_status"]["mode"] == "static"
    assert payload["artifact_status"]["reason"] == "not_generated"


def test_models_only_json_includes_artifact_status(sample_project_path: Path) -> None:
    result = runner.invoke(
        app, ["analyze", str(sample_project_path), "--json", "--models-only"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["artifact_status"]["reason"] == "not_generated"
    assert len(payload["models"]) == 12


def test_human_output_prints_artifact_status(sample_project_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(sample_project_path)])

    assert result.exit_code == 0
    assert "static" in result.stdout
    assert "not_generated" in result.stdout


def test_non_interactive_never_prompts(
    sample_project_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "_is_interactive", lambda: False)

    def _fail_confirm(*args: object, **kwargs: object) -> bool:
        raise AssertionError("Confirm.ask must not be called when non-interactive")

    monkeypatch.setattr(cli_module.Confirm, "ask", _fail_confirm)

    result = runner.invoke(app, ["analyze", str(sample_project_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["artifact_status"]["reason"] == "not_generated"


def test_interactive_prompts_and_declines_falls_back_to_static(
    sample_project_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli_module.Confirm, "ask", lambda *args, **kwargs: False)

    result = runner.invoke(app, ["analyze", str(sample_project_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["artifact_status"]["reason"] == "not_generated"


def test_interactive_prompts_and_accepts_attempts_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    monkeypatch.setattr(cli_module, "_is_interactive", lambda: True)

    confirm_calls: list[str] = []

    def fake_confirm(prompt: str, **kwargs: object) -> bool:
        confirm_calls.append(prompt)
        return True

    monkeypatch.setattr(cli_module.Confirm, "ask", fake_confirm)
    # No real `dbt` on PATH in the test environment, but force it deterministically.
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: None)

    result = runner.invoke(app, ["analyze", str(project_dir), "--json"])

    assert result.exit_code == 0
    assert len(confirm_calls) == 1
    payload = json.loads(result.stdout)
    assert payload["artifact_status"]["reason"] == "dbt_cli_unavailable"


def test_generate_artifacts_flag_skips_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    monkeypatch.setattr(cli_module, "_is_interactive", lambda: True)

    def _fail_confirm(*args: object, **kwargs: object) -> bool:
        raise AssertionError("Confirm.ask must not be called when --generate-artifacts is set")

    monkeypatch.setattr(cli_module.Confirm, "ask", _fail_confirm)
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: None)

    result = runner.invoke(
        app, ["analyze", str(project_dir), "--json", "--generate-artifacts"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["artifact_status"]["reason"] == "dbt_cli_unavailable"


def test_no_generate_artifacts_flag_skips_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    monkeypatch.setattr(cli_module, "_is_interactive", lambda: True)

    def _fail_confirm(*args: object, **kwargs: object) -> bool:
        raise AssertionError("Confirm.ask must not be called when --no-generate-artifacts is set")

    monkeypatch.setattr(cli_module.Confirm, "ask", _fail_confirm)

    result = runner.invoke(
        app, ["analyze", str(project_dir), "--json", "--no-generate-artifacts"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["artifact_status"]["reason"] == "not_generated"
