with source_transactions as (
    select
        transaction_id,
        account_id,
        customer_id,
        transaction_timestamp,
        transaction_type,
        debit_credit_indicator,
        amount,
        merchant_category,
        channel,
        description
    from {{ source('core_banking', 'transactions') }}
),

typed as (
    select
        cast(transaction_id as bigint) as transaction_id,
        cast(account_id as bigint) as account_id,
        cast(customer_id as bigint) as customer_id,
        cast(transaction_timestamp as timestamp) as transaction_timestamp,
        cast(transaction_timestamp as date) as transaction_date,
        lower(trim(transaction_type)) as transaction_type,
        lower(trim(debit_credit_indicator)) as debit_credit_indicator,
        cast(amount as numeric(18, 2)) as amount,
        lower(trim(merchant_category)) as merchant_category,
        lower(trim(channel)) as channel,
        description
    from source_transactions
),

enriched as (
    select
        transaction_id,
        account_id,
        customer_id,
        transaction_timestamp,
        transaction_date,
        transaction_type,
        debit_credit_indicator,
        amount,
        merchant_category,
        channel,
        description,
        case
            when debit_credit_indicator = 'debit' then abs(amount)
            else 0
        end as debit_amount,
        case
            when debit_credit_indicator = 'credit' then abs(amount)
            else 0
        end as credit_amount,
        case
            when transaction_type in ('card_payment', 'cash_withdrawal', 'fee', 'outgoing_transfer', 'loan_payment') then abs(amount)
            else 0
        end as spend_amount,
        case
            when transaction_type = 'incoming_transfer' then abs(amount)
            else 0
        end as incoming_transfer_amount,
        case
            when transaction_type = 'outgoing_transfer' then abs(amount)
            else 0
        end as outgoing_transfer_amount
    from typed
    where transaction_timestamp is not null
)

select *
from enriched

