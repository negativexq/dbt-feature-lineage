with customers as (
    select
        customer_id,
        customer_full_name,
        email,
        phone_number,
        country_code,
        segment_code
    from {{ ref('stg_customers') }}
),

features as (
    select
        customer_id,
        customer_age,
        customer_tenure_days,
        account_count,
        total_current_balance,
        total_spend_30d,
        active_loan_count,
        risk_segment,
        digital_activity_score
    from {{ ref('mart_customer_features') }}
),

final as (
    select
        c.customer_id,
        c.customer_full_name,
        c.email,
        c.phone_number,
        c.country_code,
        c.segment_code,
        f.customer_age,
        f.customer_tenure_days,
        f.account_count,
        f.total_current_balance,
        f.total_spend_30d,
        f.active_loan_count,
        f.risk_segment,
        f.digital_activity_score
    from customers as c
    inner join features as f
        on c.customer_id = f.customer_id
)

select *
from final

