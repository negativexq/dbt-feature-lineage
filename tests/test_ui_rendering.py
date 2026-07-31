from dbt_feature_lineage.domain.models import DbtModel, DbtModelAnalysis, DbtOutputColumn
from dbt_feature_lineage.ui import (
    build_model_flow_lines,
    filter_models,
    filter_output_columns,
    group_models_by_layer,
    summarize_model_analysis,
)


def test_group_models_by_layer() -> None:
    models = [
        DbtModel(
            name="stg_customers",
            file_path="/tmp/stg_customers.sql",
            relative_path="models/staging/stg_customers.sql",
            layer="staging",
            raw_sql="select 1",
        ),
        DbtModel(
            name="mart_customer_features",
            file_path="/tmp/mart_customer_features.sql",
            relative_path="models/marts/mart_customer_features.sql",
            layer="marts",
            raw_sql="select 1",
        ),
    ]

    grouped = group_models_by_layer(models)

    assert [model.name for model in grouped["staging"]] == ["stg_customers"]
    assert [model.name for model in grouped["marts"]] == ["mart_customer_features"]


def test_filter_models() -> None:
    models = [
        DbtModel(
            name="stg_customers",
            file_path="/tmp/stg_customers.sql",
            relative_path="models/staging/stg_customers.sql",
            layer="staging",
            raw_sql="select 1",
        ),
        DbtModel(
            name="mart_customer_features",
            file_path="/tmp/mart_customer_features.sql",
            relative_path="models/marts/mart_customer_features.sql",
            layer="marts",
            raw_sql="select 1",
        ),
    ]

    filtered = filter_models(models, "customer")

    assert [model.name for model in filtered] == ["stg_customers", "mart_customer_features"]


def test_filter_output_columns() -> None:
    columns = [
        DbtOutputColumn(
            output_name="customer_id",
            original_sql_expression="j.customer_id",
            transformation_type="direct",
            referenced_input_columns=["j.customer_id"],
        ),
        DbtOutputColumn(
            output_name="risk_segment",
            original_sql_expression="case when ... end",
            transformation_type="conditional",
            referenced_input_columns=["j.credit_utilization_ratio"],
        ),
    ]

    filtered = filter_output_columns(columns, "risk", ["conditional"])

    assert [column.output_name for column in filtered] == ["risk_segment"]


def test_build_model_flow_lines() -> None:
    analysis = DbtModelAnalysis(
        model_name="mart_customer_features",
        file_path="/tmp/mart_customer_features.sql",
        relative_path="models/marts/mart_customer_features.sql",
        layer="marts",
        raw_sql="select 1",
        cte_names=["joined", "final"],
        join_count=2,
        join_types=["LEFT", "INNER"],
        has_where_clause=True,
        group_by_columns=["customer_id"],
    )

    lines = build_model_flow_lines(analysis)

    assert "cte: joined" in lines
    assert "filters: where clause present" in lines
    assert "final select" in lines


def test_summarize_model_analysis() -> None:
    analysis = DbtModelAnalysis(
        model_name="mart_customer_features",
        file_path="/tmp/mart_customer_features.sql",
        relative_path="models/marts/mart_customer_features.sql",
        layer="marts",
        raw_sql="select 1",
        cte_names=["joined", "final"],
        join_count=2,
        output_columns=[
            DbtOutputColumn(
                output_name="customer_id",
                original_sql_expression="customer_id",
                transformation_type="direct",
            )
        ],
    )

    summary = summarize_model_analysis(analysis)

    assert summary["cte_count"] == 2
    assert summary["join_count"] == 2
    assert summary["output_column_count"] == 1
