with customer_orders as (
    select
        customer_id,
        order_count,
        lifetime_spend,
        completed_order_count
    from {{ ref('int_customer_order_summary') }}
),

final as (
    select
        customer_id,
        order_count,
        lifetime_spend,
        completed_order_count,
        case
            when order_count = 0 then 0
            else round(completed_order_count::numeric / order_count, 2)
        end as completion_rate
    from customer_orders
)

select *
from final
