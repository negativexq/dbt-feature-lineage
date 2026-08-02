with source_borrowers as (
    select
        borrower_id,
        credit_score,
        annual_income
    from {{ source('lending_raw', 'borrowers') }}
),

renamed as (
    select
        cast(borrower_id as bigint) as borrower_id,
        cast(credit_score as integer) as credit_score,
        cast(annual_income as numeric) as annual_income
    from source_borrowers
)

select *
from renamed
