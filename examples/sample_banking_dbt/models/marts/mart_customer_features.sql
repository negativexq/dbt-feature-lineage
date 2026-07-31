with customers as (
    select
        customer_id,
        customer_full_name,
        date_of_birth,
        onboarding_date,
        customer_status,
        country_code,
        segment_code
    from {{ ref('stg_customers') }}
),

activity as (
    select
        customer_id,
        account_count,
        active_account_count,
        closed_account_count,
        lifetime_transaction_count,
        active_transaction_days,
        last_transaction_date,
        customer_tenure_days,
        digital_activity_score
    from {{ ref('int_customer_activity') }}
),

spend as (
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
        days_since_last_transaction,
        incoming_transfer_amount_30d,
        outgoing_transfer_amount_30d,
        distinct_transaction_type_count_90d
    from {{ ref('int_customer_spend_metrics') }}
),

credit as (
    select
        customer_id,
        credit_limit,
        outstanding_loan_amount,
        loan_count,
        active_loan_count,
        overdue_loan_count,
        credit_utilization_ratio,
        avg_loan_interest_rate,
        first_loan_open_date,
        latest_loan_due_date
    from {{ ref('int_customer_credit_profile') }}
),

latest_balance as (
    select
        customer_id,
        sum(estimated_end_of_day_balance) as total_current_balance,
        avg(avg_30d_balance) as avg_30d_balance,
        min(min_30d_balance) as min_30d_balance,
        max(max_30d_balance) as max_30d_balance
    from {{ ref('int_customer_daily_balance') }}
    where customer_balance_rank = 1
    group by customer_id
),

account_rollup as (
    select
        a.customer_id,
        count(*) as raw_account_count,
        sum(case when a.account_status = 'active' then 1 else 0 end) as raw_active_account_count,
        sum(case when a.account_status = 'closed' then 1 else 0 end) as raw_closed_account_count,
        sum(coalesce(a.current_balance, 0)) as source_total_current_balance,
        sum(coalesce(a.credit_limit, 0)) as source_credit_limit
    from {{ ref('stg_accounts') }} as a
    group by a.customer_id
),

loan_rollup as (
    select
        l.customer_id,
        sum(case when l.loan_status = 'overdue' then 1 else 0 end) as raw_overdue_loan_count,
        sum(case when l.loan_status in ('active', 'overdue') then 1 else 0 end) as raw_active_loan_count,
        sum(coalesce(l.outstanding_amount, 0)) as raw_outstanding_loan_amount,
        max(l.due_date) as max_due_date
    from {{ ref('stg_loans') }} as l
    group by l.customer_id
),

recent_transaction_profile as (
    select
        t.customer_id,
        count(distinct case when t.transaction_date >= current_date - interval '30 day' then t.account_id end) as active_accounts_with_transactions_30d,
        count(distinct case when t.transaction_date >= current_date - interval '90 day' then t.merchant_category end) as merchant_category_count_90d,
        avg(
            case
                when t.transaction_date >= current_date - interval '30 day' then abs(t.amount)
                else null
            end
        ) as avg_30d_transaction_amount
    from {{ ref('stg_transactions') }} as t
    group by t.customer_id
),

joined as (
    select
        c.customer_id,
        c.customer_full_name,
        c.date_of_birth,
        c.onboarding_date,
        c.customer_status,
        c.country_code,
        c.segment_code,
        a.account_count,
        a.active_account_count,
        a.closed_account_count,
        a.customer_tenure_days,
        a.digital_activity_score,
        a.lifetime_transaction_count,
        a.active_transaction_days,
        s.total_spend_7d,
        s.total_spend_30d,
        s.total_spend_90d,
        s.transaction_count_7d,
        s.transaction_count_30d,
        s.transaction_count_90d,
        s.avg_transaction_amount,
        s.max_transaction_amount,
        s.days_since_last_transaction,
        s.incoming_transfer_amount_30d,
        s.outgoing_transfer_amount_30d,
        s.distinct_transaction_type_count_90d,
        cp.credit_limit,
        cp.outstanding_loan_amount,
        cp.loan_count,
        cp.active_loan_count,
        cp.overdue_loan_count,
        cp.credit_utilization_ratio,
        cp.avg_loan_interest_rate,
        lb.total_current_balance,
        lb.avg_30d_balance,
        lb.min_30d_balance,
        lb.max_30d_balance,
        ar.source_total_current_balance,
        ar.source_credit_limit,
        lr.max_due_date,
        rtp.active_accounts_with_transactions_30d,
        rtp.merchant_category_count_90d,
        rtp.avg_30d_transaction_amount
    from customers as c
    left join activity as a
        on c.customer_id = a.customer_id
    left join spend as s
        on c.customer_id = s.customer_id
    left join credit as cp
        on c.customer_id = cp.customer_id
    left join latest_balance as lb
        on c.customer_id = lb.customer_id
    left join account_rollup as ar
        on c.customer_id = ar.customer_id
    left join loan_rollup as lr
        on c.customer_id = lr.customer_id
    left join recent_transaction_profile as rtp
        on c.customer_id = rtp.customer_id
),

final as (
    select
        j.customer_id,
        cast(extract(year from age(current_date, j.date_of_birth)) as integer) as customer_age,
        j.customer_tenure_days,
        coalesce(j.account_count, j.raw_account_count, 0) as account_count,
        coalesce(j.active_account_count, j.raw_active_account_count, 0) as active_account_count,
        coalesce(j.closed_account_count, j.raw_closed_account_count, 0) as closed_account_count,
        coalesce(j.total_current_balance, j.source_total_current_balance, 0) as total_current_balance,
        coalesce(j.avg_30d_balance, 0) as avg_30d_balance,
        coalesce(j.min_30d_balance, 0) as min_30d_balance,
        coalesce(j.max_30d_balance, 0) as max_30d_balance,
        coalesce(j.total_spend_7d, 0) as total_spend_7d,
        coalesce(j.total_spend_30d, 0) as total_spend_30d,
        coalesce(j.total_spend_90d, 0) as total_spend_90d,
        coalesce(j.transaction_count_7d, 0) as transaction_count_7d,
        coalesce(j.transaction_count_30d, 0) as transaction_count_30d,
        coalesce(j.transaction_count_90d, 0) as transaction_count_90d,
        coalesce(j.avg_transaction_amount, 0) as avg_transaction_amount,
        coalesce(j.max_transaction_amount, 0) as max_transaction_amount,
        coalesce(j.days_since_last_transaction, 9999) as days_since_last_transaction,
        coalesce(j.incoming_transfer_amount_30d, 0) as incoming_transfer_amount_30d,
        coalesce(j.outgoing_transfer_amount_30d, 0) as outgoing_transfer_amount_30d,
        coalesce(j.credit_limit, j.source_credit_limit, 0) as credit_limit,
        coalesce(j.outstanding_loan_amount, 0) as outstanding_loan_amount,
        coalesce(j.loan_count, 0) as loan_count,
        coalesce(j.active_loan_count, j.raw_active_loan_count, 0) as active_loan_count,
        coalesce(j.overdue_loan_count, j.raw_overdue_loan_count, 0) as overdue_loan_count,
        coalesce(j.credit_utilization_ratio, 0) as credit_utilization_ratio,
        coalesce(
            j.outstanding_loan_amount / nullif(j.total_current_balance, 0),
            0
        ) as debt_to_balance_ratio,
        coalesce(j.digital_activity_score, 0) as digital_activity_score,
        case
            when coalesce(j.total_current_balance, j.source_total_current_balance, 0) >= 50000
                or coalesce(j.total_spend_90d, 0) >= 25000
                or coalesce(j.credit_limit, j.source_credit_limit, 0) >= 20000
                then 1
            else 0
        end as high_value_customer_flag,
        case
            when coalesce(j.days_since_last_transaction, 9999) > 90
                or coalesce(j.active_account_count, 0) = 0
                then 1
            else 0
        end as inactive_customer_flag,
        case
            when coalesce(j.overdue_loan_count, 0) > 0
                or coalesce(j.credit_utilization_ratio, 0) >= 0.9
                then 1
            else 0
        end as delinquency_flag,
        case
            when coalesce(j.overdue_loan_count, 0) > 0
                or coalesce(j.credit_utilization_ratio, 0) >= 0.9
                or coalesce(
                    j.outstanding_loan_amount / nullif(j.total_current_balance, 0),
                    0
                ) > 2
                then 'high'
            when coalesce(j.credit_utilization_ratio, 0) >= 0.6
                or coalesce(j.days_since_last_transaction, 9999) > 45
                then 'medium'
            else 'low'
        end as risk_segment
    from joined as j
)

select *
from final

