from dbt_feature_lineage.parsers.dependency_parser import (
    parse_ref_dependencies,
    parse_source_dependencies,
)


def test_ref_parsing_supports_quotes_and_whitespace() -> None:
    raw_sql = """
    select * from {{ ref('stg_customers') }}
    join {{  ref("stg_accounts")  }} using (customer_id)
    """

    dependencies = parse_ref_dependencies(raw_sql)

    assert [dependency.target_name for dependency in dependencies] == [
        "stg_customers",
        "stg_accounts",
    ]


def test_source_parsing_supports_quotes_and_whitespace() -> None:
    raw_sql = """
    select * from {{ source('core_banking', 'customers') }}
    join {{  source("core_banking", "accounts")  }} using (customer_id)
    """

    dependencies = parse_source_dependencies(raw_sql)

    assert [(dependency.source_name, dependency.target_name) for dependency in dependencies] == [
        ("core_banking", "customers"),
        ("core_banking", "accounts"),
    ]

