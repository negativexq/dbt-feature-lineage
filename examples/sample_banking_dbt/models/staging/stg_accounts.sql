with source_accounts as (
    select
        account_id,
        customer_id,
        account_type,
        account_status,
        currency_code,
        current_balance,
        available_balance,
        credit_limit,
        opened_at,
        closed_at,
        updated_at
    from {{ source('core_banking', 'accounts') }}
),

renamed as (
    select
        cast(account_id as bigint) as account_id,
        cast(customer_id as bigint) as customer_id,
        lower(trim(account_type)) as account_type,
        lower(trim(account_status)) as account_status,
        upper(trim(currency_code)) as currency_code,
        cast(current_balance as numeric(18, 2)) as current_balance,
        cast(available_balance as numeric(18, 2)) as available_balance,
        cast(credit_limit as numeric(18, 2)) as credit_limit,
        cast(opened_at as timestamp) as opened_at,
        cast(closed_at as timestamp) as closed_at,
        cast(updated_at as timestamp) as updated_at,
        case
            when lower(trim(account_status)) = 'active' then 1
            else 0
        end as is_active_account,
        case
            when lower(trim(account_status)) = 'closed' then 1
            else 0
        end as is_closed_account
    from source_accounts
)

select *
from renamed

