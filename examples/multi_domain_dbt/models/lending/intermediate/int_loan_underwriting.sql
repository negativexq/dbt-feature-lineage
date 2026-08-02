with applications as (
    select
        application_id,
        borrower_id,
        requested_amount,
        application_status
    from {{ ref('stg_loan_applications') }}
),

borrowers as (
    select
        borrower_id,
        credit_score,
        annual_income
    from {{ ref('stg_borrowers') }}
),

joined as (
    select
        a.application_id,
        a.borrower_id,
        a.requested_amount,
        a.application_status,
        b.credit_score,
        b.annual_income
    from applications as a
    left join borrowers as b
        on a.borrower_id = b.borrower_id
)

select *
from joined
