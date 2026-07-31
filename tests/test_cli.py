import json
from pathlib import Path

from typer.testing import CliRunner

from dbt_feature_lineage.cli import app

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

