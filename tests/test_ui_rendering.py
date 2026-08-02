import networkx as nx

from dbt_feature_lineage.domain.lineage import ColumnNode
from dbt_feature_lineage.domain.models import (
    DbtModel,
    DbtModelAnalysis,
    DbtOutputColumn,
    DbtProject,
)
from dbt_feature_lineage.ui import (
    build_lineage_dot,
    build_model_flow_lines,
    filter_models,
    filter_output_columns,
    group_models_by_layer,
    render_node_detail_panel,
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


def test_build_lineage_dot_includes_every_node_and_edge() -> None:
    source = ColumnNode(model="stg_customers", column="customer_id", layer="staging")
    target = ColumnNode(model="mart_customer_overview", column="customer_id", layer="marts")
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_edge(source, target, transformation_type="direct", expression_sql="a.customer_id")

    dot = build_lineage_dot(graph)

    assert dot.startswith("digraph lineage {")
    assert dot.endswith("}")
    assert '"stg_customers.customer_id"' in dot
    assert '"mart_customer_overview.customer_id"' in dot
    assert '"stg_customers.customer_id" -> "mart_customer_overview.customer_id"' in dot
    assert 'label="direct"' in dot


def test_build_lineage_dot_escapes_double_quotes_in_identifiers() -> None:
    node = ColumnNode(model='weird"model', column="col", layer="unknown")
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_node(node)

    dot = build_lineage_dot(graph)

    assert '\\"' in dot
    # The raw, unescaped quote should never appear on its own inside a label.
    assert 'weird"model' not in dot


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
