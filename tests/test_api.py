"""FastAPI backend (src/dbt_feature_lineage/api/app.py), against the bundled
example projects in static mode -- copied to tmp_path so nothing a test
does (or a stray target/ dir) leaks between tests or into the repo."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dbt_feature_lineage.api.app import app
from dbt_feature_lineage.api.cache import cached_load_project

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

client = TestClient(app)


@pytest.fixture
def banking(tmp_path: Path) -> str:
    cached_load_project.cache_clear()
    project = tmp_path / "sample_banking_dbt"
    shutil.copytree(
        EXAMPLES / "sample_banking_dbt", project, ignore=shutil.ignore_patterns("target")
    )
    return str(project)


def test_health() -> None:
    assert client.get("/api/health").status_code == 200


def test_project_summary_static_mode(banking: str) -> None:
    payload = client.get("/api/project", params={"path": banking}).json()

    assert payload["model_count"] == 12
    status = payload["artifact_status"]
    assert status["mode"] == "static"
    assert status["headline"]
    assert status["issues"] == []


def test_unknown_path_is_404() -> None:
    response = client.get("/api/project", params={"path": "/definitely/not/here"})
    assert response.status_code == 404


def test_model_detail_has_downstream_models(banking: str) -> None:
    payload = client.get("/api/models/stg_customers", params={"path": banking}).json()

    assert payload["model_name"] == "stg_customers"
    assert "int_customer_activity" in payload["downstream_models"]
    assert payload["exposures"] == []


def test_mart_has_no_downstream_models(banking: str) -> None:
    payload = client.get("/api/models/mart_risk_features", params={"path": banking}).json()
    assert payload["downstream_models"] == []


def test_lineage_search_marks_dbt_sources(banking: str) -> None:
    matches = client.get(
        "/api/lineage/search", params={"path": banking, "q": "customer_id"}
    ).json()

    layers = {m["layer"] for m in matches}
    assert "source" in layers
    assert "staging" in layers


def test_upgrade_readiness_endpoint(banking: str) -> None:
    payload = client.get("/api/upgrade-readiness", params={"path": banking}).json()

    assert payload["summary"]["error"] == 0
    assert payload["summary"]["blocker"] == 0
    assert [f["rule"] for f in payload["findings"]] == ["experimental_adapter"]


def test_upgrade_readiness_flags_legacy_meta(banking: str) -> None:
    schema = Path(banking) / "models" / "staging" / "staging.yml"
    schema.write_text(
        schema.read_text(encoding="utf-8").replace(
            "    config:\n      meta:\n        owner: core-banking-data-team\n",
            "    meta:\n      owner: core-banking-data-team\n",
        ),
        encoding="utf-8",
    )

    findings = client.get("/api/upgrade-readiness", params={"path": banking}).json()["findings"]

    meta = [f for f in findings if f["rule"] == "property_moved_to_config"]
    assert len(meta) == 1
    assert meta[0]["file"] == "models/staging/staging.yml"
