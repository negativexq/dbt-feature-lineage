with transactions as (
    select
        customer_id,
        transaction_id,
        transaction_timestamp,
        transaction_date,
        transaction_type,
        spend_amount,
        incoming_transfer_amount,
        outgoing_transfer_amount,
        amount
    from {{ ref('stg_transactions') }}
),

base as (
    select
        customer_id,
        sum(case when transaction_date >= current_date - interval '7 day' then spend_amount else 0 end) as total_spend_7d,
        sum(case when transaction_date >= current_date - interval '30 day' then spend_amount else 0 end) as total_spend_30d,
        sum(case when transaction_date >= current_date - interval '90 day' then spend_amount else 0 end) as total_spend_90d,
        count(case when transaction_date >= current_date - interval '7 day' then transaction_id end) as transaction_count_7d,
        count(case when transaction_date >= current_date - interval '30 day' then transaction_id end) as transaction_count_30d,
        count(case when transaction_date >= current_date - interval '90 day' then transaction_id end) as transaction_count_90d,
        avg(abs(amount)) as avg_transaction_amount,
        max(abs(amount)) as max_transaction_amount,
        max(transaction_date) as last_transaction_date,
        sum(case when transaction_date >= current_date - interval '30 day' then incoming_transfer_amount else 0 end) as incoming_transfer_amount_30d,
        sum(case when transaction_date >= current_date - interval '30 day' then outgoing_transfer_amount else 0 end) as outgoing_transfer_amount_30d,
        count(distinct case when transaction_date >= current_date - interval '90 day' then transaction_type end) as distinct_transaction_type_count_90d
    from transactions
    group by customer_id
),

final as (
    select
        customer_id,
        total_spend_7d,
        total_spend_30d,
        total_spend_90d,
        transaction_count_7d,
        transaction_count_30d,
        transaction_count_90d,
        avg_transaction_amount,
        max_transaction_amount,
        last_transaction_date,
        cast(current_date - last_transaction_date as integer) as days_since_last_transaction,
        incoming_transfer_amount_30d,
        outgoing_transfer_amount_30d,
        distinct_transaction_type_count_90d
    from base
)

select *
from final

