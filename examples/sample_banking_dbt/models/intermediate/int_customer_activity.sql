with customers as (
    select
        customer_id,
        onboarding_date,
        customer_status
    from {{ ref('stg_customers') }}
),

accounts as (
    select
        customer_id,
        count(*) as account_count,
        sum(is_active_account) as active_account_count,
        sum(is_closed_account) as closed_account_count
    from {{ ref('stg_accounts') }}
    group by customer_id
),

transactions as (
    select
        customer_id,
        count(*) as lifetime_transaction_count,
        count(distinct transaction_date) as active_transaction_days,
        max(transaction_date) as last_transaction_date,
        count(
            distinct case
                when channel in ('mobile', 'web') and transaction_date >= current_date - interval '30 day'
                    then transaction_date
            end
        ) as digital_active_days_30d
    from {{ ref('stg_transactions') }}
    group by customer_id
),

joined as (
    select
        c.customer_id,
        c.onboarding_date,
        c.customer_status,
        coalesce(a.account_count, 0) as account_count,
        coalesce(a.active_account_count, 0) as active_account_count,
        coalesce(a.closed_account_count, 0) as closed_account_count,
        coalesce(t.lifetime_transaction_count, 0) as lifetime_transaction_count,
        coalesce(t.active_transaction_days, 0) as active_transaction_days,
        t.last_transaction_date,
        coalesce(t.digital_active_days_30d, 0) as digital_active_days_30d
    from customers as c
    left join accounts as a
        on c.customer_id = a.customer_id
    left join transactions as t
        on c.customer_id = t.customer_id
),

final as (
    select
        customer_id,
        onboarding_date,
        customer_status,
        account_count,
        active_account_count,
        closed_account_count,
        lifetime_transaction_count,
        active_transaction_days,
        last_transaction_date,
        digital_active_days_30d,
        cast(current_date - onboarding_date as integer) as customer_tenure_days,
        case
            when customer_status = 'active' then least(100, digital_active_days_30d * 4 + active_transaction_days)
            else 0
        end as digital_activity_score
    from joined
)

select *
from final

