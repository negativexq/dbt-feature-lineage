"""Tests for loaders/project_discovery.py -- discover_dbt_projects().

Powers pages/select_project.py's project picker: recursively finds
directories containing dbt_project.yml under a root, with a depth limit
and a few directory-skipping rules to keep the scan fast and the result
list free of noise (installed packages, build output).
"""

from __future__ import annotations

from pathlib import Path

from dbt_feature_lineage.loaders.project_discovery import discover_dbt_projects

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_project(root: Path, relative_dir: str, name: str | None = None) -> Path:
    project_dir = root / relative_dir
    project_dir.mkdir(parents=True, exist_ok=True)
    content = f"name: {name}\n" if name else "config-version: 2\n"
    (project_dir / "dbt_project.yml").write_text(content, encoding="utf-8")
    return project_dir


def test_discover_dbt_projects_finds_a_project_at_the_root(tmp_path: Path) -> None:
    _write_project(tmp_path, ".", name="root_project")

    found = discover_dbt_projects(tmp_path)

    assert len(found) == 1
    assert found[0].name == "root_project"
    assert found[0].path == str(tmp_path)


def test_discover_dbt_projects_finds_projects_at_various_depths(tmp_path: Path) -> None:
    _write_project(tmp_path, "a", name="project_a")
    _write_project(tmp_path, "b/c", name="project_c")

    found = discover_dbt_projects(tmp_path)

    assert {p.name for p in found} == {"project_a", "project_c"}
    assert {p.relative_path for p in found} == {"a", "b/c"}


def test_discover_dbt_projects_stops_at_max_depth(tmp_path: Path) -> None:
    # 5 levels deep: tmp_path/l1/l2/l3/l4/l5/dbt_project.yml
    _write_project(tmp_path, "l1/l2/l3/l4/l5", name="too_deep")

    found = discover_dbt_projects(tmp_path, max_depth=4)

    assert found == []


def test_discover_dbt_projects_within_max_depth_is_found(tmp_path: Path) -> None:
    _write_project(tmp_path, "l1/l2/l3/l4", name="just_shallow_enough")

    found = discover_dbt_projects(tmp_path, max_depth=4)

    assert [p.name for p in found] == ["just_shallow_enough"]


def test_discover_dbt_projects_does_not_recurse_into_a_found_project(tmp_path: Path) -> None:
    # A project's own target/ directory can contain package-generated
    # dbt_project.yml-like state, or a project nested even deeper inside
    # a monorepo -- neither should be listed as a separate project once
    # its parent has already been identified as one.
    outer = _write_project(tmp_path, "outer", name="outer_project")
    _write_project(outer, "target/nested", name="should_not_be_found")

    found = discover_dbt_projects(tmp_path)

    assert [p.name for p in found] == ["outer_project"]


def test_discover_dbt_projects_skips_hidden_directories(tmp_path: Path) -> None:
    _write_project(tmp_path, ".hidden/project", name="in_a_hidden_dir")
    _write_project(tmp_path, "visible", name="visible_project")

    found = discover_dbt_projects(tmp_path)

    assert [p.name for p in found] == ["visible_project"]


def test_discover_dbt_projects_skips_known_noisy_directory_names(tmp_path: Path) -> None:
    _write_project(tmp_path, "dbt_packages/some_package", name="a_dependency")
    _write_project(tmp_path, "node_modules/whatever", name="js_noise")
    _write_project(tmp_path, "real", name="real_project")

    found = discover_dbt_projects(tmp_path)

    assert [p.name for p in found] == ["real_project"]


def test_discover_dbt_projects_uses_the_name_from_dbt_project_yml(tmp_path: Path) -> None:
    project_dir = tmp_path / "some_folder"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("name: actual_project_name\n", encoding="utf-8")

    found = discover_dbt_projects(tmp_path)

    assert found[0].name == "actual_project_name"


def test_discover_dbt_projects_falls_back_to_directory_name_when_yaml_has_no_name(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "fallback_dir_name"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("config-version: 2\n", encoding="utf-8")

    found = discover_dbt_projects(tmp_path)

    assert found[0].name == "fallback_dir_name"


def test_discover_dbt_projects_falls_back_to_directory_name_on_malformed_yaml(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "malformed_dir"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("name: [unclosed\n", encoding="utf-8")

    found = discover_dbt_projects(tmp_path)

    assert found[0].name == "malformed_dir"


def test_discover_dbt_projects_sorted_by_relative_path(tmp_path: Path) -> None:
    _write_project(tmp_path, "zebra", name="z")
    _write_project(tmp_path, "alpha", name="a")

    found = discover_dbt_projects(tmp_path)

    assert [p.relative_path for p in found] == ["alpha", "zebra"]


def test_discover_dbt_projects_no_projects_returns_empty_list(tmp_path: Path) -> None:
    (tmp_path / "just_a_folder").mkdir()

    assert discover_dbt_projects(tmp_path) == []


def test_discover_dbt_projects_against_the_real_examples_directory() -> None:
    # Integration check against this repo's own fixture projects, not
    # just synthetic tmp_path trees.
    found = discover_dbt_projects(REPO_ROOT / "examples")

    names = {p.name for p in found}
    assert "sample_banking_dbt" in names
    assert "multi_domain_dbt" in names
