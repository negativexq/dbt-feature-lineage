with accounts as (
    select
        account_id,
        customer_id,
        account_status,
        current_balance,
        credit_limit
    from {{ ref('stg_accounts') }}
),

transaction_days as (
    select
        t.customer_id,
        t.account_id,
        t.transaction_date as balance_date,
        sum(
            case
                when t.debit_credit_indicator = 'credit' then abs(t.amount)
                else -abs(t.amount)
            end
        ) as net_transaction_amount
    from {{ ref('stg_transactions') }} as t
    group by
        t.customer_id,
        t.account_id,
        t.transaction_date
),

daily_balance as (
    select
        td.customer_id,
        td.account_id,
        td.balance_date,
        a.account_status,
        a.credit_limit,
        a.current_balance
            - sum(td.net_transaction_amount) over (
                partition by td.account_id
                order by td.balance_date desc
                rows between unbounded preceding and current row
            ) as estimated_end_of_day_balance
    from transaction_days as td
    inner join accounts as a
        on td.account_id = a.account_id
),

rolling_metrics as (
    select
        customer_id,
        account_id,
        balance_date,
        account_status,
        credit_limit,
        estimated_end_of_day_balance,
        avg(estimated_end_of_day_balance) over (
            partition by customer_id
            order by balance_date
            rows between 29 preceding and current row
        ) as avg_30d_balance,
        min(estimated_end_of_day_balance) over (
            partition by customer_id
            order by balance_date
            rows between 29 preceding and current row
        ) as min_30d_balance,
        max(estimated_end_of_day_balance) over (
            partition by customer_id
            order by balance_date
            rows between 29 preceding and current row
        ) as max_30d_balance,
        row_number() over (
            partition by customer_id
            order by balance_date desc, account_id
        ) as customer_balance_rank
    from daily_balance
)

select
    customer_id,
    account_id,
    balance_date,
    account_status,
    credit_limit,
    estimated_end_of_day_balance,
    avg_30d_balance,
    min_30d_balance,
    max_30d_balance,
    customer_balance_rank
from rolling_metrics

