"""dbt 2.0 readiness scan.

The fixture (tests/fixtures/dbt2_readiness) holds every pattern the
scanner knows about. EXPECTED_DBT2_ERROR_LINES is what dbt-oss 2.0.11's
own `dbt parse` reported for that exact file (captured while building the
scanner) -- the scanner must flag the same lines, no more, no fewer.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from dbt_feature_lineage.cli import app
from dbt_feature_lineage.services.upgrade_readiness import check_upgrade_readiness, summarize

FIXTURE = Path(__file__).parent / "fixtures" / "dbt2_readiness"
EXPECTED_DBT2_ERROR_LINES = {4, 5, 6, 9, 10, 13, 16, 29, 30, 31, 32, 35, 36, 37, 40, 43}

runner = CliRunner()


def _project(tmp_path: Path, *, vars_block: str = "", adapter: str = "duckdb") -> Path:
    project = tmp_path / "proj"
    shutil.copytree(FIXTURE, project)
    (project / "dbt_project.yml").write_text(
        "name: probe\nversion: '1.0'\nconfig-version: 2\nprofile: probe\n" + vars_block,
        encoding="utf-8",
    )
    (project / "profiles.yml").write_text(
        f"probe:\n  target: dev\n  outputs:\n    dev:\n      type: {adapter}\n",
        encoding="utf-8",
    )
    return project


def test_flags_exactly_the_lines_dbt_2_rejects(tmp_path: Path) -> None:
    findings = check_upgrade_readiness(_project(tmp_path))

    error_lines = {f.line for f in findings if f.severity == "error"}
    assert error_lines == EXPECTED_DBT2_ERROR_LINES
    assert {f.file for f in findings} == {"models/schema.yml"}


def test_meta_finding_explains_the_owner_is_lost(tmp_path: Path) -> None:
    findings = check_upgrade_readiness(_project(tmp_path))

    meta = next(f for f in findings if f.line == 6)
    assert meta.rule == "property_moved_to_config"
    assert "owner" in meta.message and "config" in meta.fix


def test_test_arguments_are_flagged_but_config_keys_are_not(tmp_path: Path) -> None:
    findings = check_upgrade_readiness(_project(tmp_path))

    test_findings = [f for f in findings if f.rule == "test_arguments_top_level"]
    assert {f.line for f in test_findings} == {13, 16, 43}
    # `severity: warn` next to the relationships arguments isn't an argument.
    assert all("severity" not in f.message for f in test_findings)


def test_deprecated_tests_key_is_info_only(tmp_path: Path) -> None:
    findings = check_upgrade_readiness(_project(tmp_path))

    renamed = [f for f in findings if f.rule == "tests_key_renamed"]
    assert [f.severity for f in renamed] == ["info"]


def test_self_referencing_var_is_a_blocker(tmp_path: Path) -> None:
    project = _project(tmp_path, vars_block="vars:\n  t: \"{{ var('t', 'x') }}\"\n  ok: plain\n")

    findings = check_upgrade_readiness(project)

    assert findings[0].rule == "self_referencing_var"
    assert findings[0].severity == "blocker"
    assert (findings[0].file, findings[0].line) == ("dbt_project.yml", 6)


def test_experimental_adapter_is_reported(tmp_path: Path) -> None:
    findings = check_upgrade_readiness(_project(tmp_path, adapter="postgres"))

    assert any(f.rule == "experimental_adapter" and "postgres" in f.message for f in findings)


def test_clean_project_has_no_findings(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "models" / "schema.yml").write_text(
        "version: 2\nmodels:\n  - name: m\n    config: {meta: {owner: x}, tags: [a]}\n"
        "    columns:\n      - name: id\n        data_tests: [not_null]\n",
        encoding="utf-8",
    )

    assert check_upgrade_readiness(project) == []
    assert summarize([]) == {"blocker": 0, "error": 0, "info": 0}


def test_skips_target_and_packages(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "models" / "schema.yml").unlink()
    for skipped in ("target", "dbt_packages"):
        (project / skipped).mkdir()
        (project / skipped / "x.yml").write_text("models:\n  - name: m\n    meta: {}\n")

    assert check_upgrade_readiness(project) == []


def test_cli_check_upgrade_exits_1_with_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["check-upgrade", str(_project(tmp_path)), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["summary"]["error"] == len(EXPECTED_DBT2_ERROR_LINES)


def test_cli_check_upgrade_passes_on_the_bundled_examples() -> None:
    root = Path(__file__).resolve().parent.parent / "examples"
    for name in ("sample_banking_dbt", "multi_domain_dbt"):
        result = runner.invoke(app, ["check-upgrade", str(root / name)])
        assert result.exit_code == 0, result.stdout
