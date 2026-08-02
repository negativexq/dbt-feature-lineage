with source_orders as (
    select
        order_id,
        customer_id,
        order_date,
        order_status
    from {{ source('retail_raw', 'orders') }}
),

renamed as (
    select
        cast(order_id as bigint) as order_id,
        cast(customer_id as bigint) as customer_id,
        cast(order_date as date) as order_date,
        lower(trim(order_status)) as order_status
    from source_orders
)

select *
from renamed
