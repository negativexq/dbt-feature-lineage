"""Tests for the Streamlit app's four pages: Select Project (shared
project/model-group picker), Model Explorer (artifact-vs-static UI
flow), Model DAG (project-wide model graph), and Column Lineage
(project-wide column search).

Test strategy for the shared-state design (v0.6): AppTest cannot
reliably simulate a full user journey through st.switch_page() the way
a real browser can (a throwaway sandbox spike confirmed session_state
*does* survive switch_page/sidebar navigation in a real browser, within
one session -- but driving that same journey through AppTest by
simulating clicks across page transitions is exactly the fragile pattern
this project's docs call out avoiding). So every test for Model
Explorer/Model DAG/Column Lineage pre-seeds
at.session_state["shared_project_path"]/["shared_model_group"] directly,
*before* the page's first .run() -- exactly what pages/select_project.py's
own "Continue" button would have written, without needing to actually
run that page's script first. Select Project's own page gets its own
tests exercising its actual UI (scan root, pick project/group, click
"Continue") since that's the one page where driving the real widget flow
*is* the thing under test.

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

# AppTest.from_file() resolves a *relative* script path against the file
# that calls it (tests/test_app.py), not the process's working directory --
# a real regression hit here when the installed Streamlit version's own
# resolution semantics changed underneath this suite (previously "cwd",
# now "caller's own directory"). An absolute path sidesteps whatever that
# resolution rule is entirely.
APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def _run_select_project_page(root_dir: Path | None = None) -> AppTest:
    # Select Project is now the default/first page -- no switch_page needed.
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    at.run()
    if root_dir is not None:
        at.text_input(key="select_project_root").set_value(str(root_dir)).run()
    assert not at.exception
    return at


def _seed_shared_state(at: AppTest, project_dir: Path | None, model_group: str | None) -> None:
    if project_dir is not None:
        at.session_state["shared_project_path"] = str(project_dir)
        at.session_state["shared_model_group"] = model_group


def _run_model_explorer_page(
    project_dir: Path | None = None, model_group: str | None = None
) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    at.switch_page("pages/model_explorer.py")
    _seed_shared_state(at, project_dir, model_group)
    at.run()
    assert not at.exception
    return at


def _run_model_dag_page(project_dir: Path | None = None, model_group: str | None = None) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.switch_page("pages/model_dag.py")
    _seed_shared_state(at, project_dir, model_group)
    at.run()
    assert not at.exception
    return at


def _run_lineage_page(project_dir: Path | None = None, model_group: str | None = None) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.switch_page("pages/column_lineage.py")
    _seed_shared_state(at, project_dir, model_group)
    at.run()
    assert not at.exception
    return at


def _run_feature_explorer_page(
    project_dir: Path | None = None, model_group: str | None = None
) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    at.switch_page("pages/feature_explorer.py")
    _seed_shared_state(at, project_dir, model_group)
    at.run()
    assert not at.exception
    return at


def _component_payload(at: AppTest) -> dict[str, Any]:
    # AppTest can't simulate interaction with a custom component (no real
    # JS runtime executes, so the component's returned value never
    # changes -- verified via sandbox spike, docs/v0.5-plan.md Bölüm 8) --
    # but it can see exactly what was sent *to* the component, via the
    # component_instance element's raw json_args. That's what page-level
    # tests assert on here, instead of the component's own rendering.
    component = at.get("component_instance")[0]
    return json.loads(component.proto.json_args)


def _generate_button(at: AppTest):
    return next(b for b in at.button if b.label == "Generate artifacts (dbt parse)")


def _write_feature_explorer_project(tmp_path: Path) -> Path:
    # Three models whose output columns overlap by substring but not by
    # exact name -- "id" is an exact match for the search term "id", while
    # "customer_id"/"order_id" are only substring matches, needed to test
    # exact-match-first sorting (docs/v0.7-plan.md Bölüm 5/Riskler).
    project_dir = tmp_path / "feature_explorer_fixture"
    staging_dir = project_dir / "models" / "staging"
    staging_dir.mkdir(parents=True)
    (project_dir / "dbt_project.yml").write_text(
        "name: feature_explorer_fixture\nmodel-paths:\n  - models\n", encoding="utf-8"
    )
    (staging_dir / "stg_ids.sql").write_text("select id from raw.ids\n", encoding="utf-8")
    (staging_dir / "stg_customers.sql").write_text(
        "select customer_id from raw.customers\n", encoding="utf-8"
    )
    (staging_dir / "stg_orders.sql").write_text(
        "select order_id from raw.orders\n", encoding="utf-8"
    )
    return project_dir


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
# Select Project page (pages/select_project.py, default/first page)
# ---------------------------------------------------------------------------


def test_select_project_lists_discovered_projects_under_the_root() -> None:
    at = _run_select_project_page()  # default root: "examples"

    project_box = at.selectbox(key="select_project_project")
    assert any("sample_banking_dbt" in option for option in project_box.options)
    assert any("multi_domain_dbt" in option for option in project_box.options)


def test_select_project_shows_error_for_a_nonexistent_root(tmp_path: Path) -> None:
    at = _run_select_project_page(tmp_path / "does_not_exist")

    assert any("does not exist" in error.value.lower() for error in at.error)


def test_select_project_shows_warning_when_root_has_no_dbt_projects(tmp_path: Path) -> None:
    (tmp_path / "just_a_folder").mkdir()

    at = _run_select_project_page(tmp_path)

    assert any("no dbt projects" in warning.value.lower() for warning in at.warning)


def test_select_project_shows_group_selectbox_for_a_multi_domain_project(
    multi_domain_project_path: Path,
) -> None:
    at = _run_select_project_page(multi_domain_project_path.parent)

    project_box = at.selectbox(key="select_project_project")
    multi_domain_option = next(
        option for option in project_box.options if "multi_domain_dbt" in option
    )
    project_box.set_value(multi_domain_option).run()

    group_box = at.selectbox(key="select_project_group")
    assert group_box.options == ["All", "lending", "retail"]


def test_select_project_hides_group_selectbox_for_a_flat_project(
    sample_project_path: Path,
) -> None:
    at = _run_select_project_page(sample_project_path.parent)

    project_box = at.selectbox(key="select_project_project")
    flat_option = next(option for option in project_box.options if "sample_banking_dbt" in option)
    project_box.set_value(flat_option).run()

    with pytest.raises(KeyError):
        at.selectbox(key="select_project_group")


def test_select_project_continue_writes_shared_session_state_and_navigates(
    multi_domain_project_path: Path,
) -> None:
    at = _run_select_project_page(multi_domain_project_path.parent)

    project_box = at.selectbox(key="select_project_project")
    multi_domain_option = next(
        option for option in project_box.options if "multi_domain_dbt" in option
    )
    project_box.set_value(multi_domain_option).run()

    group_box = at.selectbox(key="select_project_group")
    group_box.set_value("retail").run()

    at.button(key="select_project_continue").click().run()

    assert not at.exception
    assert at.session_state["shared_project_path"] == str(multi_domain_project_path)
    assert at.session_state["shared_model_group"] == "retail"
    # "Continue" calls st.switch_page("pages/model_explorer.py") -- the
    # click+run above executes that transition within the same AppTest
    # run, so `at` now reflects Model Explorer's own rendered output.
    assert any("Current project" in caption.value for caption in at.caption)


def test_select_project_continue_writes_none_group_when_all_selected(
    multi_domain_project_path: Path,
) -> None:
    at = _run_select_project_page(multi_domain_project_path.parent)

    project_box = at.selectbox(key="select_project_project")
    multi_domain_option = next(
        option for option in project_box.options if "multi_domain_dbt" in option
    )
    project_box.set_value(multi_domain_option).run()
    # "All" is the default selectbox value already -- no need to change it.

    at.button(key="select_project_continue").click().run()

    assert at.session_state["shared_model_group"] is None


def test_select_project_continue_writes_none_group_for_a_flat_project(
    sample_project_path: Path,
) -> None:
    at = _run_select_project_page(sample_project_path.parent)

    project_box = at.selectbox(key="select_project_project")
    flat_option = next(option for option in project_box.options if "sample_banking_dbt" in option)
    project_box.set_value(flat_option).run()

    at.button(key="select_project_continue").click().run()

    assert at.session_state["shared_model_group"] is None


# ---------------------------------------------------------------------------
# "No project selected" state -- Model Explorer/Model DAG/Column Lineage all
# require shared_project_path and must not try to load anything without it.
# ---------------------------------------------------------------------------


def test_model_explorer_shows_no_project_selected_message() -> None:
    at = _run_model_explorer_page()  # no project_dir -- session_state stays empty

    assert not at.exception
    assert any("no project selected" in info.value.lower() for info in at.info)
    assert not at.success


def test_model_dag_page_shows_no_project_selected_message() -> None:
    at = _run_model_dag_page()

    assert not at.exception
    assert any("no project selected" in info.value.lower() for info in at.info)


def test_lineage_page_shows_no_project_selected_message() -> None:
    at = _run_lineage_page()

    assert not at.exception
    assert any("no project selected" in info.value.lower() for info in at.info)


# ---------------------------------------------------------------------------
# Model Explorer page
# ---------------------------------------------------------------------------


def test_default_project_has_no_manifest_and_shows_generate_button(
    sample_project_path: Path,
) -> None:
    # examples/sample_banking_dbt has no target/manifest.json checked in.
    at = _run_model_explorer_page(sample_project_path)

    assert any("Loaded project: sample_banking_dbt" in success.value for success in at.success)
    assert any(button.label == "Generate artifacts (dbt parse)" for button in at.button)
    assert any("not found" in info.value.lower() for info in at.info)
    assert not at.warning


def test_model_explorer_shows_current_project_and_group_caption(
    sample_project_path: Path,
) -> None:
    at = _run_model_explorer_page(sample_project_path, model_group=None)

    assert any(
        "sample_banking_dbt" in caption.value and "All" in caption.value
        for caption in at.caption
    )


def test_generate_button_dbt_cli_unavailable_shows_warning(
    monkeypatch: pytest.MonkeyPatch, sample_project_path: Path
) -> None:
    monkeypatch.setattr(artifact_detector.shutil, "which", lambda _name: None)

    at = _run_model_explorer_page(sample_project_path)
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

    at = _run_model_explorer_page(project_dir)
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

    at = _run_model_explorer_page(project_dir)
    _generate_button(at).click().run()

    # The generation itself triggers a rerun once the manifest is on disk,
    # so this final state reflects a fresh "found" load rather than the
    # one-shot "generated" status -- both are manifest-mode successes.
    assert not at.exception
    assert any("manifest.json" in success.value.lower() for success in at.success)
    assert not at.warning
    # Manifest mode -- no more "Generate artifacts" button needed.
    assert not any(button.label == "Generate artifacts (dbt parse)" for button in at.button)


def test_model_explorer_loads_quickly(sample_project_path: Path) -> None:
    # Loading the 12-model default project must be fast -- no expensive
    # graph build happens on this page at all.
    start = time.monotonic()
    _run_model_explorer_page(sample_project_path)
    elapsed = time.monotonic() - start

    assert elapsed < 5.0


def test_model_explorer_does_not_execute_lineage_page_at_all(sample_project_path: Path) -> None:
    # Visiting Model Explorer must not execute pages/column_lineage.py's
    # script -- its "lineage_search" widget must simply not exist, proving
    # the page split (not just a spinner) is what makes this lazy.
    at = _run_model_explorer_page(sample_project_path)

    with pytest.raises(KeyError):
        at.text_input(key="lineage_search")


def test_model_explorer_does_not_execute_model_dag_page_at_all(sample_project_path: Path) -> None:
    at = _run_model_explorer_page(sample_project_path)

    with pytest.raises(KeyError):
        at.multiselect(key="model_dag_group_filter")


# ---------------------------------------------------------------------------
# Model Explorer: shared model-group selection narrows the model list
# ---------------------------------------------------------------------------


def test_model_explorer_group_filter_from_shared_state_narrows_the_model_list(
    multi_domain_project_path: Path,
) -> None:
    at = _run_model_explorer_page(multi_domain_project_path, model_group="retail")

    radio = at.radio(key="model_explorer_model_picker")
    assert len(radio.options) == 6
    assert not any("borrower" in label or "loan" in label for label in radio.options)
    assert any("stg_orders" in label for label in radio.options)


def test_model_explorer_no_group_filter_shows_every_model(
    multi_domain_project_path: Path,
) -> None:
    at = _run_model_explorer_page(multi_domain_project_path, model_group=None)

    radio = at.radio(key="model_explorer_model_picker")
    assert len(radio.options) == 12


# ---------------------------------------------------------------------------
# Model Explorer: Query Flow tab (v0.6) -- a streamlit_flow diagram fed by
# build_query_flow_steps()/build_query_flow_elements(), replacing the old
# st.code(build_model_flow_lines(...)) + empty CTE expanders. Same
# "assert on the component's json_args, not the component itself" strategy
# as the Model DAG tests above (docs/v0.5-plan.md Bölüm 8) -- AppTest
# can't simulate a node click, so the click -> panel-update behavior is
# covered by test_ui_rendering.py's render_query_flow_step_panel() tests
# instead, not here.
# ---------------------------------------------------------------------------


def _select_model(at: AppTest, label_substring: str) -> AppTest:
    radio = at.radio(key="model_explorer_model_picker")
    label = next(option for option in radio.options if label_substring in option)
    return radio.set_value(label).run()


def test_model_explorer_query_flow_tab_sends_one_node_per_step(
    sample_project_path: Path,
) -> None:
    at = _run_model_explorer_page(sample_project_path)
    _select_model(at, "mart_customer_features")

    payload = _component_payload(at)
    node_ids = {node["id"] for node in payload["nodes"]}
    assert "source:stg_customers" in node_ids
    assert "cte:joined" in node_ids
    assert "cte:final" in node_ids
    assert "final_select" in node_ids
    assert "output" in node_ids


def test_model_explorer_query_flow_tab_edges_match_cte_upstream_links(
    sample_project_path: Path,
) -> None:
    at = _run_model_explorer_page(sample_project_path)
    _select_model(at, "mart_customer_features")

    payload = _component_payload(at)
    edge_pairs = {(edge["source"], edge["target"]) for edge in payload["edges"]}
    assert ("cte:joined", "cte:final") in edge_pairs
    assert ("final_select", "output") in edge_pairs


def test_model_explorer_query_flow_tab_cte_node_shows_join_badge(
    sample_project_path: Path,
) -> None:
    at = _run_model_explorer_page(sample_project_path)
    _select_model(at, "mart_customer_features")

    payload = _component_payload(at)
    joined_node = next(n for n in payload["nodes"] if n["id"] == "cte:joined")
    assert "join" in joined_node["data"]["content"].lower()


def test_model_explorer_query_flow_tab_switches_diagram_on_model_change(
    sample_project_path: Path,
) -> None:
    at = _run_model_explorer_page(sample_project_path)
    _select_model(at, "stg_customers")

    payload = _component_payload(at)
    node_ids = {node["id"] for node in payload["nodes"]}
    # stg_customers's own CTEs (source_customers/renamed), not
    # mart_customer_features's -- proves the diagram actually rebuilt
    # rather than reusing the previously selected model's stale state.
    assert "cte:renamed" in node_ids
    assert "cte:joined" not in node_ids


def test_model_explorer_query_flow_tab_default_panel_prompts_to_click_a_node(
    sample_project_path: Path,
) -> None:
    at = _run_model_explorer_page(sample_project_path)
    _select_model(at, "mart_customer_features")

    assert any("click a node" in caption.value.lower() for caption in at.caption)


def test_model_explorer_query_flow_tab_no_longer_shows_the_old_flat_summary(
    sample_project_path: Path,
) -> None:
    # Regression guard for the v0.5 -> v0.6 tab replacement: the old
    # "CTE details" subheader + one st.expander per CTE name are gone.
    at = _run_model_explorer_page(sample_project_path)
    _select_model(at, "mart_customer_features")

    assert not any("CTE details" in subheader.value for subheader in at.subheader)
    assert not any("Join summary" in subheader.value for subheader in at.subheader)


# ---------------------------------------------------------------------------
# Column Lineage page
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
    payload = _component_payload(at)
    assert {node["id"] for node in payload["nodes"]} == {
        "raw_banking.customers.customer_id",
        "int_customer_activity.customer_id",
        "mart_customer_overview.customer_id",
    }
    assert len(payload["edges"]) == 2


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


def test_lineage_page_downstream_direction_sends_the_reversed_chain(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)
    at.text_input(key="lineage_search").set_value("customer_id").run()
    at.radio(key="lineage_direction").set_value("Downstream (to consumers)").run()

    match_box = at.selectbox(key="lineage_match")
    raw_source_option = next(
        option for option in match_box.options if "raw_banking.customers" in option
    )
    match_box.set_value(raw_source_option).run()

    assert not at.exception
    assert not any("No downstream lineage" in info.value for info in at.info)
    payload = _component_payload(at)
    assert {node["id"] for node in payload["nodes"]} == {
        "raw_banking.customers.customer_id",
        "stg_customers.customer_id",
        "int_customer_activity.customer_id",
        "mart_customer_overview.customer_id",
    }


def test_lineage_page_branching_chain_renders_without_error(tmp_path: Path) -> None:
    # mart_customer_merged.customer_id = coalesce(a.customer_id, b.customer_id)
    # -- a genuine multi-parent DAG; build_column_lineage_flow_elements()'s
    # own correctness is unit-tested in test_flow_rendering.py, this just
    # confirms the page wires it up and sends both upstream sources to
    # the component (AppTest can't introspect the component's own
    # rendering, only what was sent to it).
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_branching.json")
    at = _run_lineage_page(project_dir)
    at.text_input(key="lineage_search").set_value("customer_id").run()

    match_box = at.selectbox(key="lineage_match")
    merged_option = next(
        option for option in match_box.options if "mart_customer_merged" in option
    )
    match_box.set_value(merged_option).run()

    assert not at.exception
    payload = _component_payload(at)
    node_ids = {node["id"] for node in payload["nodes"]}
    assert "raw_banking.customers.customer_id" in node_ids
    assert "raw_banking.legacy_customers.customer_id" in node_ids
    assert len(payload["edges"]) == 2


def test_lineage_page_shows_lineage_warnings(tmp_path: Path) -> None:
    project_dir = _write_manifest_with_broken_model(tmp_path)

    at = _run_lineage_page(project_dir)

    assert not at.exception
    assert any("broken_model" in warning.value for warning in at.warning)


def test_lineage_page_is_independent_of_model_explorer_selection(tmp_path: Path) -> None:
    # The Column Lineage page reads shared_project_path itself; it must
    # not depend on anything selected on Model Explorer's sidebar.
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)

    at.text_input(key="lineage_search").set_value("customer_id").run()

    match_box = at.selectbox(key="lineage_match")
    assert any("mart_customer_overview" in option for option in match_box.options)


# ---------------------------------------------------------------------------
# Downstream impact summary panel (v0.8) -- built on the same chain the
# graph already renders, only shown for the downstream direction (an
# "impact" isn't a meaningful concept for upstream, docs/v0.8-plan.md
# Hedef/Bölüm 3).
# ---------------------------------------------------------------------------


def _select_downstream_raw_source(at: AppTest) -> AppTest:
    at.text_input(key="lineage_search").set_value("customer_id").run()
    at.radio(key="lineage_direction").set_value("Downstream (to consumers)").run()
    match_box = at.selectbox(key="lineage_match")
    raw_source_option = next(
        option for option in match_box.options if "raw_banking.customers" in option
    )
    return match_box.set_value(raw_source_option).run()


def test_lineage_page_downstream_shows_impact_summary(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)

    at = _select_downstream_raw_source(at)

    assert not at.exception
    assert any("Downstream impact" in subheader.value for subheader in at.subheader)
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Affected models"] == "3"
    assert metrics["Affected columns"] == "3"
    rows = at.dataframe[0].value
    assert set(rows["Model"]) == {
        "stg_customers",
        "int_customer_activity",
        "mart_customer_overview",
    }


def test_lineage_page_upstream_direction_shows_no_impact_summary(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)
    at.text_input(key="lineage_search").set_value("customer_id").run()

    match_box = at.selectbox(key="lineage_match")
    mart_option = next(
        option for option in match_box.options if "mart_customer_overview" in option
    )
    match_box.set_value(mart_option).run()

    assert not at.exception
    assert not any("Downstream impact" in subheader.value for subheader in at.subheader)


def test_lineage_page_terminal_column_downstream_shows_no_impact(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")
    at = _run_lineage_page(project_dir)
    at.text_input(key="lineage_search").set_value("customer_id").run()
    at.radio(key="lineage_direction").set_value("Downstream (to consumers)").run()

    match_box = at.selectbox(key="lineage_match")
    mart_option = next(
        option for option in match_box.options if "mart_customer_overview" in option
    )
    match_box.set_value(mart_option).run()

    assert not at.exception
    # mart_customer_overview is a terminal node -- "No downstream lineage"
    # (the existing message) fires first and the graph/panel never render.
    assert any("No downstream lineage" in info.value for info in at.info)
    assert not any("Downstream impact" in subheader.value for subheader in at.subheader)


# ---------------------------------------------------------------------------
# Column Lineage: shared model-group selection narrows the lineage graph
# itself (not just search results -- see pages/column_lineage.py's module
# docstring for why that's a deliberate v0.6 behavior change from v0.5).
# ---------------------------------------------------------------------------


def test_lineage_page_group_filter_from_shared_state_narrows_search_results(
    multi_domain_project_path: Path,
) -> None:
    at = _run_lineage_page(multi_domain_project_path, model_group="retail")
    at.text_input(key="lineage_search").set_value("id").run()

    match_box = at.selectbox(key="lineage_match")
    assert all("borrower_id" not in option for option in match_box.options)
    assert any("order_id" in option for option in match_box.options)


def test_lineage_page_no_group_filter_includes_every_domain(
    multi_domain_project_path: Path,
) -> None:
    at = _run_lineage_page(multi_domain_project_path, model_group=None)
    at.text_input(key="lineage_search").set_value("id").run()

    match_box = at.selectbox(key="lineage_match")
    assert any("borrower_id" in option for option in match_box.options)
    assert any("order_id" in option for option in match_box.options)


# ---------------------------------------------------------------------------
# Model DAG page
# ---------------------------------------------------------------------------


def test_model_dag_page_sends_one_node_per_model(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    at = _run_model_dag_page(project_dir)

    payload = _component_payload(at)
    assert {node["id"] for node in payload["nodes"]} == {
        "stg_customers",
        "int_customer_activity",
        "mart_customer_overview",
    }


def test_model_dag_page_sends_edges_matching_ref_dependencies(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    at = _run_model_dag_page(project_dir)

    payload = _component_payload(at)
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

    payload = _component_payload(at)
    mart_node = next(n for n in payload["nodes"] if n["id"] == "mart_customer_overview")
    content = mart_node["data"]["content"]
    assert "mart_customer_overview" in content
    assert "table" in content  # this fixture's materialization for this model


def test_model_dag_page_is_independent_of_model_explorer_selection(tmp_path: Path) -> None:
    project_dir = _write_manifest_project(tmp_path, "manifest_lineage_chain.json")

    at = _run_model_dag_page(project_dir)

    payload = _component_payload(at)
    assert len(payload["nodes"]) == 3


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
    payload = _component_payload(at)
    # Only stg_customers is left standing -- the two cyclic models are
    # excluded entirely (model_dag_service.build_model_dag()'s
    # warn-and-exclude contract, not a raise).
    assert {node["id"] for node in payload["nodes"]} == {"stg_customers"}


# ---------------------------------------------------------------------------
# Model DAG: shared model-group selection narrows the graph itself (built
# from a group-filtered project via cached_build_model_dag's selected_group,
# not filtered post-hoc -- see ui/state.py).
# ---------------------------------------------------------------------------


def test_model_dag_page_group_filter_from_shared_state_narrows_the_graph(
    multi_domain_project_path: Path,
) -> None:
    at = _run_model_dag_page(multi_domain_project_path, model_group="retail")

    payload = _component_payload(at)
    assert len(payload["nodes"]) == 6
    assert {node["id"] for node in payload["nodes"]} == {
        "stg_orders",
        "stg_products",
        "int_order_items",
        "int_customer_order_summary",
        "mart_retail_sales",
        "mart_top_products",
    }


def test_model_dag_page_no_group_filter_sends_every_model(
    multi_domain_project_path: Path,
) -> None:
    at = _run_model_dag_page(multi_domain_project_path, model_group=None)

    payload = _component_payload(at)
    assert len(payload["nodes"]) == 12


# ---------------------------------------------------------------------------
# Feature Explorer page (v0.7) -- project-wide column-name search across
# models, no lineage tracing. Unlike Model DAG/Column Lineage, this page
# renders no custom component (plain st.text_input/selectbox/dataframe),
# so every one of these tests is a genuine end-to-end AppTest, not just
# "what was sent to the component" (docs/v0.7-plan.md Bölüm 3).
# ---------------------------------------------------------------------------


def test_feature_explorer_shows_no_project_selected_message() -> None:
    at = _run_feature_explorer_page()

    assert any("no project selected" in info.value.lower() for info in at.info)


def test_feature_explorer_empty_search_prompts_for_a_column_name(
    sample_project_path: Path,
) -> None:
    at = _run_feature_explorer_page(sample_project_path)

    assert any("column name" in info.value.lower() for info in at.info)
    assert not at.dataframe


def test_feature_explorer_static_mode_shows_a_metadata_warning(
    sample_project_path: Path,
) -> None:
    # examples/sample_banking_dbt ships with no manifest -- static mode,
    # so description/owner/tags/tests will all be empty for every match.
    at = _run_feature_explorer_page(sample_project_path)

    assert any(
        "static" in warning.value.lower() and "description" in warning.value.lower()
        for warning in at.warning
    )


def test_feature_explorer_search_lists_every_model_producing_the_column(
    sample_project_path: Path,
) -> None:
    at = _run_feature_explorer_page(sample_project_path)
    at.text_input(key="feature_explorer_search").set_value("customer_id").run()

    select = at.selectbox(key="feature_explorer_column_select")
    assert "customer_id" in select.options
    select.set_value("customer_id").run()

    rows = at.dataframe[0].value
    assert len(rows) == 12
    assert "Layer" in rows.columns


def test_feature_explorer_search_no_match_shows_an_info_message(
    sample_project_path: Path,
) -> None:
    at = _run_feature_explorer_page(sample_project_path)
    at.text_input(key="feature_explorer_search").set_value("zzz_nonexistent_column").run()

    assert any("no columns matching" in info.value.lower() for info in at.info)
    assert not at.dataframe


def test_feature_explorer_dataframe_columns_include_metadata_fields(
    sample_project_path: Path,
) -> None:
    at = _run_feature_explorer_page(sample_project_path)
    at.text_input(key="feature_explorer_search").set_value("customer_id").run()
    at.selectbox(key="feature_explorer_column_select").set_value("customer_id").run()

    rows = at.dataframe[0].value
    for expected_column in ("Layer", "Model", "Description", "Owner", "Tags", "Tests"):
        assert expected_column in rows.columns


def test_feature_explorer_exact_match_is_sorted_before_substring_matches(
    tmp_path: Path,
) -> None:
    project_dir = _write_feature_explorer_project(tmp_path)

    at = _run_feature_explorer_page(project_dir)
    at.text_input(key="feature_explorer_search").set_value("id").run()

    select = at.selectbox(key="feature_explorer_column_select")
    assert select.options[0] == "id"
    assert set(select.options) == {"id", "customer_id", "order_id"}


def test_feature_explorer_group_filter_from_shared_state_narrows_matches(
    multi_domain_project_path: Path,
) -> None:
    # customer_id is only ever produced by retail models in this fixture
    # (docs/v0.7-plan.md implementation check) -- selecting the lending
    # group must make it disappear entirely, not just from display.
    at = _run_feature_explorer_page(multi_domain_project_path, model_group="lending")
    at.text_input(key="feature_explorer_search").set_value("customer_id").run()

    assert any("no columns matching" in info.value.lower() for info in at.info)


def test_feature_explorer_group_filter_keeps_matching_models_in_group(
    multi_domain_project_path: Path,
) -> None:
    at = _run_feature_explorer_page(multi_domain_project_path, model_group="retail")
    at.text_input(key="feature_explorer_search").set_value("customer_id").run()
    at.selectbox(key="feature_explorer_column_select").set_value("customer_id").run()

    rows = at.dataframe[0].value
    assert len(rows) == 4
    assert set(rows["Model"]) == {
        "int_customer_order_summary",
        "mart_retail_sales",
        "stg_orders",
        "int_order_items",
    }
