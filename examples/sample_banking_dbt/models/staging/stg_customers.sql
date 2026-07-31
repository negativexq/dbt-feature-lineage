with source_customers as (
    select
        customer_id,
        first_name,
        last_name,
        date_of_birth,
        onboarding_date,
        customer_status,
        country_code,
        segment_code,
        email,
        phone_number,
        updated_at
    from {{ source('core_banking', 'customers') }}
),

renamed as (
    select
        cast(customer_id as bigint) as customer_id,
        trim(first_name) as first_name,
        trim(last_name) as last_name,
        cast(date_of_birth as date) as date_of_birth,
        cast(onboarding_date as date) as onboarding_date,
        lower(trim(customer_status)) as customer_status,
        upper(trim(country_code)) as country_code,
        upper(trim(segment_code)) as segment_code,
        lower(trim(email)) as email,
        phone_number,
        cast(updated_at as timestamp) as updated_at,
        concat_ws(' ', trim(first_name), trim(last_name)) as customer_full_name,
        case
            when lower(trim(customer_status)) = 'active' then 1
            else 0
        end as is_active_customer
    from source_customers
)

select *
from renamed

