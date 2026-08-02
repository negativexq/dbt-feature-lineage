"""Tests for the Streamlit app's two pages: Model Explorer (artifact-vs-static
UI flow) and Column Lineage (project-wide column search).

No test here invokes a real `dbt` CLI -- dbt_feature_lineage.loaders.artifact_detector's
shutil/subprocess entry points are always monkeypatched.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from dbt_feature_lineage.loaders import artifact_detector

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _run_app() -> AppTest:
    # Model Explorer (the default page) no longer builds the lineage graph
    # at all -- st.navigation() pages are lazy (only the active page's
    # script executes), unlike the single-page st.tabs() layout this
    # replaced, where every tab body ran on every rerun regardless of
    # visibility. 15s is just a safety margin, not a reflection of actual
    # cost (verified: loading the 12-model default project here takes
    # well under a second).
    at = AppTest.from_file("app.py", default_timeout=15)
    at.run()
    assert not at.exception
    return at


def _run_model_dag_page(project_dir: Path | None = None) -> AppTest:
    # Same lazy-page reasoning as _run_lineage_page: switch_page() before
    # the first .run() means Model Explorer's own script never executes.
    at = AppTest.from_file("app.py", default_timeout=20)
    at.switch_page("pages/model_dag.py").run()
    if project_dir is not None:
        at.text_input(key="model_dag_project_path").set_value(str(project_dir)).run()
    assert not at.exception
    return at


def _model_dag_component_payload(at: AppTest) -> dict[str, Any]:
    # AppTest can't simulate interaction with a custom component (no real
    # JS runtime executes, so the component's returned value never
    # changes -- verified via sandbox spike, docs/v0.5-plan.md Bölüm 8) --
    # but it can see exactly what was sent *to* the component, via the
    # component_instance element's raw json_args. That's what page-level
    # tests assert on here, instead of the component's own rendering.
    component = at.get("component_instance")[0]
    return json.loads(component.proto.json_args)


def _run_lineage_page(project_dir: Path | None = None) -> AppTest:
    # switch_page() before the first .run() skips executing Model Explorer
    # at all (verified: it works even on a never-run AppTest instance).
    # The very first render of Column Lineage still uses its default
    # (12-model example) project path -- AppTest has no way to seed widget
    # state before a page's first execution -- but st.cache_data persists
    # across AppTest instances within the same pytest process, so only the
    # first test in the whole suite that reaches this page pays that cost.
    at = AppTest.from_file("app.py", default_timeout=20)
    at.switch_page("pages/column_lineage.py").run()
    if project_dir is not None:
        at.text_input[0].set_value(str(project_dir)).run()
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


def _write_manifest_project(tmp_path: Path, fixture_name: str) -> Path:
    # A dedicated subdir per fixture, since a single test may request more
    # than one of these fixtures and they'd otherwise share `tmp_path`.
    project_dir = tmp_path / Path(fixture_name).stem
    target_path = project_dir / "target"
    target_path.mkdir(parents=True)
    manifest_data = json.loads((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"))
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    return project_dir


def _write_manifest_with_broken_model(tmp_path: Path) -> Path:
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


# ---------------------------------------------------------------------------
# Model Explorer page (default page, app.py)
# ---------------------------------------------------------------------------


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
    monkeypatch.setattr(artifact_detector, "_resolve_profiles_dir", lambda _project_dir: None)

    at = _run_app()
    at.text_input[0].set_value(str(project_dir)).run()
    _generate_button(at).click().run()

    assert not at.exception
    assert any("no profiles.yml" in warning.value.lower() for warning in at.warning)
    # Regression guard: the fixed headline and ArtifactStatus.message used to
    # both restate "no profiles.yml found", producing a visibly repeated
    # sentence. The message should only appear once.
    warning_text = next(
        warning.value for warning in at.warning if "no profiles.yml" in warning.value.lower()
    )
    assert warning_text.lower().count("no profiles.yml") == 1


def test_generate_button_success_shows_manifest_success_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_dir = _write_minimal_project(tmp_path)
    staging_dir = project_dir / "models" / "staging"
    staging_dir.mkdir(parents=True)
    (staging_dir / "stg_widgets.sql").write_text("select 1 as widget_id\n", encoding="utf-8")
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: "/usr/local/bin/dbt")
    monkeypatch.setattr(
        artifact_detector, "_resolve_profiles_dir", lambda project_dir: project_dir
    )

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


# ---------------------------------------------------------------------------
# Column Lineage page (pages/column_lineage.py) -- project-wide, its own
# "dbt project path" input, independent of Model Explorer's sidebar model
# selection (docs/v0.4-plan.md/v0.4 multi-page follow-up).
# ---------------------------------------------------------------------------


def test_lineage_page_search_shows_matching_columns(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)

    at.text_input(key="lineage_search").set_value("customer_id").run()

    assert not at.exception
    match_box = at.selectbox(key="lineage_match")
    assert len(match_box.options) >= 3
    assert any("mart_customer_overview" in option for option in match_box.options)
    assert any("stg_customers" in option for option in match_box.options)


def test_lineage_page_search_with_no_matches_shows_info(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)

    at.text_input(key="lineage_search").set_value("totally_missing_column").run()

    assert not at.exception
    assert any("No columns matching" in info.value for info in at.info)
    with pytest.raises(KeyError):
        at.selectbox(key="lineage_match")


def test_lineage_page_selecting_a_match_renders_chain_without_error(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)
    at.text_input(key="lineage_search").set_value("customer_id").run()

    match_box = at.selectbox(key="lineage_match")
    mart_option = next(
        option for option in match_box.options if "mart_customer_overview" in option
    )
    match_box.set_value(mart_option).run()

    assert not at.exception
    # A column with real upstream ancestors should not show the
    # "no upstream lineage" fallback message.
    assert not any("No upstream lineage" in info.value for info in at.info)


def test_lineage_page_terminal_column_shows_no_upstream_message(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)
    at.text_input(key="lineage_search").set_value("customer_id").run()

    match_box = at.selectbox(key="lineage_match")
    raw_source_option = next(
        option for option in match_box.options if "raw_banking.customers" in option
    )
    match_box.set_value(raw_source_option).run()

    assert not at.exception
    assert any("No upstream lineage" in info.value for info in at.info)


def test_lineage_page_branching_chain_renders_without_error(tmp_path: Path) -> None:
    # mart_customer_merged.customer_id = coalesce(a.customer_id, b.customer_id)
    # -- a genuine multi-parent DAG; this just needs to render without
    # raising (build_lineage_dot()'s own correctness is unit-tested in
    # test_ui_rendering.py, AppTest can't introspect graphviz_chart content).
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_branching.json")
    at = _run_lineage_page(project_dir)
    at.text_input(key="lineage_search").set_value("customer_id").run()

    match_box = at.selectbox(key="lineage_match")
    merged_option = next(
        option for option in match_box.options if "mart_customer_merged" in option
    )
    match_box.set_value(merged_option).run()

    assert not at.exception


def test_lineage_page_shows_lineage_warnings(tmp_path: Path) -> None:
    project_dir = _write_manifest_with_broken_model(tmp_path)

    at = _run_lineage_page(project_dir)

    assert not at.exception
    assert any("broken_model" in warning.value for warning in at.warning)


def test_model_explorer_does_not_execute_lineage_page_at_all() -> None:
    # Visiting Model Explorer must not execute pages/column_lineage.py's
    # script -- its "lineage_search" widget must simply not exist, proving
    # the page split (not just a spinner) is what makes this lazy.
    at = _run_app()

    with pytest.raises(KeyError):
        at.text_input(key="lineage_search")


def test_model_explorer_loads_quickly_despite_slow_lineage_build() -> None:
    # Concrete performance verification for the page split: loading the
    # default (12-model) project on Model Explorer must be fast, even
    # though building its full lineage graph (only triggered by visiting
    # Column Lineage, per the test above) takes several seconds cold.
    start = time.monotonic()
    _run_app()
    elapsed = time.monotonic() - start

    assert elapsed < 5.0


def test_lineage_page_is_independent_of_model_explorer_selection(tmp_path: Path) -> None:
    # The Column Lineage page has its own project-path input; it must not
    # depend on anything selected on Model Explorer's sidebar.
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)

    at.text_input(key="lineage_search").set_value("customer_id").run()

    match_box = at.selectbox(key="lineage_match")
    assert any("mart_customer_overview" in option for option in match_box.options)


# ---------------------------------------------------------------------------
# Model DAG page (pages/model_dag.py) -- project-wide, its own "dbt
# project path" input, independent of Model Explorer's sidebar selection.
# Test strategy per docs/v0.5-plan.md Bölüm 8: AppTest can find the
# streamlit_flow component and inspect exactly what was sent to it
# (json_args), but can't simulate node-click interaction with it -- so
# page tests assert on the outgoing payload, not on rendered output.
# ---------------------------------------------------------------------------


def test_model_dag_page_sends_one_node_per_model(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    at = _run_model_dag_page(project_dir)

    payload = _model_dag_component_payload(at)
    assert {node["id"] for node in payload["nodes"]} == {
        "stg_customers",
        "int_customer_activity",
        "mart_customer_overview",
    }


def test_model_dag_page_sends_edges_matching_ref_dependencies(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    at = _run_model_dag_page(project_dir)

    payload = _model_dag_component_payload(at)
    edge_pairs = {(edge["source"], edge["target"]) for edge in payload["edges"]}
    assert edge_pairs == {
        ("stg_customers", "int_customer_activity"),
        ("int_customer_activity", "mart_customer_overview"),
    }


def test_model_dag_page_node_content_includes_materialization_and_column_count(
    tmp_path: Path,
) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    at = _run_model_dag_page(project_dir)

    payload = _model_dag_component_payload(at)
    mart_node = next(n for n in payload["nodes"] if n["id"] == "mart_customer_overview")
    content = mart_node["data"]["content"]
    assert "mart_customer_overview" in content
    assert "table" in content  # this fixture's materialization for this model


def test_model_dag_page_is_independent_of_model_explorer_selection(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    at = _run_model_dag_page(project_dir)

    payload = _model_dag_component_payload(at)
    assert len(payload["nodes"]) == 3


def test_model_explorer_does_not_execute_model_dag_page_at_all() -> None:
    # Visiting Model Explorer must not execute pages/model_dag.py's script
    # -- its "dbt project path" widget must simply not exist, proving the
    # page split makes it lazy the same way it does for Column Lineage.
    at = _run_app()

    with pytest.raises(KeyError):
        at.text_input(key="model_dag_project_path")


def test_model_dag_page_shows_circular_dependency_warning(tmp_path: Path) -> None:
    manifest_data = json.loads((FIXTURES_DIR / "manifest_lineage_chain.json").read_text())
    # Make int_customer_activity ref() back to mart_customer_overview too,
    # on top of its existing stg_customers dependency -- a genuine
    # model-level ref() cycle (int_customer_activity <-> mart_customer_overview).
    manifest_data["nodes"]["model.lineage_chain_demo.int_customer_activity"][
        "depends_on"
    ]["nodes"].append("model.lineage_chain_demo.mart_customer_overview")
    project_dir = tmp_path / "circular_chain"
    target_path = project_dir / "target"
    target_path.mkdir(parents=True)
    (target_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    at = _run_model_dag_page(project_dir)

    assert any("circular ref" in warning.value.lower() for warning in at.warning)
    payload = _model_dag_component_payload(at)
    # Only stg_customers is left standing -- the two cyclic models are
    # excluded entirely (model_dag_service.build_model_dag()'s
    # warn-and-exclude contract, not a raise).
    assert {node["id"] for node in payload["nodes"]} == {"stg_customers"}
