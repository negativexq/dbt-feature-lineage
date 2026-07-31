with customer_features as (
    select
        customer_id,
        credit_utilization_ratio,
        debt_to_balance_ratio,
        overdue_loan_count,
        inactive_customer_flag,
        risk_segment
    from {{ ref('mart_customer_features') }}
),

credit_profile as (
    select
        customer_id,
        avg_loan_interest_rate,
        latest_loan_due_date
    from {{ ref('int_customer_credit_profile') }}
),

final as (
    select
        cf.customer_id,
        cf.credit_utilization_ratio,
        cf.debt_to_balance_ratio,
        cf.overdue_loan_count,
        cp.avg_loan_interest_rate,
        cp.latest_loan_due_date,
        cf.inactive_customer_flag,
        cf.risk_segment,
        case
            when cf.risk_segment = 'high' then 100
            when cf.risk_segment = 'medium' then 60
            else 20
        end as risk_score
    from customer_features as cf
    left join credit_profile as cp
        on cf.customer_id = cp.customer_id
)

select *
from final

