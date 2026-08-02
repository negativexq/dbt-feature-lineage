with orders as (
    select
        order_id,
        customer_id,
        order_date,
        order_status
    from {{ ref('stg_orders') }}
),

products as (
    select
        product_id,
        product_name,
        category,
        unit_price
    from {{ ref('stg_products') }}
),

joined as (
    select
        o.order_id,
        o.customer_id,
        o.order_date,
        o.order_status,
        p.product_id,
        p.product_name,
        p.category,
        p.unit_price
    from orders as o
    left join products as p
        on o.order_id = p.product_id
)

select *
from joined
