with order_items as (
    select
        product_id,
        product_name,
        category,
        unit_price
    from {{ ref('int_order_items') }}
),

ranked as (
    select
        product_id,
        product_name,
        category,
        count(*) as times_ordered,
        sum(unit_price) as total_revenue
    from order_items
    group by product_id, product_name, category
)

select *
from ranked
