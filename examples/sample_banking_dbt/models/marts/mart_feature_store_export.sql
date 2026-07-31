with customer_features as (
    select
        customer_id,
        customer_age,
        customer_tenure_days,
        account_count,
        active_account_count,
        total_current_balance,
        avg_30d_balance,
        total_spend_30d,
        total_spend_90d,
        transaction_count_30d,
        avg_transaction_amount,
        days_since_last_transaction,
        incoming_transfer_amount_30d,
        outgoing_transfer_amount_30d,
        credit_limit,
        outstanding_loan_amount,
        loan_count,
        active_loan_count,
        overdue_loan_count,
        credit_utilization_ratio,
        debt_to_balance_ratio,
        digital_activity_score,
        high_value_customer_flag,
        inactive_customer_flag,
        delinquency_flag,
        risk_segment
    from {{ ref('mart_customer_features') }}
),

final as (
    select
        customer_id,
        customer_age,
        customer_tenure_days,
        account_count,
        active_account_count,
        total_current_balance,
        avg_30d_balance,
        total_spend_30d,
        total_spend_90d,
        transaction_count_30d,
        avg_transaction_amount,
        days_since_last_transaction,
        incoming_transfer_amount_30d,
        outgoing_transfer_amount_30d,
        credit_limit,
        outstanding_loan_amount,
        loan_count,
        active_loan_count,
        overdue_loan_count,
        credit_utilization_ratio,
        debt_to_balance_ratio,
        digital_activity_score,
        high_value_customer_flag,
        inactive_customer_flag,
        delinquency_flag,
        risk_segment,
        current_timestamp as exported_at
    from customer_features
)

select *
from final

