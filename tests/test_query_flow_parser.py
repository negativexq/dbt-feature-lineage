from pathlib import Path

from dbt_feature_lineage.loaders.project_loader import load_dbt_project
from dbt_feature_lineage.parsers.query_flow_parser import (
    analyze_query_flow,
    build_query_flow_steps,
)
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


# ---------------------------------------------------------------------------
# build_query_flow_steps() -- per-CTE flow steps for the v0.6 Query Flow
# diagram (docs/v0.6-plan.md Bölüm 3/8). Does NOT touch DbtModelAnalysis or
# analyze_query_flow()'s own behavior -- see test_direct_query_flow_fallback_warning
# above, still passing, and the "existing behavior unchanged" tests below.
# ---------------------------------------------------------------------------


def _step(steps, step_id):
    return next(s for s in steps if s.step_id == step_id)


def test_build_query_flow_steps_returns_empty_list_on_parse_failure() -> None:
    assert build_query_flow_steps("select from") == []


def test_build_query_flow_steps_models_a_single_source_with_no_ctes() -> None:
    sql = "select customer_id, name from {{ ref('stg_customers') }}"

    steps = build_query_flow_steps(sql)

    assert [s.step_id for s in steps] == ["source:stg_customers", "final_select", "output"]
    source_step = _step(steps, "source:stg_customers")
    assert source_step.step_type == "source"
    assert source_step.name == "stg_customers"
    assert source_step.upstream_step_ids == []

    final_select = _step(steps, "final_select")
    assert final_select.step_type == "final_select"
    assert final_select.upstream_step_ids == ["source:stg_customers"]

    output = _step(steps, "output")
    assert output.step_type == "output"
    assert output.upstream_step_ids == ["final_select"]


def test_build_query_flow_steps_source_call_produces_schema_qualified_name() -> None:
    sql = "select id from {{ source('raw_banking', 'customers') }}"

    steps = build_query_flow_steps(sql)

    source_step = _step(steps, "source:raw_banking.customers")
    assert source_step.name == "raw_banking.customers"


def test_build_query_flow_steps_cte_upstream_is_the_previous_cte() -> None:
    sql = """
    with a as (
        select id from {{ ref('stg_x') }}
    ),
    b as (
        select id from a
    )
    select * from b
    """

    steps = build_query_flow_steps(sql)

    assert _step(steps, "cte:a").upstream_step_ids == ["source:stg_x"]
    assert _step(steps, "cte:b").upstream_step_ids == ["cte:a"]
    assert _step(steps, "final_select").upstream_step_ids == ["cte:b"]
    assert _step(steps, "output").upstream_step_ids == ["final_select"]


def test_build_query_flow_steps_cte_own_join_is_isolated_from_other_steps() -> None:
    sql = """
    with joined as (
        select a.id, b.value
        from {{ ref('stg_a') }} as a
        left join {{ ref('stg_b') }} as b on a.id = b.id
    )
    select * from joined
    """

    steps = build_query_flow_steps(sql)

    assert {s.step_id for s in steps if s.step_type == "source"} == {
        "source:stg_a",
        "source:stg_b",
    }
    joined_step = _step(steps, "cte:joined")
    assert joined_step.join_types == ["LEFT"]
    assert set(joined_step.upstream_step_ids) == {"source:stg_a", "source:stg_b"}

    final_select = _step(steps, "final_select")
    assert final_select.join_types == []
    assert final_select.upstream_step_ids == ["cte:joined"]


def test_build_query_flow_steps_cte_own_where_and_group_by_are_isolated() -> None:
    sql = """
    with agg as (
        select customer_id, sum(amount) as total
        from {{ ref('stg_transactions') }}
        where amount > 0
        group by customer_id
    )
    select * from agg
    """

    steps = build_query_flow_steps(sql)

    agg_step = _step(steps, "cte:agg")
    assert agg_step.has_where_clause is True
    assert agg_step.group_by_columns == ["customer_id"]
    assert agg_step.aggregate_functions == ["SUM"]

    # The bare "select * from agg" outer select has no WHERE/GROUP BY of its
    # own -- must not inherit agg's, which recursive find_all() over the
    # whole (WITH-attached) expression would otherwise bleed in.
    final_select = _step(steps, "final_select")
    assert final_select.has_where_clause is False
    assert final_select.group_by_columns == []
    assert final_select.aggregate_functions == []


def test_build_query_flow_steps_final_select_output_resolves_star_through_ctes() -> None:
    sql = """
    with final as (
        select customer_id, sum(amount) as total_amount
        from {{ ref('stg_transactions') }}
        group by customer_id
    )
    select * from final
    """

    steps = build_query_flow_steps(sql)

    final_select = _step(steps, "final_select")
    output_names = {c.output_name for c in final_select.output_columns}
    assert output_names == {"customer_id", "total_amount"}

    # cte:final's own output columns (not star-resolved, they're its actual
    # projections) should match too.
    cte_final = _step(steps, "cte:final")
    assert {c.output_name for c in cte_final.output_columns} == {"customer_id", "total_amount"}


def test_build_query_flow_steps_output_step_mirrors_final_select() -> None:
    sql = "select customer_id from {{ ref('stg_customers') }}"

    steps = build_query_flow_steps(sql, model_name="mart_x")

    final_select = _step(steps, "final_select")
    output = _step(steps, "output")
    assert output.name == "mart_x"
    assert output.output_columns == final_select.output_columns


def test_build_query_flow_steps_on_mart_customer_features(sample_project_path: Path) -> None:
    raw_sql = _raw_sql_for_model(sample_project_path, "mart_customer_features")

    steps = build_query_flow_steps(raw_sql, model_name="mart_customer_features")

    source_steps = [s for s in steps if s.step_type == "source"]
    cte_steps = [s for s in steps if s.step_type == "cte"]
    assert {s.name for s in source_steps} == {
        "stg_customers",
        "int_customer_activity",
        "int_customer_spend_metrics",
        "int_customer_credit_profile",
        "int_customer_daily_balance",
        "stg_accounts",
        "stg_loans",
        "stg_transactions",
    }
    assert len(cte_steps) == 10

    joined_step = _step(steps, "cte:joined")
    assert set(joined_step.upstream_step_ids) == {
        "cte:customers",
        "cte:activity",
        "cte:spend",
        "cte:credit",
        "cte:latest_balance",
        "cte:account_rollup",
        "cte:loan_rollup",
        "cte:recent_transaction_profile",
    }
    assert _step(steps, "cte:final").upstream_step_ids == ["cte:joined"]
    assert _step(steps, "final_select").upstream_step_ids == ["cte:final"]

    output = _step(steps, "output")
    assert output.name == "mart_customer_features"
    output_names = {c.output_name for c in output.output_columns}
    assert "customer_age" in output_names
    assert "risk_segment" in output_names
