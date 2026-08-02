with underwriting as (
    select
        application_id,
        borrower_id,
        requested_amount,
        application_status
    from {{ ref('int_loan_underwriting') }}
),

risk as (
    select
        borrower_id,
        risk_band
    from {{ ref('int_borrower_risk') }}
),

final as (
    select
        u.application_id,
        u.borrower_id,
        u.requested_amount,
        u.application_status,
        r.risk_band
    from underwriting as u
    left join risk as r
        on u.borrower_id = r.borrower_id
)

select *
from final
