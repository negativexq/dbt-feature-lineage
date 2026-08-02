with underwriting as (
    select
        borrower_id,
        credit_score,
        annual_income,
        requested_amount
    from {{ ref('int_loan_underwriting') }}
),

scored as (
    select
        borrower_id,
        credit_score,
        annual_income,
        requested_amount,
        case
            when credit_score >= 720 then 'low'
            when credit_score >= 620 then 'medium'
            else 'high'
        end as risk_band
    from underwriting
)

select *
from scored
