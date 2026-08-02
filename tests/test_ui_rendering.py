from dbt_feature_lineage.domain.models import (
    DbtModel,
    DbtModelAnalysis,
    DbtOutputColumn,
    DbtProject,
    QueryFlowStep,
)
from dbt_feature_lineage.ui import (
    detect_model_groups,
    filter_models,
    filter_models_by_group,
    filter_output_columns,
    group_models_by_layer,
    render_node_detail_panel,
    render_query_flow_step_panel,
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


# ---------------------------------------------------------------------------
# render_node_detail_panel() -- Model DAG's right-hand panel content, a
# plain function returning label -> value (docs/v0.5-plan.md Bölüm 8: this
# is the only way "click a node -> panel updates" logic gets tested at
# all, since AppTest can't simulate a streamlit_flow node click).
# ---------------------------------------------------------------------------


def _project_with_model(model: DbtModel) -> DbtProject:
    return DbtProject(
        name="proj",
        project_path="/tmp/proj",
        dbt_project_file="/tmp/proj/dbt_project.yml",
        model_paths=["models"],
        models=[model],
        source="manifest",
    )


def test_render_node_detail_panel_includes_every_populated_field() -> None:
    model = DbtModel(
        name="mart_customers",
        file_path="/tmp/mart_customers.sql",
        relative_path="models/marts/mart_customers.sql",
        layer="marts",
        raw_sql="select 1",
        materialization="table",
        description="Customer mart.",
        tags=["finance", "daily"],
        owner="finance-team",
        test_count=2,
    )
    project = _project_with_model(model)

    panel = render_node_detail_panel(project, "mart_customers")

    assert panel == {
        "Model": "mart_customers",
        "Layer": "marts",
        "Materialization": "table",
        "Description": "Customer mart.",
        "Tags": "finance, daily",
        "Owner": "finance-team",
        "Tests": "2",
    }


def test_render_node_detail_panel_omits_unset_fields_without_erroring() -> None:
    # Static mode (or a manifest that never documented this model) leaves
    # materialization/description/tags/owner/test_count at their defaults
    # -- the panel must quietly leave those rows out, not raise or show a
    # blank/placeholder value for each.
    model = DbtModel(
        name="stg_customers",
        file_path="/tmp/stg_customers.sql",
        relative_path="models/staging/stg_customers.sql",
        layer="staging",
        raw_sql="select 1",
    )
    project = _project_with_model(model)

    panel = render_node_detail_panel(project, "stg_customers")

    assert panel == {"Model": "stg_customers", "Layer": "staging"}


def test_render_node_detail_panel_zero_test_count_is_treated_as_unset() -> None:
    model = DbtModel(
        name="stg_customers",
        file_path="/tmp/stg_customers.sql",
        relative_path="models/staging/stg_customers.sql",
        layer="staging",
        raw_sql="select 1",
        test_count=0,
    )
    project = _project_with_model(model)

    panel = render_node_detail_panel(project, "stg_customers")

    assert "Tests" not in panel


def test_render_node_detail_panel_unknown_model_returns_empty_dict() -> None:
    project = _project_with_model(
        DbtModel(
            name="stg_customers",
            file_path="/tmp/stg_customers.sql",
            relative_path="models/staging/stg_customers.sql",
            layer="staging",
            raw_sql="select 1",
        )
    )

    panel = render_node_detail_panel(project, "does_not_exist")

    assert panel == {}


# ---------------------------------------------------------------------------
# detect_model_groups() / filter_models_by_group() / filter_column_nodes_by_group()
# -- the Model Group sidebar filter, shared by all three pages.
# ---------------------------------------------------------------------------


def _model(name: str, model_group: str | None = None) -> DbtModel:
    return DbtModel(
        name=name,
        file_path=f"/tmp/{name}.sql",
        relative_path=f"models/{name}.sql",
        layer="unknown",
        raw_sql="select 1",
        model_group=model_group,
    )


def test_detect_model_groups_returns_sorted_distinct_groups() -> None:
    models = [
        _model("stg_orders", "retail"),
        _model("stg_borrowers", "lending"),
        _model("mart_top_products", "retail"),
    ]

    assert detect_model_groups(models) == ["lending", "retail"]


def test_detect_model_groups_excludes_none() -> None:
    models = [_model("stg_orders", "retail"), _model("stg_customers", None)]

    assert detect_model_groups(models) == ["retail"]


def test_detect_model_groups_empty_for_a_flat_layout() -> None:
    # examples/sample_banking_dbt style -- no model has a model_group at all.
    models = [_model("stg_customers"), _model("mart_customer_features")]

    assert detect_model_groups(models) == []


def test_filter_models_by_group_keeps_only_selected_groups() -> None:
    models = [
        _model("stg_orders", "retail"),
        _model("stg_borrowers", "lending"),
        _model("mart_top_products", "retail"),
    ]

    filtered = filter_models_by_group(models, ["retail"])

    assert {model.name for model in filtered} == {"stg_orders", "mart_top_products"}


def test_filter_models_by_group_empty_selection_returns_all() -> None:
    models = [_model("stg_orders", "retail"), _model("stg_borrowers", "lending")]

    assert filter_models_by_group(models, []) == models


def test_filter_models_by_group_excludes_none_group_when_filter_active() -> None:
    models = [_model("stg_orders", "retail"), _model("stg_untagged", None)]

    filtered = filter_models_by_group(models, ["retail"])

    assert {model.name for model in filtered} == {"stg_orders"}


def test_filter_models_by_group_supports_multiple_selected_groups() -> None:
    models = [
        _model("stg_orders", "retail"),
        _model("stg_borrowers", "lending"),
        _model("stg_other", "shipping"),
    ]

    filtered = filter_models_by_group(models, ["retail", "lending"])

    assert {model.name for model in filtered} == {"stg_orders", "stg_borrowers"}


# ---------------------------------------------------------------------------
# render_query_flow_step_panel() -- v0.6's Query Flow tab detail panel,
# same pattern as render_node_detail_panel() above: a plain function
# (AppTest can't simulate a streamlit_flow node click, docs/v0.5-plan.md
# Bölüm 8 / docs/v0.6-plan.md Bölüm 5), boş alanlar dahil edilmez.
# ---------------------------------------------------------------------------


def test_render_query_flow_step_panel_includes_every_populated_field() -> None:
    step = QueryFlowStep(
        step_id="cte:joined",
        step_type="cte",
        name="joined",
        upstream_step_ids=["cte:customers", "cte:activity"],
        join_types=["LEFT"],
        has_where_clause=True,
        group_by_columns=["customer_id"],
        aggregate_functions=["SUM"],
        window_functions=["ROW_NUMBER() OVER (...)"],
        output_columns=[
            DbtOutputColumn(
                output_name="customer_id",
                original_sql_expression="c.customer_id",
                transformation_type="direct",
            )
        ],
    )

    panel = render_query_flow_step_panel(step)

    assert panel == {
        "Step": "joined",
        "Type": "cte",
        "Upstream": "cte:customers, cte:activity",
        "Joins": "LEFT",
        "Filters": "where clause present",
        "Group by": "customer_id",
        "Aggregations": "SUM",
        "Window functions": "ROW_NUMBER() OVER (...)",
        "Output columns": "customer_id",
    }


def test_render_query_flow_step_panel_omits_unset_fields_without_erroring() -> None:
    # A source step -- no join/filter/aggregation/output of its own.
    step = QueryFlowStep(step_id="source:stg_customers", step_type="source", name="stg_customers")

    panel = render_query_flow_step_panel(step)

    assert panel == {"Step": "stg_customers", "Type": "source"}


def test_render_query_flow_step_panel_no_where_clause_omits_filters_row() -> None:
    step = QueryFlowStep(step_id="cte:a", step_type="cte", name="a", has_where_clause=False)

    panel = render_query_flow_step_panel(step)

    assert "Filters" not in panel


def test_render_query_flow_step_panel_no_upstream_omits_upstream_row() -> None:
    # A source step is always upstream-less -- must not show a blank row.
    step = QueryFlowStep(step_id="source:x", step_type="source", name="x", upstream_step_ids=[])

    panel = render_query_flow_step_panel(step)

    assert "Upstream" not in panel
