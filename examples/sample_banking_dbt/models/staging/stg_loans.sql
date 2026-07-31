with source_loans as (
    select
        loan_id,
        customer_id,
        account_id,
        loan_status,
        loan_type,
        principal_amount,
        outstanding_amount,
        interest_rate,
        installment_amount,
        loan_open_date,
        due_date,
        closed_date
    from {{ source('core_banking', 'loans') }}
),

renamed as (
    select
        cast(loan_id as bigint) as loan_id,
        cast(customer_id as bigint) as customer_id,
        cast(account_id as bigint) as account_id,
        lower(trim(loan_status)) as loan_status,
        lower(trim(loan_type)) as loan_type,
        cast(principal_amount as numeric(18, 2)) as principal_amount,
        cast(outstanding_amount as numeric(18, 2)) as outstanding_amount,
        cast(interest_rate as numeric(10, 4)) as interest_rate,
        cast(installment_amount as numeric(18, 2)) as installment_amount,
        cast(loan_open_date as date) as loan_open_date,
        cast(due_date as date) as due_date,
        cast(closed_date as date) as closed_date,
        case
            when lower(trim(loan_status)) in ('active', 'overdue') then 1
            else 0
        end as is_active_loan,
        case
            when lower(trim(loan_status)) = 'overdue' then 1
            else 0
        end as is_overdue_loan
    from source_loans
)

select *
from renamed

