from pathlib import Path

import pytest


@pytest.fixture
def sample_project_path() -> Path:
    return Path(__file__).resolve().parent.parent / "examples" / "sample_banking_dbt"


@pytest.fixture
def multi_domain_project_path() -> Path:
    return Path(__file__).resolve().parent.parent / "examples" / "multi_domain_dbt"

