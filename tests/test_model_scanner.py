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


def test_model_discovery_leaves_manifest_only_metadata_fields_unset(
    sample_project_path: Path,
) -> None:
    # description/tags/owner/test_count (v0.5) only come from manifest.json
    # (model docs, meta.owner, separate test nodes) -- static mode has no
    # equivalent source for any of them, so they must stay at their
    # Pydantic defaults (None/[]/None/0) rather than being guessed at or
    # silently left in some other, inconsistent shape.
    models = discover_models(sample_project_path, ["models"])

    assert models
    for model in models:
        assert model.description is None
        assert model.tags == []
        assert model.owner is None
        assert model.test_count == 0

