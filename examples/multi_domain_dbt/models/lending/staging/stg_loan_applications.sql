with source_applications as (
    select
        application_id,
        borrower_id,
        requested_amount,
        application_status
    from {{ source('lending_raw', 'loan_applications') }}
),

renamed as (
    select
        cast(application_id as bigint) as application_id,
        cast(borrower_id as bigint) as borrower_id,
        cast(requested_amount as numeric) as requested_amount,
        lower(trim(application_status)) as application_status
    from source_applications
)

select *
from renamed
