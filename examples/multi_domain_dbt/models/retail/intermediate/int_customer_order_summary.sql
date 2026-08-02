with order_items as (
    select
        order_id,
        customer_id,
        order_status,
        unit_price
    from {{ ref('int_order_items') }}
),

aggregated as (
    select
        customer_id,
        count(distinct order_id) as order_count,
        sum(unit_price) as lifetime_spend,
        sum(
            case
                when order_status = 'completed' then 1
                else 0
            end
        ) as completed_order_count
    from order_items
    group by customer_id
)

select *
from aggregated
