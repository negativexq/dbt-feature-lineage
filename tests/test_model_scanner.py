from pathlib import Path

from dbt_feature_lineage.scanners.model_scanner import (
    detect_model_layer,
    discover_models,
    extract_model_group,
)


def test_detect_model_layer() -> None:
    assert detect_model_layer("models/staging/stg_customers.sql") == "staging"
    assert detect_model_layer("models/intermediate/int_customer_activity.sql") == "intermediate"
    assert detect_model_layer("models/marts/mart_customer_features.sql") == "marts"
    assert detect_model_layer("models/other/model.sql") == "unknown"


# ---------------------------------------------------------------------------
# extract_model_group(): the domain-grouping folder between `models/` and
# the layer folder (staging/intermediate/marts), if any -- e.g.
# examples/multi_domain_dbt's `models/retail/staging/...` -> "retail".
# ---------------------------------------------------------------------------


def test_extract_model_group_nested_domain_layout_returns_the_domain() -> None:
    # examples/multi_domain_dbt style: models/<domain>/<layer>/<model>.sql
    assert extract_model_group("models/retail/staging/stg_orders.sql") == "retail"
    assert extract_model_group("models/lending/marts/mart_default_risk.sql") == "lending"
    assert (
        extract_model_group("models/retail/intermediate/int_order_items.sql") == "retail"
    )


def test_extract_model_group_flat_layout_returns_none() -> None:
    # examples/sample_banking_dbt style: the layer folder sits directly
    # under models/, with no grouping folder to extract.
    assert extract_model_group("models/staging/stg_customers.sql") is None
    assert extract_model_group("models/intermediate/int_customer_activity.sql") is None
    assert extract_model_group("models/marts/mart_customer_features.sql") is None


def test_extract_model_group_no_recognized_layer_folder_returns_none() -> None:
    # No staging/intermediate/marts anywhere in the path -- there's no
    # layer boundary to anchor a "group" against, so this isn't treated
    # as a domain folder (matches detect_model_layer() also falling back
    # to "unknown" for the same path, rather than guessing at a group).
    assert extract_model_group("models/other/model.sql") is None
    assert extract_model_group("models/model.sql") is None


def test_extract_model_group_deeper_nesting_still_returns_the_first_segment() -> None:
    # models/<domain>/<subdomain>/<layer>/<model>.sql -- extract_model_group()
    # deliberately only looks at the single segment right after `models`
    # (the same "one grouping level" simplification detect_model_layer()
    # doesn't need to make, since "in parts" has no such limit) rather
    # than the segment immediately before the layer folder. Not exercised
    # by either example project (both are exactly one level deep), but
    # pinned down here so the behavior for deeper nesting is a documented
    # choice, not an accident.
    assert extract_model_group("models/retail/orders/staging/x.sql") == "retail"


def test_extract_model_group_accepts_a_path_object() -> None:
    assert extract_model_group(Path("models/retail/staging/stg_orders.sql")) == "retail"


def test_extract_model_group_too_short_path_returns_none() -> None:
    assert extract_model_group("staging.sql") is None


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


def test_model_discovery_sets_model_group_for_a_nested_domain_layout(
    multi_domain_project_path: Path,
) -> None:
    models = discover_models(multi_domain_project_path, ["models"])

    assert len(models) == 12
    groups_by_name = {model.name: model.model_group for model in models}
    assert groups_by_name["stg_orders"] == "retail"
    assert groups_by_name["mart_top_products"] == "retail"
    assert groups_by_name["stg_borrowers"] == "lending"
    assert groups_by_name["mart_default_risk"] == "lending"
    assert all(model.model_group in ("retail", "lending") for model in models)


def test_model_discovery_leaves_model_group_none_for_a_flat_layout(
    sample_project_path: Path,
) -> None:
    # examples/sample_banking_dbt has no domain-grouping folder -- every
    # model's layer folder sits directly under models/.
    models = discover_models(sample_project_path, ["models"])

    assert models
    assert all(model.model_group is None for model in models)

