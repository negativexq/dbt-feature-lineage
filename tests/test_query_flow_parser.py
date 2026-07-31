from pathlib import Path

from dbt_feature_lineage.loaders.project_loader import load_dbt_project
from dbt_feature_lineage.parsers.query_flow_parser import analyze_query_flow
from dbt_feature_lineage.services.model_analysis_service import inspect_model


def _raw_sql_for_model(sample_project_path: Path, model_name: str) -> str:
    project = load_dbt_project(sample_project_path)
    for model in project.models:
        if model.name == model_name:
            return model.raw_sql
    raise AssertionError(f"Model not found in test fixture: {model_name}")


def test_staging_model_inspection(sample_project_path: Path) -> None:
    analysis = inspect_model(sample_project_path, "stg_customers")

    assert analysis.layer == "staging"
    assert [dependency.target_name for dependency in analysis.source_dependencies] == ["customers"]
    assert analysis.output_columns
    assert any(column.output_name == "customer_full_name" for column in analysis.output_columns)


def test_intermediate_aggregation_model(sample_project_path: Path) -> None:
    analysis = inspect_model(sample_project_path, "int_customer_spend_metrics")

    assert analysis.layer == "intermediate"
    assert "SUM" in analysis.aggregate_functions
    assert "AVG" in analysis.aggregate_functions
    assert "MAX" in analysis.aggregate_functions
    assert analysis.has_where_clause is False


def test_model_with_multiple_ctes(sample_project_path: Path) -> None:
    analysis = inspect_model(sample_project_path, "mart_customer_features")

    assert len(analysis.cte_names) >= 8
    assert analysis.join_count >= 4
    assert "LEFT" in " ".join(analysis.join_types)


def test_model_with_window_functions(sample_project_path: Path) -> None:
    analysis = inspect_model(sample_project_path, "int_customer_daily_balance")

    assert analysis.window_functions
    assert any("ROW_NUMBER" in window.upper() for window in analysis.window_functions)


def test_model_with_case_expressions(sample_project_path: Path) -> None:
    analysis = inspect_model(sample_project_path, "mart_customer_features")

    conditional_columns = [
        column for column in analysis.output_columns if column.transformation_type == "conditional"
    ]
    assert any(column.output_name == "risk_segment" for column in conditional_columns)
    assert any(column.output_name == "high_value_customer_flag" for column in conditional_columns)


def test_output_aliases(sample_project_path: Path) -> None:
    analysis = inspect_model(sample_project_path, "mart_customer_features")

    output_names = {column.output_name for column in analysis.output_columns}
    assert "customer_age" in output_names
    assert "credit_utilization_ratio" in output_names


def test_direct_query_flow_fallback_warning() -> None:
    analysis = analyze_query_flow("select from")

    assert analysis.parsing_warnings
    assert analysis.raw_sql == "select from"
