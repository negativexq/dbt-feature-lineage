with loan_metrics as (
    select
        l.customer_id,
        count(*) as loan_count,
        sum(case when l.is_active_loan = 1 then 1 else 0 end) as active_loan_count,
        sum(case when l.is_overdue_loan = 1 then 1 else 0 end) as overdue_loan_count,
        sum(coalesce(l.outstanding_amount, 0)) as outstanding_loan_amount,
        avg(nullif(l.interest_rate, 0)) as avg_loan_interest_rate,
        min(l.loan_open_date) as first_loan_open_date,
        max(l.due_date) as latest_loan_due_date
    from {{ ref('stg_loans') }} as l
    group by l.customer_id
),

credit_accounts as (
    select
        a.customer_id,
        sum(coalesce(a.credit_limit, 0)) as credit_limit,
        sum(
            case
                when a.account_type = 'credit' then greatest(coalesce(a.current_balance, 0), 0)
                else 0
            end
        ) as revolving_balance
    from {{ ref('stg_accounts') }} as a
    group by a.customer_id
),

combined as (
    select
        coalesce(lm.customer_id, ca.customer_id) as customer_id,
        coalesce(ca.credit_limit, 0) as credit_limit,
        coalesce(ca.revolving_balance, 0) as revolving_balance,
        coalesce(lm.outstanding_loan_amount, 0) as outstanding_loan_amount,
        coalesce(lm.loan_count, 0) as loan_count,
        coalesce(lm.active_loan_count, 0) as active_loan_count,
        coalesce(lm.overdue_loan_count, 0) as overdue_loan_count,
        lm.avg_loan_interest_rate,
        lm.first_loan_open_date,
        lm.latest_loan_due_date
    from loan_metrics as lm
    full outer join credit_accounts as ca
        on lm.customer_id = ca.customer_id
),

final as (
    select
        customer_id,
        credit_limit,
        revolving_balance,
        outstanding_loan_amount,
        loan_count,
        active_loan_count,
        overdue_loan_count,
        avg_loan_interest_rate,
        first_loan_open_date,
        latest_loan_due_date,
        coalesce(
            revolving_balance / nullif(credit_limit, 0),
            0
        ) as credit_utilization_ratio
    from combined
)

select *
from final

