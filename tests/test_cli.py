import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import dbt_feature_lineage.cli as cli_module
from dbt_feature_lineage.cli import app
from dbt_feature_lineage.loaders import artifact_detector

runner = CliRunner()
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _write_manifest_project(tmp_path: Path, fixture_name: str) -> Path:
    # A dedicated subdir per fixture, since a single test may request more
    # than one of these fixtures and they'd otherwise share `tmp_path`.
    project_dir = tmp_path / Path(fixture_name).stem
    target_path = project_dir / "target"
    target_path.mkdir(parents=True)
    manifest_data = json.loads((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"))
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    return project_dir


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


# ---------------------------------------------------------------------------
# `lineage` command
# ---------------------------------------------------------------------------


def test_lineage_zero_matches_exits_nonzero(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(app, ["lineage", str(project_dir), "does_not_exist_anywhere"])

    assert result.exit_code != 0
    assert "does_not_exist_anywhere" in result.stdout


def test_lineage_single_natural_match_json_output(tmp_path: Path) -> None:
    # "last_name" only appears in stg_customers in this fixture -- no
    # --model needed, and its chain has no further ancestors (verified:
    # tracing it doesn't reach past stg_customers in this project).
    project_dir = _write_manifest_project(tmp_path, "manifest.json")

    result = runner.invoke(app, ["lineage", str(project_dir), "last_name", "--json"])

    assert result.exit_code == 0
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["column"] == "last_name"
    assert payload["model"] == "stg_customers"
    assert payload["layer"] == "staging"
    assert payload["chain"] == [
        {"model": "stg_customers", "column": "last_name", "layer": "staging"}
    ]
    assert payload["edges"] == []
    assert payload["lineage_warnings"] == []


def test_lineage_single_natural_match_human_output(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest.json")

    result = runner.invoke(app, ["lineage", str(project_dir), "last_name"])

    assert result.exit_code == 0
    assert "last_name" in result.stdout
    assert "stg_customers" in result.stdout


def test_lineage_ambiguous_without_model_non_interactive_exits_nonzero(
    tmp_path: Path,
) -> None:
    # CliRunner's stdin isn't a TTY, so this must list the matches and
    # exit rather than hang waiting for interactive input.
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(app, ["lineage", str(project_dir), "customer_id"])

    assert result.exit_code != 0
    assert "stg_customers" in result.stdout
    assert "int_customer_activity" in result.stdout
    assert "mart_customer_overview" in result.stdout
    assert "--model" in result.stdout


def test_lineage_ambiguous_resolved_with_model_flag_linear_chain(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(
        app,
        [
            "lineage",
            str(project_dir),
            "customer_id",
            "--model",
            "mart_customer_overview",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["model"] == "mart_customer_overview"
    assert [entry["model"] for entry in payload["chain"]] == [
        "raw_banking.customers",
        "int_customer_activity",
        "mart_customer_overview",
    ]
    assert len(payload["edges"]) == 2
    assert all(edge["transformation_type"] for edge in payload["edges"])


def test_lineage_model_flag_with_no_matching_model_exits_nonzero(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(
        app,
        ["lineage", str(project_dir), "customer_id", "--model", "does_not_exist"],
    )

    assert result.exit_code != 0


def test_lineage_interactive_prompts_and_uses_selected_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    monkeypatch.setattr(cli_module, "_is_interactive", lambda: True)

    prompt_calls: list[tuple[str, list[str] | None]] = []

    def fake_prompt_ask(prompt: str, **kwargs: object) -> str:
        choices = kwargs.get("choices")
        prompt_calls.append((prompt, choices))  # type: ignore[arg-type]
        return "mart_customer_overview"

    monkeypatch.setattr(cli_module.Prompt, "ask", fake_prompt_ask)

    result = runner.invoke(app, ["lineage", str(project_dir), "customer_id", "--json"])

    assert result.exit_code == 0
    assert len(prompt_calls) == 1
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["model"] == "mart_customer_overview"


def test_lineage_branching_chain_includes_both_upstream_sources(tmp_path: Path) -> None:
    # mart_customer_merged.customer_id = coalesce(a.customer_id, b.customer_id)
    # -- a genuine multi-parent DAG, not a single arrow chain
    # (docs/v0.4-plan.md Bölüm 3): the CLI's edge-list format must show
    # both upstream inputs, not just one.
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_branching.json")

    result = runner.invoke(
        app,
        [
            "lineage",
            str(project_dir),
            "customer_id",
            "--model",
            "mart_customer_merged",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload: dict[str, Any] = json.loads(result.stdout)
    chain_models = {entry["model"] for entry in payload["chain"]}
    assert chain_models == {
        "raw_banking.customers",
        "raw_banking.legacy_customers",
        "mart_customer_merged",
    }
    assert len(payload["edges"]) == 2
    edge_sources = {edge["source"]["model"] for edge in payload["edges"]}
    assert edge_sources == {"raw_banking.customers", "raw_banking.legacy_customers"}


def test_lineage_branching_chain_human_output_lists_both_sources(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_branching.json")

    result = runner.invoke(
        app,
        ["lineage", str(project_dir), "customer_id", "--model", "mart_customer_merged"],
    )

    assert result.exit_code == 0
    assert "raw_banking.customers" in result.stdout
    assert "raw_banking.legacy_customers" in result.stdout


def _manifest_with_broken_model(tmp_path: Path) -> Path:
    manifest_data = json.loads((FIXTURES_DIR / "manifest.json").read_text(encoding="utf-8"))
    broken_sql = (
        "with upstream as (select customer_id from raw_banking.customers) "
        "select upstream.customer_id, upstream.nonexistent_column as x from upstream"
    )
    manifest_data["nodes"]["model.sample_banking_dbt.broken_model"] = {
        "resource_type": "model",
        "unique_id": "model.sample_banking_dbt.broken_model",
        "name": "broken_model",
        "path": "staging/broken_model.sql",
        "original_file_path": "models/staging/broken_model.sql",
        "database": "banking_dev",
        "schema": "analytics_staging",
        "alias": "broken_model",
        "fqn": ["sample_banking_dbt", "staging", "broken_model"],
        "tags": [],
        "config": {"materialized": "view"},
        "raw_code": broken_sql,
        "compiled_code": broken_sql,
        "compiled": True,
        "depends_on": {
            "macros": [],
            "nodes": ["source.sample_banking_dbt.core_banking.customers"],
        },
    }

    project_dir = tmp_path / "manifest_with_broken_model"
    target_path = project_dir / "target"
    target_path.mkdir(parents=True)
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    return project_dir


def test_lineage_shows_lineage_warnings_when_present(tmp_path: Path) -> None:
    project_dir = _manifest_with_broken_model(tmp_path)

    result = runner.invoke(app, ["lineage", str(project_dir), "last_name", "--json"])

    assert result.exit_code == 0
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["lineage_warnings"]
    assert any("broken_model" in warning for warning in payload["lineage_warnings"])


def test_lineage_shows_lineage_warnings_in_human_output(tmp_path: Path) -> None:
    project_dir = _manifest_with_broken_model(tmp_path)

    result = runner.invoke(app, ["lineage", str(project_dir), "last_name"])

    assert result.exit_code == 0
    assert "broken_model" in result.stdout


# ---------------------------------------------------------------------------
# `lineage` command: --direction downstream
# ---------------------------------------------------------------------------


def test_lineage_direction_defaults_to_upstream(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(
        app,
        ["lineage", str(project_dir), "customer_id", "--model", "mart_customer_overview", "--json"],
    )

    assert result.exit_code == 0
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["direction"] == "upstream"


def test_lineage_direction_downstream_from_raw_source(tmp_path: Path) -> None:
    # raw_banking.customers.customer_id fans out to stg_customers directly
    # (a dead end) and, separately, through int_customer_activity to
    # mart_customer_overview -- a genuine branching downstream DAG (see
    # test_column_search.py's module note on this fixture's real topology).
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(
        app,
        [
            "lineage",
            str(project_dir),
            "customer_id",
            "--model",
            "raw_banking.customers",
            "--direction",
            "downstream",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["direction"] == "downstream"
    chain_models = {entry["model"] for entry in payload["chain"]}
    assert chain_models == {
        "raw_banking.customers",
        "stg_customers",
        "int_customer_activity",
        "mart_customer_overview",
    }
    assert len(payload["edges"]) == 3


def test_lineage_direction_downstream_human_output(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(
        app,
        [
            "lineage",
            str(project_dir),
            "customer_id",
            "--model",
            "raw_banking.customers",
            "--direction",
            "downstream",
        ],
    )

    assert result.exit_code == 0
    assert "Downstream lineage:" in result.stdout
    assert "mart_customer_overview" in result.stdout


def test_lineage_direction_downstream_terminal_column_reports_no_lineage(
    tmp_path: Path,
) -> None:
    # mart_customer_overview is the end of the chain fixture's DAG -- nothing
    # downstream consumes it, so the single-element chain path must be hit.
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(
        app,
        [
            "lineage",
            str(project_dir),
            "customer_id",
            "--model",
            "mart_customer_overview",
            "--direction",
            "downstream",
        ],
    )

    assert result.exit_code == 0
    assert "No downstream lineage found" in result.stdout


def test_lineage_direction_invalid_value_exits_nonzero(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    result = runner.invoke(
        app,
        ["lineage", str(project_dir), "customer_id", "--direction", "sideways"],
    )

    assert result.exit_code != 0
