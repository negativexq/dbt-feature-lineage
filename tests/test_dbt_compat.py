"""End-to-end against a real `dbt` binary: run `dbt parse` on the bundled
examples and check the app reads the manifest it writes.

Opt-in (DFL_DBT_COMPAT=1) because it shells out to whichever `dbt` is
first on PATH -- CI's `dbt-compat` job runs it once with dbt-core 1.x and
once with dbt 2.x (dbt-oss), which is the point: the same assertions must
hold on both majors.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from dbt_feature_lineage.loaders.artifact_detector import resolve_dbt_project
from dbt_feature_lineage.services.lineage_service import build_project_lineage
from dbt_feature_lineage.services.upgrade_readiness import check_upgrade_readiness

pytestmark = pytest.mark.skipif(
    os.environ.get("DFL_DBT_COMPAT") != "1" or shutil.which("dbt") is None,
    reason="set DFL_DBT_COMPAT=1 with a dbt binary on PATH to run",
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# name -> (models, models with an owner, exposures, data tests on models)
EXPECTED = {
    "sample_banking_dbt": (12, 6, 0, 43),
    "multi_domain_dbt": (12, 6, 1, 11),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_dbt_parse_produces_a_clean_manifest(tmp_path: Path, name: str) -> None:
    project_dir = tmp_path / name
    shutil.copytree(EXAMPLES / name, project_dir, ignore=shutil.ignore_patterns("target"))

    project = resolve_dbt_project(project_dir, generate_artifacts=True, force_parse=True)

    status = project.artifact_status
    assert status is not None
    assert (status.mode, status.reason) == ("manifest", "generated"), status.message
    assert status.dbt_version

    models, owned, exposures, tests = EXPECTED[name]
    assert len(project.models) == models
    assert sum(1 for m in project.models if m.owner) == owned
    assert len(project.exposures) == exposures
    assert sum(m.test_count for m in project.models) == tests

    graph = build_project_lineage(project)
    assert any(node.layer == "source" for node in graph.nodes)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_examples_have_no_dbt2_incompatibilities(name: str) -> None:
    findings = check_upgrade_readiness(EXAMPLES / name)
    assert [f for f in findings if f.severity != "info"] == []
