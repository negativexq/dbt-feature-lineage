with risk as (
    select
        risk_band,
        requested_amount
    from {{ ref('int_borrower_risk') }}
),

aggregated as (
    select
        risk_band,
        count(*) as borrower_count,
        sum(requested_amount) as total_requested_amount,
        avg(requested_amount) as avg_requested_amount
    from risk
    group by risk_band
)

select *
from aggregated
