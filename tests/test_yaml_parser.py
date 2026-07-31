from pathlib import Path

from dbt_feature_lineage.parsers.yaml_parser import parse_source_definitions


def test_source_yaml_parsing(sample_project_path: Path) -> None:
    yaml_files = [sample_project_path / "models" / "sources.yml"]

    sources = parse_source_definitions(yaml_files)

    assert len(sources) == 1
    assert sources[0].name == "core_banking"
    assert [table.name for table in sources[0].tables] == [
        "customers",
        "accounts",
        "transactions",
        "loans",
    ]

