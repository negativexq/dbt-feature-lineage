# multi_domain_dbt

A small, static-mode-only example project with two top-level model
domains (`retail/`, `lending/`), each with its own `staging/`,
`intermediate/`, and `marts/` subfolder:

```text
models/
├── retail/
│   ├── staging/       stg_orders, stg_products
│   ├── intermediate/  int_order_items, int_customer_order_summary
│   └── marts/         mart_retail_sales, mart_top_products
└── lending/
    ├── staging/       stg_loan_applications, stg_borrowers
    ├── intermediate/  int_loan_underwriting, int_borrower_risk
    └── marts/         mart_loan_portfolio, mart_default_risk
```

Exists to exercise `scanners/model_scanner.py::detect_model_layer()`
against layer folders nested *under* a domain folder (e.g.
`models/retail/staging/...`), rather than sitting directly under
`models/` the way `examples/sample_banking_dbt` does. No `profiles.yml`
credentials are real; this project is not meant to be run against a
live warehouse.
