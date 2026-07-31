from dbt_feature_lineage.parsers.sql_parser import (
    parse_sql_with_fallback,
    preprocess_dbt_sql,
    restore_placeholders,
)


def test_preprocess_dbt_sql_replaces_ref_and_source() -> None:
    raw_sql = """
    select * from {{ ref('stg_customers') }}
    join {{ source('core_banking', 'accounts') }} as a on 1 = 1
    """

    processed_sql, mapping = preprocess_dbt_sql(raw_sql)

    assert "stg_customers" in processed_sql
    assert "core_banking__accounts" in processed_sql
    assert mapping["stg_customers"] == "{{ ref('stg_customers') }}"
    assert mapping["core_banking__accounts"] == "{{ source('core_banking', 'accounts') }}"


def test_restore_placeholders() -> None:
    restored = restore_placeholders(
        "select * from stg_customers join core_banking__accounts",
        {
            "stg_customers": "{{ ref('stg_customers') }}",
            "core_banking__accounts": "{{ source('core_banking', 'accounts') }}",
        },
    )

    assert "{{ ref('stg_customers') }}" in restored
    assert "{{ source('core_banking', 'accounts') }}" in restored


def test_parser_failure_fallback() -> None:
    parse_result = parse_sql_with_fallback("select from")

    assert parse_result.expression is None
    assert parse_result.parsing_warnings
