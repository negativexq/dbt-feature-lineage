# sample_banking_dbt

This sample dbt project represents a realistic banking analytics and feature store pipeline built for static lineage testing. It models customers, deposit accounts, transactions, and loans, then derives intermediate customer metrics and downstream marts such as customer features, risk features, customer 360, and a feature store export.

The project is intended for static analysis inside `dbt-feature-lineage`. It is not the lineage explorer itself.

## Notes

- All source definitions live in `models/sources.yml`.
- Physical source database, schema, and identifiers are parameterized with `env_var()` and `var()` patterns.
- The models are written to be PostgreSQL-compatible where possible.
- Static parsing is possible without a real database connection.
- Commands that require a live adapter connection may still need a valid PostgreSQL profile. If `dbt parse` or `dbt compile` fails in another environment due to profile or adapter setup, do not assume model logic is invalid.

