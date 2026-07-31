from pathlib import Path

from dbt_feature_lineage.scanners.model_scanner import detect_model_layer, discover_models


def test_detect_model_layer() -> None:
    assert detect_model_layer("models/staging/stg_customers.sql") == "staging"
    assert detect_model_layer("models/intermediate/int_customer_activity.sql") == "intermediate"
    assert detect_model_layer("models/marts/mart_customer_features.sql") == "marts"
    assert detect_model_layer("models/other/model.sql") == "unknown"


def test_model_discovery(sample_project_path: Path) -> None:
    models = discover_models(sample_project_path, ["models"])

    assert len(models) == 12
    assert {model.name for model in models} >= {
        "stg_customers",
        "int_customer_activity",
        "mart_feature_store_export",
    }

