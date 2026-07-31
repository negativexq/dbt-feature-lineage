from pathlib import Path

import pytest

from dbt_feature_lineage.loaders.project_loader import load_dbt_project


def test_invalid_project_path() -> None:
    with pytest.raises(FileNotFoundError):
        load_dbt_project("/path/does/not/exist")


def test_missing_dbt_project_file(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)

    with pytest.raises(FileNotFoundError):
        load_dbt_project(tmp_path)


def test_complete_sample_project_model_count(sample_project_path: Path) -> None:
    project = load_dbt_project(sample_project_path)

    assert project.name == "sample_banking_dbt"
    assert len(project.models) == 12
    assert len(project.sources) == 1
    assert len(project.sources[0].tables) == 4

